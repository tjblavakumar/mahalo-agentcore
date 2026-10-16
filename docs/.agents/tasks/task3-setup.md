# Task 3 — Setup / Readiness Note

Preparatory work only. No code or seed data ported yet (reserved for later steps).

## 1. Artifact directory

`docs/.agents/tasks/` already exists under the agentcore workspace. No creation needed.

## 2. AWS caller identity

`aws sts get-caller-identity --profile lava` succeeded:

- **Account:** `<AWS_ACCOUNT_ID>`
- **Arn:** `<SSO_ROLE_ARN>`
- **UserId:** `<SSO_USER_ID>`
- **Region:** us-east-1

Credentials are live; no `aws sso login` needed.

## 3. Source mocks (read-only, from mahalo-dock)

Path: `D:/<USER>/LavaCode/AI/mahalo-dock/mock-services/<svc>/` — READ ONLY, nothing copied.

| Service     | main.py | store.py | seed_data.py | requirements.txt | Dockerfile | Extra files |
|-------------|:-------:|:--------:|:------------:|:----------------:|:----------:|-------------|
| jira        | yes     | yes      | yes          | yes              | yes        | .gitkeep |
| confluence  | yes     | yes      | yes          | yes              | yes        | .gitkeep |
| github      | yes     | yes      | yes          | yes              | yes        | .gitkeep, backend_base.py, gitea_backend.py, mock_backend.py |
| servicenow  | yes     | yes      | yes          | yes              | yes        | (none) |

All five expected files present in every service. The github mock additionally ships a
pluggable backend layer (`backend_base.py`, `mock_backend.py`, `gitea_backend.py`) to note
when porting later.

## 4. Agent tool modules (agentcore workspace)

Path: `D:/<USER>/LavaCode/AI/mahalo-agentcore/agent/tools/`

Present:

- `jira_tools.py`, `jira_write_tools.py`
- `github_tools.py`, `github_write_tools.py`
- `confluence_tools.py`  *(read tools only)*
- `servicenow_tools.py`, `servicenow_write_tools.py`
- support: `http.py`, `__init__.py`

**Note:** there is **no `confluence_write_tools.py`** — confluence currently exposes read
tools only. Keep this in mind when enumerating the endpoints the Confluence Lambda must
support.

## 5. Toolchain versions confirmed

- **python:** 3.13.9
- **node:** v24.13.0
- **cdk:** 2.1145.0 (build 13877dc)

## Status

Setup prerequisites satisfied. Ready for later steps to port the mock services into
Lambdas and wire them to the agent tool endpoints. No code/seed porting done here.
