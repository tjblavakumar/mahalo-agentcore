# Review — Gitea behind HTTPS/443 via CloudFront

## Verdict: APPROVED

## Scope reviewed
- Plan: `docs/.agents/tasks/plan.md`
- Coder report: `docs/.agents/tasks/gitea-cloudfront.md`
- Progress note: `docs/GITEA-REAL-PLAN.md` (STEP 1 section)
- Diff/source: `infra-cdk/mahalo_infra/gitea_stack.py`, `infra-cdk/tests/test_gitea_stack.py`
- Commit `f38cd66`

## What I verified

### CDK change (committed and truthful)
- `gitea_stack.py` adds `cloudfront.Distribution("GiteaDistribution", ...)` with the required
  settings and a `GiteaCloudFrontUrl` CfnOutput. The existing `GiteaPublicUrl` (HTTP:3000) output
  is retained as the Lambda-facing URL.
- Cache-behavior settings in source match the requirement exactly:
  - `origins.HttpOrigin(_GITEA_ORIGIN_DNS=ec2-32-193-103-5.compute-1.amazonaws.com,
    protocol_policy=OriginProtocolPolicy.HTTP_ONLY, http_port=3000)`
  - `viewer_protocol_policy=REDIRECT_TO_HTTPS`
  - `allowed_methods=AllowedMethods.ALLOW_ALL`
  - `cache_policy=CachePolicy.CACHING_DISABLED`
  - `origin_request_policy=OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER`
- The out-of-band application is documented by an in-code comment block (lines ~243-255) stating the
  live distribution was created via `aws cloudfront create-distribution` and was NOT `cdk deploy`-ed.
- Commit `f38cd66` stages exactly the intended files (gitea_stack.py, test_gitea_stack.py, and the
  three docs). Working tree is clean except the untracked `plan.md` and scratch dir — not blockers.

### Internal path preservation
- Source adds the distribution only; it does not touch `HTTP_PORT` (`_GITEA_PORT=3000`) or the
  `0.0.0.0` container bind (`-p 3000:3000`, default Gitea bind). Report and progress note both state
  ROOT_URL was set while HTTP_PORT=3000 and the 0.0.0.0 bind were left unchanged, and that the github
  Lambda keeps reaching `http://<eip>:3000`. Consistent with requirement.

### Server-side verification evidence (recorded)
- Report records: distribution Status=Deployed; origin `curl http://localhost:3000/api/healthz`
  returning a passing health JSON after the ROOT_URL change + restart; app.ini re-grep confirming
  `ROOT_URL = https://d3ec76atxiij9a.cloudfront.net/` and `HTTP_PORT = 3000`; app.ini chowned
  1000:1000 / chmod 660 and `docker restart gitea`. pytest `tests/test_gitea_stack.py` → 8 passed.
- Browser edge check is explicitly deferred to the user because the VDI is behind the same 443-only
  corporate proxy. This is acceptable per the step prompt — verifiable server-side checks were NOT
  skipped.

### Independent read-only spot-checks (non-mutating)
- Ran `pytest tests/test_gitea_stack.py` → 8 passed (matches recorded evidence), including the new
  `test_cloudfront_distribution_present`.
- Ran a single read-only `aws cloudfront get-distribution --id E2KKG6SJXJ4K1M`. Live config matches
  the report and plan exactly: Status=Deployed, Enabled=true, Domain=d3ec76atxiij9a.cloudfront.net,
  origin ec2-32-193-103-5.compute-1.amazonaws.com / http-only / port 3000, viewer redirect-to-https,
  all 7 allowed methods, CachePolicyId 4135ea2d-6df8-44a3-9df3-4b5a84be39ad (CachingDisabled),
  OriginRequestPolicyId b689b0a8-53d0-40ab-baf2-68738e2966ac (AllViewerExceptHostHeader).

### Scope / non-destructive
- No `cdk deploy`; no change to the instance, EBS volume, or EIP association. GitHub Lambda was not
  flipped to real mode and Gitea data was not seeded — all correctly out of scope for this task.

## Findings
None. All approved requirements are met, the live distribution matches the committed IaC, the
internal Lambda path is preserved, and the deferred browser check is a legitimate environment
constraint rather than a skipped server-side check.
