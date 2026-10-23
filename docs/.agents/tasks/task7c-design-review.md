# Task 7c — Design Review: Hardcoded Persona Login (demo)

Reviewer: design-review subagent (fresh read, no authoring context).
Target: `docs/.agents/tasks/task7c-design.md`
Reference: `docs/.agents/tasks/task7c-investigation.md`

Every technical claim in the design was checked against the actual source in the
workspace. The design is self-contained: `personas.ts`, `auth.py`, and the
`api.ts` transport are given as concrete code; the CDK edits name exact
constructs; the test changes name exact functions. All of the "unambiguous
contract" items in the review brief (A–G) are resolved concretely and were
verified against real code.

Verdict: **APPROVED** — zero HIGH and zero MEDIUM findings. Three NITs below.

---

## Findings

### 1. NIT — Wrong / unreachable source citation for the dev-id table (§A.1, investigation §1)

**Where:** Design §A.1 ("It uses the real dev-ids from
`mahalo-dock/mock-services/jira/seed_data.py`"); investigation §1 cites the same
path.

**Problem:** `mahalo-dock` does not exist anywhere in this workspace
(`file_search` for `mahalo-dock` returns nothing; the cited `seed_data.py` path
does not resolve). An implementer who tries to verify the credential table
against the cited file will not find it.

**Why only NIT:** The table values are nonetheless CORRECT. The real seed file is
`tools-lambdas/jira/seed_data.py`, whose `DEVELOPERS` list confirms exactly:
`dev-1` = Marcus Chen, `dev-5` = David Kim, `dev-6` = Lava Dev. The role strings
(`product_manager`, `developer`, `executive`) are confirmed in
`agent/prompts.py` `ROLE_PROMPTS`. The design also restates the full table inline
and gives `personas.ts` verbatim, so the design does not actually depend on
reading the cited file to be implementable.

**Concrete fix:** Change the provenance reference in §A.1 from
`mahalo-dock/mock-services/jira/seed_data.py` to
`tools-lambdas/jira/seed_data.py` (the real file). No table value changes.

---

### 2. NIT — "Port the SHAPE of mahalo-dock's AuthContext / ProtectedRoute / login" references an absent repo (§D.3)

**Where:** Design §D.3 (three "port the mahalo-dock SHAPE" bullets for
`AuthContext.tsx`, `ProtectedRoute.tsx`, `login/page.tsx`).

**Problem:** There is no `mahalo-dock` tree in the workspace, so the implementer
cannot open the reference files the design points at.

**Why only NIT:** §D.3 specifies the required behavior in enough prose to build
each file without the reference: `login(userid,password)` calls the pure
`authenticate()` from `personas.ts`; on success it stores the `Persona` in React
state + `sessionStorage` key `mahalo_persona` (value = `personaId`); `logout()`
clears; `restoreSession()` rehydrates from `PERSONAS` on mount; `ProtectedRoute`
shows a spinner while `isLoading`, redirects to `/login` when no `persona`, else
renders children; the login page is a centered card with userid/password fields,
error banner, submit, optional quick-login buttons, and `router.push("/chat")` on
success. That is a complete spec. The missing repo removes a convenience, not a
requirement.

**Concrete fix:** Either (a) drop the "port from mahalo-dock" phrasing and keep
only the behavioral spec already present, or (b) note that the mahalo-dock
reference is external to this workspace and the behavioral spec in §D.3 is
authoritative. No design decision changes.

---

### 3. NIT — `AuthProvider` must be a Client Component; current root layout is a Server Component (§D.3)

**Where:** Design §D.3 ("`frontend/src/app/layout.tsx` (changed) — wrap
`{children}` in `<AuthProvider>`").

**Problem:** `frontend/src/app/layout.tsx` today has no `"use client"` directive
(it exports `metadata`, which is only allowed in a Server Component). `AuthProvider`
uses React context, `useState`, and `sessionStorage`, so it must be a Client
Component. The design does not state this explicitly.

**Why only NIT:** The standard Next.js pattern — a Server Component layout
rendering a Client Component provider as a child — works and does not require the
layout itself to become a client file. The implementer just needs `"use client"`
at the top of `AuthContext.tsx` (which the behavior already implies). No
architectural change.

**Concrete fix:** Add a one-line note to §D.3: "`AuthContext.tsx` carries
`"use client"`; `layout.tsx` stays a Server Component and renders
`<AuthProvider>` as a child so `export const metadata` remains valid." Per the
workspace rule, the implementer must also read the relevant guide under
`node_modules/next/dist/docs/` before writing the layout/provider.

---

## Verified Assumptions

All checked against workspace source:

1. **Role strings.** `agent/prompts.py` `ROLE_PROMPTS` keys are exactly
   `product_manager`, `developer`, `executive` — matches §A.1/§A.2 and the
   default. `agent/runtime_app.py` `_resolve_role` keeps a role only if it is a
   `ROLE_PROMPTS` key, else falls back to `_DEFAULT_ROLE` — matches the design's
   "unknown → developer" claim.
2. **Dev-ids + display names.** `tools-lambdas/jira/seed_data.py` `DEVELOPERS`:
   `dev-1` Marcus Chen, `dev-5` David Kim, `dev-6` Lava Dev — matches the §A.1
   table (dev-1→PM, dev-5→exec, dev-6→dev). `dev-6` is the already-wired default
   in `api/app/auth.py`.
3. **Header mapping is the single swap point.** `api/app/auth.py` today is a
   zero-arg `current_identity()` returning a fixed `Identity(dev-6, developer)`;
   both chat routes consume it via `Depends(current_identity)`
   (`api/app/routers/chat.py`). The design's `current_identity(request)` keeps the
   same return type, so `chat.py`, `models.py`, `runtime_client.py` are genuinely
   unchanged. FastAPI injects `Request` automatically — valid.
4. **Chat router forwards developer_id + role on /chat, developer_id only on
   /approve.** Confirmed in `routers/chat.py` (`send_message` forwards both;
   `approve_action` forwards `developer_id`, not `role`). The design's claim that
   persona → role is already wired end-to-end holds.
5. **Function URL is AuthType=AWS_IAM with a CORS block today.**
   `infra-cdk/mahalo_infra/api_stack.py` `fn.add_function_url(auth_type=...AWS_IAM,
   cors=...)` with `allowed_methods=[POST, GET]`, SigV4 headers + `Content-Type`,
   `max_age=300`, and a `FrontendOrigin` `CfnParameter`. The design's edits
   (→ `NONE`, drop SigV4 headers, add `X-Mahalo-Persona`, `allowed_origins=["*"]`,
   drop `FrontendOrigin`) are all actionable against this exact code. The
   `max_age`/`allowed_methods` "unchanged" claims are correct.
6. **`*` CORS origin is safe under AuthType=NONE.** Correct: with no credentials
   sent (no cookies, no `Authorization`), the browser's "credentialed request
   cannot use `*`" rule does not apply. Justification in §B is sound.
7. **Cognito lives inside the frontend stack (not a separate stack).**
   `frontend_stack.py` contains `CfnIdentityPool`, `UnauthRole` with
   `lambda:InvokeFunctionUrl` on `api_stack.function.function_arn`,
   `CfnIdentityPoolRoleAttachment`, `self.identity_pool`, and the `IdentityPoolId`
   output — all present exactly as the design lists them for deletion. Removing
   them keeps the stack count at 11 (claim verified against `test_app.py`).
8. **`api_stack` param is used ONLY for the deleted policy.** Confirmed — the only
   reference in `frontend_stack.py` is `api_stack.function.function_arn` inside the
   unauth-role policy. Dropping the param is safe. The three call sites the design
   names all pass `api_stack=`: `infra-cdk/app.py`, `tests/test_app.py`, and the
   `_frontend_template` helper in `tests/test_frontend_stack.py` — all three
   verified, all three must be updated (design §C / files #4, #4b, #18).
9. **Nothing else references `IdentityPoolId` / `self.identity_pool`.** The only
   downstream consumer was the frontend `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`
   env, removed in §D.4. The `FrontendUrl` output is retained.
10. **Infra test claims are accurate.** `test_api_stack.py::test_function_url_auth_iam`
    asserts `AuthType: "AWS_IAM"` and `test_function_url_cors_block` asserts
    `AuthType == "AWS_IAM"` + `AllowOrigins != ["*"]` — both will break and the
    design's rewrites target them correctly. `test_frontend_stack.py` has
    `test_identity_pool_unauthenticated`, `test_unauth_role_only_invoke_function_url`,
    and `test_outputs_identity_pool_and_frontend_url` exactly as cited.
    `RuntimeApiUrl` is the real Function-URL output name (design never
    misnames it).
11. **Frontend transport + tests.** `frontend/src/services/api.ts` imports
    `aws4fetch` + `@aws-sdk/credential-providers` and exposes
    `api.{get,post,put,delete}`, `ApiResponse<T>`, `API_BASE_URL`,
    `normalizeErrorMessage` — the public surface the design promises to preserve.
    `api.test.ts` mocks both libraries and asserts `interrupt_id`/`approved`/
    `Content-Type` in the body and the `systems_queried`-optional case — the two
    assertions the design preserves. `package.json` deps are exactly
    `@aws-sdk/credential-providers@3.1154.0` and `aws4fetch@1.0.20`.
12. **`.env.example`** documents `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_AWS_REGION`,
    `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` — the design keeps the first and drops
    the latter two, as stated.
13. **`UserRole` type** `"product_manager" | "developer" | "executive"` exists in
    `frontend/src/types/index.ts` — `personas.ts` can import it as designed.
14. **Chat page** hardcodes `role: "developer"` in the `buildSuggestions` memo and
    calls `api.post("/chat", …)` / `api.post("/chat/approve", …)` — the exact edit
    points §D.3 step (2)/(3) target. The two-call HITL flow is as described.
15. **Session id ≥ 33 chars.** `routers/chat.py` generates `str(uuid.uuid4())`
    (36 chars) when `session_id` is absent, and the chat page already threads the
    echoed id (`page.tsx` stores `result.data.session_id`). The design's "keep
    API-generated ids" decision is correct and needs no client change.
16. **NEXT_PUBLIC_API_URL stays env-driven.** `api.ts` reads
    `process.env.NEXT_PUBLIC_API_URL` with a placeholder fallback; the live URL is
    not hardcoded in source. Design §D.1 preserves this.
17. **ABSOLUTE RULE.** Every entry in the design's "Files to change" table is
    under `mahalo-agentcore`. No modification to `mahalo-dock` is proposed (and it
    is not even present). Honored.
18. **test_chat_proposal_passthrough stays green.** It asserts
    `developer_id == "dev-6"` and sends no persona header, so the new default path
    returns `dev-6`/`developer` — unaffected, as the design claims.

## Unverified / Wrong Assumptions

1. **WRONG provenance path (finding 1):** `mahalo-dock/mock-services/jira/seed_data.py`
   does not exist; the real file is `tools-lambdas/jira/seed_data.py`. The *values*
   derived from it are correct, so this is a citation error, not a data error.
2. **UNVERIFIABLE reference shape (finding 2):** the mahalo-dock
   `AuthContext.tsx` / `ProtectedRoute.tsx` / `login/page.tsx` the design says to
   "port the shape of" are not in the workspace and could not be read. The design's
   inline behavioral spec was treated as the authoritative substitute and is
   sufficient to implement.
3. **NOT INDEPENDENTLY RUN:** the offline gate (`npm ci/lint/test/build`,
   `cdk synth --all` = 11 templates, `pytest`) was not executed in this review —
   it is a static design review. The gate is concrete and achievable given the
   verified source; actually running it is the implementer/verification step.
