# Deploy MAHALO to your own AWS account

A self-contained package to take this repository and run it end to end in a **personal,
unrestricted AWS account**, from your own machine, with no corporate tooling. It is designed to
be driven either by you or by an AI assistant (Kiro, GitHub Copilot) following the runbook.

Scope: the **mock-git** version. Jira, Confluence, ServiceNow and GitHub are mock Lambdas backed
by DynamoDB, so there is no server to run. What you get is the same app: persona login, chat
with the AgentCore agent, the chart dashboard, and the human approval gate on writes.

## What is in this folder

| File | Purpose |
|---|---|
| `RUNBOOK.md` | The step-by-step procedure, with rules and gates. **Start here.** |
| `PROMPT.md` | A ready-to-paste prompt that makes your AI assistant follow the runbook safely. |
| `deploy.py` | The deploy orchestrator (Python, standard library only; Windows, macOS, Linux). |
| `TROUBLESHOOTING.md` | Symptom to fix table for preflight, deploy and post-deploy problems. |
| `tests/` | Offline unit tests for `deploy.py` (no AWS needed). |

No existing code was changed. The package drives the CDK app in `infra-cdk/`, which already
takes its account and region from your credentials.

## Quick start (human)

```
git clone https://github.com/tjblavakumar/mahalo-agentcore.git
cd mahalo-agentcore

aws configure --profile personal                       # your own account
python docs/deploy-aws-personal/deploy.py preflight --profile personal --region us-east-1
python docs/deploy-aws-personal/deploy.py bootstrap --profile personal --region us-east-1
python docs/deploy-aws-personal/deploy.py deploy    --profile personal --region us-east-1
python docs/deploy-aws-personal/deploy.py verify    --profile personal --region us-east-1
```

Each command that changes AWS shows the account, region and principal and asks you to type
`yes`. Use `--expect-account <id>` to refuse any other account, and `--dry-run` to preview.

Commands: `setup`, `preflight`, `bootstrap`, `deploy [--stage backend|runtime-api|frontend]`,
`outputs`, `status`, `verify`, `budget`, `destroy`, and `up` (preflight, bootstrap, deploy, verify).

## Prerequisites

| Need | Detail |
|---|---|
| AWS account | Personal, with administrator-level rights for the first deploy |
| Python | 3.10 or newer |
| Node.js | 20.9 or newer (22 or 24 LTS recommended) |
| AWS CLI | v2, recent |
| Docker | Docker Desktop, Linux containers, running. Builds the arm64 agent image |
| Bedrock | Claude Sonnet 4.5 enabled in a **US** region (use `us-east-1`) |

## What gets created

Ten CloudFormation stacks in one region: AgentCore Memory, Identity, Gateway and Runtime; the
four mock Lambdas; the thin API Lambda (public Function URL); DynamoDB tables for the mock data
and for saved dashboards; a private S3 bucket and a CloudFront distribution for the site. An
eleventh stack, a small keep-warm schedule, is available with `--with-keepwarm`.

## Cost

Estimates from published rates, not a bill: roughly **$3 to $8 per light demo day**, under about
$30 with heavy testing. Almost all of it is Bedrock token usage. Set a spend alarm first:

```
python docs/deploy-aws-personal/deploy.py budget --profile personal --email you@example.com --amount 20
```

## Honest limits

- This package was **verified offline only**: unit tests, a dry-run of the full plan, and a check
  that its stack names match what the CDK app really synthesizes. It has not been run against a
  live personal account, so your first run may surface account-specific surprises (model access,
  quotas, the arm64 build on your hardware). The troubleshooting table covers the likely ones.
- Each deploy stage re-synthesizes the whole CDK app first (about 1 to 2 minutes). That is normal.
- The public API endpoints have no authentication. It is a demo with synthetic data. Tear it down
  when you are done.
- The Connections page's Gitea link points at the original author's host and will not work here.

## Tests

```
python -m unittest discover -s docs/deploy-aws-personal/tests -v
```
