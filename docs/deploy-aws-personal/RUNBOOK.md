# RUNBOOK: deploy MAHALO to a personal AWS account

This runbook is written for an **operator**, who can be you or an AI assistant such as
Kiro or GitHub Copilot working in your terminal. Follow it in order. Do not skip the
gates. Every command below is run from the repository root.

Scope: the **mock-git** version. Jira, Confluence, ServiceNow and GitHub are all mock
Lambdas backed by DynamoDB. Real Gitea is not included.

---

## 0. Rules for the operator (read first)

1. **Never ask for, accept, or paste AWS access keys or secrets.** The user configures
   credentials locally (step 2). You only ever need a profile name.
2. **Confirm the AWS account with the user before anything that changes AWS.**
   Show the output of `python docs/deploy-aws-personal/deploy.py preflight` (it prints the
   account). Then use `--expect-account <12-digit id>` and `--yes` on mutating commands, so a
   wrong profile cannot deploy into the wrong account.
3. **Do not edit repository source code** to make a deploy work. If something fails, check
   `TROUBLESHOOTING.md`. If it is not covered, stop and report the exact error to the user.
4. **Never run `destroy` without the user's explicit approval** in the current conversation.
5. **Do not commit or push anything** during a deployment. Do not write the account id, URLs
   or credentials into any file in the repo.
6. **Long commands are normal.** The `runtime-api` and `frontend` stages can each take 10 to 30
   minutes. Do not kill them. Use a long timeout, or run in the background and poll with
   `python docs/deploy-aws-personal/deploy.py status`.
7. **Every stage is safe to re-run.** CloudFormation converges. If a stage fails, fix the
   cause and run the same command again.
8. **Stop at the first FAIL** and report it. Do not work around a failed preflight check.

---

## 1. Get the code

```
git clone https://github.com/tjblavakumar/mahalo-agentcore.git
cd mahalo-agentcore
```

On Windows, clone to a short path such as `C:/src/mahalo` to avoid long-path problems in
`node_modules` and `cdk.out`.

## 2. Install the tools (once)

| Tool | Version | Check |
|---|---|---|
| Python | 3.10 or newer | `python --version` |
| Node.js | 20.9 or newer (22 or 24 LTS recommended) | `node --version` |
| AWS CLI | v2, recent | `aws --version` |
| Docker | Docker Desktop with Linux containers, running | `docker info` |
| git | any | `git --version` |

Docker is required: the agent image (linux/arm64) is built locally and the API Lambda's
dependencies are bundled in a container. On an Apple Silicon Mac this is native. On an x86
Windows or Linux machine the arm64 image builds under emulation, which works but is slower.

## 3. Configure credentials for the personal account (the user does this)

Pick one. The user runs it in their own terminal; nothing is typed into a chat.

```
aws configure --profile personal          # access key based
aws configure sso --profile personal      # IAM Identity Center based (then: aws sso login --profile personal)
```

The identity needs administrator-level rights for the first deploy. CDK bootstrap and the
stacks create IAM roles, Lambdas, DynamoDB tables, S3, CloudFront, ECR, Bedrock AgentCore
resources and SSM parameters.

Check it:

```
aws sts get-caller-identity --profile personal
```

**Gate:** the account id printed must be the user's personal account. Ask the user to confirm it.

## 4. Enable the model (the user does this, in the console)

Open the AWS console in the target region, go to **Amazon Bedrock**, and make sure
**Claude Sonnet 4.5** is available to the account. Anthropic models may ask for a one-time
use-case form. Region must be a **US** region (use `us-east-1`); the stacks use the
`us.` cross-region inference profile.

Preflight proves access with a real 5-token call, so you do not need to guess.

## 5. Preflight (read-only)

```
python docs/deploy-aws-personal/deploy.py preflight --profile personal --region us-east-1
```

It checks Python, Node, npm, AWS CLI, credentials, region, CDK bootstrap, Docker (including
arm64 support), a real Bedrock call, and AgentCore availability. Expected end:

```
Preflight: N passed, 1 warnings, 0 failed.
Preflight is clean enough to deploy.
```

One WARN is expected on a fresh account: **CDK bootstrap not done yet**. Any **FAIL** blocks
the deployment: see `TROUBLESHOOTING.md`, fix it, and re-run preflight until clean.

## 6. Set a spend alarm (recommended)

```
python docs/deploy-aws-personal/deploy.py budget --profile personal --region us-east-1 --email you@example.com --amount 20
```

This creates a daily budget that emails at 80 percent and 100 percent. If it fails with a
billing-access error, enable IAM access to billing in the account settings or create the budget
in the console (Billing, Budgets).

## 7. Bootstrap CDK (once per account and region)

```
python docs/deploy-aws-personal/deploy.py bootstrap --profile personal --region us-east-1 --expect-account <ACCOUNT_ID> --yes
```

It shows the account, region and principal, then runs `cdk bootstrap`. Takes a few minutes.

## 8. Deploy

Simplest, all stages in order:

```
python docs/deploy-aws-personal/deploy.py deploy --profile personal --region us-east-1 --expect-account <ACCOUNT_ID> --yes
```

Or one stage at a time (recommended for an AI operator, so each result can be reported):

| Stage | Command suffix | What it creates | Needs Docker |
|---|---|---|---|
| 1 backend | `--stage backend` | AgentCore Memory and Identity, AgentCore Gateway, the four mock Lambdas, DynamoDB tables | no |
| 2 runtime-api | `--stage runtime-api` | Agent image built and pushed to ECR, AgentCore Runtime, the thin API Lambda (Function URL) | **yes** |
| 3 frontend | `--stage frontend` | Builds the site with the API URL baked in, S3 bucket, CloudFront | no |

Notes:

- Each stage runs `cdk deploy`, which first **synthesizes the whole CDK app** (about 1 to 2
  minutes on a typical laptop) before touching AWS. That is expected.
- Add `--with-keepwarm` to the `runtime-api` stage to also deploy a small scheduled ping that keeps
  the agent warm on weekday demo hours. It adds a small recurring cost, so it is off by default.
- Rough time for a first full run is on the order of an hour. That is an estimate, not a
  measurement; CloudFront creation and the image build dominate.
- `--dry-run` prints every command without running it. Use it to preview.

## 9. Outputs and verification

```
python docs/deploy-aws-personal/deploy.py outputs --profile personal --region us-east-1
python docs/deploy-aws-personal/deploy.py verify  --profile personal --region us-east-1
```

`verify` checks the frontend (HTTP 200), the dashboard API (DynamoDB seeded default) and a real
chat through AgentCore Runtime. The first chat can take about a minute (cold start). All three
must print PASS.

## 10. Manual validation (the user, in a browser)

Open the `FrontendUrl` from `outputs`. Demo logins (hard-coded demo credentials, not secrets):

| User | Password | Persona |
|---|---|---|
| `pm` | `pm123` | Product Manager |
| `dev` | `dev123` | Developer |
| `exec` | `exec123` | Executive |

Try:

1. Log in as `pm`, open **Chat**, ask "Give me a delivery status overview". Expect a formatted
   table within about a minute (first call slower).
2. Open **Dashboard**. Expect a pre-seeded chart, all five projects selected, and a "Suggested
   for you" strip that fills in after a few seconds. Add a suggestion, reload, and confirm it persisted.
3. Ask "create a story in PAY". Expect an approve/reject card (nothing is written until you approve).
4. Log in as `dev` and `exec` and confirm each persona gets different content.

Known limitation: the **Connections** page has an "Open" link for GitHub that points at the
original author's Gitea host, not yours. In this mock-git deployment it will not work. Ignore it.

## 11. Teardown

Only with the user's explicit approval:

```
python docs/deploy-aws-personal/deploy.py destroy --profile personal --region us-east-1 --expect-account <ACCOUNT_ID> --yes
```

This deletes every MAHALO stack and its data. These small items remain after `destroy` because
they belong to CDK bootstrap: the `CDKToolkit` stack, an S3 assets bucket and an ECR repository
holding old agent images. They cost cents per month. To remove them completely: empty the
bucket and the repository, then delete the `CDKToolkit` stack in the CloudFormation console.

Also delete the budget (Billing, Budgets) if you created one.

## 12. Cost

These are estimates from published rates, not a bill. A light demo day (a few dozen agent
questions) is roughly $3 to $8; heavy testing stays under about $30. Almost all of it is Bedrock
token spend, not infrastructure. See `docs/aws-personal-cloud-deployment.md` section 9 for the
breakdown. Check AWS Cost Explorer after the first real day.

## 13. Security notes

- The thin API and the four mock Lambdas use public **Function URLs with no authentication**
  (`AuthType=NONE`). Persona identity is a header the browser sends. This is a demo design with
  synthetic data only. Do not put real data in it, and tear it down when finished.
- CloudFront serves the site over HTTPS. The S3 bucket is private.
- Nothing in this package stores credentials. `deploy.py` reads the profile you name.

## 14. Not included, and why

- **Real Gitea** (a self-hosted git server on EC2). It needs extra host bootstrap steps that
  could not be tested here. The GitHub tool runs as a mock Lambda instead.
- **Terraform and Docker Compose.** AgentCore Runtime, Gateway and Memory are managed AWS
  services that cannot run in Compose, and rewriting 13 stacks in Terraform would create a second,
  untested source of truth next to the working CDK app.
- **The EC2 builder stack.** It only existed because the corporate workstation had no Docker.
  Docker on your own machine replaces it.

### Important: the mock-git override

`infra-cdk/cdk.json` sets `giteaMode` to `real` by default, because the original author's
account runs a Gitea server. Your account does not. `deploy.py` therefore appends
`-c giteaMode=mock` to every `cdk` command it runs, so the GitHub tool stays a mock Lambda.
If you ever run `cdk` by hand in `infra-cdk/`, pass `-c giteaMode=mock` yourself, or the
GitHub Lambda will be wired to a Gitea host and SSM token that do not exist in your account.
