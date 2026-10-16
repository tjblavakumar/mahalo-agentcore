# agent — local Strands agent (Task 1)

A [Strands Agents](https://strandsagents.com) agent that runs **locally** and answers
**read** questions about the mahalo mock enterprise systems (Jira, Confluence, GitHub,
ServiceNow) by calling them over HTTP. It uses Amazon Bedrock (Claude Sonnet 4.5) for
reasoning and tool-calling. **No LangChain anywhere.**

Task 1 is read-only. The write / propose / approve flow is Task 2.

## Layout

```
agent/
  config.py            env-driven settings (base URLs, tokens, model, timeouts)
  strands_agent.py     build_agent(...) -> configured Strands Agent
  prompts.py           ported system prompts (base + 3 role prompts)
  chat.py              CLI / REPL entrypoint
  tools/
    http.py            shared httpx request helper (X-API-Token)
    jira_tools.py      7 read tools  (JIRA_TOOLS)
    github_tools.py    4 read tools  (GITHUB_TOOLS)
    confluence_tools.py 3 read tools (CONFLUENCE_TOOLS)
    servicenow_tools.py 5 read tools (SERVICENOW_TOOLS)
  tests/
    test_tools_unit.py        offline unit tests (mocked HTTP)
    test_integration_live.py  one live test; skips when the tunnel is down
```

## Setup (Windows PowerShell)

From the `agent/` directory:

```powershell
py -3.13 -m venv .venv          # fall back to: python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`.venv/` is gitignored. Use `agent/.venv/Scripts/python.exe` for all test runs.

## AWS credentials

Credentials come from the `lava` AWS SSO profile — nothing is baked into code.

```powershell
$env:AWS_PROFILE = "lava"
aws sso login --profile lava          # when the SSO session has expired
```

## The mock backend tunnel

The agent calls the mahalo-dock mocks on ports 5001-5004. See `docs/CONTINUATION.md`
for the full SSH tunnel command (it forwards 5001-5004 among others). Open that tunnel
in a separate terminal before running the agent against live data. Quick reachability
check once it is up:

```powershell
curl.exe -s -H "X-API-Token: mock-jira-token-12345" http://localhost:5001/projects
```

## Configuration (env vars, with defaults)

| Variable | Default |
| --- | --- |
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `AWS_REGION` | `us-east-1` |
| `AWS_PROFILE` | `lava` |
| `BEDROCK_READ_TIMEOUT` | `300` |
| `BEDROCK_CONNECT_TIMEOUT` | `10` |
| `JIRA_URL` / `JIRA_TOKEN` | `http://localhost:5001` / `mock-jira-token-12345` |
| `CONFLUENCE_URL` / `CONFLUENCE_TOKEN` | `http://localhost:5002` / `mock-confluence-token-12345` |
| `GITHUB_URL` / `GITHUB_TOKEN` | `http://localhost:5003` / `mock-github-token-12345` |
| `SERVICENOW_URL` / `SERVICENOW_TOKEN` | `http://localhost:5004` / `mock-servicenow-token-12345` |
| `HTTP_TIMEOUT` | `10.0` |

## Run the agent

Single-shot:

```powershell
.\.venv\Scripts\python.exe -m agent.chat "show my stories"
```

Interactive REPL (type `quit`/`exit` to leave):

```powershell
.\.venv\Scripts\python.exe -m agent.chat
```

The REPL identity is hard-coded to the demo developer **dev-6 ("Lava Dev")**, so
"show my stories" resolves to dev-6 (PAY stories in the seed data).

## Run the tests

From the repository root:

```powershell
# unit suite (fully offline)
.\agent\.venv\Scripts\python.exe -m pytest agent/tests/test_tools_unit.py -v

# full suite — unit tests pass, the live integration test SKIPS when the tunnel is down
.\agent\.venv\Scripts\python.exe -m pytest agent -v
```

## Verified Strands API facts (strands-agents 1.61.1)

Checked against the installed package under `agent/.venv/Lib/site-packages/strands/`:

- **Tool decorator / Agent:** `from strands import Agent, tool`.
- **Bedrock model:** `from strands.models import BedrockModel`.
  The botocore `Config` (used to set `read_timeout=300`) is passed via the
  `boto_client_config` kwarg: `BedrockModel(model_id=..., boto_session=session,
  boto_client_config=Config(...))`. `model_id` is a valid `BedrockConfig` field.
  The region is supplied through the `boto3.Session` — BedrockModel raises
  "Cannot specify both `region_name` and `boto_session`" if you pass both.
- A decorated tool is a `DecoratedFunctionTool`; calling it directly
  (`jira_list_projects(...)`) runs the original function, which is how the unit
  tests exercise the tools.
