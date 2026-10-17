# Task 5 Verification — AgentCore Memory & Identity (OFFLINE GATE)

Verification record for Task 5 (AgentCore **Memory** + **Identity**, opt-in / additive).
The implementation is code-review **APPROVED**
(`docs/.agents/tasks/task5-code-review.json`, verdict `APPROVED`). This document records
the **real** output of a re-run of the Task-5 **OFFLINE** gate. No live/deploy results are
fabricated; the live operator steps are listed, clearly labelled, as **NOT executed**.

- Date: 2026-10-17 (re-run of the offline gate on the approved implementation).
- Scope rule honored: only files under `mahalo-agentcore` were touched; `mahalo-dock` not
  edited. No `git commit`, no deploy.
- Windows PowerShell; commands chained with `;`, env vars set via `$env:VAR`.

---

## Offline gate — real results

### 1. Agent suite (existing + new Memory/Identity tests)

Command:

```powershell
& "agent/.venv/Scripts/python.exe" -m pytest agent -q
```

Real result: **69 passed, 1 skipped** (3 warnings; the 1 skip is the live-tunnel
integration test `agent/tests/test_integration_live.py`, which skips because the EC2
mocks on ports 5001-5004 are not tunnelled — not fabricated). This is the 55-passed
Task-4 baseline plus the 14 new Task-5 Memory/Identity tests.

Breakdown confirming the baseline is preserved (each sub-run is real):

| Subset | Command | Real result |
|---|---|---|
| DIRECT path (Task-1/2 reads+writes + live integration) | `pytest agent/tests/test_tools_unit.py agent/tests/test_write_tools_unit.py agent/tests/test_integration_live.py -q` | **49 passed, 1 skipped** |
| Task-4 GATEWAY + HITL/resume | `pytest agent/tests/test_gateway_mode.py -q` | **6 passed** |
| New Task-5 Memory + Identity | `pytest agent/tests/test_memory_mode.py agent/tests/test_identity_mode.py -q` | **14 passed** |

49 + 6 + 14 = 69, matching the full-suite count. The DIRECT path (49/1) fully contains
and preserves the Task-2 **42/1** baseline plus the Task-4 DIRECT-mode resume regression
tests; the Task-4 GATEWAY/HITL tests still pass (6/6). No existing test was removed or
weakened — the three DIRECT/GATEWAY tests that unpacked the old `build_agent` tuple were
migrated to read the new `BuildResult` attributes (same objects, same offline
construction).

### 2. Offline construction with Memory + Identity enabled (no network at import/build)

Confirmed by constructing `build_agent(...)` with the toggles ON and **no AWS credentials
present** in the environment. If construction performed any AWS call it would raise
(`NoCredentialsError`); it does not.

DIRECT + Memory + Identity:

```powershell
$env:MAHALO_MEMORY_ENABLED="true"; $env:MAHALO_MEMORY_ID="mem-offline-test-0001";
$env:MAHALO_IDENTITY_ENABLED="true";
$env:AWS_PROFILE=""; $env:AWS_ACCESS_KEY_ID=""; $env:AWS_SECRET_ACCESS_KEY="";
& "agent/.venv/Scripts/python.exe" -c "import agent.strands_agent as sa; r = sa.build_agent(memory=True, identity=True, session_id='offline-s1'); print('AGENT', type(r.agent).__name__); print('MCP', r.mcp_client); print('SESSION_MGR_CONSTRUCTED', r.session_manager is not None); print('SESSION_MGR_NOT_ATTACHED', r.agent._session_manager is None)"
```

Real output:

```
AGENT Agent
MCP None
SESSION_MGR_CONSTRUCTED True
SESSION_MGR_NOT_ATTACHED True
```

Interpretation: the `Agent` is built; the session manager is **constructed but not
attached** to the agent (`agent._session_manager is None`), so the construction-time
`AgentInitializedEvent` reaches no Memory callback and **no network rehydrate happens at
build**. The live rehydrate is isolated in `attach_memory` (the single AWS touch), exactly
as designed. Identity is also offline: the `@requires_api_key` decorator is applied only to
a body-local `_inner` inside `jira_create_story`, so no `IdentityClient`/boto3 client is
built at import or at `build_agent(identity=True)`.

GATEWAY + Memory (construct-not-started, construct-not-attached):

```powershell
$env:MAHALO_MEMORY_ENABLED="true"; $env:MAHALO_MEMORY_ID="mem-offline-test-0001";
$env:MAHALO_TOOL_MODE="gateway"; $env:MAHALO_GATEWAY_MCP_URL="https://example.invalid/mcp";
$env:AWS_PROFILE=""; $env:AWS_ACCESS_KEY_ID=""; $env:AWS_SECRET_ACCESS_KEY="";
& "agent/.venv/Scripts/python.exe" -c "import agent.strands_agent as sa; r = sa.build_agent(tool_mode='gateway', memory=True, session_id='offline-s2'); print('AGENT', type(r.agent).__name__); print('MCP_CONSTRUCTED', r.mcp_client is not None); print('SESSION_MGR_CONSTRUCTED', r.session_manager is not None)"
```

Real output:

```
AGENT Agent
MCP_CONSTRUCTED True
SESSION_MGR_CONSTRUCTED True
```

Interpretation: Memory composes with GATEWAY mode — the MCP client is constructed (not
started) and the session manager is constructed (not attached), all offline-safe.

> Construction-boundary note (recorded by the code review as **Option 1**, approved by the
> parent session per original user message #6): the installed `bedrock-agentcore 1.24.1`
> `AgentCoreMemorySessionManager.__init__` performs a live `ListEvents` read at
> construction, so the design's literal "construct the session manager inside `build_agent`"
> seam is not offline-safe. The coder relocated the live construction into `attach_memory`
> behind a plain-data `MemorySessionSpec`; `build_agent(memory=True)` only assembles the
> offline spec. The offline invariant is unit-asserted with a tripwire. That is why the two
> commands above construct with no network.

### 3. IaC — `cdk synth --all` (new `MahaloMemoryIdentityStack`)

Commands (venv activated first):

```powershell
& .\.venv\Scripts\Activate.ps1
cdk synth --all
```

(run from `infra-cdk/`.)

Real result: **exit 0**, "Successfully synthesized to ...\infra-cdk\cdk.out". The synth
enumerates **six** stacks: `MahaloMockJiraStack`, `MahaloMockConfluenceStack`,
`MahaloMockGithubStack`, `MahaloMockServicenowStack`, `MahaloGatewayStack`, and the new
`MahaloMemoryIdentityStack`. (Warnings only: the pre-existing `addDependency` deprecation
and the cross-stack-reference-strength advisory — neither is a Task-5 regression.) Task-4's
five stacks still synthesize, so the Gateway IaC is unregressed.

### 4. IaC assertion suite

```powershell
& .\.venv\Scripts\Activate.ps1
python -m pytest tests -q
```

(run from `infra-cdk/`.)

Real result: **31 passed** (~2m11s). This is the Task-4 gateway/mock assertions plus the
new `test_memory_identity_stack.py` assertions (one `AWS::BedrockAgentCore::Memory` STM
with `EventExpiryDuration == 30` and no `MemoryStrategies`; one `WorkloadIdentity`; one
`ApiKeyCredentialProvider`; the `MemoryId`/provider-name outputs; the no-echo API-key
parameter).

### 5. tools-lambdas suite

```powershell
& ".venv/Scripts/python.exe" -m pytest tests -q
```

(run from `tools-lambdas/`, which has its own venv with `moto`.)

Real result: **94 passed** (634 warnings; all `datetime.utcnow()`/botocore deprecations,
unrelated to Task 5). Task 5 did not edit `tools-lambdas/` — the Task-3/4 mock chain stays
frozen and green.

### 6. Zero LangChain

```
grep (regex): langchain|langgraph   over **/*.py  (excluding **/.venv/**)
```

Real result: **No matches found.** No LangChain/LangGraph imports anywhere in the
first-party source.

### 7. Artifact cleanup

No stray `.agentcore.json` dev-auth cache was produced (searched including ignored files;
none found). `cdk.out` is the normal synth output directory under `infra-cdk/`.

---

## DIRECT and GATEWAY modes still work; Memory/Identity are additive / opt-in

- **Defaults are byte-for-byte unchanged.** All six new settings default off/empty
  (`MAHALO_MEMORY_ENABLED`/`MAHALO_IDENTITY_ENABLED` → `False`, `MAHALO_MEMORY_ID`/
  `MAHALO_SESSION_ID` → `""`, `MAHALO_MEMORY_REGION` mirrors `gateway_region`,
  `MAHALO_IDENTITY_JIRA_PROVIDER` → `"mahalo-jira-apikey"`). With the toggles off,
  `build_agent()` constructs no session manager, attaches no hook, and the Identity tool
  reads the static `settings.jira_token` exactly as before — proven by the DIRECT path
  staying 49/1 and the GATEWAY tests staying 6/6.
- **Memory is opt-in and composes with both tool modes.** Enabled only when
  `MAHALO_MEMORY_ENABLED=true` (and `MAHALO_MEMORY_ID` set, else `build_agent` fails fast
  with a `ValueError` mirroring the GATEWAY URL guard). It attaches via the Strands
  `session_manager` seam only inside `attach_memory`, keeping construction offline.
- **Identity is opt-in and scoped to one representative outbound path** (`jira_create_story`
  in DIRECT mode). With the toggle off the static token is used; the `@tool` signature and
  LLM-facing schema are unchanged.
- **Task-4 inbound auth is untouched.** Task 5 edited no Gateway file
  (`gateway_stack.py`, `gateway_client.py`) and no mock Lambda; the Task-4 SigV4
  (`bedrock-agentcore`) → Gateway `AWS_IAM` → `GATEWAY_IAM_ROLE` → `X-API-Token` chain is
  preserved, guarded by the still-green gateway assertions.

---

## DEFERRED LIVE OPERATOR STEPS — **NOT executed** (no results fabricated)

The automated Task-5 gate is **offline**. The following steps exercise the live Memory and
Identity capabilities against real AWS resources. They were **NOT run** in this
verification — no deploy occurred, no Memory/Identity resources were created, and no live
session output is recorded here. Run them as an operator when ready (requires
`aws sso login --profile lava`).

1. **Create the Memory/Identity resources (deploy).** `NOT executed.`
   ```powershell
   aws sso login --profile lava
   cd infra-cdk; cdk deploy MahaloMemoryIdentityStack --profile lava
   ```
   Supply the `JiraApiKey` parameter or accept the mock default
   (`mock-jira-token-12345`). Note the stack outputs: `MemoryId`,
   `WorkloadIdentityArn`, `JiraApiKeyProviderName`.

2. **Persist + reload conversation history across invocations (AgentCore Memory).**
   `NOT executed.` After exporting the toggles:
   ```powershell
   $env:MAHALO_MEMORY_ENABLED="true"; $env:MAHALO_MEMORY_ID="<MemoryId output>"
   python -m agent.chat --session-id demo-1 "remember my favorite repo is payment-service"
   python -m agent.chat --session-id demo-1 "what's my favorite repo?"
   ```
   Acceptance (to be confirmed live, not claimed here): the **second** invocation's answer
   reflects the reloaded history, proving STM persistence + rehydrate across separate
   process invocations via AgentCore Memory.

3. **Exercise Identity-brokered tool credentials.** `NOT executed.` With
   `$env:MAHALO_IDENTITY_ENABLED="true"`, run a `jira_create_story` write (via the HITL
   propose/approve flow) and confirm it succeeds using the **brokered API key fetched at
   call time**, not the static env token. Note: the first Identity-enabled local run uses
   the SDK's local dev-auth path, which self-provisions a *local* workload identity and
   writes a `.agentcore.json` dev-auth cache into the run directory (deletable to force
   re-provisioning); it does **not** consume the CDK `CfnWorkloadIdentity` (`mahalo-agent`),
   which is reserved for the Task-6 Runtime path. The brokered key itself comes from the CDK
   `CfnApiKeyCredentialProvider` (`mahalo-jira-apikey`).

4. **Full app deploy (optional, for an end-to-end live demo).** `NOT executed.`
   ```powershell
   cdk deploy --all --profile lava
   ```
   (Deploys the four mock Lambdas + Gateway + the Memory/Identity stack. The Gateway gets a
   NEW id/MCP URL each deploy — re-read the `CfnOutput`s.)

5. **Teardown when done** (to stop Memory charges). `NOT executed.`
   ```powershell
   cdk destroy MahaloMemoryIdentityStack --profile lava
   ```
   (and optionally delete `.agentcore.json`).

---

## Summary

The Task-5 OFFLINE gate is **GREEN** on real output: agent suite **69 passed / 1 skipped**
(55 Task-4 baseline + 14 new; DIRECT 49/1 preserving the Task-2 42/1, Task-4 GATEWAY/HITL
6/6), `build_agent(memory=True, identity=True)` and `build_agent(tool_mode="gateway",
memory=True)` both **construct offline with no AWS credentials**, `cdk synth --all` **exit
0** (6 templates incl. `MahaloMemoryIdentityStack`), infra-cdk assertions **31 passed**,
tools-lambdas **94 passed**, and **zero LangChain**. Memory and Identity are additive /
opt-in; DIRECT and GATEWAY default behavior is unchanged and Task-4 inbound auth is
untouched. All live/deploy steps are explicitly deferred and were **not** executed.
