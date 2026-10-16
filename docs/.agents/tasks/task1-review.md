# Task 1 review — local Strands agent (read-only) over the mock systems

The coder ported mahalo-dock's four-system SDLC assistant into a fresh `agent/` package that runs the reasoning loop on the Strands Agents SDK instead of LangChain. The package is env-driven config, a Bedrock-backed Strands agent (Claude Sonnet 4.5, 300s read timeout, `lava` profile), the three system prompts ported verbatim, 19 read-only tools over Jira/GitHub/Confluence/ServiceNow, a `python -m agent.chat` CLI/REPL baked to the dev-6 "Lava Dev" identity, and unit + live-integration tests. The write/propose/approve tools are deliberately deferred to Task 2.

I reviewed against the plan, the recorded verification evidence, the new files, and the mahalo-dock originals (read-only) for byte-for-byte parity. Per the task I did not re-run the suites or the venv install — I trusted the recorded commands/output and limited myself to reading files and inspecting git state.

Watch for: nothing blocking. Two non-blocking notes — the live Bedrock + tunnel path is still unexercised (by design, deferred to the user) [confirmed], and the agent registers tools but has no explicit tool-count assertion in the committed tests beyond the import smoke recorded in the verification file [confirmed].

**Verdict**: APPROVED

## High-level view

The port is faithful. All four tool modules (`jira_tools`, `github_tools`, `confluence_tools`, `servicenow_tools`) carry the mahalo-dock tool names, parameters, endpoints, docstrings, and human-readable output strings unchanged; the only structural changes are the LangChain `@tool` swapped for the Strands `@tool` and the per-instance closure factory replaced by module-level functions reading `agent.config.settings`. The six write tools (`jira_create_story`, `jira_update_story`, `github_create_branch`, `github_commit_files`, `github_open_pull_request`, `servicenow_create_incident`) are cleanly dropped, and the GitHub repo_id docstrings keep the "use a real NAME from github_list_repos, never invent repo-1" discipline.

Error handling is centralized in one `make_request` helper that returns the exact `Request failed with status {code}: {text}` string on any non-2xx, preserving demo parity across all four services.

The Bedrock wiring uses the parameter the coder verified against the installed strands-agents 1.61.1 source — `boto_client_config` for the botocore `Config(read_timeout=300)` — and supplies region through the `boto3.Session` because BedrockModel rejects `region_name` and `boto_session` together. Credentials come from the `lava` profile via the session with a fallback to the default chain; no AWS keys are baked in. Model construction is lazy, so `build_agent()` imports and constructs offline.

`prompts.py` is a verbatim copy of mahalo-dock's `BASE_PROMPT`, the three role prompts, and `ROLE_PROMPTS`, write-tool references intact. The dev-6 identity is injected at build time via a CURRENT USER IDENTITY block appended to the formatted developer prompt, and `chat.py` hard-codes that identity.

The offline bar is met and recorded: unit suite 13 passed, full suite 13 passed + 1 integration skip (exit 0), zero LangChain, import + offline `build_agent()` succeed. The live path remains for the user and is not claimed as verified.

<details>
<summary>Issues (2)</summary>

1. **Live path unverified (non-blocking, by design)** — the real Bedrock + tunnel run (`list my repositories` -> payment-service; `show my stories` -> PAY stories; integration test running not skipping) is deferred to the user; the task scoped this out of the offline bar, so it is not a Task 1 defect.
2. **Region/session coupling nuance (informational)** — region is carried only by the `boto3.Session`, not `region_name`, because BedrockModel forbids both; if a future caller passes `region_name` directly it will raise. Documented in code and README, so no action needed now.

</details>

<details>
<summary>Details</summary>

## Tool parity: names, params, endpoints, output

I diffed each ported module against its mahalo-dock source. Jira's seven read tools (`jira_list_projects`, `jira_list_developers`, `jira_search_stories`, `jira_get_stories_by_assignee`, `jira_get_story`, `jira_get_sprint_info`, `jira_get_board`) keep identical signatures, endpoint paths (`/projects`, `/developers`, `/projects/{id}/stories`, `/stories/{id}`, `/sprints/{id}`, `/projects/{id}/board`), docstrings, and the `_fetch_developers` / `_resolve_assignee` / `_format_stories` helpers verbatim — including the dev- passthrough, exact-name/email match, and single first-name/email-local-part match with ambiguity returning None. GitHub's four (`github_list_repos`, `github_get_pull_requests`, `github_get_commits`, `github_get_repo_stats`), Confluence's three (`confluence_search`, `confluence_get_page` with the 2000-char `... [content truncated]` suffix, `confluence_list_spaces`), and ServiceNow's five (`servicenow_list_deployments`, `servicenow_deployment_status_by_project`, `servicenow_list_incidents`, `servicenow_get_incident`, `servicenow_get_stats`) likewise match. The ServiceNow incidents docstring keeps the "omit status by default = all; open+investigating = being worked on" guidance, and `deployment_status_by_project` keeps the services/deployments join reporting PAY/CART/AUTH/PROD/ORD project IDs. Emoji markers (🔀 🚀 🔥 📄 📌) and count strings ("Found N stories ...", "Deployments (N found)") are preserved exactly.

The repo-name discipline survives the port: all three repo-scoped GitHub docstrings warn that repo_id MUST be a real NAME from `github_list_repos` (e.g. "payment-service") and never an invented id like "repo-1".

## Write tools dropped, read scope enforced

Against each original I confirmed the write tools are absent from both the module bodies and the exported `*_TOOLS` lists: no `jira_create_story`/`jira_update_story`, no `github_create_branch`/`github_commit_files`/`github_open_pull_request`, no `servicenow_create_incident`. No `__PROPOSAL__` strings exist in the new package. The `make_request` helper keeps POST/PUT branches for Task 2 reuse, but no Task 1 tool calls anything but GET, so the read-only contract holds.

## Bedrock configuration

`strands_agent._build_bedrock_model` builds `Config(read_timeout=300, connect_timeout=10, retries={"max_attempts": 3, "mode": "adaptive"})` and passes it as `boto_client_config` — the kwarg the verification record confirms via `inspect.signature(BedrockModel.__init__)` on the installed 1.61.1 package (`(self, *, boto_session=None, boto_client_config=None, region_name=None, ...)`). This is a verified API, not a guess. Region rides on the `boto3.Session(profile_name=settings.aws_profile, region_name=...)`; the code comments that BedrockModel raises "Cannot specify both region_name and boto_session". A bare `except Exception` falls back to the default credential chain when the `lava` profile is missing, which keeps offline import working. No AWS keys appear anywhere; `config.py` reads everything from `os.getenv` with defaults and does no network or credential work at import.

## Prompts and identity

`prompts.py` is byte-for-byte identical to mahalo-dock's `BASE_PROMPT` (ServiceNow PAY/CART/AUTH/PROD/ORD guidance and all eight IMPORTANT RULES with write-tool references intact), the three role prompts, and `ROLE_PROMPTS`. The dev-6 identity is injected at build time via a CURRENT USER IDENTITY block appended after `{integrations_context}`/`{user_name}`/`{user_role}` are filled for the developer persona, and `chat.py` hard-codes `developer_id="dev-6"` as the REPL default — matching the required "Lava Dev" identity.

## Tests

The unit suite exercises two layers with no network: `make_request` against an `httpx.MockTransport` (asserting URL, query params, the `X-API-Token` header value, and the exact 404 error string), and a representative tool per service through a monkeypatched `make_request` asserting endpoint/params and byte-for-byte output. Jira resolution is covered across dev- passthrough, full-name, email, first-name single match, email-local-part, and ambiguous/unknown -> None, plus the "Could not resolve" message. ServiceNow's default-all-incidents behavior (no status param) is asserted. The verification record shows 13 passed. The integration test probes `{JIRA_URL}/projects` with a 2s timeout and `pytest.skip`s on any connection error/non-200, and guards agent build and the live Bedrock call behind try/except skips, so it never fails the suite offline — the recorded full run was `13 passed, 1 skipped`, exit 0. Not tested offline (by design): the real Bedrock tool-calling round trip and the live tunnel assertions ("payment-service", "PAY-").

## Git state and isolation

The Task 1 commit `727ba7b` sits on `main` and is not pushed (origin/main remains at `af28f1e`). It added 20 files, all under `agent/` and `docs/` (the four tool modules, http helper, config, strands_agent, prompts, chat, two test files, three `__init__.py`, requirements.txt, README.md, plus the two task docs and the CONTINUATION/PLAN updates) — specific paths, not a blanket `git add -A`. No `.venv` path is tracked (`git ls-files agent/` returns nothing matching `.venv`). mahalo-dock is a separate repository and this commit touched none of its files; the parity work read from it only.

</details>

<details>
<summary>File map</summary>

- `agent/config.py` — frozen `Settings` dataclass, all values from `os.getenv` with task defaults; no creds/network at import.
- `agent/tools/http.py` — shared `make_request` with `X-API-Token` and the exact error string; single mock seam.
- `agent/tools/jira_tools.py` — 7 read tools + resolution helpers, ported verbatim; `JIRA_TOOLS`.
- `agent/tools/github_tools.py` — 4 read tools with real-repo-name docstrings; `GITHUB_TOOLS`.
- `agent/tools/confluence_tools.py` — 3 read tools incl. 2000-char truncation; `CONFLUENCE_TOOLS`.
- `agent/tools/servicenow_tools.py` — 5 read tools incl. by-project join; `SERVICENOW_TOOLS`.
- `agent/prompts.py` — verbatim BASE + 3 role prompts + `ROLE_PROMPTS`.
- `agent/strands_agent.py` — `build_agent(...)`; verified `boto_client_config`; lazy/offline-safe.
- `agent/chat.py` — single-shot + REPL, dev-6 identity.
- `agent/tests/test_tools_unit.py` — offline unit tests (HTTP + tool + resolution).
- `agent/tests/test_integration_live.py` — one live test, skips gracefully offline.
- `agent/requirements.txt` — pins `strands-agents==1.61.1`, `bedrock-agentcore==1.24.1`, `boto3`, `httpx`, `pytest`.
- `agent/README.md` — setup, env table, verified Strands API facts.
- `docs/CONTINUATION.md`, `docs/PLAN.md` — status updated to Task 1 code-complete.

Full diff: `git show 727ba7b`.

</details>
