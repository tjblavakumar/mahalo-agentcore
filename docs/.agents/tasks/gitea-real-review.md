# Review — Gitea real-mode seed + flip + E2E

Point the deployed GitHub mock Lambda at a real Gitea backend over CloudFront, seed that Gitea with 5 repos / feature branches / labeled PRs under a single admin owner, and prove the whole path works through the deployed agent (reads return real data; a HITL write creates a real branch). This review reads the recorded evidence only — the AWS/SSM/CDK/thin-API commands were run by the coder and their outputs are quoted in the reports; I did not re-run them. I checked the committed diff, the seed script, the appended plan progress, and the E2E report against the task's acceptance criteria and hard constraints.

**Watch for:** the code commit bundles a `httpx` vendor shim (`gitea_backend.py` + `_vendor/`) that the plan's D3 did not list — this is a documented, justified fix for a real-mode cold-start crash, not a blocking issue (confirmed). A cosmetic PR-URL host mismatch is documented and out of scope (confirmed).

**Verdict**: APPROVED

## High-level view

Seeding (STEP A) is faithful to the source of truth. The committed `gitea/seed_gitea.py` encodes the exact repo/branch/PR matrix from `tools-lambdas/github/seed_data.py` with the resolved persona name + role + linked story in every commit message and PR title/body, all owned by `mahalo_admin`, and every create is guarded by a GET existence check so re-runs are safe. The on-box verification quoted in the report shows repo count = 5 and lists the branches + labeled open PRs for payment-service and auth-service.

The flip (STEP B) is a two-line env change in `infra-cdk/app.py` pointing `GITEA_URL` and `GITEA_PUBLIC_URL` at the CloudFront HTTPS endpoint, with admin user, demo dev id, and token-param name preserved. The deployed Lambda config quoted from `get-function-configuration` confirms `GITHUB_MODE=real` and both URLs on CloudFront. Only `MahaloMockGithubStack` was deployed; `MahaloGiteaStack` was not touched. The `ssm:GetParameter` grant was already present, so no IAM edit was needed.

A real-mode deploy gap surfaced and was fixed: the adapter imports `httpx`, which the Lambda asset never pip-installs, so the first real read 500'd with `ModuleNotFoundError`. The coder vendored httpx + its pure-Python closure under `github/_vendor/` and appended a `sys.path` fallback before the import. This is extra scope beyond the plan's "commit only app.py," but it is the difference between a deployed-but-broken system and a working one, which is this task's actual success bar.

E2E (STEP C) is evidenced by real responses: reads as Dev return all 5 repos and the 3 labeled payment-service PRs; the HITL write returned a `pending_approval` proposal with an `interrupt_id`, the approve call executed, and the created branch was confirmed present in real Gitea (HTTP 200), with the reject path confirmed to have written nothing (HTTP 404).

Hard constraints hold: no per-persona Gitea users, SG 3000 not opened to the world, single-user + simple-attribution kept, and no secret values in the diff.

<details>
<summary>Issues (2)</summary>

1. **Vendor shim beyond plan scope** — the code commit includes `gitea_backend.py` + `_vendor/` in addition to `app.py`, which D3 said to commit alone. Non-blocking: it is a required, documented fix for a real-mode crash and is appended (not prepended) so dev/test keeps its own httpx. No action required; noted for the record.
2. **PR-URL host mismatch (cosmetic)** — agent-echoed PR `url` fields render the EIP host instead of the CloudFront domain. Non-blocking and documented as out of scope; the browser demo opens CloudFront directly. No action required.

</details>

<details>
<summary>Details</summary>

## STEP A — seeding fidelity and idempotency

The committed `gitea/seed_gitea.py` is the seeding source and it matches the plan matrix line-for-line. All objects are created under `OWNER = "mahalo_admin"`; the git commit author is never overridden, so attribution lives only in text (the locked simple-attribution decision). Every commit message carries `— authored by <Name> (<Role>)  [<STORY>]` and every PR title/body carries `— authored by <Name> (<Role>)` plus `Linked story: <STORY>`. Spot-checking against the jira persona table: PAY-105 → Marcus Chen (Product Manager), PAY-106 → Raj Patel (Developer), PAY-108 → David Kim (Executive), AUTH-306 → Lava Dev (Developer), PROD-403 → Emily Zhang (Developer), ORD-503 → David Kim (Executive) — all present and correctly labeled in the script data.

Idempotency is real, not claimed: `ensure_repo`/`ensure_branch`/`ensure_file`/`ensure_pr` each issue a GET (with `allow_404`) and skip or short-circuit when the object already exists (repo 200, branch 200, file sha present, PR with matching head ref). The report corroborates this operationally — the first run hit a transient `403 cannot lock ref` race on cart-service, and a clean re-run (`9638e290-...`) returned `Status=Success`, `RC=0`, which is exactly the behavior an idempotent seeder should exhibit.

PAY-107 is handled as the plan specified: branch + representative file + commit, but `pr_title`/`pr_body` are `None`, so `main()` skips `ensure_pr` for it. That yields 10 feature branches and 9 open PRs. The report explicitly reconciles the plan's "11 branches" as an arithmetic slip (payment-service has 4 feature branches, not 5), and 10 matches `seed_data.py`. The on-box verification quotes `REPO COUNT: 5`, the five repo names, payment-service's 4 feature branches + 3 labeled open PRs, and auth-service's 2 feature branches + 2 labeled open PRs — satisfying the "quote the on-box verification for a couple of repos" requirement.

## STEP B — env flip and deployed config

The `git diff main -- infra-cdk/app.py` shows exactly the intended two-value change: `GITEA_URL` and `GITEA_PUBLIC_URL` moved from the `gitea.internal`/`gitea.public` placeholders to `https://d3ec76atxiij9a.cloudfront.net`, with `GITEA_ADMIN_USER=mahalo_admin`, `DEMO_DEVELOPER_ID=dev-6`, and `GITEA_TOKEN_PARAM=/mahalo/gitea/adapter-token` untouched. The quoted `get-function-configuration` output confirms the deployed reality: `GITHUB_MODE=real`, both URLs on CloudFront HTTPS, admin user, demo dev id, and token param all as required. Only `MahaloMockGithubStack` was deployed (`UPDATE_COMPLETE`); `MahaloGiteaStack` was left alone, so its 0.0.0.0/0 default SG rule was never re-applied. The `ssm:GetParameter` grant was confirmed already present in `mock_service_stack.py`'s real-mode branch, so no IAM change was made or needed.

### httpx vendoring — scope beyond the plan, justified

The real-mode adapter imports `httpx`, which the `Code.from_asset("../tools-lambdas")` path does not pip-install (the mock path needs no third-party deps, and httpx lived only in `requirements-dev.txt`, which the asset excludes). The first real read 500'd with `ModuleNotFoundError: No module named 'httpx'`, quoted from CloudWatch in the report. With no Docker on the VDI, the coder vendored `httpx==0.28.1` and its pure-Python closure into `tools-lambdas/github/_vendor/` and added a `sys.path.append(_VENDOR)` fallback in `gitea_backend.py`. I read the top of `gitea_backend.py` to confirm the shim is appended (not prepended) and guarded by `os.path.isdir`, so a dev/test venv that already has httpx keeps using its own copy and only the deployed Lambda resolves from `_vendor/`. The exclude list keeps `_vendor/` out of the other three service Lambdas. This is extra scope versus D3's "stage only app.py," but it is the fix that makes real mode actually run, and the task is explicitly graded on the deployed system working. Recorded as an issue for transparency, not as a blocker.

## STEP C — end-to-end through the deployed agent

The report quotes actual thin-API behavior, not a plan restatement. C1 (read as Dev, "list my repositories") returned all 5 real repos. C2 ("show open pull requests for payment-service") returned the 3 seeded PRs with persona labels and real Gitea PR numbers #1–#3. C3 (HITL write) is the load-bearing check: call 1 returned `status=pending_approval` with a concrete `interrupt_id` and a `create_branch` proposal for `feature/demo-smoke`; call 2 to `/chat/approve` with `{approved:true}` returned a success message; and the branch was confirmed to exist via a direct on-box `GET /repos/mahalo_admin/payment-service/branches/feature/demo-smoke → HTTP 200`. C4's reject path returned HTTP 404 for the proposed branch, confirming reject writes nothing. The report also notes the deployed `/chat/approve` contract uses a boolean `approved` rather than the plan's `decision` string — a harmless accurate correction, and the two-call interrupt/approve flow still executed as designed.

## Hard constraints and secret hygiene

No per-persona Gitea users are created (the seeder only ever writes under `mahalo_admin`). SG 3000 was not opened to 0.0.0.0/0 — `MahaloGiteaStack` was not deployed, and the plan's reachability path is the CloudFront prefix-list rule. `HTTP_PORT=3000` and the `0.0.0.0` bind are noted unchanged. Single-user + simple-attribution is preserved by construction. Scanning the diff for secret-looking values turned up only SSM parameter *names* (`/mahalo/gitea/adapter-token`), the token read from env at runtime (`GITEA_TOKEN = os.environ.get(...)`), literal demo placeholders (`BASE32SECRET`, `<EntityDescriptor/>`), and the pre-existing non-secret `MOCK_GITHUB_TOKEN=mock-github-token-12345` mock constant (unchanged, not a credential). No real token or password value is committed.

## Deliverables

`docs/GITEA-REAL-PLAN.md` was appended, not rewritten: STEP 2 / STEP 3 / STEP 4 are checked off with dated one-line summaries and a live-state note quoting the real results, and the earlier STEP 1 content and locked decisions are intact. `docs/.agents/tasks/gitea-real-e2e.md` exists and captures the seeding command ids + verification output, the deploy result + env dump, and the C1–C4 request/response evidence. The code change is committed on branch `gitea-real-mode-flip`; `git diff main -- infra-cdk/app.py` is the intended two-line change, and the docs/helper scripts are in a separate docs commit.

</details>

<details>
<summary>File map</summary>

- `infra-cdk/app.py` — `_GITEA_ENV` URLs flipped to the CloudFront HTTPS endpoint (the only intended code change).
- `tools-lambdas/github/gitea_backend.py` — appended `_vendor` `sys.path` fallback before `import httpx` (real-mode crash fix).
- `tools-lambdas/github/_vendor/**` — vendored httpx + pure-Python deps, shipped only in the github Lambda.
- `gitea/seed_gitea.py` — idempotent stdlib seeder encoding the repo/branch/PR matrix with persona labels.
- `gitea/verify_gitea.py` — on-box verification helper.
- `docs/.agents/tasks/gitea-real-e2e.md` — E2E evidence report (STEP A/B/C outputs).
- `docs/GITEA-REAL-PLAN.md` — appended STEP 2/3/4 progress + live-state note.

Full diff: `git diff main..gitea-real-mode-flip`.

</details>
