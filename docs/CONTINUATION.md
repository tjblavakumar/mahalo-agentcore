# CONTINUATION — read this first (fresh-session handoff)

This file lets a new chat session (opened with `mahalo-agentcore` as the workspace
root) continue the AgentCore rewrite with zero prior context. Read it top to
bottom before doing anything.

> HARD RULE: Only create or modify files UNDER
> `D:\<USER>\LavaCode\AI\mahalo-agentcore`. NEVER write to
> `D:\<USER>\LavaCode\AI\mahalo-dock` — that is the original, working
> project kept as a fallback demo. You MAY read from mahalo-dock to copy reusable
> assets, but never edit it. (If your workspace root is mahalo-agentcore, that
> protection is mostly automatic.)

---

## What this project is

A ground-up rewrite of "mahalo-dock" (a multi-persona SDLC chat assistant over
four mock enterprise systems: Jira, Confluence, GitHub/Gitea, ServiceNow) to use
the **Amazon Bedrock AgentCore** stack + **Strands Agents SDK** instead of the
old hand-rolled LangChain/LangGraph agent loop.

Target architecture (see docs/ARCHITECTURE.md):
- Strands Agents SDK = the reasoning/tool loop (replaces LangChain).
- AgentCore Runtime = hosts the agent (managed, in AWS).
- AgentCore Gateway = exposes the 4 mock systems (as Lambdas) as MCP tools.
- AgentCore Memory = sessions + conversation history (replaces in-memory session.py).
- AgentCore Identity = brokers tool credentials.
- Self-hosted Gitea = real branch/commit/PR backend (kept, always-on host).
- Next.js frontend = reused from mahalo-dock.
- AWS CDK (Python) = IaC for everything (must survive a monthly account reset).

Full phased plan: docs/PLAN.md. This file covers operational details that plan
doesn't.

## Status

- Task 0 DONE: skeleton, docs, scripts/verify-agentcore.ps1, git repo. First
  commit pushed to https://github.com/tjblavakumar/mahalo-agentcore (branch main).
- NEXT: Task 1 — a Strands agent running LOCALLY that calls the EXISTING
  mahalo-dock mock services over HTTP (read tools first), proving the new loop
  works with no LangChain.

## AWS environment (verified)

- Account: <AWS_ACCOUNT_ID>, Region: us-east-1, SSO profile: `lava`.
- Re-auth when the session expires: `aws sso login --profile lava`, verify with
  `aws sts get-caller-identity --profile lava`.
- Bedrock model (tool-calling, verified ACTIVE):
  `us.anthropic.claude-sonnet-4-5-20250929-v1:0`.
- AgentCore capability check PASSED (11/11). Re-run anytime:
  `pwsh ./scripts/verify-agentcore.ps1`.
- Toolchain: Python 3.13, Node 24, npm 11, AWS CLI v2, AWS CDK 2.1145.0.
- SDKs install cleanly: `strands-agents` (1.61.1), `bedrock-agentcore` (1.24.1).

## The running mock backend (Task 1 uses option "a" = reuse what's deployed)

The mahalo-dock stack is already deployed on an EC2 instance and is the backend
Task 1 talks to. Do NOT redeploy it; just reach it over an SSH tunnel.

- EC2 instance: `i-0234d7d98744d60b9`, public IP **13.223.68.203** (the IP can
  change if the instance is stopped/started — re-check with:
  `aws ec2 describe-instances --filters "Name=tag:project,Values=mahalo-dock" "Name=instance-state-name,Values=running" --query "Reservations[0].Instances[0].PublicIpAddress" --output text --profile lava --region us-east-1`).
- SSH key: `%USERPROFILE%\.ssh\mahalo-dock-key.pem`.
- Mock services are published on the EC2 host on these ports (verified):
  - mock-jira 5001, mock-confluence 5002, mock-github 5003, mock-servicenow 5004
  - backend 8008, frontend 3000, gitea 3001
- Static auth header for every mock: `X-API-Token: mock-<svc>-token-12345`
  (e.g. `mock-jira-token-12345`, `mock-github-token-12345`).

### Open the tunnel for Task 1 (INCLUDES the mock ports 5001-5004)

The old tunnel only forwarded 3000/3001/8008. For Task 1 the agent calls the
mocks directly, so ALSO forward 5001-5004. Run in a separate terminal, leave open:

```powershell
ssh -i "$env:USERPROFILE\.ssh\mahalo-dock-key.pem" -N `
  -L 5001:localhost:5001 -L 5002:localhost:5002 `
  -L 5003:localhost:5003 -L 5004:localhost:5004 `
  -L 8008:localhost:8008 -L 3001:localhost:3001 `
  ubuntu@13.223.68.203
```

Then the agent's mock base URLs are: http://localhost:5001 (jira),
http://localhost:5002 (confluence), http://localhost:5003 (github),
http://localhost:5004 (servicenow). Make these ENV-CONFIGURABLE in the agent so
the same code works against localhost-tunnel now and other hosts later.

Quick reachability check once the tunnel is up:
```powershell
curl.exe -s -H "X-API-Token: mock-jira-token-12345" http://localhost:5001/projects
```

## Reuse map (copy FROM mahalo-dock, never edit it there)

Framework-agnostic assets to copy into mahalo-agentcore as Task 1+ needs them:
- Seed data: `mahalo-dock/mock-services/*/seed_data.py` (verbatim) — only needed
  when mocks become Lambdas (Task 3); Task 1 just calls the live mocks.
- Prompts: `mahalo-dock/backend/app/agent/prompts.py` (base + 3 role prompts,
  behavioral rules) -> port into the Strands system prompt.
- Tool CONTRACTS/semantics (names, params, read vs write) — see the tool list in
  docs/PLAN.md and the mahalo-dock tool modules under
  `backend/app/agent/tools/{jira,github,confluence,servicenow}_tools.py`.
- DB models + JWT auth + persona/project seeding (for the Task 6 thin API):
  `backend/app/models/`, `services/auth_service.py`, `services/identity.py`,
  `services/user_seed.py`, `services/project_seed.py`.
- Frontend: the whole `mahalo-dock/frontend/` (Task 7).
- Hard-won behaviors to carry forward: Bedrock read_timeout=300s; real repo NAME
  discipline (never invent repo-1 etc.; use github list -> real names like
  payment-service); persona identity mapping (lava@dev/exe/pm.com -> dev-6);
  github author->dev-6 mapping; proxy error propagation; dashboard array guards;
  propose/approve human-in-the-loop on all writes.

## The 7 write actions (preserve the human-approval gate)

create_story, update_story, create_branch, commit_files, open_pull_request,
create_incident. In mahalo-dock these were proposed (not executed) and approved
in a second step. Reproduce this human-in-the-loop in Strands (Task 2). Also keep
the "branch already exists = success" resilience and the branch->commit->PR
chaining.

## Task 1 — concrete definition (do this next)

Goal: a Strands agent, run LOCALLY, that answers read questions by calling the
live EC2 mocks over the tunnel. No LangChain anywhere.

1. In `agent/`, create a Python package with a venv and
   `requirements.txt` pinning `strands-agents`, `bedrock-agentcore`, `boto3`,
   `httpx`. (Keep .venv out of git — already in .gitignore.)
2. Configure the Strands agent to use Bedrock model
   `us.anthropic.claude-sonnet-4-5-20250929-v1:0` in us-east-1, with a botocore
   read timeout of 300s (large code-gen responses exceed the 60s default).
   Creds come from the `lava` profile locally (AWS_PROFILE=lava) — do NOT bake
   keys.
3. Port the base + developer role system prompt from
   mahalo-dock/backend/app/agent/prompts.py.
4. Implement the READ tools as Strands tools (HTTP + X-API-Token), base URLs
   from env (defaults to the localhost tunnel ports above):
   - jira: list_projects, list_developers, search_stories,
     get_stories_by_assignee, get_story, get_sprint_info, get_board
   - github: list_repos, get_pull_requests, get_commits, get_repo_stats
   - confluence: search, get_page, list_spaces
   - servicenow: list_deployments, deployment_status_by_project,
     list_incidents, get_incident, get_stats
   Keep the behavioral rules in tool descriptions (real repo names; resolve
   people to dev-ids; current user = dev-6 for "me/my").
5. Provide a small CLI/REPL (e.g. `python -m agent.chat "show my stories"`) for
   manual testing.
6. Tests: unit-test the tool HTTP wrappers (mocked), and ONE integration test
   that hits the live mocks via the tunnel ("show my stories" -> dev-6 -> PAY
   stories; "list my repositories" -> payment-service). Integration test should
   skip gracefully if the tunnel/mocks are unreachable.

Verification for Task 1: with the tunnel up and AWS session valid, the REPL
answers "list my repositories" (returns payment-service) and "show PAY-109"
correctly, routing through Strands + Bedrock, with zero LangChain imports.
Defer the write/propose/approve flow to Task 2.

## Working agreement for every session

- Only write under mahalo-agentcore. Never edit mahalo-dock.
- Commit to the mahalo-agentcore repo (origin/main) at the end of each task with
  a clear message; keep mahalo-dock's git history separate.
- Update this file's "Status" section and docs/PLAN.md as tasks complete.
- Each task should produce something runnable (phased build).
