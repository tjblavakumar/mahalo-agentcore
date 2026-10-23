# infra-cdk â€” mock-service Lambdas (AWS CDK v2, Python)

CDK app that provisions the four mahalo mock services (Jira, Confluence, GitHub,
ServiceNow) as AWS Lambda functions, each fronted by a Function URL and backed by
its own DynamoDB table. Each service is a separate stack
(`MahaloMock<Service>Stack`) built from the one reusable
`mahalo_infra/mock_service_stack.py::MockServiceStack`.

- Account / region: `<AWS_ACCOUNT_ID>` / `us-east-1` (see `app.py`).
- Deploy profile: `lava` (SSO).
- The Lambda code is bundled from `../tools-lambdas` (the `common/` package plus the
  one target service directory per function).

## Layout

```
infra-cdk/
  app.py                     # cdk.App(); instantiates the four stacks
  cdk.json                   # "app": "python app.py"
  requirements.txt           # aws-cdk-lib>=2,<3, constructs>=10,<11
  requirements-dev.txt       # pytest
  mahalo_infra/
    __init__.py
    mock_service_stack.py    # reusable stack: DynamoDB table + Lambda + Function URL
  tests/
    __init__.py
    test_synth.py            # CDK assertions (synth, offline, no AWS creds)
```

## One-time setup

The virtualenv (`infra-cdk/.venv`) and `cdk.out/` are gitignored.

```powershell
cd infra-cdk
py -3.13 -m venv .venv
& .venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

## Synth (offline â€” no AWS creds)

```powershell
cd infra-cdk
.\.venv\Scripts\Activate.ps1
cdk synth --all
```

Produces four CloudFormation templates under `cdk.out/`.

## Tests (offline â€” no AWS creds)

```powershell
cd infra-cdk
& .venv/Scripts/python.exe -m pytest tests -q
```

## Bootstrap (operator, one-time per account/region)

CDK needs a bootstrap stack before the first deploy. Re-run it after a monthly
account reset.

```powershell
cd infra-cdk
.\.venv\Scripts\Activate.ps1
cdk bootstrap --profile lava
```

## Deploy

```powershell
cd infra-cdk
.\.venv\Scripts\Activate.ps1
cdk deploy --all --profile lava
```

Deploy prints each stack's outputs: the four Function URLs and function ARNs.

### Output â†’ agent `*_URL` mapping

Each stack emits two CfnOutputs â€” a Function URL and a function ARN (the ARN feeds
Task 4's Gateway import). Map the URL outputs onto the agent's `*_URL` env vars:

| Stack                         | URL output     | ARN output     | Agent env var       |
|-------------------------------|----------------|----------------|---------------------|
| `MahaloMockJiraStack`         | `JiraUrl`      | `JiraArn`      | `JIRA_URL`          |
| `MahaloMockConfluenceStack`   | `ConfluenceUrl`| `ConfluenceArn`| `CONFLUENCE_URL`    |
| `MahaloMockGithubStack`       | `GithubUrl`    | `GithubArn`    | `GITHUB_URL`        |
| `MahaloMockServicenowStack`   | `ServiceNowUrl`| `ServiceNowArn`| `SERVICENOW_URL`    |

A Lambda Function URL ends with a trailing `/`. The agent builds request paths as
`<base>/projects` etc., so set each `*_URL` to the base URL with **no trailing
slash** (strip the trailing `/` from the CfnOutput value).

Tokens default to the agent's values (`mock-<svc>-token-12345`) and are set as the
`MOCK_<SVC>_TOKEN` env var on each function; `GITHUB_MODE` is deliberately not set
(the GitHub handler defaults it to `mock`).

## Teardown

```powershell
cd infra-cdk
.\.venv\Scripts\Activate.ps1
cdk destroy --all --profile lava
```

Tables use `RemovalPolicy.DESTROY`, so teardown is clean (supports the monthly
account reset).

## Resetting table data without redeploying

The tables self-seed on first call via a `_meta`/`seeded` sentinel. To force a
re-seed (clear items but keep the tables), run the operator reset script:

```powershell
./scripts/reset-mock-tables.ps1 -Profile lava
```

It targets only the four exact table names, deletes their items (including the
sentinel), and never drops a table. It is an operator path and is not reachable by
the agent.
