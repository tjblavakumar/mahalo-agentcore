# Task 2 (HITL writes) — Verification record

This records the exact commands run and their output so the reviewer can confirm
the cross-FEAT integration result without re-running. All commands use the
project venv python at `agent/.venv/Scripts/python.exe`. Unless noted, the
working directory is the repo root
`d:\lavakumar.baskaran\LavaCode\AI\mahalo-agentcore`.

Environment: Windows, PowerShell, Python 3.13.9. The SSH tunnel to the mocks
(ports 5001-5004) is DOWN and the live Bedrock path is NOT exercised here — so
the OFFLINE bar is what is verified below. The live REPL/Bedrock/tunnel checks
remain for the user (see the end).

Scope of this record: integration verification across FEAT-001 (the six write
`@tool` functions) and FEAT-002 (the `WriteApprovalHook` + the `chat.py`
interrupt/approve driver + the `strands_agent.py` registration). The seams
confirmed by reading the sources:

- Registration: `strands_agent.build_agent()` passes
  `tools=[*READ_TOOLS, *WRITE_TOOLS]` and `hooks=[WriteApprovalHook()]`.
  `READ_TOOLS` has 19 tools, `WRITE_TOOLS` has 6.
- Hook → driver contract: `build_proposal` emits `{"action","system","params",
  "description"}` where `action` is the tool name with its service prefix
  stripped (`github_create_branch` → `create_branch`). The driver reads
  `proposal["description"]` for the prompt and switches `_emit_system_signal`
  on `proposal["action"]` (`create_branch` / `commit_files` /
  `open_pull_request`).
- Param-name contract: the `[SYSTEM]` breadcrumbs in `_emit_system_signal`
  (`p['branch_name']`, `p['repo_id']`, `p['branch']`, `p['head']`,
  `p.get('base','main')`) match the write-tool parameter names in
  `github_write_tools.py`, so `params` (a copy of `tool_use["input"]`) keys line
  up.
- Resume contract: the driver resumes with
  `{"interruptResponse": {"interruptId": itr.id, "response": "APPROVE"|"REJECT"}}`
  and the hook treats any non-`"APPROVE"` response as a rejection via
  `event.cancel_tool`.

## 1. Import smoke test (the closest thing to a build)

```
& "D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe" -c "import agent.strands_agent, agent.chat; print('import OK')"
# import OK
```

## 2. build_agent() offline construction + tool counts

```
& "D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe" -c "from agent.strands_agent import build_agent, READ_TOOLS, WRITE_TOOLS; build_agent(); print('read',len(READ_TOOLS),'write',len(WRITE_TOOLS))"
# read 19 write 6
```

`build_agent()` constructs the Agent (with the `WriteApprovalHook` registered and
all 25 tools attached) with no network call and no AWS creds. This is the offline
bar for the build.

## 3. Full suite (offline) — unit pass, live integration SKIPS

```
& "D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe" -m pytest agent -q
# s................................. [ 79%]
# .........                          [100%]
# 42 passed, 1 skipped in 8.10s
```

Exit code 0. 42 unit tests passed; the ONE live integration test
`test_live_agent_reads_repos_and_my_stories` SKIPPED because the mocks/tunnel are
unreachable (ports 5001-5004 down) — it never fails the suite when the tunnel is
down. This covers the Task 1 read tools, the Task 2 write tools (byte-for-byte
output + endpoint/verb/body assertions), and the HITL interrupt/approve/reject
flow.

## 4. Zero LangChain usage

```
& "D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe" -c "import pathlib,sys; bad=[str(p) for p in pathlib.Path('agent').rglob('*.py') if '.venv' not in p.parts and 'langchain' in p.read_text(encoding='utf-8').lower()]; print('LANGCHAIN FOUND:',bad); sys.exit(1 if bad else 0)"
# LANGCHAIN FOUND: []
# (exit code 0)
```

No LangChain imports anywhere under `agent/` (the only `langchain` string matches
live inside `agent/.venv` third-party packages, which the scan excludes).

## What is NOT verified here (DEFERRED — the user runs these once the tunnel is up)

Task 2 is NOT verified end-to-end. These exercise the real Bedrock + tunnel path,
which could not run offline. With the SSH tunnel up (ports 5001-5004) and a valid
`lava` AWS SSO session, the user runs:

1. Full suite with the live integration test actually running (not skipped):

   ```
   & "D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe" -m pytest agent -q
   ```
   Expectation: `test_live_agent_reads_repos_and_my_stories` runs and passes
   (`list my repositories` → contains `payment-service`; `show my stories` →
   contains `PAY-`). Everything else stays green.

2. Live HITL write (create-a-story) — approve path:

   ```
   & "D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe" -m agent.chat "create a story in PAY titled 'Add retry to payment webhook'"
   ```
   Expectation: the agent PROPOSES the write and pauses (`PROPOSED: Create story
   ...`), prompts `Approve this write? [y/N]`; answering `y` runs the POST and
   returns `✅ Story created successfully: ...`.

3. Live HITL write — reject path (answer `n` to the same prompt): nothing is
   written and no `[SYSTEM]` breadcrumb is appended.

4. Live GitHub check-in chain (branch → commit → PR), approving each step, to
   confirm the `[SYSTEM]` breadcrumbs stop each approved step from being
   re-proposed:

   ```
   & "D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe" -m agent.chat
   # then drive: create a branch in payment-service, commit the code, open a PR
   ```

Do NOT fabricate results for the deferred commands — they require the live tunnel
and a valid AWS SSO session.
