# Task 2 — Implementation Plan: propose/approve HITL write tools

Derived from the approved `task2-design.md` and `task2-hitl-decision.md`. The
architecture is already decided (native Strands 1.61.1 interrupt via a
`BeforeToolCallEvent` hook); this plan sequences the work faithfully without
re-deciding it.

## Ground rules (apply to every step)

- Only read/write under `D:/<USER>/LavaCode/AI/mahalo-agentcore`.
  NEVER touch `mahalo-dock` (read-only fallback).
- Use the venv python for ALL python/pytest:
  `D:/<USER>/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe`.
- Shell is Windows PowerShell: chain with `;` (NOT `&&`); env vars are `$env:VAR`.
- Do NOT `git commit` as part of these steps (the workflow handles commits).
- Verification runs from the repo root
  `D:/<USER>/LavaCode/AI/mahalo-agentcore`, same as Task 1.
- The six write tools (count reconciled in the design — mahalo-dock defines
  exactly SIX; CONTINUATION's "7" is a miscount): `jira_create_story`,
  `jira_update_story`, `github_create_branch`, `github_commit_files`,
  `github_open_pull_request`, `servicenow_create_incident`.
- No new third-party dependencies; `agent/requirements.txt` is unchanged.
- No change to `agent/prompts.py` — it was ported verbatim in Task 1 and already
  carries the full propose/approve + CHECK-IN-CODE FLOW + `[SYSTEM]` language,
  which is mechanism-agnostic and correct for the interrupt mechanism. The plan
  calls this out so no reviewer expects a prompt diff.

## Tunnel status at planning time: DOWN

Probed `http://localhost:5001/projects` with `mock-jira-token-12345` — timed out
(TUNNEL DOWN). Therefore verification is **full OFFLINE** (unit suite + import +
construction + Task 1 suite stays green). The live propose→approve→write
end-to-end check is NOT run and NOT fabricated; the exact commands the user runs
once the tunnel is up are documented in step 6.

---

# Implementation Plan

- [ ] 1. Create the three write-tool modules as thin `@tool` functions (resolve
      params → `make_request` POST/PUT → format result string), mirroring the
      Task 1 per-service module convention. Each module exports its `*_WRITE_TOOLS`
      list. Contracts (names, params/defaults, verbs, endpoints, success strings)
      come verbatim from the design's "Exact tool contracts" table.
      - `jira_write_tools.py`: `jira_create_story(project_id, title, description,
        priority="medium", story_points=0, assignee=None)` → POST `/stories`;
        `jira_update_story(story_id, status=None, assignee=None, priority=None,
        story_points=None, sprint_id=None)` → pre-GET `/stories/{story_id}` (via
        the shared read seam `make_request(settings.jira_url, settings.jira_token,
        endpoint=f"/stories/{story_id}")`, default GET) to confirm existence,
        resolve a name assignee via `_resolve_assignee`, build `changes` from only
        provided fields (empty → "No changes specified"), then PUT
        `/stories/{story_id}`. Import the resolvers directly from the frozen read
        module: `from agent.tools.jira_tools import _resolve_assignee,
        _fetch_developers` (design's chosen one-way dependency; do NOT hoist to a
        new module, do NOT edit `jira_tools.py`). Exports `JIRA_WRITE_TOOLS`.
      - `github_write_tools.py`: `github_create_branch(repo_id, branch_name,
        from_branch="main")` → POST `/repos/{repo_id}/branches`;
        `github_commit_files(repo_id, branch, message, files)` → POST
        `/repos/{repo_id}/commits` with `files` run through the ported
        `_normalize_files_arg` (tolerates JSON string / single dict / list of
        dicts; keeps `{"path","content"}`, content coerced to str, entries without
        a path dropped); `github_open_pull_request(repo_id, head, base="main",
        title="", body="")` → POST `/repos/{repo_id}/pulls` with `title or head`.
        `github_create_branch` MUST treat 409/422/"already exists" in the error
        text as SUCCESS ("already exists — reusing it"), per the design snippet.
        Retain the real-repo-NAME and full-file-contents docstrings. Exports
        `GITHUB_WRITE_TOOLS` and holds `_normalize_files_arg`.
      - `servicenow_write_tools.py`: `servicenow_create_incident(title,
        affected_service, severity="P3", description="", assignee=None,
        linked_deployment=None)` → POST `/incidents`. Exports `SERVICENOW_WRITE_TOOLS`.
      - Every write body wraps its `make_request` write call to catch
        `httpx.HTTPError`/`OSError` and return `"❌ Failed to {verb}: {exc}"`
        instead of raising (design "transport-error wrap"; the pre-GET and the
        error-dict path stay as-is).
      Files: `agent/tools/jira_write_tools.py`,
      `agent/tools/github_write_tools.py`,
      `agent/tools/servicenow_write_tools.py`.
      Verify (offline): `& "<venv-py>" -c "import agent.tools.jira_write_tools,
      agent.tools.github_write_tools, agent.tools.servicenow_write_tools; print('import OK')"`
      → prints `import OK`; and the Task 1 suite still passes:
      `& "<venv-py>" -m pytest agent -q` → existing unit tests pass, live
      integration test SKIPS (tunnel down).

- [ ] 2. Create the approval layer in `agent/approval.py`: the module-level
      `WRITE_TOOL_NAMES: set[str]` (the six tool names), a `build_proposal(tool_use)
      -> dict` helper producing `{"action","system","params","description"}`
      (`action`/`system` derived from the tool name; `params` = a copy of
      `tool_use["input"]`; `description` the human sentence per the design), and
      `WriteApprovalHook(HookProvider)` registering a `BeforeToolCallEvent`
      callback. The callback: no-op if `event.tool_use["name"]` not in
      `WRITE_TOOL_NAMES`; otherwise `response = event.interrupt("write_approval",
      reason=build_proposal(event.tool_use))` — on first pass this raises
      `InterruptException` (stops the loop, no body runs); on resume it returns
      the stored response, and if the response is not "APPROVE" the callback sets
      `event.cancel_tool = "Write rejected by user."` (so the body never runs).
      Imports confirmed against installed source per the HITL decision:
      `from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry`.
      Files: `agent/approval.py`.
      Verify (offline): `& "<venv-py>" -c "from agent.approval import
      WriteApprovalHook, WRITE_TOOL_NAMES, build_proposal; assert len(WRITE_TOOL_NAMES)==6;
      print('approval OK', sorted(WRITE_TOOL_NAMES))"` → prints the six names.

- [ ] 3. Wire the write tools and hook into `agent/strands_agent.py`: import the
      three `*_WRITE_TOOLS` lists and `WriteApprovalHook`; add
      `WRITE_TOOLS = [*JIRA_WRITE_TOOLS, *GITHUB_WRITE_TOOLS, *SERVICENOW_WRITE_TOOLS]`;
      in `build_agent()` register `tools=[*READ_TOOLS, *WRITE_TOOLS]` and
      `hooks=[WriteApprovalHook()]`. Nothing else in `build_agent` changes
      (BedrockModel construction stays lazy/offline-safe).
      Files: `agent/strands_agent.py`.
      Verify (offline): `& "<venv-py>" -c "from agent.strands_agent import
      build_agent, READ_TOOLS, WRITE_TOOLS; a=build_agent();
      print('read',len(READ_TOOLS),'write',len(WRITE_TOOLS))"` → `read 19 write 6`,
      construction succeeds with no network/creds.

- [ ] 4. Add the approval-loop driver to `agent/chat.py`: replace `_ask` so it
      detects `result.stop_reason == "interrupt"` and loops — for each
      `itr` in `result.interrupts`, capture `itr.reason` (the proposal dict),
      print `proposal["description"]`, read approve/reject, build
      `{"interruptResponse": {"interruptId": itr.id, "response": "APPROVE"|"REJECT"}}`,
      resume with `agent(responses)`, then for each APPROVED proposal call
      `_emit_system_signal(agent, proposal)` which appends one `[SYSTEM]`
      assistant-role message to `agent.messages` keyed on `proposal["action"]`
      using the three verbatim GitHub chain templates (create_branch /
      commit_files / open_pull_request) and the generic fallback for the other
      writes (templates transcribed in the design). Emit on approve only; nothing
      on reject. Keep the single-shot and REPL entrypoints using the same `_ask`.
      Files: `agent/chat.py`.
      Verify (offline): covered by the driver unit test in step 5 (`test_approval_driver`),
      plus `& "<venv-py>" -c "import agent.chat; print('chat import OK')"`.

- [ ] 5. Add `agent/tests/test_write_tools_unit.py` (same style as
      `test_tools_unit.py`: monkeypatch the per-module `make_request` seam;
      assert endpoint, verb, body, byte-for-byte output). Cover all branches from
      the design's test plan:
      - PROPOSE path (NO HTTP write): drive `WriteApprovalHook.before_tool_call`
        with a tiny fake event exposing `tool_use` + an `interrupt()` that raises
        `InterruptException` on first (unanswered) call; assert the exception
        propagates and `build_proposal` produced the right
        `{action,system,params,description}`; assert a non-write tool name is a
        no-op (no interrupt); structurally assert zero POST/PUT during propose.
      - REJECT path: fake event whose `interrupt()` returns `"REJECT"`; assert the
        hook sets `cancel_tool` to the rejection message and runs no body.
      - APPROVE path (mocked HTTP write), per tool, calling the body directly with
        `make_request` monkeypatched per module:
        `jira_create_story` → POST `/stories`, body=params, success string on a
        `{"id","title"}` 201; `jira_update_story` → pre-GET `/stories/{id}` then
        PUT with only provided `changes`, plus not-found / unresolved-assignee /
        empty-change branches (mock PUT return shaped `{"id","title"}`);
        `github_create_branch` → POST `/repos/{repo}/branches` AND the 409
        "already exists" → SUCCESS string; `github_commit_files` → POST
        `/repos/{repo}/commits` plus `_normalize_files_arg` cases (JSON string,
        single dict, list, missing-path dropped, content coerced to str);
        `github_open_pull_request` → POST `/repos/{repo}/pulls`, `title` defaults
        to `head`; `servicenow_create_incident` → POST `/incidents`, success
        string with `{id,title,severity}`.
      - Transport-error wrap: `make_request` raising `httpx.HTTPError` → the tool
        returns the `"❌ Failed to …"` string and does not raise.
      - DRIVER (`_ask`): fake agent returning an interrupt result once then a
        normal result; assert the driver builds the `interruptResponse` with the
        correct `interruptId`, re-invokes, and appends the `[SYSTEM]` signal to
        `agent.messages` on approve (and not on reject).
      Files: `agent/tests/test_write_tools_unit.py`.
      Verify (offline): `& "<venv-py>" -m pytest agent/tests/test_write_tools_unit.py -v`
      → all new tests pass; then `& "<venv-py>" -m pytest agent -q` → all existing
      unit tests remain green and the live integration test SKIPS (tunnel down).
      (Gate on "existing unit tests remain green," not a hard-coded count, since
      this adds a new test file.)

- [ ] 6. Record OFFLINE verification and the deferred live commands in
      `docs/.agents/tasks/task2-verification.md`: paste the real offline command
      output (import smoke, `read 19 write 6`, `pytest agent` result with the
      integration SKIP, zero-LangChain scan). Then document — do NOT run,
      do NOT fabricate — the exact live sequence the user runs once the tunnel is
      up (ports 5001-5004) and `lava` SSO is valid:
      1. Open the tunnel (the ssh `-L 5001..5004,8008,3001` command from
         CONTINUATION.md), leave it open in a separate terminal.
      2. `$env:AWS_PROFILE="lava"` then
         `& "<venv-py>" -m agent.chat "create a feature branch for PAY-109"`
         → prints a PROPOSAL and writes nothing (confirm the branch is absent via
         a read), approve → branch appears; "commit the code" → propose → approve
         → commit; "open a PR" → propose → approve → PR appears; confirm the
         `[SYSTEM]` signal prevents a re-proposed branch.
      3. `& "<venv-py>" -m pytest agent -q` with tunnel+creds up → the live
         integration test runs (not skipped) and stays green.
      Files: `docs/.agents/tasks/task2-verification.md`.
      Verify: file exists and contains both the real offline results and the
      clearly-labelled "run once tunnel is up" live commands.

## Dependency order rationale

1 (tools) must come before 2–3 because the hook's `WRITE_TOOL_NAMES` and the
agent's `WRITE_TOOLS` reference them. 2 (hook) before 3 (wiring) because
`build_agent` imports the hook. 4 (driver) depends on the interrupt contract the
hook establishes. 5 (tests) exercises 1–4. 6 records results last. Each step
leaves the package importable and the Task 1 suite green.
