# Plan: deploying Mahalo into an AWS Innovation Sandbox lease

Status: **PLAN ONLY, not started.** Nothing in this document has been built. Discussed with the user on 2026-11-25.

## Why

The company is moving to the [Innovation Sandbox on AWS](https://docs.aws.amazon.com/solutions/latest/innovation-sandbox-on-aws/solution-overview.html) model. Instead of one long-lived AWS account, a user leases a temporary account from a pool. When the lease ends, the account is cleaned with AWS Nuke and returned to the pool ([account lifecycle](https://docs.aws.amazon.com/solutions/latest/innovation-sandbox-on-aws/account-lifecycle-in-isb.html), [cleanup](https://docs.aws.amazon.com/solutions/latest/innovation-sandbox-on-aws/account-cleaner-component.html)). Mahalo today is deployed once, by hand, from a WorkSpace with local tools and an EC2 builder. That does not fit a 30-day disposable account.

Goal: **fresh lease, one command from AWS CloudShell, demo ready in about 30 to 40 minutes**, with no dependence on the local desktop.

## Known lease facts (from the user)

| Question | Answer |
|---|---|
| Lease length | 30 days |
| Regions | Current region only (us-east-1 assumed) |
| Services | Everything Mahalo uses is allowed; the default allowed-services list is not narrowed |
| GitHub access from the account | Expected to work (the repo is public) |
| CDK bootstrap survives cleanup? | No: bootstrap every lease |
| Lease budget | **Unknown: ask** |

The default [allowed services](https://docs.aws.amazon.com/solutions/latest/innovation-sandbox-on-aws/allowed-services-reference.html) include Bedrock, Bedrock AgentCore, CloudFormation, CloudFront, CodeBuild, CodePipeline, CloudShell and Cognito (identity pools and user pools).

## Blocking risk: Bedrock cross-region inference

Mahalo calls Claude Sonnet 4.5 and Nova Lite through US cross-region **inference profiles** (model ids starting `us.`). Bedrock may route those calls to us-east-2 or us-west-2. The sandbox's region-limit SCP then denies the call with an error naming a region the user never asked for. This is an open issue in the solution: [aws-solutions/innovation-sandbox-on-aws#74](https://github.com/aws-solutions/innovation-sandbox-on-aws/issues/74), with no released fix at the time of writing.

- Newer Claude models on Bedrock are, as far as we know, offered only through inference profiles, so switching to a single-region model id is probably not possible. Verify in the first lease.
- **Ask the cloud team** to add the exception proposed in that issue to the region-limit SCP: allow requests that carry `bedrock:InferenceProfileArn` for `us.*` inference profiles (US-only routing keeps data in US regions).
- **Day-one test (1 minute, from CloudShell):** one `bedrock-runtime converse` call to the `us.anthropic.claude-sonnet-4-5...` profile, and one to the `us.amazon.nova-lite...` profile. If they work, the agent will work.

## What a lease looks like

| When | What happens |
|---|---|
| Day 1 | Open CloudShell. `git clone` the public repo. Run `scripts/sandbox-up.sh`. It bootstraps CDK, creates a CodeBuild project, and starts a build that deploys everything (below). At the end it prints the site URL, the API URL and the Gitea URL. |
| Days 1 to 30 | Demo as usual. Before each demo: Settings, Refresh demo data. |
| Lease end | AWS Nuke deletes everything. Next lease: repeat day 1. |

Build order inside CodeBuild (Docker is available there, so no EC2 builder):

1. `cdk bootstrap` (every lease).
2. Mock services (Jira, Confluence, ServiceNow, GitHub), DynamoDB tables, Memory/Identity, Skills, Dashboard, Model config stacks.
3. Gitea stack, then wait for Gitea to answer, then `gitea/seed_gitea.py` (repos, branches, PRs).
4. GitHub mock in real-Gitea mode, using the Gitea URL **read from the Gitea stack output** (not hard-coded).
5. Gateway, then Runtime (agent image), then the thin API (Lambda bundle).
6. Frontend: `next build` with `NEXT_PUBLIC_API_URL` (and the Gitea link) read from stack outputs, S3 sync, CloudFront invalidation.
7. `POST /admin/refresh-demo-data` so dates are re-based to the lease's today.
8. Smoke test: `/briefing` for each persona, one chat call, `/JIRA_ROADMAP PAY` (Sprint A 29 of 30, Sprint B 26 of 30). Print the URLs.

## Code changes needed (small)

The application code (agent, thin API, mock services, frontend logic, skills) does **not** change. The work is deployment tooling plus a few hard-coded values.

| Change | Where | Size |
|---|---|---|
| Gitea URL comes from the Gitea stack output instead of a literal | `infra-cdk/app.py` (`_GITEA_ENV`) | Small |
| Connections page Gitea link from a build-time env var (for example `NEXT_PUBLIC_GITEA_URL`) | `frontend/src/lib/connections.ts` + its test | Small |
| One CloudShell entry script | new `scripts/sandbox-up.sh` | Medium |
| CodeBuild project (role, privileged Docker build) and buildspec running the order above | new small CDK/CloudFormation stack + `buildspec` | Medium |
| Stop hard-coding the CloudFront distribution id, frontend bucket, API URL and instance ids in scripts: read stack outputs | build scripts (the old `scripts/builder-deploy.sh` logic is reused, not the EC2 builder) | Small |
| Optional teardown script for an early, clean stop | new `scripts/sandbox-down.sh` | Small |
| Docs: replace hard-coded URLs with "printed by sandbox-up" | about 14 docs | Small, text only |

Starting points that already exist: `docs/deploy-aws-personal/` (`deploy.py` with setup / preflight / bootstrap / deploy / outputs / verify / destroy), `scripts/builder-deploy.sh`, `gitea/aws-host-bootstrap.sh`, `gitea/seed_gitea.py`, `gitea/verify_gitea.py`. The EC2 builder (`MahaloBuilderStack`) is no longer needed in a sandbox.

## What is lost every lease

| Lost | Handling |
|---|---|
| Jira, Confluence, ServiceNow demo data | Reseeded by the build (step 7) |
| Gitea repos, branches and PRs, including rehearsal branches | Re-seeded by `seed_gitea.py` |
| Uploaded skills, saved dashboards, model settings (DynamoDB) | Lost. Keep important skills as files in `skills/` so they are built in |
| AgentCore Memory (chat history) | Lost; fine for a demo |
| URLs (site, API, Gateway, Gitea) | New each lease; printed at the end of the build |
| Gitea admin password | Generated per lease, stored in SSM Parameter Store, never committed |

## Budget (rough, not measured)

| Item | Monthly cost |
|---|---|
| Gitea EC2 (always on) | about $15 to $20 |
| CloudFront, Lambda, DynamoDB | a few dollars |
| AgentCore Runtime and Bedrock | usage-based; roughly a few dollars per full demo run with Sonnet |
| CodeBuild deploys | cents per deploy |
| WAF IP allow-list (if added) | about $5 to $10 |

A budget threshold breach can **freeze** the account and revoke access, so set an AWS Budgets alarm well below the lease's freeze threshold.

**Option to cut cost and setup time:** run without Gitea (the GitHub mock in DynamoDB mode, which the app already supports). This removes the only server but loses the "real git" proof point. Decide per audience.

## Security (after the deploy works)

1. **IP allow-list:** AWS WAF on the CloudFront distribution, allowing only the corporate egress ranges.
2. **API behind CloudFront:** today the thin API is a public Lambda Function URL (AuthType NONE). Route it through the same CloudFront with origin access control and AuthType AWS_IAM so only the site can reach it.
3. **Edge password:** an optional simple password at CloudFront, on top of the demo logins.
4. **Cognito sign-in:** allowed in the sandbox (it is blocked by SCP in the current account), so real sign-in becomes possible later. Long term: the company identity provider (Okta).

Lightsail and EKS were considered and rejected: Lightsail would mean rewriting the app as a single server and dropping AgentCore, Gateway and Lambda; EKS adds a control-plane cost of about $70 a month plus operational work. Neither solves the real problem, which is a repeatable deploy into a temporary account.

## Questions still open

1. What is the lease budget, and at what threshold does the account freeze?
2. Will the cloud team add the Bedrock inference-profile exception to the region-limit SCP?
3. Is Claude Sonnet 4.5 (and Nova Lite) model access already enabled in leased accounts?
4. Can a demo account be kept past 30 days or ejected if a key demo falls near a lease end?

## Suggested order

1. First lease: run the day-one Bedrock test; send the SCP request to the cloud team.
2. Build the one-command deploy (sandbox-up script, CodeBuild project, removal of hard-coded values) as a reviewed workflow with user approval gates.
3. Add security (IP allow-list, API behind CloudFront).
4. Optional: Cognito sign-in; Gitea-off mode for low-budget leases.
