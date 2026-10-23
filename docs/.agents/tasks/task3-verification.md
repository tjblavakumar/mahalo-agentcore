# Task 3 â€” Verification (Lambda reimplementation of the four mocks)

Status: COMPLETE. Code reviewed and APPROVED
(`docs/.agents/tasks/task3-code-review.json`, verdict `APPROVED`). Offline
verification below is green; the live AWS deploy + Function-URL integration check
are DEFERRED operator actions (see end).

## Verification commands and results

Run from the workspace root `<WORKSPACE_ROOT>`.

1. tools-lambdas unit/handler suite

   ```powershell
   & "tools-lambdas/.venv/Scripts/python.exe" -m pytest tools-lambdas/tests -q
   ```

   Result: **68 passed** (503 warnings â€” benign `datetime.utcnow()`
   DeprecationWarning from botocore's signer; no failures).

2. infra-cdk synth + unit suite

   ```powershell
   cd infra-cdk ; .\.venv\Scripts\Activate.ps1 ; cdk synth --all ; & .venv/Scripts/python.exe -m pytest tests -q
   ```

   Results:
   - `cdk synth` (CDK 2.1145.0) synthesized all four stacks to
     `infra-cdk/cdk.out`:
     `MahaloMockJiraStack.template.json`,
     `MahaloMockConfluenceStack.template.json`,
     `MahaloMockGithubStack.template.json`,
     `MahaloMockServicenowStack.template.json`.
     (Note: this CDK version prints "Unknown option(s): --all" and ignores the
     flag â€” `synth` already defaults to synthesizing every stack, so all four
     templates were still produced. Spot-checked the Jira template: `"Runtime":
     "python3.13"`, Function-URL `"AuthType": "NONE"`, and the `JiraUrl` /
     `JiraArn` outputs are present.)
   - `pytest tests -q` -> **20 passed**.

Both suites green; synth produced all four templates.

## Function URL / ARN CfnOutput names (Task-4 Gateway import contract)

Each `MockServiceStack` emits one Function-URL output and one ARN output. Logical
IDs (from `infra-cdk/mahalo_infra/mock_service_stack.py`, `_OUTPUT_IDS`):

| Service     | Stack                         | Function URL output | Function ARN output |
|-------------|-------------------------------|---------------------|---------------------|
| jira        | `MahaloMockJiraStack`         | `JiraUrl`           | `JiraArn`           |
| confluence  | `MahaloMockConfluenceStack`   | `ConfluenceUrl`     | `ConfluenceArn`     |
| github      | `MahaloMockGithubStack`       | `GithubUrl`         | `GithubArn`         |
| servicenow  | `MahaloMockServicenowStack`   | `ServiceNowUrl`     | `ServiceNowArn`     |

## Env-swap mapping (deployed Function URLs -> agent `*_URL` vars)

After deploy, point the Strands agent at the Lambdas by overriding only the four
base-URL env vars (`agent/config.py`). The static `X-API-Token` tokens already
match the Lambda defaults (`_DEFAULT_TOKENS` in `mock_service_stack.py` equal the
`*_TOKEN` defaults in `agent/config.py`), so no token override is needed.

| CfnOutput (deployed value) | Agent env var    | agent/config.py default            |
|----------------------------|------------------|------------------------------------|
| `JiraUrl`                  | `JIRA_URL`       | `http://localhost:5001`            |
| `ConfluenceUrl`            | `CONFLUENCE_URL` | `http://localhost:5002`            |
| `GithubUrl`                | `GITHUB_URL`     | `http://localhost:5003`            |
| `ServiceNowUrl`            | `SERVICENOW_URL` | `http://localhost:5004`            |

Tokens (unchanged, defaults already aligned): `JIRA_TOKEN=mock-jira-token-12345`,
`CONFLUENCE_TOKEN=mock-confluence-token-12345`,
`GITHUB_TOKEN=mock-github-token-12345`,
`SERVICENOW_TOKEN=mock-servicenow-token-12345`.

## DEFERRED operator actions (require live AWS; NOT run here)

These need the `lava` SSO session and will create/modify real AWS resources, so
they are left for the operator. No live-deploy results are recorded above because
no deploy was performed.

1. Bootstrap the environment (once per account/region):

   ```powershell
   cd infra-cdk ; cdk bootstrap --profile lava
   ```

2. Deploy all four stacks:

   ```powershell
   cd infra-cdk ; cdk deploy --all --profile lava
   ```

   Capture the four `*Url` CfnOutputs from the deploy summary and set the agent's
   `JIRA_URL` / `CONFLUENCE_URL` / `GITHUB_URL` / `SERVICENOW_URL` per the mapping
   above.

3. Opt-in live Function-URL integration check (after deploy): hit each deployed
   Function URL with its `X-API-Token` header and confirm a known read returns
   the seeded data (e.g. `GET <JiraUrl>projects`), then optionally run the agent
   against the deployed URLs end-to-end. This is an explicit opt-in step, not part
   of the offline gate.
