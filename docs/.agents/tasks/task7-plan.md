# Task 7 — Implementation Plan

Derived from the APPROVED design `docs/.agents/tasks/task7-design.md` (grounded by
`docs/.agents/tasks/task7-investigation.md`). The design decisions A–E are LOCKED; this
plan only sequences the work — it does not re-decide architecture.

**Absolute rules.** Only write under `d:/<USER>/LavaCode/AI/mahalo-agentcore`.
`mahalo-dock` (`d:/<USER>/LavaCode/AI/mahalo-dock/`) is READ ONLY — copy from
it, never edit it. No git commit/push. No `npm run dev`/`next dev`/`next start`/watch. No
deploy (no `cdk deploy`/`cdk bootstrap`). Windows PowerShell: `;` not `&&`, `$env:VAR="x"`.
Run `pytest agent -q` in a shell with NO `MAHALO_*` env vars (Task-5 quirk). `infra-cdk`
has its own `.venv` (activate before `cdk`/its `pytest`); the agent venv is at
`agent/.venv/Scripts/python.exe`.

**Offline gate baselines to preserve.** agent `pytest agent -q` = 99 passed / 1 skipped
(no `MAHALO_*` env); api `pytest api -q` = 15; tools-lambdas `pytest tools-lambdas/tests
-q` = 94 (mock default) + new real-mode tests; infra-cdk `pytest tests -q` = 42 passed /
1 skipped + new assertions; `cdk synth --all` exit 0 offline, 8 → 10 templates; zero
LangChain; frontend `npm ci; npm run lint; npm run test; npm run build` GREEN.

This plan has two largely independent parts: Part A (frontend port) and Part B (Gitea +
hosting IaC + Lambda wiring). They share no code, so either order works; the items within
each part are ordered by dependency.

## Part A — Frontend port (design §A, §B browser side, §D.1)

- [ ] 1. Scaffold `frontend/` with the VERBATIM config/tooling copied from
      `mahalo-dock/frontend/`: `package.json`, `package-lock.json`, `vitest.config.ts`,
      `tsconfig.json`, `postcss.config.mjs`, `eslint.config.mjs`, `next.config.ts`,
      `.gitignore`, `AGENTS.md`, `src/app/favicon.ico`, `src/app/globals.css`.
      Files: `frontend/` (new tree).
      Verify: files present; `cd frontend; npm ci` succeeds (defer lint/test/build to item 8).

- [ ] 2. Port VERBATIM the chat components + suggestion logic:
      `src/components/chat/{ProposalCard,ChatInput,ChatMessage,ContextPanel}.tsx`,
      `src/lib/chatSuggestions.ts`, `src/lib/chatSuggestions.test.ts`. Port
      `src/types/index.ts` WITH A TRIM: keep `UserRole` + the FULL `Project` interface,
      drop `User`/`HealthStatus`/`Integration`/`ProjectProposal`; then grep `@/types`
      across the kept set and re-add any still-referenced type.
      Files: `frontend/src/components/chat/*`, `frontend/src/lib/*`, `frontend/src/types/index.ts`.
      Verify: `cd frontend; npx vitest run src/lib/chatSuggestions.test.ts` passes.

- [ ] 3. Static-export + layout + landing edits. `next.config.ts`: add `output: 'export'`
      and `images: { unoptimized: true }`. `src/app/layout.tsx`: drop the three providers;
      drop `next/font/google` (Geist/Geist_Mono) and add a system font stack to
      `globals.css` via a Tailwind 4 `@theme { --font-sans; --font-mono }` block.
      `src/app/page.tsx`: keep `'use client'`, use `useRouter().push('/chat')` in a
      `useEffect` (NOT server `redirect()`).
      Files: `frontend/next.config.ts`, `frontend/src/app/layout.tsx`,
      `frontend/src/app/globals.css`, `frontend/src/app/page.tsx`.
      Verify: deferred to item 8 (`npm run build` must not fetch fonts).

- [ ] 4. Thread the HITL interrupt id + status gating. Add optional
      `interrupt_id?: string` to BOTH the page-local `Proposal` (`chat/page.tsx`) and the
      `ProposalCard.tsx` `Proposal` (one coupled edit). In `chat/page.tsx`: change
      `handleApprove`/`handleReject` to take `(msg: Message)`, update the render site to
      pass `msg`, read `msg.proposal?.interrupt_id`, POST `/chat/approve` with
      `{session_id, interrupt_id, approved}`, early-return (card stays disabled) if the id
      is falsy; make `ChatApiResponse.systems_queried` optional and add `status: string`;
      render the Approve/Reject card only when `status === 'pending_approval'` AND
      `proposal` present. Do NOT edit `ChatMessage.tsx`.
      Files: `frontend/src/app/(protected)/chat/page.tsx`,
      `frontend/src/components/chat/ProposalCard.tsx`.
      Verify: deferred to item 8 (`npm run build` type-checks these reads).

- [ ] 5. Trim dropped-context deps in `chat/page.tsx`: remove
      `useAuth`/`useProjects`/`useConnections`/`useRequiredConnections` and every derived
      value/state/handler that reads them (`scopedProject`, `scopedProjectId`,
      `connectedTypes`, `suggestionSignature`, `displayedSuggestions`,
      `llmSuggestions`/`generatingSuggestions`, `handleGenerateSuggestions`,
      `sessionScopeRef`/`scopeChanged`) and the `/chat/suggestions` call; simplify the
      `/chat` POST body to `{ message, session_id, project_id: null }`; replace suggestions
      with `buildSuggestions({ role: 'developer', project: null, connectedTypes: ['github','jira'] })`;
      delete the "Connections Required" block; make the "How can I help you today?" block
      unconditional (gated on `messages.length === 0`); remove the "✨ Generate more"
      button and the header scope chip; reduce `ChatInput` `disabled` to `isLoading`.
      Files: `frontend/src/app/(protected)/chat/page.tsx`.
      Verify: deferred to item 8.

- [ ] 6. Swap the API client auth (`src/services/api.ts`). Keep `request()`/
      `normalizeErrorMessage`/`api.get/post/...`; keep base URL from
      `process.env.NEXT_PUBLIC_API_URL` (update only the default/comment); REMOVE the
      `sessionStorage['mahalo3_token']` → `Authorization: Bearer` block; add SigV4 signing
      via `fromCognitoIdentityPool` (`NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`,
      `NEXT_PUBLIC_AWS_REGION`) + `new AwsClient({ ..., service: 'lambda', region })` and
      `aws.fetch(url, { method, headers, body: JSON.stringify(body) })`; do NOT mutate
      headers/body after signing. Add exact-pinned deps `aws4fetch` +
      `@aws-sdk/credential-providers` to `package.json` and regenerate `package-lock.json`.
      Add `frontend/.env.example`. Surface §B.5 auth errors into the assistant error bubble.
      Files: `frontend/src/services/api.ts`, `frontend/package.json`,
      `frontend/package-lock.json`, `frontend/.env.example`.
      Verify: deferred to item 8.

- [ ] 7. DROP the old-backend surface (do not port): `src/app/login/`,
      `src/app/register/`, `src/app/(protected)/layout.tsx`, `src/app/(protected)/dashboard/`
      + `src/components/dashboard/**`, `src/app/(protected)/connections/**` (incl. `[id]`),
      `src/contexts/**`, `src/hooks/useRequiredConnections.ts`,
      `src/components/common/{ProjectMultiSelect,ProtectedRoute,Sidebar}.tsx`,
      `src/types/react-grid-layout.d.ts`. (These are simply never created in `frontend/`.)
      Files: none created under those paths.
      Verify: deferred to item 8 (static export has no dynamic route).

- [ ] 8. Add a unit test asserting the approve call sends `interrupt_id` and
      `systems_queried` is optional (mock the signer/fetch), then run the full offline
      gate.
      Files: `frontend/src/**/*.test.ts(x)`.
      Verify: `cd frontend; npm ci; npm run lint; npm run test; npm run build` — all exit 0
      and `frontend/out/index.html` is produced.

## Part B — Gitea + hosting IaC + Lambda wiring (design §B.4, §C, §D.2, §E)

- [ ] 9. Port the Gitea adapter into `tools-lambdas/github/` from
      `mahalo-dock/mock-services/github/`: `gitea_backend.py` (repo_id==name under one
      owner, `_publicize` rewrite, `_write_file` via the contents API) and `backend_base.py`
      (`GithubBackend`/`BackendError`). Adapt imports to `tools-lambdas/common/`; keep `httpx`.
      Files: `tools-lambdas/github/gitea_backend.py`, `tools-lambdas/github/backend_base.py`.
      Verify: `python -c "import ast,pathlib; ast.parse(pathlib.Path('tools-lambdas/github/gitea_backend.py').read_text())"` parses; real verification at item 12.

- [ ] 10. Wire real mode into the github Lambda. `routes.py`: ADD
      `build_gitea_router(backend)` (same route table, delegates to the backend, maps
      `BackendError`→`error()`); leave `build_router(store, token)` UNCHANGED. `handler.py`:
      add module-scope `_MODE` + Gitea env constants + SSM token resolution (boto3
      `get_parameter(..., WithDecryption=True)` cached, fallback `GITEA_TOKEN`/
      `GITEA_TOKEN_FILE`); make `_get_router()` short-circuit the DynamoDB `Store`/seed when
      `_MODE == 'real'` (return `(None, build_gitea_router(...))`) and run the existing path
      unchanged otherwise; guard `store.ensure_seeded()` on `store is not None`. Never log
      the token.
      Files: `tools-lambdas/github/routes.py`, `tools-lambdas/github/handler.py`.
      Verify: item 12.

- [ ] 11. Add real-mode unit tests (httpx transport mocked, no live Gitea) asserting the
      contract translation (repo_id→name, `_publicize` rewrite, author-id mapping) and that
      mock mode is untouched.
      Files: `tools-lambdas/tests/test_github_handler.py`.
      Verify: item 12.

- [ ] 12. Run the tools-lambdas gate: `pytest tools-lambdas/tests -q` (moto installed) =
      94 passed for the existing suite PLUS the new real-mode tests; no existing test sets
      `GITHUB_MODE=real`.
      Verify: command above passes.

- [ ] 13. Guard the github-only Gitea wiring on `MockServiceStack` (design §C.4b): add
      optional kwargs `gitea_mode=False`, `gitea_env=None`, `gitea_token_param_name=None`;
      the env merge (`GITHUB_MODE=real` + Gitea env) and the SSM `grant_read` branch are
      BOTH guarded `service == 'github' and gitea_mode`. Defaults leave all four instances
      byte-identical.
      Files: `infra-cdk/mahalo_infra/mock_service_stack.py`.
      Verify: item 18.

- [ ] 14. Create `MahaloGiteaStack` (design §C.2/§C.3/§C.5): dedicated `aws_ec2.Vpc` (1
      public subnet, no NAT, NOT `from_lookup`); `aws_ec2.Instance` (AL2023, t3.small,
      public subnet/IP) with UserData that `docker run`s `gitea/gitea:1.27.3` by reference
      and runs the `gitea/` bootstrap one-shot; `aws_ec2.SecurityGroup` (SSH 22 → CfnParameter
      `AdminCidr` no 0.0.0.0/0 default; Gitea 3000 → CfnParameter `GiteaIngressCidr` default
      0.0.0.0/0); gp3 EBS at `/data` `RemovalPolicy.DESTROY` (overridable via `RetainGiteaData`);
      SSM SecureString param-name refs for token + admin password; CfnOutput public URL. No
      `fromLookup`, no `DockerImageAsset`.
      Files: `infra-cdk/mahalo_infra/gitea_stack.py`.
      Verify: item 18.

- [ ] 15. Create `MahaloFrontendStack` (design §D.2, §B.2): private `aws_s3.Bucket`
      (`DESTROY`, `auto_delete_objects=True`, no public access); `aws_cloudfront.Distribution`
      with a SINGLE S3 origin via OAC and SPA 403/404→`index.html` (NO Function-URL origin);
      flag-gated `aws_s3_deployment.BucketDeployment` behind `-c buildFrontend=1`/
      `MAHALO_BUILD_FRONTEND=1` (offline uses an empty/placeholder source or skips);
      `aws_cognito.CfnIdentityPool(allow_unauthenticated_identities=True)` + `aws_iam.Role`
      (web-identity trust on `cognito-identity.amazonaws.com`, inline policy granting ONLY
      `lambda:InvokeFunctionUrl` on `api_stack.function.function_arn`) +
      `CfnIdentityPoolRoleAttachment`; take `api_stack` only for `.function.function_arn`;
      CfnOutputs `IdentityPoolId` + `FrontendUrl`.
      Files: `infra-cdk/mahalo_infra/frontend_stack.py`.
      Verify: item 18.

- [ ] 16. Add `FunctionUrlCorsOptions` to `MahaloApiStack` (design §B.4): add a `cors=`
      block to the existing `fn.add_function_url(auth_type=AWS_IAM)` call — `allowed_origins`
      = CloudFront origin (CfnParameter, NOT `*`); `allowed_methods` = POST/GET/OPTIONS;
      `allowed_headers` = Authorization, X-Amz-Date, X-Amz-Security-Token,
      X-Amz-Content-Sha256, Content-Type; `max_age` ≈ 300s. Auth stays AWS_IAM.
      Files: `infra-cdk/mahalo_infra/api_stack.py`.
      Verify: item 18.

- [ ] 17. Wire the new stacks in `app.py` by direct construct reference (design §E.1):
      read `giteaMode` context once and pass Gitea kwargs to the github instance ONLY; add
      `MahaloGiteaStack` and `MahaloFrontendStack(api_stack=...)` after `MahaloApiStack`,
      all with `env=_ENV`. Port the Gitea bootstrap assets into `gitea/` (`bootstrap.sh` +
      `Dockerfile`) from `mahalo-dock/mock-services/gitea-bootstrap/`, pushing the token to
      SSM instead of the Compose shared-volume file.
      Files: `infra-cdk/app.py`, `gitea/bootstrap.sh`, `gitea/Dockerfile`.
      Verify: item 18.

- [ ] 18. Add CDK synth assertion tests and run the infra offline gate. Tests (following
      `test_synth.py`/`test_api_stack.py`): `test_gitea_stack.py` (VPC created not looked up,
      EC2 + SG ingress + EBS, no `DockerImageAsset`); `test_frontend_stack.py` (single S3
      origin, no Function-URL origin, private bucket, identity pool + unauthenticated role
      with `lambda:InvokeFunctionUrl`, CfnOutputs); extend `test_api_stack.py` for the CORS
      block with auth still AWS_IAM.
      Files: `infra-cdk/tests/test_gitea_stack.py`,
      `infra-cdk/tests/test_frontend_stack.py`, `infra-cdk/tests/test_api_stack.py`.
      Verify: from `infra-cdk/` (.venv active) `cdk synth --all` exit 0 offline (Docker-free,
      no creds) with 10 templates; `pytest tests -q` passing; `cdk synth -c giteaMode=real`
      succeeds offline and only the github template gains `GITHUB_MODE=real`.

- [ ] 19. Write `docs/.agents/tasks/task7-deploy-runbook.md` with the DEFERRED live operator
      steps (design §E.4, §D.2): SSM param creation; `cdk deploy MahaloGiteaStack`; confirm
      Gitea healthy + seed repo; `cdk deploy MahaloMockGithubStack -c giteaMode=real`; the
      ordered frontend deploy (API → read `RuntimeApiUrl`; frontend stack without
      `-c buildFrontend=1` → read `IdentityPoolId` + CloudFront domain; set the three
      `NEXT_PUBLIC_*` + `npm run build`; frontend stack `-c buildFrontend=1`; re-deploy API
      so CORS `allowed_origins` includes the CloudFront domain); end-to-end smoke test. State
      clearly none of this runs in the offline gate.
      Files: `docs/.agents/tasks/task7-deploy-runbook.md`.
      Verify: file exists and covers all five deploy phases.

## Final verification (both parts)

- [ ] 20. Run every offline gate and confirm green: frontend
      `cd frontend; npm ci; npm run lint; npm run test; npm run build`;
      `pytest tools-lambdas/tests -q` (94 + new); from `infra-cdk/` `cdk synth --all`
      (10 templates, offline) + `pytest tests -q`; and — only if touched — `pytest agent -q`
      (NO `MAHALO_*` env; expect 99/1) and `pytest api -q` (expect 15). Confirm zero
      LangChain and clean up any temp files. No commit/push, no deploy.
