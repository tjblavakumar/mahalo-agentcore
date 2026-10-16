# Task 1 Implementation Plan — Local Strands Agent (read-only) vs live mocks

This plan builds "Task 1" of mahalo-agentcore: a Strands Agents SDK agent that runs LOCALLY and
answers READ questions by calling the live mock enterprise systems (Jira/Confluence/GitHub/ServiceNow)
over an SSH tunnel, with ZERO LangChain anywhere. The coder follows these items in order; each item
leaves the package in a buildable/importable state.

## Context the coder must honor (read first)

- Work ONLY under `d:\<USER>\LavaCode\AI\mahalo-agentcore`. NEVER write to or edit
  `d:\<USER>\LavaCode\AI\mahalo-dock` (READ allowed only, to copy exact output-formatting
  strings for byte-for-byte parity — never modify it).
- Do NOT redeploy any backend. Do NOT run `aws sso login` or open SSH tunnels. The live integration
  test MUST skip gracefully when the tunnel/mocks are unreachable so the whole suite passes offline.
- Zero LangChain imports anywhere in the new `agent/` package. The mahalo-dock originals import
  `from langchain_core.tools import tool`; the port MUST replace that with the Strands `@tool`.
- All new code lives under `agent/` as a Python package (see the file map below).
- Review gate file for the implement-and-review loop:
  `d:\<USER>\LavaCode\AI\mahalo-agentcore\docs\.agents\tasks\task1-review.json`
  with shape `{"verdict":"APPROVED"|"CHANGES_REQUESTED","findings":[...],"reviewDoc":"..."}`.
  The coder and reviewer must honor this file; the coder does not write it (the reviewer does), but
  the coder should fix every finding it lists on later iterations.

## Design decisions (made here; do not re-decide)

1. **Tool structure — module-level `@tool` functions reading config from a module singleton, not
   per-instance factories.** mahalo-dock used `create_jira_tools(url, token)` closures because each
   logged-in user had its own integration URLs/tokens from a DB. Task 1 is a single local process with
   env-driven config, so a closure factory adds no value and complicates registering tools with the
   Strands `Agent`. Instead, each `agent/tools/*_tools.py` defines plain module-level `@tool` functions
   that pull their base URL + token from `agent/config.py`. This keeps tool signatures clean for the LLM
   and makes registration a simple import list.
2. **Shared HTTP helper in `agent/tools/http.py`.** All four services repeat the same
   `X-API-Token` request/response/error pattern. Consolidate into one helper so the unit tests can
   monkeypatch a single function and so error formatting ("Error: Request failed with status {code}:
   {text}") is identical everywhere. Rationale: single seam for mocking, single place for parity-critical
   error strings.
3. **Botocore timeout via `BedrockModel(boto_client_config=Config(...))`.** The official Strands Python
   API (`strands.models.bedrock.BedrockModel.__init__`) accepts `boto_client_config: botocore.config.Config`
   plus `boto_session`, `region_name`, and model config (`model_id`, `temperature`, ...). This mirrors
   mahalo-dock's `botocore Config(read_timeout, connect_timeout, retries)` pattern. The AWS profile is
   supplied by constructing a `boto3.Session(profile_name=...)` (from `AWS_PROFILE`/config) and passing it
   as `boto_session`, so no AWS keys are baked into code. VERIFY the exact parameter name against the
   installed 1.61.1 package (step 2) before relying on it — the docs track the latest release.
4. **REPL identity is hard-coded to dev-6 / "Lava Dev" / developer role.** mahalo-dock resolves this via
   `developer_id_for_email` (lava@dev.com -> dev-6). Task 1 has no login, so bake dev-6 directly into the
   REPL's system-prompt identity block so "show my stories" resolves to dev-6 deterministically. Rationale:
   matches the verified seed-data identity and the CONTINUATION.md requirement.
5. **Prompts ported verbatim from mahalo-dock.** `BASE_PROMPT`, the three role prompts, and `ROLE_PROMPTS`
   are copied as-is (including write-tool references, kept intact per the task even though write tools
   aren't registered in Task 1). Placeholders `{integrations_context}`, `{user_name}`, `{user_role}` are
   filled for the developer persona.
6. **Tool output strings copied byte-for-byte from mahalo-dock** (bullets, emoji markers, "Found N
   stories ...", "Error: ..." etc.) so demo output matches and the reviewer can confirm parity.

## Verified facts (so the coder doesn't re-derive)

- No venv exists yet under `agent/` (dir contains only `.gitkeep`). `.venv/` is already in `.gitignore`.
- strands-agents is NOT installed anywhere locally yet — the coder MUST create the venv and install, then
  verify the API against the installed source.
- mahalo-dock tool contracts, formatting strings, and the LangChain `@tool` usage to be replaced are in
  `mahalo-dock/backend/app/agent/tools/{jira,github,confluence,servicenow}_tools.py`.
- Prompts to port: `mahalo-dock/backend/app/agent/prompts.py`.
- Identity mapping (dev-6 = "Lava Dev", lava@ecommerce.io): `mahalo-dock/backend/app/services/identity.py`.
- Bedrock config pattern reference: `mahalo-dock/backend/app/agent/llm_factory.py` (`_build_bedrock`).
- Official Strands Python API confirms `BedrockModel(... boto_session=, boto_client_config=, region_name=,
  **model_config)` and the quickstart import pattern `from strands import Agent, tool` /
  `from strands.models import BedrockModel`. Treat as high-confidence but VERIFY against installed 1.61.1.

---

## Implementation items

- [ ] 1. Create the package skeleton and pinned requirements.
      Create `agent/__init__.py` (empty or a one-line docstring), `agent/tools/__init__.py`,
      `agent/tests/__init__.py`, and `agent/requirements.txt` pinning exactly:
      `strands-agents==1.61.1`, `bedrock-agentcore==1.24.1`, `boto3`, `httpx`, `pytest`.
      Files: `agent/__init__.py`, `agent/tools/__init__.py`, `agent/tests/__init__.py`,
      `agent/requirements.txt`.
      Verify: `py -3.13 -c "import pathlib; print(pathlib.Path('agent/requirements.txt').read_text())"`
      prints the five pinned lines (sanity check only; real verification is step 2's install).

- [ ] 2. Create the venv, install requirements, and VERIFY the installed strands-agents 1.61.1 API.
      From the `agent/` dir run `py -3.13 -m venv .venv` (fall back to `python -m venv .venv` if 3.13 is
      absent), then install `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`. Then confirm,
      against the INSTALLED package source under `agent/.venv/Lib/site-packages/strands/`, the two
      API facts this plan depends on and record them in `agent/README.md` (step 11):
      (a) the exact import for the tool decorator — expected `from strands import tool` (and `Agent`);
      (b) the exact way to pass a botocore `Config` into the Bedrock model — expected
      `from strands.models import BedrockModel` with `BedrockModel(boto_client_config=Config(...),
      boto_session=..., region_name=..., model_id=...)`. If the installed package differs from these
      expectations, use what the installed package actually exposes (read
      `agent/.venv/Lib/site-packages/strands/models/bedrock.py` and the top-level `strands/__init__.py`),
      and adjust steps 3–8 accordingly. Do NOT guess.
      Files: `agent/.venv/` (generated, git-ignored).
      Verify: `.\.venv\Scripts\python.exe -c "import strands, strands.models.bedrock as b; from strands
      import Agent, tool; from strands.models import BedrockModel; import importlib.metadata as m;
      print(m.version('strands-agents'))"` prints `1.61.1` and raises no ImportError. Run from `agent/`.

- [ ] 3. Write `agent/config.py` — env-driven configuration.
      Provide a single config object/dataclass (e.g. `Settings` with a module-level `settings` instance)
      exposing, with the task's defaults:
      Bedrock: `BEDROCK_MODEL_ID` default `us.anthropic.claude-sonnet-4-5-20250929-v1:0`,
      `AWS_REGION` default `us-east-1`, `AWS_PROFILE` default `lava`,
      `BEDROCK_READ_TIMEOUT` default `300`, `BEDROCK_CONNECT_TIMEOUT` default `10`.
      Mock bases + tokens (env-overridable):
      `JIRA_URL=http://localhost:5001` / `JIRA_TOKEN=mock-jira-token-12345`;
      `CONFLUENCE_URL=http://localhost:5002` / `CONFLUENCE_TOKEN=mock-confluence-token-12345`;
      `GITHUB_URL=http://localhost:5003` / `GITHUB_TOKEN=mock-github-token-12345`;
      `SERVICENOW_URL=http://localhost:5004` / `SERVICENOW_TOKEN=mock-servicenow-token-12345`.
      Also `HTTP_TIMEOUT` default `10.0`. Read every value with `os.getenv(..., default)`; do NOT bake AWS
      keys. Importing this module MUST NOT require live creds or network.
      Files: `agent/config.py`.
      Verify: `.\.venv\Scripts\python.exe -c "from agent.config import settings;
      print(settings.jira_url, settings.bedrock_read_timeout, settings.bedrock_model_id)"` run from the
      repo root with `PYTHONPATH` set to repo root (or `py -m`), printing the defaults.

- [ ] 4. Write `agent/tools/http.py` — shared httpx request helper with `X-API-Token`.
      One function (e.g. `make_request(base_url, token, endpoint="", params=None, method="GET",
      body=None, timeout=None) -> dict`) that sets header `{"X-API-Token": token}`, builds
      `f"{base_url}{endpoint}"`, uses `httpx.Client(timeout=settings.http_timeout)`, returns
      `response.json()` on status in `(200, 201)`, else returns
      `{"error": f"Request failed with status {response.status_code}: {response.text}"}`
      (exact string, matching mahalo-dock). This is the single seam the unit tests monkeypatch. READ-ONLY
      scope: GET is the only method the Task 1 tools call, but keep the signature general.
      Files: `agent/tools/http.py`.
      Verify: covered by step 9's unit tests (asserts endpoint, params, header, and error string); for a
      quick smoke, `.\.venv\Scripts\python.exe -c "from agent.tools.http import make_request; print(callable(make_request))"`.

- [ ] 5. Write `agent/tools/jira_tools.py` — 7 read tools as module-level Strands `@tool` functions.
      Port VERBATIM contracts, docstrings, and output formatting from
      `mahalo-dock/backend/app/agent/tools/jira_tools.py`, replacing the LangChain `@tool` with the
      Strands `@tool` (import confirmed in step 2) and the closure factory with module-level functions that
      call `make_request(settings.jira_url, settings.jira_token, ...)`. Include the private helpers
      `_fetch_developers()`, `_resolve_assignee()` (dev- passthrough; exact full name/email match; then
      first-name/email-local-part/partial single match), and `_format_stories()`. Tools:
      `jira_list_projects` (GET /projects -> id/name/description),
      `jira_list_developers` (GET /developers -> id/name/email),
      `jira_search_stories(query?, project_id?, status?, assignee?)` (per-project GET
      /projects/{id}/stories with params {status, assignee}; loop all projects if no project_id;
      client-side keyword filter on title/description; resolve assignee name->dev-id),
      `jira_get_stories_by_assignee(assignee, status?, project_id?)`,
      `jira_get_story(story_id)` (GET /stories/{story_id}),
      `jira_get_sprint_info(project_id)` (GET /sprints/{project_id}),
      `jira_get_board(project_id)` (GET /projects/{project_id}/board).
      Do NOT port the write tools (`jira_create_story`, `jira_update_story`) — Task 2. Export a list
      `JIRA_TOOLS = [...]` of the 7 read tools.
      Files: `agent/tools/jira_tools.py`.
      Verify: `.\.venv\Scripts\python.exe -c "from agent.tools.jira_tools import JIRA_TOOLS; print(len(JIRA_TOOLS))"`
      prints `7`; full behavior checked by step 9 unit tests.

- [ ] 6. Write `agent/tools/github_tools.py`, `agent/tools/confluence_tools.py`,
      `agent/tools/servicenow_tools.py` — remaining read tools (same port pattern as step 5).
      This is one item: identical change pattern across three files. Port VERBATIM contracts/docstrings/
      formatting from the matching mahalo-dock modules; drop all write tools.
      GitHub read tools: `github_list_repos` (GET /repos), `github_get_pull_requests(repo_id, status?,
      author_id?)` (GET /repos/{repo_id}/pulls), `github_get_commits(repo_id, branch?, author?)`
      (GET /repos/{repo_id}/commits), `github_get_repo_stats(repo_id)` (GET /repos/{repo_id}/stats).
      Keep the CRITICAL docstring rule: repo_id MUST be a REAL repo NAME from `github_list_repos`
      (e.g. "payment-service"); never invent ids like repo-1/repo-4/product-service; always call
      `github_list_repos` first. Export `GITHUB_TOOLS` (4).
      Confluence read tools: `confluence_search(query, space_id?)` (GET /search params {q, space_id}),
      `confluence_get_page(page_id)` (GET /pages/{page_id}; truncate content >2000 chars with the exact
      "... [content truncated]" suffix), `confluence_list_spaces` (GET /spaces). Export `CONFLUENCE_TOOLS` (3).
      ServiceNow read tools: `servicenow_list_deployments(service?, environment?, status?)`
      (GET /deployments), `servicenow_deployment_status_by_project()` (GET /services AND GET /deployments,
      join on service id, group by service, report project_id PAY/CART/AUTH/PROD/ORD), 
      `servicenow_list_incidents(severity?, status?, service?)` (GET /incidents; OMIT status by default =
      all; keep the "working on/addressing" = open+investigating docstring guidance),
      `servicenow_get_incident(incident_id)` (GET /incidents/{id}), `servicenow_get_stats()` (GET /stats).
      Export `SERVICENOW_TOOLS` (5). Drop `servicenow_create_incident` (Task 2).
      Files: `agent/tools/github_tools.py`, `agent/tools/confluence_tools.py`,
      `agent/tools/servicenow_tools.py`.
      Verify: `.\.venv\Scripts\python.exe -c "from agent.tools.github_tools import GITHUB_TOOLS;
      from agent.tools.confluence_tools import CONFLUENCE_TOOLS; from agent.tools.servicenow_tools import
      SERVICENOW_TOOLS; print(len(GITHUB_TOOLS), len(CONFLUENCE_TOOLS), len(SERVICENOW_TOOLS))"`
      prints `4 3 5`.

- [ ] 7. Write `agent/prompts.py` — ported system prompts.
      Copy VERBATIM from `mahalo-dock/backend/app/agent/prompts.py`: `BASE_PROMPT`,
      `PRODUCT_MANAGER_PROMPT`, `DEVELOPER_PROMPT`, `EXECUTIVE_PROMPT`, and the `ROLE_PROMPTS` dict.
      Keep the write-tool references inside the prompt text intact (per task). Placeholders
      `{integrations_context}`, `{user_name}`, `{user_role}` remain in the text; they are filled by the
      agent builder (step 8), not here.
      Files: `agent/prompts.py`.
      Verify: `.\.venv\Scripts\python.exe -c "from agent.prompts import ROLE_PROMPTS;
      print(sorted(ROLE_PROMPTS))"` prints `['developer', 'executive', 'product_manager']`.

- [ ] 8. Write `agent/strands_agent.py` — build and return the configured Strands Agent.
      Expose `build_agent(role="developer", user_name="Lava Dev", user_role="Developer",
      developer_id="dev-6") -> Agent`. Steps:
      (a) build botocore `Config(read_timeout=settings.bedrock_read_timeout,
      connect_timeout=settings.bedrock_connect_timeout, retries={"max_attempts": 3, "mode": "adaptive"})`;
      (b) build `boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)` so
      creds come from the `lava` profile (do NOT bake keys); if the profile is absent fall back to the
      default credential chain;
      (c) construct `BedrockModel(model_id=settings.bedrock_model_id, region_name=settings.aws_region,
      boto_session=session, boto_client_config=config)` — use the EXACT parameter names verified in step 2;
      (d) assemble the system prompt: `ROLE_PROMPTS[role].format(integrations_context=<short string listing
      Jira/Confluence/GitHub/ServiceNow with their base URLs>, user_name=user_name, user_role=user_role)`,
      then append a CURRENT USER IDENTITY block stating the logged-in user is developer id `developer_id`
      and that "me"/"my"/"mine"/"assigned to me" must use that id directly (mirror mahalo-dock's wording);
      (e) register all read tools: `tools = [*JIRA_TOOLS, *GITHUB_TOOLS, *CONFLUENCE_TOOLS,
      *SERVICENOW_TOOLS]`;
      (f) return `Agent(model=model, tools=tools, system_prompt=system_prompt)` (confirm the `Agent`
      constructor kwargs against the installed package in step 2).
      Importing this module and calling `build_agent()` MUST succeed WITHOUT live AWS creds or network
      (model construction is lazy; only an actual agent call needs creds). If `build_agent()` touches the
      network, defer that work so import/build stays offline-safe.
      Files: `agent/strands_agent.py`.
      Verify: `.\.venv\Scripts\python.exe -c "from agent.strands_agent import build_agent;
      a = build_agent(); print(type(a).__name__)"` prints `Agent` with no network call. If this requires
      creds, that is a bug to fix in this step.

- [ ] 9. Write `agent/tests/test_tools_unit.py` — offline unit tests for the HTTP wrappers.
      Use the venv pytest. Monkeypatch `agent.tools.http.make_request` (the shared seam) OR use
      `httpx.MockTransport`/`respx`; the plan's design (step 2 decision) makes monkeypatching the shared
      helper the simplest. Cover, at minimum:
      (a) one representative tool per service asserts the endpoint path, query params, and that the
      `X-API-Token` header value is passed (when testing at the httpx layer) AND that the returned string
      matches the exact mahalo-dock output formatting (bullets/emoji/counts);
      (b) jira assignee name->dev-id resolution (`_resolve_assignee`): "dev-6" passthrough, full-name and
      email match, first-name single-match, and ambiguous/no-match returns None / the "Could not resolve"
      message;
      (c) the error path: a non-2xx response yields the exact `Error: Request failed with status {code}:
      {text}` string. These tests MUST pass with no network.
      Files: `agent/tests/test_tools_unit.py`.
      Verify: `.\.venv\Scripts\python.exe -m pytest agent/tests/test_tools_unit.py -q` run from repo root
      — all tests pass with no network access.

- [ ] 10. Write `agent/tests/test_integration_live.py` — one live test that skips gracefully.
      Single test that first probes reachability (short-timeout GET `{JIRA_URL}/projects` with the token
      header); on any connection error / non-200, call `pytest.skip("mocks/tunnel unreachable")` so the
      suite passes offline. When reachable AND AWS creds are available, build the dev-6 developer agent and
      assert: a "list my repositories" message yields output containing `payment-service`; a "show my
      stories" message (dev-6) yields output containing PAY stories (e.g. contains `PAY-`). Guard the AWS
      part so a missing/expired profile also skips rather than fails. The test MUST NEVER fail the suite
      when the tunnel is down.
      Files: `agent/tests/test_integration_live.py`.
      Verify: `.\.venv\Scripts\python.exe -m pytest agent/tests -q` run from repo root with the tunnel
      DOWN — the integration test reports skipped and the overall run passes (exit code 0).

- [ ] 11. Write `agent/chat.py` — CLI/REPL entrypoint, and `agent/README.md`.
      `agent/chat.py`: runnable as `python -m agent.chat "show my stories"` (single-shot: build the
      developer/dev-6 agent, send the one message, print the agent's text, exit) and with no args as an
      interactive REPL (loop reading stdin, printing responses, exit on `quit`/`exit`/EOF). Keep it small.
      Guard imports so `import agent.chat` works WITHOUT live creds; only an actual run (sending a message)
      needs AWS creds and the tunnel. Build the agent via `build_agent(role="developer",
      user_name="Lava Dev", user_role="Developer", developer_id="dev-6")`.
      `agent/README.md`: how to create the venv, install, set `AWS_PROFILE=lava`, open the tunnel
      (reference CONTINUATION.md; do NOT instruct to run it here), configure env vars, run the REPL, and
      run tests. Record the two verified API facts from step 2 (tool decorator import path; how the
      botocore Config is passed to BedrockModel) and note the installed strands-agents version.
      Files: `agent/chat.py`, `agent/README.md`.
      Verify: `.\.venv\Scripts\python.exe -c "import agent.chat"` succeeds with no creds/network;
      and `.\.venv\Scripts\python.exe -m pytest agent/tests -q` still passes (regression check).

- [ ] 12. Final guardrail check — assert zero LangChain anywhere in the new package.
      Confirm no `langchain` import/string exists under `agent/` (excluding `.venv/`). This is a
      correctness gate the task mandates, not a substitute for the functional verification in steps 9–11.
      Files: none (verification only).
      Verify: from repo root run
      `.\agent\.venv\Scripts\python.exe -c "import pathlib,sys; bad=[str(p) for p in
      pathlib.Path('agent').rglob('*.py') if '.venv' not in p.parts and 'langchain' in
      p.read_text(encoding='utf-8').lower()]; print('LANGCHAIN FOUND:',bad) or sys.exit(1 if bad else 0)"`
      — prints an empty list and exits 0. Also re-run the full suite
      `.\agent\.venv\Scripts\python.exe -m pytest agent/tests -q` and confirm it passes offline.

## Notes / open assumptions (reasonable defaults chosen; coder may adjust if the installed API differs)

- The exact Strands `Agent` call return shape (how to extract text from `agent("msg")`) is confirmed by
  the quickstart to be stringifiable, but the coder should confirm against the installed package when
  wiring `chat.py` and the integration assertions (e.g. `str(result)` vs `result.message`).
- If strands-agents 1.61.1 names the botocore-config parameter differently from `boto_client_config`
  (the current docs' name), step 2 is where that is caught; steps 8 and 11 then use the real name.
- `integrations_context` content is a short, static listing of the four systems and their base URLs —
  there is no DB of per-user integrations in Task 1.
- Do not add the propose/approve write flow, synthesis pass, or session persistence — those are Task 2+.
