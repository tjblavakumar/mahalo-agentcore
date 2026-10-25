# Implementation Plan — Put the live Gitea instance behind HTTPS/443 via CloudFront

## Goal (one line)
Give the user a working `https://<cloudfront-domain>/` URL (over 443 only) that serves the
Gitea web UI + REST API from the browser, so a corporate network that blocks all non-443
outbound ports can reach Gitea and the user can log in as `mahalo_admin`.

## Why CloudFront (chosen approach + rationale)
The office network blocks the *port* (3000), not the host — `http://32.193.103.5:3000` is
routable but times out from the browser. CloudFront terminates HTTPS on 443 (which the
network allows) and forwards to the Gitea origin over AWS's own network (not the office
network), so the origin can stay plain HTTP:3000. This mirrors the existing
`MahaloFrontendStack` CloudFront pattern already proven in this repo. The agent's write path
is unaffected: the github Lambda talks to Gitea at `http://<eip>:3000` internally and does
NOT go through CloudFront, so CloudFront only needs to serve the interactive UI + REST API to
the browser. We do NOT touch `HTTP_PORT` (stays 3000) or the `0.0.0.0` bind.

## Verified facts this plan is grounded in
- Stack: `infra-cdk/mahalo_infra/gitea_stack.py` class `MahaloGiteaStack`, wired in
  `infra-cdk/app.py` as `MahaloGiteaStack(app, "MahaloGiteaStack", env=_ENV)`.
- CfnParameters on the stack: `AdminCidr` (no default — REQUIRED on deploy; was
  `3.83.200.219/32`), `GiteaIngressCidr` (default `0.0.0.0/0`), `RetainGiteaData`
  (default `false`), `GiteaTokenParamName`, `GiteaAdminPasswordParamName`, `GiteaAdminUser`.
- Live: instance `i-06d65fadd3fbd211b`, image `gitea/gitea:1.27.3`, container name `gitea`,
  `--restart=always`, bound `0.0.0.0:3000`. EIP `32.193.103.5`
  (public DNS `ec2-32-193-103-5.compute-1.amazonaws.com`). SG `sg-04c06aeba215f7b94`
  (tcp/3000 from 0.0.0.0/0, tcp/22 from `3.83.200.219/32`).
- app.ini: inside container `/data/gitea/conf/app.ini`; host path is the `/data` bind mount
  + `/gitea/conf/app.ini`. INSTALL_LOCK=true. MUST stay `chown 1000:1000` / `chmod 660`
  or Gitea crash-loops on OAUTH2_JWT_SECRET write.
- gitea CLI inside container runs as git:
  `docker exec -u git gitea gitea --config /data/gitea/conf/app.ini ...`.
- CloudFront pattern reference: `infra-cdk/mahalo_infra/frontend_stack.py` uses
  `aws_cloudfront as cloudfront`, `aws_cloudfront_origins as origins`,
  `cloudfront.Distribution(...)`, `cloudfront.BehaviorOptions(...)`.
- CDK version in `infra-cdk/.venv` (`aws-cdk-lib>=2.251`) CONFIRMS these symbols exist:
  `origins.HttpOrigin`, `cloudfront.OriginProtocolPolicy.HTTP_ONLY`,
  `cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS`, `cloudfront.AllowedMethods.ALLOW_ALL`,
  `cloudfront.CachePolicy.CACHING_DISABLED`,
  `cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER`.
- No local Docker, no SSH. On-box work via SSM Run Command (`AWS-RunShellScript`);
  SSM agent is Online on the instance. Fetch results with
  `aws ssm get-command-invocation`.
- VDI gotcha: CDK/Node SDK cannot read the SSO token cache. Before any cdk/SDK-authenticated
  command, export creds into the env. Plain `aws` CLI can use `--profile lava` directly.

---

## CHOSEN DEPLOY PATH: out-of-band `aws cloudfront create-distribution` + commit the CDK change (do NOT `cdk deploy`)

Rationale (the key risk decision): `MahaloGiteaStack` owns the LIVE, stateful instance,
its EBS data volume, and (critically) the EIP association is NOT part of this stack — the
EIP `eipalloc-0d582218ab8434359` and its association were created out-of-band after the
original deploy (the stack only sets `associate_public_ip_address = True`). A `cdk deploy`
would reconcile the live stack against the template and could (a) try to re-manage or drop
the out-of-band EIP association, and (b) is high-risk against a running instance with
non-reproducible manual state (SSM role attachment, completed install-lock, the EIP) that
was all applied out-of-band per CONTINUATION.md. Deploying is a hard-to-reverse,
broad-blast-radius action on live infra. Therefore:

- **Create the CloudFront distribution out-of-band** with `aws cloudfront create-distribution`
  (plain `aws --profile lava`, no CDK creds dance, no stack reconciliation).
- **Commit the equivalent CDK change** to `gitea_stack.py` so source stays truthful and a
  future clean redeploy reproduces the distribution — but do NOT run `cdk deploy` in this task.
- Before committing, OPTIONALLY run `cdk diff` (read-only, no mutation) to confirm the CDK
  change ADDS only the distribution + output and does not replace/destroy the instance, EIP,
  or EBS. `cdk diff` is safe (no AWS mutation) but needs the env-cred export; it is a
  nice-to-have verification, not required for the out-of-band path.

If the coder later decides a `cdk deploy` is genuinely safe (e.g. after confirming via
`cdk diff` that the only change is `+ AWS::CloudFront::Distribution` and `+ Output`, with
ZERO changes to `AWS::EC2::Instance`, `AWS::EC2::Volume`, `AWS::EC2::EIP*`), that is the
cleaner path — but default to out-of-band and STOP for user confirmation before any
`cdk deploy` against this live stack.

---

## Plan

- [ ] 1. Add the CloudFront distribution + output to the CDK stack (source-of-truth change; not deployed this task).
      In `infra-cdk/mahalo_infra/gitea_stack.py`: add imports
      `from aws_cdk import aws_cloudfront as cloudfront` and
      `from aws_cdk import aws_cloudfront_origins as origins`. After the instance/EIP block
      and before the CfnOutputs, construct `cloudfront.Distribution(self, "GiteaDistribution", ...)`
      with a single `default_behavior=cloudfront.BehaviorOptions(origin=origins.HttpOrigin(
      "ec2-32-193-103-5.compute-1.amazonaws.com", protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
      http_port=3000), viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL, cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
      origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER)`.
      Add `CfnOutput(self, "GiteaCloudFrontUrl", value=f"https://{distribution.distribution_domain_name}",
      description="HTTPS/443 CloudFront front door for the Gitea web UI + REST API.")`.
      Keep the existing `GiteaPublicUrl` (HTTP:3000) output intact — it is still the Lambda-facing URL.
      Rationale: the origin domain is the stable EIP-backed public DNS; HOST-header stripping
      (ALL_VIEWER_EXCEPT_HOST_HEADER) is required so CloudFront forwards everything except Host,
      which matters because Gitea compares the Host against ROOT_URL for some flows; CACHING_DISABLED
      keeps the dynamic UI/API correct; ALLOW_ALL permits the REST API's POST/PUT/DELETE/PATCH.
      Files: `infra-cdk/mahalo_infra/gitea_stack.py`
      Verify: run the stack's synth assertion suite with the venv python —
      `cd infra-cdk; .\.venv\Scripts\python.exe -m pytest tests/test_gitea_stack.py -q` — all
      existing tests still pass (the change is additive; no existing assertion regresses).

- [ ] 2. Add an assertion test that the distribution + output are synthesized.
      In `infra-cdk/tests/test_gitea_stack.py` add `test_cloudfront_distribution_present` asserting
      `tmpl.resource_count_is("AWS::CloudFront::Distribution", 1)` and that
      `tmpl.find_outputs("*")` contains `GiteaCloudFrontUrl`. Follow the existing test style in
      that file (it uses `assertions.Template.from_stack`). This locks the CDK change so a future
      offline gate catches a regression.
      Files: `infra-cdk/tests/test_gitea_stack.py`
      Verify: `cd infra-cdk; .\.venv\Scripts\python.exe -m pytest tests/test_gitea_stack.py -q`
      — the new test passes, existing tests still green.

- [ ] 3. (OPTIONAL, read-only) Confirm the CDK change is purely additive against the live stack.
      Export creds into the env first (SSO cache is unreadable by CDK on this VDI):
      run `aws configure export-credentials --profile lava --format env-no-export` and set every
      `AWS_*` var it prints into the shell, plus `CDK_DEFAULT_ACCOUNT=<AWS_ACCOUNT_ID>` and
      `CDK_DEFAULT_REGION=us-east-1`. Then, WITHOUT `--profile`, run
      `cdk diff MahaloGiteaStack --parameters AdminCidr=3.83.200.219/32` from `infra-cdk/`
      using the venv (cdk.json runs `python app.py`, so the venv python must be active).
      This can exceed 120s (Defender cold-start) — run with a generous timeout or in the
      background; if you hit "Another CLI (PID=...) is currently synthing", remove stale
      `cdk.out/*.lock` and kill stray node processes, then retry.
      EXPECTED: the diff shows ONLY `[+] AWS::CloudFront::Distribution GiteaDistribution` and
      `[+] Output GiteaCloudFrontUrl`, with NO `[~]`/`[-]` on `AWS::EC2::Instance`,
      `AWS::EC2::Volume`, or any EIP resource. `cdk diff` performs NO mutation.
      Files: none (read-only verification).
      Verify: diff output matches the EXPECTED set above. If it shows any change/replace/destroy
      on the instance/EBS/EIP, STOP — do not deploy; the out-of-band path in steps 4-6 is the
      safe route regardless.

- [ ] 4. Create the CloudFront distribution out-of-band via the AWS CLI.
      Write a distribution config JSON (file, e.g. `infra-cdk/.agents/scratch/gitea-cf-dist.json`
      OR a temp path outside the repo) describing a single custom origin
      `ec2-32-193-103-5.compute-1.amazonaws.com` with `CustomOriginConfig` HTTPPort=3000,
      OriginProtocolPolicy `http-only`; DefaultCacheBehavior with ViewerProtocolPolicy
      `redirect-to-https`, AllowedMethods = all 7 (GET,HEAD,OPTIONS,PUT,POST,PATCH,DELETE),
      the AWS managed CachePolicyId for "CachingDisabled"
      (`4135ea2d-6df8-44a3-9df3-4b5a84be39ad`) and the managed OriginRequestPolicyId for
      "AllViewerExceptHostHeader" (`b689b0a8-53d0-40ab-baf2-68738e2966ac`); `Enabled=true`;
      a unique `CallerReference`. Then run
      `aws cloudfront create-distribution --distribution-config file://<path> --profile lava
      --region us-east-1`. Capture the returned `Distribution.Id` and
      `Distribution.DomainName` (the `dxxxx.cloudfront.net` host). CloudFront is a global
      service; `--region us-east-1` is fine for the API call.
      NOTE for the coder: prefer `--distribution-config` from a file over inline JSON to avoid
      PowerShell quoting pain. Do NOT commit any file that contains account-specific ARNs/secrets;
      the managed-policy IDs above are public AWS constants and safe.
      Files: a distribution-config JSON (scratch; not required to commit).
      Verify: the CLI returns HTTP 200 with a `Distribution.Id` and `DomainName`; record both.

- [ ] 5. Set Gitea `ROOT_URL` to the CloudFront HTTPS domain via SSM Run Command (edit app.ini in-container).
      Build a shell script that: reads the host app.ini path via
      `docker inspect gitea --format '{{ range .Mounts }}{{ if eq .Destination "/data" }}{{ .Source }}{{ end }}{{ end }}'`
      + `/gitea/conf/app.ini`; sets `[server] ROOT_URL = https://<cloudfront-domain>/` (and ensures
      `[server] ROOT_URL` exists under the `[server]` section — use awk with the value passed as an
      awk var, mirroring the existing `gitea/aws-host-bootstrap.sh` awk approach so there is no regex
      interpretation); DOES NOT touch `HTTP_PORT` (stays 3000) or the `0.0.0.0` bind; then
      `chown 1000:1000 "$HOSTINI" && chmod 660 "$HOSTINI"`; `docker restart gitea`; and polls
      `curl -fsS http://localhost:3000/api/healthz` up to ~60×2s until healthy.
      base64-encode this whole script locally and have the SSM command
      `echo <b64> | base64 -d > /tmp/set_root_url.sh && bash /tmp/set_root_url.sh` to avoid
      SSM shell-quoting problems. Run it with
      `aws ssm send-command --document-name AWS-RunShellScript --instance-ids i-06d65fadd3fbd211b
      --parameters commands='[...]' --profile lava --region us-east-1`, then poll
      `aws ssm get-command-invocation --command-id <id> --instance-id i-06d65fadd3fbd211b
      --profile lava --region us-east-1` until Status=Success.
      Rationale: `ROOT_URL` must reflect the public HTTPS origin so Gitea builds absolute links
      (OAuth redirects, clone URLs, email links, asset URLs) against `https://<domain>/`, not
      `http://<eip>:3000`. The agent/Lambda write path uses the REST API with explicit URLs and is
      unaffected by ROOT_URL. Keeping the app.ini owned by uid 1000 is MANDATORY (crash-loop risk).
      Files: a local SSM script (scratch).
      Verify: `get-command-invocation` Status=Success and the script's final health poll printed a
      healthy `/api/healthz` (HTTP 200). Also re-read app.ini via a follow-up read-only SSM command
      (`docker exec gitea sh -c 'grep -n ROOT_URL /data/gitea/conf/app.ini; grep -n "^HTTP_PORT" /data/gitea/conf/app.ini'`)
      and confirm ROOT_URL = the CloudFront URL and HTTP_PORT is still 3000.

- [ ] 6. Verify origin health and (if reachable) the CloudFront edge; otherwise hand the final browser check to the user.
      (a) Origin health from the box (SSM, read-only): confirm `curl -fsS http://localhost:3000/api/healthz`
      returns 200 + Gitea health JSON on `i-06d65fadd3fbd211b`.
      (b) Distribution status: `aws cloudfront get-distribution --id <dist-id> --profile lava
      --query 'Distribution.Status'` — wait until it reports `Deployed` (can take 5-15 min).
      (c) Edge check IF the workflow environment can egress to CloudFront: `curl -sS -o /dev/null
      -w '%{http_code}' https://<cloudfront-domain>/api/healthz` expecting 200 with Gitea health
      JSON, and `curl -sS https://<cloudfront-domain>/user/login` expecting 200 with the login page
      (and ROOT_URL reflected in the HTML). NOTE: this VDI/workflow environment may sit behind the
      SAME corporate proxy that blocks non-443 — but CloudFront IS on 443, so the edge check should
      work here even when `:3000` does not; if the environment cannot reach it at all, leave the
      final browser confirmation to the user.
      (d) User-facing: provide `https://<cloudfront-domain>/`, user `mahalo_admin`, password in SSM
      `/mahalo/gitea/admin-password` (reference by name — do NOT echo the secret value).
      Files: none.
      Verify: origin healthz 200 via SSM; distribution Status=Deployed; edge healthz/login 200 if
      reachable; otherwise explicitly note the browser check is deferred to the user.

- [ ] 7. Update CONTINUATION.md / DEMO.md with the new HTTPS URL and the out-of-band distribution.
      Record: the CloudFront distribution id + domain, that it was created OUT-OF-BAND (and the CDK
      change in `gitea_stack.py` mirrors it but was NOT deployed this task), the new `ROOT_URL`, and
      that the HTTP:3000 URL remains the internal Lambda-facing path. Update the Gitea access block in
      `docs/DEMO.md` (if present) with the HTTPS URL.
      Files: `docs/CONTINUATION.md`, `docs/DEMO.md` (if it exists).
      Verify: the new URL and deploy-path note are present and consistent with what was actually done.

- [ ] 8. Commit the CDK + test + doc changes (do NOT push unless asked; do NOT deploy).
      Stage specifically `infra-cdk/mahalo_infra/gitea_stack.py`,
      `infra-cdk/tests/test_gitea_stack.py`, `docs/CONTINUATION.md`, and `docs/DEMO.md` (if changed).
      Do NOT stage scratch distribution-config JSON or any file with credentials. Commit with a
      message describing the CloudFront-front-door addition and the out-of-band deploy decision.
      Files: as listed.
      Verify: `git status` shows only the intended files committed; `git show --stat HEAD` lists them.

## Ordering / dependency notes
- Steps 1-2 (CDK source + test) are independent of the live work and can be done first; they
  leave the repo buildable (synth-green) regardless of the live steps.
- Step 4 (create distribution) must precede step 5 (ROOT_URL needs the CloudFront domain) and
  step 6 (verification needs the distribution).
- Step 3 is optional read-only confirmation; skip-able if creds export is flaky, since the
  chosen path is out-of-band and does not deploy the stack.

## Gaps / assumptions
- Assumption: the origin should be the stable public DNS `ec2-32-193-103-5.compute-1.amazonaws.com`
  (EIP-backed, survives reboot). If the instance is ever stopped/started the EIP stays associated,
  so the origin remains valid.
- Assumption: no custom domain / ACM cert is required — the default `*.cloudfront.net` cert over
  443 satisfies "reachable from a 443-only network." If the user later wants a branded domain,
  that is a follow-up (Route53 + ACM in us-east-1 + alias), out of scope here.
- Open item for the coder: confirm whether `docs/DEMO.md` exists before editing it (step 7).
