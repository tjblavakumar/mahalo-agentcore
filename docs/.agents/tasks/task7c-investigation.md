# Task 7c — Frontend / Browser-Auth Investigation

Read-only investigation. Goal of the overall change: replace the SCP-blocked
Cognito Unauthenticated Identity Pool + in-browser SigV4 path with a SIMPLE
hardcoded userid/password **persona** login (Product Manager, Developer,
Executive) so the browser UI can be deployed and used for the demo. The point of
personas is that the agent **behaves as the selected persona** — the persona only
changes the agent's `role` (and thus its system prompt / synthesized view). Same
backend, same shared services for everyone. Demo-only, single user, mock data,
security explicitly not a concern.

All paths below are repo-relative to `mahalo-agentcore` unless prefixed with
`mahalo-dock/` (read-only reference repo).

---

## 1. Credential -> persona -> {developer_id, role} table

### Where the facts come from

- **Real dev-ids / names** — `mahalo-dock/mock-services/jira/seed_data.py:3-10`
  (`DEVELOPERS` list). These are the identities the agent's tools understand
  (e.g. `jira_list_developers`, `jira_get_stories_by_assignee`):
  - `dev-1` Marcus Chen, `dev-2` Sarah Johnson, `dev-3` Raj Patel,
    `dev-4` Emily Zhang, `dev-5` David Kim, **`dev-6` Lava Dev**.
- **`dev-6` = "Lava Dev" / developer** is the demo identity baked in everywhere:
  `api/app/auth.py:16-17` (`Identity` defaults), `agent/strands_agent.py:128-131`
  (`build_agent` defaults `role="developer"`, `user_name="Lava Dev"`,
  `developer_id="dev-6"`), `agent/runtime_app.py:54-55` (`_DEFAULT_DEVELOPER_ID`,
  `_DEFAULT_ROLE`).
- **Valid `role` strings** — `agent/prompts.py:150-154`, the `ROLE_PROMPTS` dict.
  The ONLY accepted keys are:
  - `"product_manager"`, `"developer"`, `"executive"`.
  The Runtime enforces this: `agent/runtime_app.py:82-86` (`_resolve_role`) keeps
  the request role only when `raw.strip() in ROLE_PROMPTS`, otherwise falls back
  to `"developer"` and logs a warning. Confirmed by
  `agent/tests/test_runtime_app.py:160-175` (role `"wizard"` -> falls back to
  `"developer"`) and `:142-157` (role `"executive"` is honored).

### Chosen table (real dev-ids, confirmed role strings)

The persona login maps a hardcoded credential to exactly the two fields the
backend already consumes — `developer_id` and `role`. Pick real dev-ids from the
seed list so "me/my/mine" resolution and assignee filters return real data.

| userid (login) | password | persona          | developer_id | role             | display name |
|----------------|----------|------------------|--------------|------------------|--------------|
| `pm`           | `pm`     | Product Manager  | `dev-1`      | `product_manager`| Marcus Chen  |
| `dev`          | `dev`    | Developer        | `dev-6`      | `developer`      | Lava Dev     |
| `exec`         | `exec`   | Executive        | `dev-5`      | `executive`      | David Kim    |

Rationale (one line each):

- **Developer -> `dev-6` / `developer`.** This is the already-wired demo identity
  (`auth.py`, `strands_agent.py`, every agent test). Keeping it as the Developer
  persona means the existing green path is unchanged; "Lava Dev" owns real stories
  (e.g. `PAY-109`, `PAY-110`, `AUTH-306` in seed_data) so "my stories" works.
- **Product Manager -> `dev-1` (Marcus Chen) / `product_manager`.** `dev-1` is the
  lead of the `PAY` project and assignee of many stories
  (`seed_data.py` PAY-101/102/105/107), giving the PM persona rich cross-sprint
  data to summarize.
- **Executive -> `dev-5` (David Kim) / `executive`.** `dev-5` leads `ORD` and spans
  payment + order + product stories, fitting the portfolio/overview framing of the
  executive prompt.

Passwords are intentionally trivial (security is explicitly out of scope; real
auth = OKTA in GovCloud later). The table is the demo's entire "auth" surface.

> Assumption (flagged): the agent's `user_name`/`user_role` identity string
> (shown in the system prompt's "Current user" / "CURRENT USER IDENTITY" block)
> is NOT currently forwarded from the request — see §3. The persona `role` fully
> drives agent behavior today; wiring the persona's display name through is an
> optional enhancement, not required for the persona->role behavior change.

---

## 2. The in-browser SigV4 path — exactly what to replace

### Files that implement the SigV4 / Cognito path today

1. **`frontend/src/services/api.ts`** — the whole SigV4 client.
   - `:9-10` module docstring: Function URL `AuthType=AWS_IAM`; browser fetches
     short-lived creds from a Cognito **unauthenticated** identity pool and signs
     each request in-browser with `aws4fetch`.
   - `:12-13` imports `AwsClient` from `aws4fetch` and `fromCognitoIdentityPool`
     from `@aws-sdk/credential-providers`.
   - `:31` `IDENTITY_POOL_ID = process.env.NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`.
   - `:70-121` the SigV4 machinery: `getProvider()` (Cognito pool),
     `getCredentials()` (in-memory cache + skew), `getSigner()` (builds the
     `AwsClient` for service `"lambda"`), and `request()` calling `aws.fetch(...)`.
   - `:186-194` the exported `api.{get,post,put,delete}` helpers used by the UI.

   **Replacement:** strip aws4fetch + Cognito entirely. `request()` becomes a plain
   `fetch(url, { method, headers, body })` against the Function URL (now
   `AuthType=NONE`, see §4). Keep the exact public surface — `api.post<T>()`,
   `ApiResponse<T>`, `normalizeErrorMessage` (`:38-67`), `API_BASE_URL` (`:26-28`),
   and the body-passed-verbatim behavior the test asserts — so callers and
   `api.test.ts` need no shape change beyond dropping the signer. The persona's
   `developer_id`/`role` do NOT need to travel from the browser (the thin API
   stamps them in `auth.py`, see §4); the browser only needs to tell the API which
   persona is logged in. Simplest: add the chosen persona's `role`/`developer_id`
   to the JSON body or a header and have `current_identity()` read it — OR keep the
   API authoritative and select persona server-side. Design decision deferred to
   the design step; this file is the single frontend swap point either way.

2. **`frontend/src/services/api.test.ts`** — mocks `aws4fetch` (`:10-14`) and
   `@aws-sdk/credential-providers` (`:17-25`). Must be rewritten to mock plain
   `fetch` instead; the two behavioral assertions (`interrupt_id` present in the
   sent body `:46-66`; a `/chat` reply without `systems_queried` is valid
   `:68-85`) should be preserved.

3. **`frontend/.env.example`** — `:1-10` documents `NEXT_PUBLIC_API_URL`,
   `NEXT_PUBLIC_AWS_REGION`, `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`. Drop the
   region + Cognito vars; keep `NEXT_PUBLIC_API_URL`.

4. **`frontend/package.json`** — `:11-12` deps `@aws-sdk/credential-providers`
   `3.1154.0` and `aws4fetch` `1.0.20` become removable once `api.ts` no longer
   imports them.

### What is NOT yet present (must be added for the persona login)

The agentcore frontend has **no auth UI at all today** (confirmed: `file_search`
for `frontend/src/app` structure found only `layout.tsx`, `page.tsx`,
`(protected)/chat/page.tsx`, and chat components; there is **no**
`login/`, `register/`, `contexts/AuthContext.tsx`, or `(protected)/layout.tsx`).

- `frontend/src/app/layout.tsx:9-18` — a bare root layout; no `AuthProvider`.
- `frontend/src/app/page.tsx:9-12` — immediately `router.push("/chat")`; there is
  no gate. A persona login must intercept here (or via a protected layout).
- `frontend/src/app/(protected)/chat/page.tsx` — the chat page. It:
  - `:63-76` hardcodes a static `role: "developer"` into `buildSuggestions` and a
    static context (`connectedTypes: ["github","jira"]`). This should become the
    **logged-in persona's** role so suggestions match the persona.
  - `:78-110` `handleSend` -> `api.post("/chat", {message, session_id, project_id})`.
  - **Two-call HITL approve UX** `:112-144`: `handleApprove`/`handleReject` both
    call `api.post("/chat/approve", {session_id, interrupt_id, approved})`. This
    UX is unchanged by the auth rework — only the transport under `api.post`
    changes.
- `frontend/src/types/index.ts:6` already exports
  `UserRole = "product_manager" | "developer" | "executive"` — ready to type the
  persona. (mahalo-dock additionally has a `User` interface with `developer_id?`
  at `mahalo-dock/frontend/src/types/index.ts:9-18` — a useful shape to mirror.)

### mahalo-dock login reference (read-only, pattern to adapt)

- `mahalo-dock/frontend/src/contexts/AuthContext.tsx` — `AuthProvider` with
  `user/token/isLoading`, `login(email,password)` (`:60-82`), `logout` (`:100-104`),
  `useAuth()` hook (`:117-124`); it calls a real `/auth/login` + `/auth/me` backend
  and persists a token in `sessionStorage`. For the demo there is **no** auth
  backend — the persona login is a pure client-side lookup against the hardcoded
  table in §1, storing the selected persona (role + developer_id) in React
  context / `sessionStorage`. No token, no `/auth/*` calls.
- `mahalo-dock/frontend/src/components/common/ProtectedRoute.tsx` — redirects to
  `/login` when `!user`; a minimal version can gate `(protected)/` here.
- `mahalo-dock/frontend/src/app/login/page.tsx` — email/password form shape to
  adapt into a userid/password + persona-picker login page.

---

## 3. persona -> role -> agent-prompt is ALREADY wired end-to-end

Confirmed. The only thing a persona changes is the agent's `role`, and that chain
already exists and is tested:

1. **Thin API stamps identity.** `api/app/auth.py:15-22` — `Identity{developer_id,
   role}` with a `current_identity()` FastAPI dependency; the docstring (`:6`)
   calls this "the single swap point". Today it returns the fixed
   `dev-6`/`developer`.
2. **Chat router forwards it to the Runtime.**
   `api/app/routers/chat.py:48-54` (`/chat`) forwards `developer_id` **and**
   `role` into the invoke body; `:88-95` (`/chat/approve`) forwards `developer_id`
   only (by design §B.3 — approve replays the pending tool without a model call,
   so `role` is intentionally not re-sent).
3. **Runtime validates + dispatches on role.**
   `agent/runtime_app.py:146-150` (`_handle_chat`) resolves `role` via
   `_resolve_role` (`:82-86`) and passes it to `build_and_attach`.
4. **`build_and_attach` -> `build_agent` selects the prompt.**
   `agent/runtime_session.py:61-66` passes `role` into `build_agent`;
   `agent/strands_agent.py:185-190` does `system_prompt = ROLE_PROMPTS[role].format(
   ...)`. The three role prompts differ substantively —
   `agent/prompts.py:95-118` (PM: strategic, velocity/sprint),
   `:120-134` (Developer: technical, branches/PRs),
   `:136-148` (Executive: high-level, portfolio/risk).
5. **Tests prove it.** `agent/tests/test_runtime_app.py:142-157`
   (role `executive` honored), `:160-175` (bogus role falls back to `developer`).
   `api/tests/test_api.py:138-141` asserts `/chat` forwards `developer_id`;
   `:197-199` asserts `role` is NOT forwarded on approve.

**Conclusion:** choosing a persona at login = choosing a `role` string in
`{product_manager, developer, executive}` + a `developer_id`. Everything
downstream already consumes those two fields. No agent/prompt/runtime change is
needed for persona behavior — only the frontend login and the API's
`current_identity()` need to surface the chosen persona.

> Caveat worth recording for the design step: `build_and_attach`
> (`runtime_session.py:38-66`) and the Runtime entrypoint accept only
> `developer_id` and `role`; `user_name`/`user_role` are NOT request fields and
> default to "Lava Dev"/"Developer" in `build_agent` (`strands_agent.py:128-131`).
> So the agent's **role-driven behavior** switches per persona, but the literal
> display name in the identity block stays "Lava Dev" unless a later change also
> forwards `user_name`/`user_role`. Not required for the demo's persona point.

---

## 4. Existing swap points (confirmed)

- **`api/app/auth.py`** — `Identity{developer_id="dev-6", role="developer"}`
  (`:15-17`); `current_identity()` (`:20-22`) returns the fixed identity; docstring
  (`:1-7`) names this "the single swap point". For the persona demo, this is where
  the request's chosen persona must become the returned `Identity` (read a
  body field / header the browser sends, mapping it to one of the three roles).
- **`api/app/routers/chat.py`** — both legs forward from `current_identity()`:
  `/chat` forwards `developer_id` + `role` (`:48-54`); `/chat/approve` forwards
  `developer_id` (`:88-95`). No change needed if `current_identity()` is updated.
- **`api/app/models.py`** — `ChatRequest{message, session_id?, project_id?}`
  (`:17-26`); `ApprovalRequest{session_id, interrupt_id, approved, proposal?}`
  (`:38-49`). NOTE: the Runtime REQUIRES `runtimeSessionId` length >= 33 chars
  (session id threading via `runtime_app._resolve_session_id`,
  `runtime_app.py:113-127`); the browser-generated session id must satisfy this —
  the current chat page lets the API/Runtime generate it
  (`chat/page.tsx:91`, `routers/chat.py:43`). If a persona field is added it would
  go on `ChatRequest` (or be read from a header in `auth.py`).
- **`infra-cdk/mahalo_infra/api_stack.py`** — Function URL `AuthType=AWS_IAM`
  (`:111-115` of the `add_function_url` call) **with** a `FunctionUrlCorsOptions`
  block (`:150-...`) allowing a `FrontendOrigin` `CfnParameter` (`:126-137`);
  Lambda is ARM64 (`:98`), `python3.13`. **Swap:** change `auth_type` to
  `FunctionUrlAuthType.NONE` so the browser can call it without SigV4. CORS stays
  (demo-only; can widen origin). boto3 note: the task brief says boto3 1.43.114 —
  not pinned in `api_stack.py` itself; dependency bundling installs from
  `api/requirements.txt` on the operator-deploy branch (`:66-92`).
- **`infra-cdk/mahalo_infra/frontend_stack.py`** — S3 (`:60-67`) + CloudFront
  single S3 origin (`:70-105`) + the **Cognito UNAUTHENTICATED Identity Pool**
  (`:109-114`), an unauthenticated IAM role (`:115-130`) with a
  `lambda:InvokeFunctionUrl` policy (`:132-137`) scoped to
  `api_stack.function.function_arn`, and the role attachment (`:137-143`), plus an
  `IdentityPoolId` output (`:149-154`). **This Cognito part is BLOCKED by org SCP**
  (`cognito-identity:CreateIdentityPool` explicit-deny). **Swap:** delete the
  Cognito pool + unauth role + attachment + `IdentityPoolId` output; keep the
  S3 + CloudFront static hosting. No credential-vending needed once the Function
  URL is `AuthType=NONE`.

---

## 5. Offline-gate reality & tests that assert Cognito / AuthType=AWS_IAM

### Build/test surfaces observed

- **Frontend** (`frontend/`): Next.js **16.3.3** / React **19.2.8** / Tailwind v4,
  **static export** (`next.config.ts:4` `output: "export"` -> `out/`). Scripts
  (`package.json:5-11`): `build` (`next build`), `lint` (`eslint`), `test`
  (`vitest run`). Vitest tests: `src/services/api.test.ts`,
  `src/lib/chatSuggestions.test.ts`.
  - NOTE (`frontend/AGENTS.md`): this Next.js version has breaking changes; the
    implementer must read `node_modules/next/dist/docs/` before writing frontend
    code, and the `BEGIN/END:nextjs-agent-rules` block in `AGENTS.md` is
    auto-regenerated by `next dev` — commit it with the work to keep the tree
    clean, do not delete it.
- **infra-cdk** (`infra-cdk/`): own `.venv`; `cdk synth` runs offline/Docker-free
  on the default branch (both API Lambda bundling `api_stack.py:93-105` and the
  frontend `BucketDeployment` `frontend_stack.py:95-105` are flag-gated behind
  `buildImage` / `buildFrontend`); `pytest tests`.

### Infra/API tests that assert Cognito or AuthType=AWS_IAM (WILL need updating)

- **`infra-cdk/tests/test_frontend_stack.py`** — the Cognito assertions:
  - `test_identity_pool_unauthenticated` (`:70-77`) — asserts exactly one
    `AWS::Cognito::IdentityPool` with `AllowUnauthenticatedIdentities: True` and one
    `AWS::Cognito::IdentityPoolRoleAttachment`. **Will break** when Cognito is
    removed — delete/replace this test.
  - `test_unauth_role_only_invoke_function_url` (`:81-93`) — asserts a
    `lambda:InvokeFunctionUrl` grant scoped to that single action. **Will break** —
    remove with the unauth role.
  - `test_outputs_identity_pool_and_frontend_url` (`:96-101`) — asserts an
    `IdentityPoolId` output exists. **Will break** on the `IdentityPoolId` half;
    keep the `FrontendUrl` assertion.
  - (Unaffected: `test_private_bucket`, `test_distribution_single_s3_origin...`,
    `test_spa_error_responses`, `test_bucket_deployment_flag_gated`.)
- **`infra-cdk/tests/test_api_stack.py`** — the AWS_IAM assertions:
  - `test_function_url_auth_iam` (`:37-39`) — asserts `AWS::Lambda::Url`
    `AuthType: "AWS_IAM"`. **Will break** when switched to `NONE` — update to
    assert `AuthType: "NONE"`.
  - `test_function_url_cors_block` (`:42-62`) — asserts `AuthType == "AWS_IAM"`
    plus the CORS block. **Will break** on the auth assertion; update to `NONE`
    (CORS assertions can stay if CORS is retained).
  - (Unaffected: `test_single_python313_lambda`, `test_runtime_arn_env_and_output`,
    `test_lambda_role_can_invoke_runtime`.)

### Tests that mention AWS_IAM but do NOT assert the API/frontend auth being reworked (leave as-is)

- `infra-cdk/tests/test_runtime_stack.py:46-49` — asserts the **Runtime** has no
  custom JWT authorizer (AWS_IAM default). This is the backend Runtime, already
  live-validated; not in scope.
- `infra-cdk/tests/test_gateway_stack.py:60-69` — asserts the **Gateway**
  `AuthorizerType` param defaults to `AWS_IAM`. Backend; not in scope.
- `infra-cdk/tests/test_synth.py:112-115` — asserts a mock-service Function URL is
  `AuthType=NONE` (already NONE; unrelated to the thin API).

### Frontend test that must change with the SigV4 removal

- `frontend/src/services/api.test.ts` — mocks `aws4fetch` and
  `@aws-sdk/credential-providers` (§2). Rewrite to mock plain `fetch`; preserve the
  `interrupt_id`-in-body and `systems_queried`-optional assertions.

---

## Summary of swap points (one place each)

| Concern | File:line today | Change |
|---|---|---|
| Browser transport | `frontend/src/services/api.ts` (SigV4 via aws4fetch + Cognito, `:70-184`) | Plain `fetch`; drop aws4fetch/Cognito |
| Browser transport test | `frontend/src/services/api.test.ts:10-25` | Mock `fetch` not the signer |
| Env vars | `frontend/.env.example:1-10` | Drop region + Cognito vars |
| Deps | `frontend/package.json:11-12` | Remove `aws4fetch`, `@aws-sdk/credential-providers` |
| Login UI | (absent today) | Add persona login page + context gating `(protected)/` |
| Chat suggestions role | `frontend/src/app/(protected)/chat/page.tsx:63-66` | Use logged-in persona's role |
| API identity | `api/app/auth.py:15-22` | `current_identity()` returns the chosen persona's `{developer_id, role}` |
| Function URL auth | `infra-cdk/mahalo_infra/api_stack.py` `add_function_url(... AWS_IAM ...)` | `AuthType=NONE` |
| Cognito pool (SCP-blocked) | `infra-cdk/mahalo_infra/frontend_stack.py:109-154` | Delete pool + unauth role + attachment + `IdentityPoolId` output |
| Infra tests | `test_api_stack.py:37-62`, `test_frontend_stack.py:70-101` | Update AWS_IAM->NONE; remove Cognito assertions |
