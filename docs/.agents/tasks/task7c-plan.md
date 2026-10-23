# Task 7c — Implementation Plan: Hardcoded Persona Login (demo), remove SCP-blocked Cognito

Derived from the APPROVED design `docs/.agents/tasks/task7c-design.md` and investigation
`docs/.agents/tasks/task7c-investigation.md`. The plan stays strictly within the design's
decisions; it re-sequences them by dependency and does not re-decide architecture.

## Ground rules for the implementer (read first)

- **Absolute path rule:** modify ONLY files under `D:/<USER>/LavaCode/AI/mahalo-agentcore`.
  NEVER modify anything under `D:/<USER>/LavaCode/AI/mahalo-dock` — it is read-only and is
  used only as a *shape* reference for the login/AuthContext/ProtectedRoute UI.
- **No git commit. No worktree.**
- **Shell is Windows PowerShell:** chain with `;`, never `&&`. Never run `npm run dev` or any
  watch/long-running process.
- **Next.js 16 rule (`frontend/AGENTS.md`):** before writing ANY frontend code, read the relevant
  guide under `frontend/node_modules/next/dist/docs/`. Leave the `BEGIN/END:nextjs-agent-rules`
  block in `frontend/AGENTS.md` intact (it is auto-regenerated); do not delete it.
- **The persona contract is shared across layers and must match exactly everywhere:**
  header name `X-Mahalo-Persona`; values `pm` / `dev` / `exec`; mapping
  `pm -> {dev-1, product_manager}`, `dev -> {dev-6, developer}`, `exec -> {dev-5, executive}`;
  absent/unknown -> default `{dev-6, developer}`. The frontend table (`personas.ts`) and the
  server table (`auth.py`) are the same table in two languages — keep them in sync.
- Each item leaves the tree buildable. Items 1–2 define/confirm the contract backend-side,
  3–5 fix infra, 6–13 do the frontend, 14–15 are env/deps, 16–20 are tests. Where an item depends
  on an earlier item's output, it says so.

---

# Implementation Plan

- [ ] 1. Rework `current_identity()` to resolve the persona from the `X-Mahalo-Persona` header.
      Change `api/app/auth.py` so `current_identity(request: Request)` reads the header, strips +
      lowercases it, and maps it via a module-level `_PERSONA_MAP = {"pm": ("dev-1","product_manager"),
      "dev": ("dev-6","developer"), "exec": ("dev-5","executive")}` with `_DEFAULT = ("dev-6","developer")`
      and `PERSONA_HEADER = "X-Mahalo-Persona"`. Absent/unknown/wrong-case-after-lowering -> `_DEFAULT`,
      silently (no 4xx, no required logging). Keep the `Identity` dataclass and its defaults unchanged so
      the return type is identical; FastAPI injects `Request` automatically. Rewrite the module docstring
      to describe the AuthType=NONE + persona-header model (not the old AWS_IAM/SigV4 story). Do NOT touch
      `routers/chat.py`, `models.py`, or `runtime_client.py` — the `Depends(current_identity)` surface is unchanged.
      Files: `api/app/auth.py`
      Verify: `cd api; python -m pytest tests/test_api.py -q` — existing suite still passes (new header
      tests are added in item 16; this item must not break current tests, including
      `test_no_langchain_or_agent_in_api_source` and `test_chat_proposal_passthrough` which sends no header and still sees `dev-6`).

- [ ] 2. Confirm no change is needed to the chat router / models / runtime client for the persona path.
      Read `api/app/routers/chat.py`, `api/app/models.py`, `api/app/runtime_client.py` and confirm both
      `/chat` (forwards `developer_id`+`role`) and `/chat/approve` (forwards `developer_id` only) already
      consume `current_identity()` and need no edits, and that API-generated session ids (`str(uuid.uuid4())`,
      36 chars) still satisfy the Runtime `runtimeSessionId >= 33` rule. This is a read-only confirmation item;
      make NO edits. Record the confirmation in the item's done note.
      Files: none (read-only confirmation of `api/app/routers/chat.py`, `api/app/models.py`, `api/app/runtime_client.py`)
      Verify: `cd api; python -m pytest tests/test_api.py -q` — unchanged, still green.

- [ ] 3. Switch the thin-API Function URL to `AuthType=NONE` and update its CORS block.
      In `infra-cdk/mahalo_infra/api_stack.py`, change the `fn.add_function_url(...)` `auth_type` from
      `lambda_.FunctionUrlAuthType.AWS_IAM` to `lambda_.FunctionUrlAuthType.NONE`. In the
      `FunctionUrlCorsOptions`: set `allowed_origins=["*"]`; set
      `allowed_headers=["Content-Type", "X-Mahalo-Persona"]` (remove the SigV4 headers Authorization/
      X-Amz-Date/X-Amz-Security-Token/X-Amz-Content-Sha256); keep `allowed_methods=[POST, GET]` and
      `max_age=Duration.seconds(300)`. Remove the now-unused `FrontendOrigin` `CfnParameter` and any
      reference to it. Rewrite the module docstring/inline comments that describe "AuthType stays AWS_IAM /
      browser signs SigV4" to describe the NONE + persona-header model.
      Files: `infra-cdk/mahalo_infra/api_stack.py`
      Verify: `cd infra-cdk; .\.venv\Scripts\Activate.ps1; cdk synth MahaloApiStack` exits 0 offline
      (Docker-free); then `python -m pytest tests/test_api_stack.py -q` (tests updated in item 17 — after
      this item alone the old AWS_IAM assertions will fail, which is expected until item 17).

- [ ] 4. Remove the SCP-blocked Cognito identity pool from the frontend stack and drop its `api_stack` dependency.
      In `infra-cdk/mahalo_infra/frontend_stack.py` delete: the `cognito.CfnIdentityPool` ("IdentityPool"),
      the `iam.Role` ("UnauthRole") with its FederatedPrincipal assume-role, the
      `unauth_role.add_to_policy(...)` `lambda:InvokeFunctionUrl` statement, the
      `cognito.CfnIdentityPoolRoleAttachment` ("IdentityPoolRoleAttachment"), the `self.identity_pool`
      attribute, and the `IdentityPoolId` `CfnOutput`. Remove the now-unused `aws_cognito as cognito` and
      `aws_iam as iam` imports. Drop the `api_stack` parameter from `MahaloFrontendStack.__init__` (its only
      use was the deleted policy; no cross-stack ref remains, so no explicit `add_dependency` is needed).
      Keep S3 (private, OAC) + CloudFront (single S3 origin, SPA error routing) + flag-gated
      `BucketDeployment` + the `FrontendUrl` output. Fix the module docstring to drop the Cognito story.
      Files: `infra-cdk/mahalo_infra/frontend_stack.py`
      Verify: `cd infra-cdk; .\.venv\Scripts\Activate.ps1; cdk synth MahaloFrontendStack` exits 0 offline —
      BUT this will fail to synth until item 5 updates the call sites that still pass `api_stack=`. Treat item 4
      and item 5 as a paired change; run the synth verification after item 5.

- [ ] 5. Update the three `MahaloFrontendStack(...)` instantiation sites to drop the `api_stack=` arg.
      Depends on item 4 (the dropped constructor parameter). Edit `infra-cdk/app.py` and
      `infra-cdk/tests/test_app.py` to stop passing `api_stack=` to `MahaloFrontendStack(...)`. (The
      `_frontend_template` helper in `infra-cdk/tests/test_frontend_stack.py` is handled in item 18.) Keep the
      `== 11` stacks assertion in `test_app.py` unchanged — no stack is added or removed.
      Files: `infra-cdk/app.py`, `infra-cdk/tests/test_app.py`
      Verify: `cd infra-cdk; .\.venv\Scripts\Activate.ps1; cdk synth MahaloFrontendStack` exits 0 offline;
      `cdk synth --all` still emits 11 templates; `python -m pytest tests/test_app.py -q` passes.

- [ ] 6. Create the single frontend persona credential table.
      New `frontend/src/lib/personas.ts` exporting: `type PersonaId = "pm" | "dev" | "exec"`; a `Persona`
      interface (`personaId`, `userid`, `password`, `displayName`, `personaLabel`, `developerId`, `role: UserRole`);
      `PERSONAS: Record<PersonaId, Persona>` with the three rows
      (`pm`/`pm123`/Marcus Chen/`dev-1`/`product_manager`/"Product Manager";
      `dev`/`dev123`/Lava Dev/`dev-6`/`developer`/"Developer";
      `exec`/`exec123`/David Kim/`dev-5`/`executive`/"Executive"); and a pure
      `authenticate(userid, password): Persona | null`. Import `UserRole` from `@/types`.
      Files: `frontend/src/lib/personas.ts`
      Verify: `cd frontend; npx tsc --noEmit` (or `npm run lint`) — file type-checks. (Unit test added in item 20.)

- [ ] 7. Rewrite the API transport to plain `fetch` with the persona header, dropping SigV4/Cognito.
      Depends on item 6 (`PersonaId`). Rewrite `frontend/src/services/api.ts`: remove the `aws4fetch` and
      `@aws-sdk/credential-providers` imports and all SigV4 machinery (provider/credential cache/signer).
      Keep the EXACT public surface — `ApiResponse<T>`, `API_BASE_URL` (still
      `process.env.NEXT_PUBLIC_API_URL || "https://<function-id>.lambda-url.us-east-1.on.aws"`),
      `normalizeErrorMessage`, and `api.{get,post,put,delete}`. `request<T>(endpoint, options, personaId?)`
      now calls `fetch(`${API_BASE_URL}${endpoint}`, {method, headers, body})` where `headers` always sets
      `Content-Type: application/json` and, only when `personaId` is provided, `X-Mahalo-Persona: personaId`.
      Preserve today's error contract: network failure caught -> `{data:null, error}`; non-2xx read for
      `detail`/`message` -> `{data:null, error}`; nothing thrown to callers. Give all four helpers an optional
      trailing `personaId?: PersonaId` arg (only `post` is used by the chat flow). Remove the stale
      AWS_IAM/Cognito module docstring and drop the `AWS_REGION`/`IDENTITY_POOL_ID` constants.
      Files: `frontend/src/services/api.ts`
      Verify: `cd frontend; npm run lint` passes. (The rewritten `api.test.ts` in item 19 is the behavioral check;
      run `npm test -- --run` after item 19.)

- [ ] 8. Add the client-only persona auth context.
      New `frontend/src/contexts/AuthContext.tsx` porting the SHAPE of
      `mahalo-dock/frontend/src/contexts/AuthContext.tsx` (read-only reference) but with NO backend:
      `AuthProvider` exposing `{ persona, isLoading, login, logout }`; `login(userid, password)` calls the pure
      `authenticate()` from `@/lib/personas`, on success stores the `Persona` in React state and persists its
      `personaId` string to `sessionStorage` under key `mahalo_persona`; `logout()` clears state + storage;
      on mount it rehydrates from `sessionStorage` via `PERSONAS`. Export a `useAuth()` hook. No token, no
      `/auth/*` calls. Mark the file a client component as required by the Next.js 16 guide you read.
      Files: `frontend/src/contexts/AuthContext.tsx`
      Verify: `cd frontend; npm run lint` passes.

- [ ] 9. Add the route guard.
      New `frontend/src/components/common/ProtectedRoute.tsx` porting the SHAPE of
      `mahalo-dock/frontend/src/components/common/ProtectedRoute.tsx`: while `isLoading` render a spinner;
      if no `persona` redirect to `/login`; otherwise render children. Use `useAuth()` from item 8. Client component.
      Files: `frontend/src/components/common/ProtectedRoute.tsx`
      Verify: `cd frontend; npm run lint` passes.

- [ ] 10. Add the persona login page.
      New `frontend/src/app/login/page.tsx` porting the mahalo-dock login form SHAPE (centered card, error
      banner, submit button) but with `userid` + `password` text fields (not email). On submit call
      `useAuth().login(userid, password)`; on success `router.push("/chat")`; on failure show
      "Invalid credentials". Optionally add three quick-login buttons (PM/Developer/Executive) that prefill
      credentials. Client component.
      Files: `frontend/src/app/login/page.tsx`
      Verify: `cd frontend; npm run lint` passes.

- [ ] 11. Gate the `(protected)` segment and provide auth context app-wide.
      New `frontend/src/app/(protected)/layout.tsx` wrapping `{children}` in `<ProtectedRoute>` (item 9), and
      edit `frontend/src/app/layout.tsx` to wrap `{children}` in `<AuthProvider>` (item 8) so context is
      available everywhere including `/login`. Follow the Next.js 16 layout conventions from the guide.
      Files: `frontend/src/app/(protected)/layout.tsx`, `frontend/src/app/layout.tsx`
      Verify: `cd frontend; npm run lint` passes.

- [ ] 12. Route the index page by persona instead of unconditionally pushing to /chat.
      Edit `frontend/src/app/page.tsx` to read `useAuth()` and push to `/chat` when a persona exists, else to
      `/login` (single decision point, no double redirect). Client component.
      Files: `frontend/src/app/page.tsx`
      Verify: `cd frontend; npm run lint` passes.

- [ ] 13. Wire the chat page to the logged-in persona (role for suggestions, persona header, logout UI).
      Edit `frontend/src/app/(protected)/chat/page.tsx`: (1) `const { persona, logout } = useAuth();`
      (2) replace the hardcoded `role: "developer"` in the `buildSuggestions({...})` memo with
      `role: persona?.role ?? "developer"` and add `persona?.role` to the `useMemo` deps;
      (3) pass `persona?.personaId` as the third arg to the `/chat` `api.post` call and to BOTH
      `/chat/approve` `api.post` calls (the two-call HITL approve/reject UX is otherwise unchanged);
      (4) add a header element showing `personaLabel · displayName` (e.g. "Developer · Lava Dev") and a
      Logout button that calls `logout()` then `router.push("/login")`.
      Files: `frontend/src/app/(protected)/chat/page.tsx`
      Verify: `cd frontend; npm run lint` passes; `npm run build` produces the static export to `frontend/out/`.

- [ ] 14. Trim the frontend env example to the one remaining var.
      Edit `frontend/.env.example`: keep `NEXT_PUBLIC_API_URL` (document it as the AuthType=NONE Function URL);
      remove `NEXT_PUBLIC_AWS_REGION` and `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`.
      Files: `frontend/.env.example`
      Verify: open the file and confirm only `NEXT_PUBLIC_API_URL` remains; `cd frontend; npm run build` still succeeds.

- [ ] 15. Remove the two AWS auth dependencies and regenerate the lockfile.
      Edit `frontend/package.json` to remove `@aws-sdk/credential-providers` (`3.1154.0`) and `aws4fetch`
      (`1.0.20`) from `dependencies`. Add no new dependency (`fetch`/`crypto.randomUUID` are built-ins).
      Regenerate `frontend/package-lock.json` so `npm ci` stays deterministic. Depends on item 7 (nothing
      imports the removed packages anymore).
      Files: `frontend/package.json`, `frontend/package-lock.json`
      Verify: `cd frontend; npm install` updates the lockfile, then `npm ci` resolves cleanly; `npm run build`
      succeeds with no unresolved-import errors for aws4fetch/@aws-sdk.

- [ ] 16. Add thin-API persona-header mapping tests.
      Depends on item 1. In `api/tests/test_api.py` add route-boundary tests using the existing
      `_client()`/`TestClient` with a monkeypatched `invoke_runtime` capturing the forwarded `body`, sending
      `X-Mahalo-Persona`: `pm -> body.developer_id=="dev-1" & body.role=="product_manager"`;
      `dev -> dev-6/developer`; `exec -> dev-5/executive`; absent header -> dev-6/developer;
      unknown (`wizard`) -> dev-6/developer. Add a direct unit test `test_current_identity_maps_header`
      calling `current_identity` with a fake object exposing `.headers` for `exec` -> `Identity("dev-5","executive")`
      and empty/unknown -> `Identity("dev-6","developer")`. Leave the existing approve test
      (role NOT forwarded) and `test_chat_proposal_passthrough` as-is.
      Files: `api/tests/test_api.py`
      Verify: `cd api; python -m pytest tests/test_api.py -q` — all tests, including the new ones, pass.

- [ ] 17. Update the API-stack infra assertions for AuthType=NONE.
      Depends on item 3. In `infra-cdk/tests/test_api_stack.py`: retarget `test_function_url_auth_iam` to
      `test_function_url_auth_none` asserting `AWS::Lambda::Url` `AuthType == "NONE"`; in
      `test_function_url_cors_block` change the auth assertion to `AuthType == "NONE"`, require
      `"Content-Type"` and `"X-Mahalo-Persona"` in `AllowHeaders` and assert the SigV4 headers are absent,
      assert `AllowOrigins == ["*"]`, keep `AllowMethods == {"POST","GET"}` and `MaxAge == 300`. Leave
      `test_single_python313_lambda`, `test_runtime_arn_env_and_output`, `test_lambda_role_can_invoke_runtime`.
      Files: `infra-cdk/tests/test_api_stack.py`
      Verify: `cd infra-cdk; .\.venv\Scripts\Activate.ps1; python -m pytest tests/test_api_stack.py -q` passes.

- [ ] 18. Update the frontend-stack infra assertions for the Cognito removal.
      Depends on items 4 and 5. In `infra-cdk/tests/test_frontend_stack.py`: delete
      `test_identity_pool_unauthenticated` and `test_unauth_role_only_invoke_function_url`; rename
      `test_outputs_identity_pool_and_frontend_url` to `test_outputs_frontend_url_only` asserting
      `"FrontendUrl" in outputs` and `"IdentityPoolId" not in outputs`; add `test_no_cognito_identity_pool`
      asserting `resource_count_is("AWS::Cognito::IdentityPool", 0)` and
      `resource_count_is("AWS::Cognito::IdentityPoolRoleAttachment", 0)`; update the `_frontend_template`
      helper to stop passing `api_stack=` (removing the `api` stack instantiation from the helper is cleaner).
      Leave `test_private_bucket`, `test_distribution_single_s3_origin_no_function_url_origin`,
      `test_spa_error_responses`, `test_bucket_deployment_flag_gated`.
      Files: `infra-cdk/tests/test_frontend_stack.py`
      Verify: `cd infra-cdk; .\.venv\Scripts\Activate.ps1; python -m pytest tests/test_frontend_stack.py -q` passes.

- [ ] 19. Rewrite the transport test to mock `fetch` and assert the persona header.
      Depends on item 7. Rewrite `frontend/src/services/api.test.ts`: remove the `aws4fetch` and
      `@aws-sdk/credential-providers` mocks; mock the global `fetch` (`vi.stubGlobal("fetch", fetchMock)`).
      Preserve the two behavioral assertions: `/chat/approve` sends `interrupt_id` in the body
      (`approved === true`, `Content-Type: application/json`); a `/chat` reply without `systems_queried` is
      valid. Add: when a `personaId` is passed, the request carries `headers["X-Mahalo-Persona"]`; when
      omitted, the header is absent.
      Files: `frontend/src/services/api.test.ts`
      Verify: `cd frontend; npm test -- --run` — this test passes.

- [ ] 20. Add the persona credential-table unit test.
      Depends on item 6. New `frontend/src/lib/personas.test.ts`: assert `authenticate("pm","pm123")` returns
      the PM persona (`developerId === "dev-1"`, `role === "product_manager"`); same positive checks for
      `dev`/`dev123` and `exec`/`exec123`; a wrong password or unknown userid returns `null`.
      Files: `frontend/src/lib/personas.test.ts`
      Verify: `cd frontend; npm test -- --run` — this test passes.

- [ ] 21. Run the full offline gate end-to-end and confirm everything is green.
      No new code. Run every gate from design §G in a clean shell (no `MAHALO_*` env):
      frontend `cd frontend; npm ci; npm run lint; npm test -- --run; npm run build`;
      infra `cd ..\infra-cdk; .\.venv\Scripts\Activate.ps1; cdk synth MahaloApiStack; cdk synth MahaloFrontendStack; cdk synth --all; python -m pytest tests -q`;
      and the API suite `cd ..\api; python -m pytest tests -q`. Confirm `cdk synth --all` emits 11 templates,
      the build emits `frontend/out/`, and the `BEGIN/END:nextjs-agent-rules` block in `frontend/AGENTS.md`
      is left intact. Fix any failure before declaring done. Do NOT git commit.
      Files: none (verification only)
      Verify: all commands above exit 0; `cdk synth --all` reports 11 templates; `frontend/out/` exists.

---

## Notes / assumptions

- The design is APPROVED and exhaustive (20-file change table with exact code shapes, test names, and gate
  commands). This plan follows it without re-deciding any architecture. The persona display name staying
  "Lava Dev" in the agent identity block (only `role` switches behavior) is an accepted out-of-scope item per
  design §E — no agent/prompt/runtime/`models.py`/`common/` change is planned.
- Items 4+5 and 3+17 and 7+19 are dependency pairs: the first member can leave a sibling test temporarily
  red, which the paired item resolves. Run the paired verification at the point noted in each item; item 21 is
  the final whole-gate confirmation.
- `mahalo-dock` is referenced ONLY as read-only shape guidance for items 8/9/10; nothing under it is modified.
