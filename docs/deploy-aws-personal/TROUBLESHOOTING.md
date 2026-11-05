# Troubleshooting

Find the symptom, apply the fix, and re-run the same command. Stages are idempotent.
If your problem is not here, stop and report the exact error text; do not change repository code.

## Preflight failures

| Symptom | Cause | Fix |
|---|---|---|
| `AWS credentials: not usable` | No profile, wrong profile, or expired SSO session | `aws configure --profile personal`, or `aws sso login --profile personal`, then pass `--profile personal` |
| `Bedrock model: ... not invokable` / `AccessDeniedException` | Claude Sonnet 4.5 not enabled for the account or region | In the Bedrock console enable Claude Sonnet 4.5 (Anthropic may ask for a one-time use-case form), wait a minute, retry |
| `Region: ... is not a US region` | The stack uses the `us.` cross-region inference profile | Use `--region us-east-1` (`us-east-2` and `us-west-2` also work) |
| `Bedrock AgentCore: ... not available in this region` | AgentCore is not offered in that region | Use `us-east-1` |
| `Bedrock AgentCore: WARN ... AWS CLI is too old` | The CLI has no `bedrock-agentcore-control` command | Upgrade AWS CLI v2. This is only a warning; the deploy can still work |
| `Docker: not running` | Docker Desktop is stopped | Start Docker Desktop, make sure it is in **Linux containers** mode |
| `arm64 images: x86 host cannot run linux/arm64 containers` | No emulation | Update Docker Desktop. On Linux: `docker run --privileged --rm tonistiigi/binfmt --install arm64` |
| `Node.js: ... need >= 20.9` | Old Node | Install Node 22 or 24 LTS |
| `Stale CDK state` warning | `infra-cdk/cdk.context.json` or `cdk.out` left from another account | Delete both, then re-run |
| `CDK bootstrap: not bootstrapped yet` (WARN) | Fresh account | Run the `bootstrap` command |

## Deploy failures

| Symptom | Cause | Fix |
|---|---|---|
| `SSM parameter /cdk-bootstrap/.../version not found` | Account not bootstrapped | Run `deploy.py bootstrap` |
| `ExpiredToken` / `The security token included in the request is expired` mid-deploy | Short-lived credentials ran out | Refresh credentials (`aws sso login`), re-run the same stage |
| Stack is `ROLLBACK_COMPLETE` | A first-time create failed and CloudFormation rolled back | Run `deploy.py destroy`, which removes it, then deploy again. Read the failure reason with `aws cloudformation describe-stack-events --stack-name <name>` first |
| `exec format error` during the Docker build | arm64 emulation missing on an x86 host | See the arm64 row above |
| `ENAMETOOLONG` with `cdk.out/asset...` nested paths | A stale `cdk.out` inside an asset | Delete `infra-cdk/cdk.out` and retry |
| `Cannot connect to the Docker daemon` during `runtime-api` | Docker stopped mid-run | Start Docker, re-run `--stage runtime-api` |
| Pull errors from `public.ecr.aws` | Network or rate limit | Retry later; check connectivity |
| `npm ci` fails with an engines error | Node too old | Install Node 20.9 or newer |
| `next build` runs out of memory | Small machine | Close other apps and retry; needs about 2 GB free |
| Long paths error on Windows | Repo cloned deep in the tree | Clone to a short path such as `C:/src/mahalo` and enable Windows long paths |
| `cdk` says it cannot find `python` or imports fail | Wrong interpreter | `deploy.py` puts `infra-cdk/.venv` first on PATH. If you run `npx aws-cdk` by hand, activate that venv first |
| Deploy seems stuck for a minute or two before any AWS output | CDK is synthesizing all 13 stacks | Normal. Wait |
| `Resource handler returned message: ... already exists` | A previous partial deploy left a resource | `destroy`, then deploy again. If it is a named table, delete the leftover table in the console |
| AgentCore resource create fails with a permissions error | The deploying identity lacks rights | Use an administrator-level identity for the first deploy |

## After deploy

| Symptom | Cause | Fix |
|---|---|---|
| Frontend is blank or HTTP 403 right after the deploy | CloudFront still propagating | Wait 5 to 10 minutes and hard refresh. `verify` retries automatically |
| First chat takes about a minute | Cold start of the agent container | Normal. Later calls are faster. `--with-keepwarm` reduces it on weekdays |
| Chat returns an error mentioning `AccessDenied` for `InvokeModel` | Model not enabled, or wrong region | Re-run preflight; enable the model in the Bedrock console |
| Chat returns HTTP 502 | Agent runtime error | Open CloudWatch Logs and look for the log group whose name contains `bedrock-agentcore` (the Runtime's) for the real error |
| Chat says the session id is too short | AgentCore Runtime needs a session id of 33 or more characters | The thin API already normalizes short ids. If you call the Runtime yourself, use a longer id |
| Dashboard is empty | New persona with a saved empty set | Expected after you delete every widget; defaults only seed a never-seen persona |
| Connections page Gitea link does not work | It points at the original author's Gitea host | Expected in this mock-git version. Ignore it |
| `verify` dashboard check fails with HTTP 5xx | DynamoDB or the API Lambda not ready | Wait a minute and re-run `verify`; check the API Lambda's CloudWatch logs |

## Destroy problems

| Symptom | Fix |
|---|---|
| Frontend stack fails to delete the bucket | Re-run `destroy`; the bucket empties via a custom resource and occasionally needs a second pass |
| `CDKToolkit` remains | By design (bootstrap resources). Remove manually if you want a fully clean account: empty the assets bucket and the ECR repository, then delete the stack |

## Still stuck

Collect, and report to the user: the exact command, the full error text, `deploy.py status`
output, and the failing stack's events (`aws cloudformation describe-stack-events --stack-name <name>`
filtered to `FAILED`). Do not paste credentials or the account id into public places.
