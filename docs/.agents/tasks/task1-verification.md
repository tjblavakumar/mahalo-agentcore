# Task 1 â€” Verification record

This records the exact commands run and their output so the reviewer can confirm
the result without re-running. All commands use the project venv python at
`agent/.venv/Scripts/python.exe`. Unless noted, the working directory is the repo
root `<WORKSPACE_ROOT>`.

Environment: Windows, PowerShell, Python 3.13.9. The SSH tunnel to the mocks was
NOT opened and AWS SSO was NOT logged in â€” so the offline bar is what is verified
here; the live REPL/Bedrock/tunnel checks remain for the user (see the end).

## 1. Create venv and install requirements

Run from `agent/`:

```
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Installed versions confirmed (no install errors):

```
.\.venv\Scripts\python.exe -m pip show strands-agents bedrock-agentcore
# Name: strands-agents     Version: 1.61.1
# Name: bedrock-agentcore  Version: 1.24.1
```

## 2. Strands API verification (against installed 1.61.1)

```
.\.venv\Scripts\python.exe -c "from strands import Agent, tool; from strands.models import BedrockModel; print('imports OK')"
# imports OK

.\.venv\Scripts\python.exe -c "import inspect; from strands.models import BedrockModel; print(inspect.signature(BedrockModel.__init__))"
# (self, *, boto_session=None, boto_client_config=None, region_name=None,
#  endpoint_url=None, api_key=None, **model_config)
```

Findings used by the implementation:
- Tool decorator & agent: `from strands import Agent, tool`.
- botocore `Config` is passed via `boto_client_config`; `model_id` is a valid
  `BedrockConfig` field; region is supplied via the `boto3.Session` because
  BedrockModel rejects passing both `region_name` and `boto_session`
  ("Cannot specify both `region_name` and `boto_session`.").
- A decorated tool is a `DecoratedFunctionTool`; calling it directly runs the
  underlying function (used by the unit tests).

## 3. Unit suite (offline) â€” all pass

```
.\agent\.venv\Scripts\python.exe -m pytest agent/tests/test_tools_unit.py -v
```

Result: `13 passed in 5.66s`. Tests cover the shared HTTP helper (URL/params/
`X-API-Token` header + exact error string), a representative tool per service
with byte-for-byte output formatting, the Jira assignee name->dev-id resolution
(dev- passthrough, full name, email, first-name single match, ambiguous/unknown
-> None), and the ServiceNow default-all incidents behavior (no status param).

## 4. Full suite (offline) â€” unit pass, integration SKIPS

```
.\agent\.venv\Scripts\python.exe -m pytest agent -v
```

Result: `13 passed, 1 skipped in 6.43s` (exit code 0). The live integration test
`test_live_agent_reads_repos_and_my_stories` SKIPPED because the mocks/tunnel are
unreachable â€” it never fails the suite when the tunnel is down.

## 5. Zero LangChain usage

```
.\agent\.venv\Scripts\python.exe -c "import pathlib,sys; bad=[str(p) for p in pathlib.Path('agent').rglob('*.py') if '.venv' not in p.parts and 'langchain' in p.read_text(encoding='utf-8').lower()]; print('LANGCHAIN FOUND:',bad); sys.exit(1 if bad else 0)"
# LANGCHAIN FOUND: []
# (exit code 0)
```

## 6. Import smoke test + offline agent construction

```
.\agent\.venv\Scripts\python.exe -c "import agent.strands_agent, agent.chat; print('import OK')"
# import OK

.\agent\.venv\Scripts\python.exe -c "from agent.strands_agent import build_agent, READ_TOOLS; a = build_agent(); print(type(a).__name__); print('tools:', len(READ_TOOLS))"
# Agent
# tools: 19
```

`build_agent()` constructs the Agent with no network call and registers all 19
read tools (7 Jira + 4 GitHub + 3 Confluence + 5 ServiceNow). No live Bedrock
call was attempted (needs AWS SSO, unavailable now); import + construction is the
offline bar.

## What is NOT verified here (remains for the user)

Task 1 is NOT verified end-to-end. With the SSH tunnel up (ports 5001-5004) and a
valid `lava` AWS SSO session, the user must still confirm live:
- `python -m agent.chat "list my repositories"` returns `payment-service`.
- `python -m agent.chat "show my stories"` (dev-6) returns PAY stories.
- `pytest agent` with the tunnel + creds up runs the integration test (not skipped).
These exercise the real Bedrock + tunnel path, which could not run offline.
