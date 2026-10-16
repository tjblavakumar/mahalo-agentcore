"""Handler tests for the GitHub mock Lambda (mock mode only)."""

import importlib

import pytest

from tests.conftest import body_of, make_event

TOKEN = "mock-github-token-12345"


@pytest.fixture
def handler(dynamo_table, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_GITHUB_TOKEN", TOKEN)
    monkeypatch.delenv("GITHUB_MODE", raising=False)
    import github.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    return h


def invoke(handler, method, path, **kwargs):
    return handler.lambda_handler(make_event(method, path, **kwargs), None)


def test_health_mode_mock(handler):
    resp = invoke(handler, "GET", "/health")
    assert resp["statusCode"] == 200
    assert body_of(resp)["mode"] == "mock"


def test_auth_401(handler):
    resp = invoke(handler, "GET", "/repos")
    assert resp["statusCode"] == 401


def test_list_repos(handler):
    resp = invoke(handler, "GET", "/repos", token=TOKEN)
    ids = {r["id"] for r in body_of(resp)["repos"]}
    assert ids == {"repo-1", "repo-2", "repo-3", "repo-4", "repo-5"}


def test_get_repo_by_name_404_no_resolution(handler):
    # Agent passes the repo NAME; the mock keys by id and so 404s. Replicated.
    resp = invoke(handler, "GET", "/repos/payment-service", token=TOKEN)
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Repository not found"


def test_get_repo_by_id(handler):
    resp = invoke(handler, "GET", "/repos/repo-1", token=TOKEN)
    assert resp["statusCode"] == 200
    assert body_of(resp)["name"] == "payment-service"


def test_list_branches_404_off_branchset(handler):
    resp = invoke(handler, "GET", "/repos/nope/branches", token=TOKEN)
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Repository not found"


def test_create_branch_missing_name_422(handler):
    resp = invoke(handler, "POST", "/repos/repo-1/branches", token=TOKEN, body={})
    assert resp["statusCode"] == 422
    assert body_of(resp)["detail"] == "Field 'name' is required"


def test_create_branch_duplicate_409(handler):
    resp = invoke(
        handler, "POST", "/repos/repo-1/branches", token=TOKEN, body={"name": "main"}
    )
    assert resp["statusCode"] == 409
    assert body_of(resp)["detail"] == "Branch already exists"


def test_get_pull_int_coercion_and_404(handler):
    resp = invoke(handler, "GET", "/repos/repo-1/pulls/142", token=TOKEN)
    assert resp["statusCode"] == 200
    assert body_of(resp)["id"] == "pr-1"
    missing = invoke(handler, "GET", "/repos/repo-1/pulls/99999", token=TOKEN)
    assert missing["statusCode"] == 404
    assert body_of(missing)["detail"] == "Pull request not found"


def test_create_pull_missing_head_422(handler):
    resp = invoke(handler, "POST", "/repos/repo-1/pulls", token=TOKEN, body={"title": "x"})
    assert resp["statusCode"] == 422
    assert body_of(resp)["detail"] == "head branch is required"


def test_commit_missing_field_422_verbatim(handler):
    # Legacy metadata shape (no files) requires author_id.
    resp = invoke(
        handler,
        "POST",
        "/repos/repo-1/commits",
        token=TOKEN,
        body={"branch": "main", "message": "m"},
    )
    assert resp["statusCode"] == 422
    assert body_of(resp)["detail"] == "Field 'author_id' is required"


def test_task2_chain_branch_commit_pull(handler):
    # create branch
    br = invoke(
        handler,
        "POST",
        "/repos/repo-1/branches",
        token=TOKEN,
        body={"name": "feature/new", "from_branch": "main"},
    )
    assert br["statusCode"] == 201

    # commit on that branch (file-contents shape -> author_id defaults to mahalo-bot)
    commit = invoke(
        handler,
        "POST",
        "/repos/repo-1/commits",
        token=TOKEN,
        body={"branch": "feature/new", "message": "add", "files": [{"path": "a", "content": "b"}]},
    )
    assert commit["statusCode"] == 201
    cbody = body_of(commit)
    assert cbody["id"] == "c035"  # count-based: 34 seed commits -> c035
    assert cbody["author_id"] == "mahalo-bot"

    # open PR
    pull = invoke(
        handler,
        "POST",
        "/repos/repo-1/pulls",
        token=TOKEN,
        body={"head": "feature/new", "title": "My PR"},
    )
    assert pull["statusCode"] == 201
    pbody = body_of(pull)
    assert pbody["id"] == "pr-10"  # count-based: 9 seed PRs -> pr-10
    assert pbody["number"] == 145  # max-based: max seed number 144 -> 145


def test_three_collection_split_fresh_repo(handler):
    created = invoke(handler, "POST", "/repos", token=TOKEN, body={"name": "New-Repo"})
    assert created["statusCode"] == 201
    assert body_of(created)["id"] == "new-repo"  # lower+strip

    # branch/commit/pull succeed (BRANCHSET was created)...
    branches = invoke(handler, "GET", "/repos/new-repo/branches", token=TOKEN)
    assert branches["statusCode"] == 200
    assert body_of(branches)["branches"][0]["name"] == "main"

    commit = invoke(
        handler,
        "POST",
        "/repos/new-repo/commits",
        token=TOKEN,
        body={"branch": "main", "message": "m", "author_id": "dev-1"},
    )
    assert commit["statusCode"] == 201

    # ...but stats 404 because no STATS item was created.
    stats = invoke(handler, "GET", "/repos/new-repo/stats", token=TOKEN)
    assert stats["statusCode"] == 404
    assert body_of(stats)["detail"] == "Repository not found"


def test_create_repo_duplicate_409(handler):
    first = invoke(handler, "POST", "/repos", token=TOKEN, body={"name": "dup"})
    assert first["statusCode"] == 201
    second = invoke(handler, "POST", "/repos", token=TOKEN, body={"name": "dup"})
    assert second["statusCode"] == 409
    assert body_of(second)["detail"] == "Repository already exists"


def test_stats_seed_repo(handler):
    resp = invoke(handler, "GET", "/repos/repo-1/stats", token=TOKEN)
    assert resp["statusCode"] == 200
    body = body_of(resp)
    assert body["active_branches"] == 5  # repo-1 seed has 5 branches
    assert body["total_commits"] == 35  # 15 + 8 + 12
    assert body["open_prs"] == 3  # pr-1, pr-2, pr-3 all open on repo-1


def test_commits_sorted_desc(handler):
    resp = invoke(handler, "GET", "/repos/repo-1/commits", token=TOKEN)
    dates = [c["date"] for c in body_of(resp)["commits"]]
    assert dates == sorted(dates, reverse=True)
