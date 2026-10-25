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


# ---------------------------------------------------------------------------
# Real-mode (GITHUB_MODE=real) Gitea adapter tests (httpx mocked, no live Gitea).
#
# These assert the contract translation the GiteaBackend performs (repo_id->name
# path, _publicize URL rewrite, author-id mapping, BackendError->status mapping)
# and that the handler short-circuits the DynamoDB Store in real mode. The mock
# path above is unchanged: no test here sets GITHUB_MODE=real on the mock fixture.
# ---------------------------------------------------------------------------

import json  # noqa: E402

import httpx  # noqa: E402

GITEA_BASE = "http://gitea.example:3000"
GITEA_PUBLIC = "http://gitea.public.example"
OWNER = "mahalo_admin"


def _gitea_client_factory(routes_map):
    """Return an httpx.Client factory bound to a MockTransport.

    ``routes_map`` maps ``(METHOD, path)`` -> (status, json-or-None) where path is
    the Gitea API path after ``/api/v1``. A missing route returns 404.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in routes_map:
            return httpx.Response(404, json={"message": "Not Found"})
        status, payload = routes_map[key]
        if payload is None:
            return httpx.Response(status)
        return httpx.Response(status, json=payload)

    transport = httpx.MockTransport(_handler)
    real_client_cls = httpx.Client  # capture before any monkeypatch swaps it

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    return _factory


def _make_backend(monkeypatch, routes_map):
    import github.gitea_backend as gb

    monkeypatch.setattr(gb.httpx, "Client", _gitea_client_factory(routes_map))
    return gb.GiteaBackend(
        base_url=GITEA_BASE,
        token="gitea-adapter-token",
        owner=OWNER,
        public_url=GITEA_PUBLIC,
        demo_developer_id="dev-6",
    )


def test_real_get_repo_maps_repo_id_to_name_path(monkeypatch):
    # repo_id "payment-service" must resolve to /repos/<owner>/payment-service.
    routes_map = {
        ("GET", f"/api/v1/repos/{OWNER}/payment-service"): (
            200,
            {
                "name": "payment-service",
                "description": "Payment svc",
                "language": "Python",
                "default_branch": "main",
                "stars_count": 2,
                "open_issues_count": 1,
                "updated_at": "2026-10-14T03:30:56Z",
            },
        ),
    }
    backend = _make_backend(monkeypatch, routes_map)
    repo = backend.get_repo("payment-service")
    assert repo["id"] == "payment-service"
    assert repo["name"] == "payment-service"
    assert repo["last_push"] == "2026-10-14"  # ISO ts reduced to date


def test_real_get_repo_404_maps_to_backend_error(monkeypatch):
    from github.backend_base import BackendError

    backend = _make_backend(monkeypatch, {})  # no routes -> 404
    with pytest.raises(BackendError) as exc:
        backend.get_repo("nope")
    assert exc.value.status == 404


def test_real_pull_publicizes_url_and_maps_author(monkeypatch):
    # The owner login maps to the demo developer id; html_url is rewritten to the
    # public host.
    pr_payload = [
        {
            "number": 7,
            "title": "Add charge retry",
            "body": "desc",
            "user": {"login": OWNER, "full_name": "Mahalo Admin"},
            "state": "open",
            "head": {"ref": "feature/retry"},
            "base": {"ref": "main"},
            "created_at": "2026-10-10T01:02:03Z",
            "updated_at": "2026-10-11T01:02:03Z",
            "html_url": f"{GITEA_BASE}/{OWNER}/payment-service/pulls/7",
        }
    ]
    routes_map = {
        ("GET", f"/api/v1/repos/{OWNER}/payment-service/pulls"): (200, pr_payload),
    }
    backend = _make_backend(monkeypatch, routes_map)
    out = backend.list_pulls("payment-service")
    assert out["total"] == 1
    pr = out["pull_requests"][0]
    assert pr["id"] == "pr-7"
    assert pr["author_id"] == "dev-6"  # owner login -> demo developer id
    assert pr["url"] == f"{GITEA_PUBLIC}/{OWNER}/payment-service/pulls/7"


def test_real_non_owner_author_passthrough(monkeypatch):
    pr_payload = [
        {
            "number": 8,
            "title": "x",
            "user": {"login": "someone-else"},
            "state": "closed",
            "merged": True,
            "head": {"ref": "f"},
            "base": {"ref": "main"},
            "html_url": f"{GITEA_BASE}/{OWNER}/payment-service/pulls/8",
        }
    ]
    routes_map = {
        ("GET", f"/api/v1/repos/{OWNER}/payment-service/pulls"): (200, pr_payload),
    }
    backend = _make_backend(monkeypatch, routes_map)
    pr = backend.list_pulls("payment-service")["pull_requests"][0]
    assert pr["author_id"] == "someone-else"  # non-owner passthrough
    assert pr["status"] == "merged"  # merged=true -> "merged"


def test_real_publicizes_url_from_any_internal_host(monkeypatch):
    # REGRESSION: Gitea stamps html_url from the REQUEST host, which in the live
    # deploy is NOT base_url (CloudFront) but the origin host Gitea actually served
    # (localhost:3000 via the box, or the EIP host:3000 via CloudFront's origin
    # fetch). _publicize must rewrite the whole origin to the public URL regardless
    # of which internal host appears, so browser-clickable links always resolve.
    pr_payload = [
        {
            "number": 9,
            "title": "Internal-host link",
            "user": {"login": OWNER},
            "state": "open",
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
            # A host that differs from base_url (GITEA_BASE) entirely:
            "html_url": f"http://ec2-32-193-103-5.compute-1.amazonaws.com:3000/{OWNER}/payment-service/pulls/9",
        }
    ]
    routes_map = {
        ("GET", f"/api/v1/repos/{OWNER}/payment-service/pulls"): (200, pr_payload),
    }
    backend = _make_backend(monkeypatch, routes_map)
    pr = backend.list_pulls("payment-service")["pull_requests"][0]
    # Despite the EIP host in the raw html_url, the returned url is publicized.
    assert pr["url"] == f"{GITEA_PUBLIC}/{OWNER}/payment-service/pulls/9"


def test_real_create_branch_duplicate_409(monkeypatch):
    from github.backend_base import BackendError

    routes_map = {
        ("GET", f"/api/v1/repos/{OWNER}/payment-service"): (200, {"name": "payment-service"}),
        ("GET", f"/api/v1/repos/{OWNER}/payment-service/branches/main"): (
            200,
            {"name": "main"},
        ),
    }
    backend = _make_backend(monkeypatch, routes_map)
    with pytest.raises(BackendError) as exc:
        backend.create_branch("payment-service", "main", "main")
    assert exc.value.status == 409


@pytest.fixture
def real_handler(monkeypatch):
    """Load github.handler in real mode with the Gitea HTTP client mocked."""
    monkeypatch.setenv("GITHUB_MODE", "real")
    monkeypatch.setenv("GITEA_URL", GITEA_BASE)
    monkeypatch.setenv("GITEA_ADMIN_USER", OWNER)
    monkeypatch.setenv("GITEA_PUBLIC_URL", GITEA_PUBLIC)
    monkeypatch.setenv("GITEA_TOKEN", "gitea-adapter-token")
    monkeypatch.setenv("MOCK_GITHUB_TOKEN", TOKEN)
    monkeypatch.delenv("GITEA_TOKEN_PARAM", raising=False)
    monkeypatch.delenv("GITEA_TOKEN_FILE", raising=False)

    import github.gitea_backend as gb
    import github.handler as h

    importlib.reload(gb)
    importlib.reload(h)
    h._store = None
    h._router = None
    return h, gb


def test_real_handler_health_reports_real_mode_no_store(real_handler, monkeypatch):
    h, gb = real_handler
    # The adapter never touches DynamoDB: any route that triggers HTTP uses the
    # mocked client, and /health needs no backend call.
    monkeypatch.setattr(gb.httpx, "Client", _gitea_client_factory({}))
    resp = h.lambda_handler(make_event("GET", "/health"), None)
    assert resp["statusCode"] == 200
    assert body_of(resp)["mode"] == "real"
    # Store short-circuited: no DynamoDB Store constructed in real mode.
    assert h._store is None


def test_real_handler_list_repos_through_router(real_handler, monkeypatch):
    h, gb = real_handler
    routes_map = {
        ("GET", "/api/v1/user/repos"): (
            200,
            [{"name": "payment-service", "updated_at": "2026-10-14T00:00:00Z"}],
        ),
    }
    monkeypatch.setattr(gb.httpx, "Client", _gitea_client_factory(routes_map))
    resp = h.lambda_handler(
        make_event("GET", "/repos", token=TOKEN), None
    )
    assert resp["statusCode"] == 200
    repos = body_of(resp)["repos"]
    assert [r["id"] for r in repos] == ["payment-service"]
    # Auth still enforced on the real path.
    denied = h.lambda_handler(make_event("GET", "/repos"), None)
    assert denied["statusCode"] == 401


def test_real_handler_ssm_token_resolution(monkeypatch):
    """GITEA_TOKEN_PARAM resolves via boto3 SSM once at cold start."""
    monkeypatch.setenv("GITHUB_MODE", "real")
    monkeypatch.setenv("GITEA_URL", GITEA_BASE)
    monkeypatch.setenv("GITEA_TOKEN_PARAM", "/mahalo/gitea/adapter-token")
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    monkeypatch.delenv("GITEA_TOKEN_FILE", raising=False)
    monkeypatch.setenv("MOCK_GITHUB_TOKEN", TOKEN)

    import github.gitea_backend as gb
    import github.handler as h

    importlib.reload(gb)
    importlib.reload(h)

    captured = {}

    class _FakeSsm:
        def get_parameter(self, Name, WithDecryption):
            captured["name"] = Name
            captured["decrypt"] = WithDecryption
            return {"Parameter": {"Value": "resolved-secret-token"}}

    import boto3

    monkeypatch.setattr(boto3, "client", lambda svc, *a, **k: _FakeSsm())
    monkeypatch.setattr(gb.httpx, "Client", _gitea_client_factory({}))

    h._store = None
    h._router = None
    store, _ = h._get_router()
    assert store is None  # real mode: no DynamoDB Store
    assert captured == {"name": "/mahalo/gitea/adapter-token", "decrypt": True}


def test_mock_mode_unaffected_by_real_imports(handler):
    """Sanity: the mock fixture still reports mock mode after the real tests."""
    resp = invoke(handler, "GET", "/health")
    assert body_of(resp)["mode"] == "mock"
    assert json.loads(resp["body"])["mode"] == "mock"
