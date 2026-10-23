# Task 7c â€” Design: Hardcoded Persona Login (demo), remove SCP-blocked Cognito

## Overview

The MAHALO demo UI must be deployable and usable without the Cognito
Unauthenticated Identity Pool that the org SCP explicitly denies
(`cognito-identity:CreateIdentityPool`). This design replaces the in-browser
SigV4 + Cognito credential-vending path with a **plain client-side persona
login**: three hardcoded userid/password credentials (PM / Developer /
Executive) each resolving to a `{developer_id, role}` pair. The browser calls the
thin-API Function URL **directly with no AWS credentials** (Function URL switched
to `AuthType=NONE`) and tells the API which persona is active via a single
request header, `X-Mahalo-Persona`. The thin API's `current_identity()` maps that
header to the `{developer_id, role}` the Runtime already consumes.

Nothing downstream of the thin API changes: persona -> role -> agent system
prompt is already wired and tested end-to-end (investigation Â§3). This task
touches only four surfaces â€” the thin API identity dependency, the two CDK
stacks (`api_stack.py`, `frontend_stack.py`), the frontend transport + login UI,
and the tests that assert the old auth shape.

**Security posture (explicitly ACCEPTED):** this is demo-only, single-user, mock
data, no live systems. There is no password hashing, no token, no server-side
session, no per-user service credentials, and the persona is asserted by the
browser with no verification. The Function URL becomes publicly invokable. These
tradeoffs are deliberately accepted for the demo; the production path (AWS
GovCloud) will replace this with OKTA, and `current_identity()` remains the
single swap point for that future JWT-claim extraction.

**Technology stack (locked):** Frontend Next.js 16.3.3 / React 19.2.8 / Tailwind
v4, static export to `frontend/out/`, Vitest for tests, plain `fetch` for
transport (no aws4fetch, no AWS SDK). Thin API FastAPI on `python3.13` ARM64
Lambda behind a Function URL. Infra AWS CDK (Python, `infra-cdk/.venv`). No new
dependencies are introduced; two are removed.

> **Absolute path rule honored:** every file listed below is under
> `<WORKSPACE_ROOT>`. `mahalo-dock` is
> read-only â€” only the *shape* of its login/`AuthContext`/`ProtectedRoute` UI is
> ported; no file in `mahalo-dock` is modified. No git commit. No worktree.

---

## A. Login + persona model (single source of truth)

### A.1 The one credential table (frontend)

The hardcoded credential table lives in exactly **one** new frontend module,
`frontend/src/lib/personas.ts`, and is the demo's entire auth surface. It uses
the real dev-ids from `mahalo-dock/mock-services/jira/seed_data.py` and the
confirmed role strings from `agent/prompts.py` `ROLE_PROMPTS`
(investigation Â§1).

| userid | password | personaId | developer_id | role              | display name |
|--------|----------|-----------|--------------|-------------------|--------------|
| `pm`   | `pm123`  | `pm`      | `dev-1`      | `product_manager` | Marcus Chen  |
| `dev`  | `dev123` | `dev`     | `dev-6`      | `developer`       | Lava Dev     |
| `exec` | `exec123`| `exec`    | `dev-5`      | `executive`       | David Kim    |

Passwords use the `â€¦123` form from the task brief. `role` values are exactly the
three `ROLE_PROMPTS` keys â€” any other value is rejected by the Runtime's
`_resolve_role` and falls back to `developer`.

Shape (TypeScript):

```ts
// frontend/src/lib/personas.ts
import type { UserRole } from "@/types";

export type PersonaId = "pm" | "dev" | "exec";

export interface Persona {
  personaId: PersonaId;     // the X-Mahalo-Persona header value
  userid: string;           // login id
  password: string;         // demo-only plaintext (security out of scope)
  displayName: string;      // shown in the UI header
  personaLabel: string;     // "Product Manager" | "Developer" | "Executive"
  developerId: string;      // dev-1 | dev-6 | dev-5
  role: UserRole;           // product_manager | developer | executive
}

export const PERSONAS: Record<PersonaId, Persona> = { /* three entries above */ };

// Pure credential check used by the login form.
export function authenticate(userid: string, password: string): Persona | null {
  const match = Object.values(PERSONAS).find(
    (p) => p.userid === userid && p.password === password,
  );
  return match ?? null;
}
```

`PersonaId` is the only thing persisted and the only thing sent to the API; the
sensitive-looking `password` never leaves the browser and never travels in a
request.

### A.2 How the persona reaches the backend â€” EXACT contract

- **Header name (exact):** `X-Mahalo-Persona`
- **Allowed values (exact):** `pm`, `dev`, `exec`
- **Sent on:** every `POST /chat` and every `POST /chat/approve` call.
- **Mapping in the thin API** (`api/app/auth.py`, `current_identity()`):

  | `X-Mahalo-Persona` | developer_id | role              |
  |--------------------|--------------|-------------------|
  | `pm`               | `dev-1`      | `product_manager` |
  | `dev`              | `dev-6`      | `developer`       |
  | `exec`             | `dev-5`      | `executive`       |
  | absent / unknown   | `dev-6`      | `developer`       (default) |

The browser is the untrusted authority here; because security is a non-goal we
deliberately trust the header. The server-side table in `auth.py` and the
client-side table in `personas.ts` are conceptually the same table expressed in
two languages; both are tiny and must be kept in sync by hand. Keeping the
authoritative `{developer_id, role}` derivation in `auth.py` (not read from a
free-form body field) means a malformed or hostile header can only ever select
one of three fixed, known-good identities or the safe default â€” never inject an
arbitrary `developer_id`/`role`.

### A.3 Thin-API `current_identity()` â€” exact new shape

`api/app/auth.py` changes from a zero-arg dependency returning a constant to a
dependency that reads the header off the FastAPI `Request`:

```python
from __future__ import annotations
from dataclasses import dataclass
from fastapi import Request

# The one server-side persona table (mirror of frontend/src/lib/personas.ts).
_PERSONA_MAP: dict[str, tuple[str, str]] = {
    "pm":   ("dev-1", "product_manager"),
    "dev":  ("dev-6", "developer"),
    "exec": ("dev-5", "executive"),
}
_DEFAULT = ("dev-6", "developer")
PERSONA_HEADER = "X-Mahalo-Persona"

@dataclass(frozen=True)
class Identity:
    developer_id: str = "dev-6"
    role: str = "developer"

def current_identity(request: Request) -> Identity:
    """Map the X-Mahalo-Persona header to a fixed {developer_id, role}.

    Demo-only: the browser asserts the persona with no verification. An absent
    or unknown value falls back to the developer identity.
    """
    raw = request.headers.get(PERSONA_HEADER, "").strip().lower()
    developer_id, role = _PERSONA_MAP.get(raw, _DEFAULT)
    return Identity(developer_id=developer_id, role=role)
```

`current_identity()` keeps the same *return type* (`Identity`) and is still the
single `Depends(...)` used by both chat routes, so `chat.py`, `models.py`, and
`runtime_client.py` are **unchanged**. FastAPI injects `Request` automatically;
no route signature changes.

**Validation rules for the header (external input):** optional; string; compared
case-insensitively after `strip()`; the only accepted values are `pm|dev|exec`.
On any other value (empty, unknown, wrong case that still is not one of the
three after lowercasing, multiple values) the behavior is a silent fallback to
`("dev-6", "developer")`. No error is raised and nothing is logged at request
time â€” a demo user mistyping a header must never see a 4xx; the safe default is
correct behavior, not an error. (If desired, a single `logger.debug` on fallback
is acceptable but not required.)

---

## B. Thin-API edge auth: `AuthType=NONE` + CORS

In `infra-cdk/mahalo_infra/api_stack.py`, the `fn.add_function_url(...)` call
changes `auth_type` from `lambda_.FunctionUrlAuthType.AWS_IAM` to
`lambda_.FunctionUrlAuthType.NONE`. The browser then calls the Function URL with
no SigV4 and no AWS credentials.

**CORS block â€” kept, with these exact changes:**

- `allowed_origins`: **`["*"]`** for the demo. Justification: with
  `AuthType=NONE` the browser sends **no credentials** (no cookies, no
  `Authorization`), so the "credentialed requests cannot use `*`" browser rule
  does not apply; a wildcard is safe to *CORS*, and it removes the chicken-and-egg
  re-deploy dance where the API needed the CloudFront domain as a
  `CfnParameter` before the frontend stack existed. Because the endpoint is
  already publicly invokable under `AuthType=NONE`, narrowing CORS to the
  CloudFront origin would add no real security (CORS is not an auth control) â€”
  it would only add deploy-ordering friction. For the demo the `*` wildcard is
  the simpler, honest choice and is explicitly accepted. The `FrontendOrigin`
  `CfnParameter` is therefore **removed** from `api_stack.py` (it no longer
  gates anything), which also simplifies Â§C.
- `allowed_methods`: unchanged â€” `[POST, GET]` (OPTIONS preflight is served
  automatically and is not a valid value).
- `allowed_headers`: **`["Content-Type", "X-Mahalo-Persona"]`**. The SigV4
  headers (`Authorization`, `X-Amz-Date`, `X-Amz-Security-Token`,
  `X-Amz-Content-Sha256`) are **removed** because no request is signed anymore.
  `X-Mahalo-Persona` MUST be present or the browser preflight for the custom
  header fails and every `/chat` call is blocked by CORS.
- `max_age`: unchanged (`Duration.seconds(300)`).

The module docstring and the inline comment that describe "AuthType stays
AWS_IAM / browser signs SigV4" must be rewritten to describe the `AuthType=NONE`
+ persona-header model so the source does not contradict itself.

**Security tradeoff (explicitly ACCEPTED):** `AuthType=NONE` makes the thin-API
Function URL callable by anyone on the internet who knows the URL. For a
single-user demo over mock data with no live systems this is accepted. The URL
is not secret-grade but is also not published in source (see Â§D). Documented
here as the deliberate demo posture; GovCloud/OKTA replaces it later.

---

## C. Remove Cognito from `frontend_stack.py`

Delete from `infra-cdk/mahalo_infra/frontend_stack.py`:

- the `cognito.CfnIdentityPool` ("IdentityPool") construct (Â§4 block),
- the `iam.Role` ("UnauthRole") with its `FederatedPrincipal` assume-role,
- the `unauth_role.add_to_policy(...)` `lambda:InvokeFunctionUrl` statement that
  referenced `api_stack.function.function_arn`,
- the `cognito.CfnIdentityPoolRoleAttachment` ("IdentityPoolRoleAttachment"),
- the `self.identity_pool = identity_pool` attribute,
- the `IdentityPoolId` `CfnOutput`.

Remove the now-unused imports `aws_cognito as cognito` and `aws_iam as iam`. The
stack then provisions only **S3 (private, OAC) + CloudFront (single S3 origin,
SPA error routing) + the flag-gated `BucketDeployment`**, and keeps the
`FrontendUrl` `CfnOutput`.

**`api_stack` dependency:** `frontend_stack.py` took `api_stack` ONLY to read
`api_stack.function.function_arn` for the deleted policy. With that policy gone,
the `api_stack` constructor parameter is no longer needed. Decision: **keep the
`api_stack` parameter in the signature but stop referencing it**, OR drop it.
Chosen: **drop the `api_stack` parameter** from `MahaloFrontendStack.__init__`
and update **all three** instantiation sites accordingly â€”
`infra-cdk/app.py`, the test helper `_frontend_template` in
`infra-cdk/tests/test_frontend_stack.py`, and
`infra-cdk/tests/test_app.py` (the 11-stack guard) â€” each currently passes
`api_stack=...`. Carrying an unused constructor arg is dead weight and the
investigation confirms nothing else uses it. (If `app.py` relies
on an explicit stack dependency for ordering, replace it with
`frontend.add_dependency(api)` only if a cross-stack ref still exists; after the
Cognito removal there is no cross-stack reference, so no explicit dependency is
required.)

**Dangling-reference check:** nothing else may reference the deleted
`IdentityPoolId` output or `self.identity_pool`. `grep` confirms the only
consumer was the frontend `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` env var, which
is removed in Â§D. The stack must still `cdk synth` with the Cognito constructs
gone; `cdk synth --all` must still emit **11 templates** (the pool/role lived
inside this existing stack, not a separate stack, so the count is unchanged).
Synth stays offline/Docker-free and flag-gated exactly as today (the
`BucketDeployment` remains behind `-c buildFrontend=1` / `MAHALO_BUILD_FRONTEND=1`).

---

## D. Frontend changes

### D.1 Transport: plain `fetch` (`frontend/src/services/api.ts`)

Rewrite `api.ts` to drop `aws4fetch` and `@aws-sdk/credential-providers`
entirely. Keep the **exact public surface** so callers and the chat page need no
change: `api.{get,post,put,delete}`, `ApiResponse<T>`, `API_BASE_URL`, and
`normalizeErrorMessage`.

`request()` becomes:

```ts
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://<function-id>.lambda-url.us-east-1.on.aws";

async function request<T>(endpoint, options, personaId?: PersonaId): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(personaId ? { "X-Mahalo-Persona": personaId } : {}),
    ...(options.headers as Record<string, string> ?? {}),
  };
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method: options.method, headers, body: options.body,
  });
  // ...same ok/!ok handling and normalizeErrorMessage as today...
}
```

The persona header value comes from the logged-in persona. Chosen wiring: the
`post` helper accepts an optional `personaId` and the chat page passes the
active persona's `personaId` into each `api.post(...)` call. (Alternative â€” a
module-level `setPersona()` mutable singleton â€” is rejected: it is implicit
global state that is harder to test and reason about than an explicit argument.)
So the signature becomes `api.post<T>(endpoint, body, personaId?)`; `get/put/
delete` gain the same optional trailing arg for symmetry though only `post` is
used by the chat flow.

- `API_BASE_URL` stays env-driven via `NEXT_PUBLIC_API_URL`. The live Function
  URL (`https://<LAMBDA_URL_HOST>/`)
  is supplied at deploy time, **never hardcoded in source** â€” the placeholder
  default is retained only as a non-functional fallback.
- Error handling for the transport (each `fetch` can fail): a network/DNS
  failure throws and is caught, returning `{ data: null, error: <message> }`
  (recoverable at the UI â€” the chat page already renders
  `Sorry, I encountered an error: â€¦`). A non-2xx response is read for a
  `detail`/`message` body and returned as `{ data: null, error }`. Nothing is
  thrown to the caller; nothing is logged beyond the existing `console.error`
  path. This mirrors today's contract so `chat/page.tsx` is unaffected.

### D.2 Session id (Runtime requires `runtimeSessionId` length >= 33)

Unchanged by this task but called out: the browser still lets the thin API
generate the session id on the first `/chat` (the API does `str(uuid.uuid4())` =
36 chars, satisfying the >= 33 rule) and echoes it back; the chat page stores
and resends it. No client-side id generation is required. If the client ever
generates one, it MUST be >= 33 chars; the simplest safe choice is
`crypto.randomUUID()` (36 chars). Decision: **keep API-generated session ids** â€”
it is the existing green path and needs no change.

### D.3 Login UI + persona context (port mahalo-dock SHAPE only)

New/changed files, all under the agentcore frontend:

- **`frontend/src/contexts/AuthContext.tsx`** (new) â€” ports the *shape* of
  mahalo-dock's `AuthProvider`/`useAuth`, but with **no backend**: `login(userid,
  password)` calls the pure `authenticate()` from `personas.ts`; on success it
  stores the selected `Persona` in React state and persists it to
  `sessionStorage` under key `mahalo_persona` (value = the `personaId` string);
  `logout()` clears it. `restoreSession()` on mount reads `mahalo_persona` and
  rehydrates from `PERSONAS`. No token, no `/auth/*` calls, no `api.get("/auth/me")`.
  Exposes `{ persona, isLoading, login, logout }`.

  Decision on storage: **`sessionStorage`** (per-tab, cleared on tab close) over
  `localStorage` â€” the task allows either; `sessionStorage` matches mahalo-dock
  and keeps demo sessions from leaking across tabs. React context is the
  in-memory source of truth; `sessionStorage` is only for reload-survival.

- **`frontend/src/components/common/ProtectedRoute.tsx`** (new) â€” ports
  mahalo-dock's guard: while `isLoading` show the spinner, if no `persona`
  redirect to `/login`, else render children.

- **`frontend/src/app/login/page.tsx`** (new) â€” ports the mahalo-dock login form
  *shape* (centered card, error banner, submit button) but with **userid +
  password** fields instead of email, plus a small persona hint. A persona
  selector is implicit: typing one of the three credentials selects the persona.
  Optionally render three "quick login" buttons (PM / Developer / Executive)
  that prefill the credentials â€” a nice demo affordance, not required. On
  successful `login()` it `router.push("/chat")`; on failure it shows "Invalid
  credentials".

- **`frontend/src/app/(protected)/layout.tsx`** (new) â€” wraps children in
  `<ProtectedRoute>` so the whole `(protected)/` segment (which already contains
  `chat/`) is gated. This is the cleanest gate point given Next's route groups.

- **`frontend/src/app/layout.tsx`** (changed) â€” wrap `{children}` in
  `<AuthProvider>` so context is available app-wide (including `/login`).

- **`frontend/src/app/page.tsx`** (changed) â€” instead of unconditionally pushing
  to `/chat`, read `useAuth()`: push to `/chat` when a persona exists, else to
  `/login`. (Simpler alternative: always push to `/login` and let the login page
  bounce an already-authenticated user to `/chat`. Chosen: route from `page.tsx`
  based on context â€” one decision point, no double redirect.)

- **`frontend/src/app/(protected)/chat/page.tsx`** (changed) â€”
  1. call `const { persona, logout } = useAuth();`
  2. replace the hardcoded `role: "developer"` in the `buildSuggestions({...})`
     memo with `role: persona?.role ?? "developer"` (and add `persona?.role` to
     the `useMemo` dep array) so starter prompts match the logged-in persona;
  3. pass `persona?.personaId` as the third arg to both
     `api.post<ChatApiResponse>("/chat", {...}, persona?.personaId)` and the two
     `api.post<ActionResult>("/chat/approve", {...}, persona?.personaId)` calls;
  4. add a small header element showing the persona label + display name (e.g.
     "Developer Â· Lava Dev") and a **Logout** button that calls `logout()` then
     `router.push("/login")`.

  The two-call HITL approve/reject UX is otherwise unchanged â€” only the
  transport under `api.post` and the added persona arg differ.

### D.4 Env + dependencies

- **`frontend/.env.example`** â€” keep `NEXT_PUBLIC_API_URL` (document it as the
  `AuthType=NONE` Function URL now); **remove** `NEXT_PUBLIC_AWS_REGION` and
  `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`.
- **`frontend/package.json`** â€” remove `@aws-sdk/credential-providers`
  (`3.1154.0`) and `aws4fetch` (`1.0.20`) from `dependencies`. No new dependency
  is added (`crypto.randomUUID` and `fetch` are platform built-ins). `npm ci`
  must still resolve the lockfile â€” the lockfile is regenerated as part of the
  implementation so `npm ci` stays deterministic.
- **`frontend/AGENTS.md`** â€” the `BEGIN/END:nextjs-agent-rules` block is
  auto-regenerated by `next dev`; the implementer must not run `next dev` (the
  offline gate forbids watch processes) and must leave that block intact. Before
  writing any frontend code the implementer reads the relevant guide under
  `node_modules/next/dist/docs/` per the workspace rule.

---

## E. Demo-simplicity constraints (restated as design guarantees)

- No password hashing, no token store, no server session, no per-user service
  credentials. A plain client-side credential check (`authenticate()`) gating
  the UI is the entire auth. Explicitly accepted.
- The agent and all mock services are **shared** across personas; the ONLY
  things that vary by persona are `role` and `developer_id`, both consumed
  unchanged by the already-wired Runtime path (investigation Â§3). No agent,
  prompt, runtime, `common/`, or `models.py` change is in scope.
- The agent's literal identity display name stays "Lava Dev" (only `role`
  switches behavior), as flagged in the investigation; forwarding `user_name`
  is out of scope for this task.

---

## F. Testing design

### F.1 Thin-API persona-header mapping (new assertions in `api/tests/test_api.py`)

Add tests that drive `current_identity()` through the real app so the header
mapping is proven at the route boundary. Use the existing `_client()` /
`TestClient` + a monkeypatched `invoke_runtime` that captures the forwarded
`body`, and send the header:

- `test_persona_header_pm_maps_to_dev1_product_manager` â€” `POST /chat` with
  header `X-Mahalo-Persona: pm` â‡’ captured `body["developer_id"] == "dev-1"` and
  `body["role"] == "product_manager"`.
- `test_persona_header_dev_maps_to_dev6_developer` â€” header `dev` â‡’
  `developer_id == "dev-6"`, `role == "developer"`.
- `test_persona_header_exec_maps_to_dev5_executive` â€” header `exec` â‡’
  `developer_id == "dev-5"`, `role == "executive"`.
- `test_persona_header_absent_defaults_to_developer` â€” no header â‡’
  `developer_id == "dev-6"`, `role == "developer"`.
- `test_persona_header_unknown_defaults_to_developer` â€” header `wizard` â‡’
  `developer_id == "dev-6"`, `role == "developer"`.

Also add a direct unit test on the dependency using a lightweight stub request:

- `test_current_identity_maps_header` â€” call `current_identity` with a fake
  object exposing `.headers = {"X-Mahalo-Persona": "exec"}` â‡’
  `Identity("dev-5", "executive")`; empty/unknown â‡’ `Identity("dev-6","developer")`.

The existing approve test already asserts `role` is NOT forwarded on approve;
that stays. The capture-based `test_chat_proposal_passthrough` (which asserts
`developer_id == "dev-6"`) still passes with no header sent (default), so it is
unaffected.

### F.2 Infra assertions

**`infra-cdk/tests/test_api_stack.py` â€” UPDATE:**
- `test_function_url_auth_iam` -> rename/retarget to
  `test_function_url_auth_none`: assert `AWS::Lambda::Url` `AuthType == "NONE"`.
- `test_function_url_cors_block`: change the auth assertion to
  `props["AuthType"] == "NONE"`; update the header assertion to require
  `"Content-Type"` and `"X-Mahalo-Persona"` in `cors["AllowHeaders"]` and assert
  the SigV4 headers are **absent**; `AllowMethods == {"POST","GET"}` and
  `MaxAge == 300` stay. Replace the `AllowOrigins != ["*"]` assertion with
  `cors["AllowOrigins"] == ["*"]` (the demo wildcard, Â§B).
- Unaffected: `test_single_python313_lambda`, `test_runtime_arn_env_and_output`,
  `test_lambda_role_can_invoke_runtime`.

**`infra-cdk/tests/test_frontend_stack.py` â€” UPDATE:**
- Delete `test_identity_pool_unauthenticated` and
  `test_unauth_role_only_invoke_function_url` (the constructs are gone).
- `test_outputs_identity_pool_and_frontend_url` -> rename to
  `test_outputs_frontend_url_only`: assert `"FrontendUrl" in outputs` and
  **`"IdentityPoolId" not in outputs`**.
- Add `test_no_cognito_identity_pool`:
  `tmpl.resource_count_is("AWS::Cognito::IdentityPool", 0)` and
  `resource_count_is("AWS::Cognito::IdentityPoolRoleAttachment", 0)`.
- Update the `_frontend_template` helper to stop passing `api_stack=api` to
  `MahaloFrontendStack(...)` (per Â§C the parameter is dropped). The `api`
  stack may stay instantiated in the helper or be removed; removing it is
  cleaner since the frontend no longer depends on it.
- Unaffected: `test_private_bucket`,
  `test_distribution_single_s3_origin_no_function_url_origin`,
  `test_spa_error_responses`, `test_bucket_deployment_flag_gated`.

**`infra-cdk/tests/test_app.py` â€” UPDATE (not an assertion change, a call-site
fix):** its `MahaloFrontendStack(app, "MahaloFrontendStack", api_stack=api_stack,
env=_ENV)` line must drop `api_stack=` per Â§C, or synth throws on the removed
parameter. The assertion itself â€” `len(app.synth().stacks) == 11` â€” stays and
must still hold (the Cognito constructs lived inside the existing frontend
stack, so no stack is added or removed).

**Leave as-is (not in scope):** `test_runtime_stack.py` (Runtime AWS_IAM),
`test_gateway_stack.py` (Gateway authorizer), `test_synth.py:112-115`
(mock-service Function URL already `NONE`). Any `--all` 11-template assertion
(`test_app.py`) must still pass after the Cognito removal.

### F.3 Frontend tests

**`frontend/src/services/api.test.ts` â€” REWRITE:** remove the `aws4fetch` and
`@aws-sdk/credential-providers` mocks; mock the global `fetch` instead
(`vi.stubGlobal("fetch", fetchMock)` or `globalThis.fetch = fetchMock`).
Preserve the two behavioral assertions:
- interrupt_id present in the sent body on `/chat/approve`
  (`JSON.parse(options.body).interrupt_id === "int-42"`, `approved === true`,
  `Content-Type: application/json`);
- a `/chat` reply without `systems_queried` is valid.
Add one assertion: when a `personaId` is passed, the request carries
`headers["X-Mahalo-Persona"] === "<personaId>"`; when omitted, the header is
absent.

**New `frontend/src/lib/personas.test.ts`:** assert `authenticate("pm","pm123")`
returns the PM persona with `developerId === "dev-1"`, `role ===
"product_manager"`; same for `dev`/`exec`; and that a wrong password or unknown
userid returns `null`.

`src/lib/chatSuggestions.test.ts` is unaffected (the lib is unchanged).

**Testability note:** `personas.ts` and `auth.py` are pure/dependency-light and
unit-testable in isolation. The header->identity mapping is best proven at the
route boundary via `TestClient` (integration-style, no AWS). The transport is
unit-tested by mocking `fetch`. CDK output shape is asserted via `assertions.
Template` (synth-only, offline). AuthContext/ProtectedRoute are thin React
wrappers; they are exercised by the build/lint gate rather than added unit tests
(no component test harness exists today and adding one is out of scope).

---

## G. Offline gate (must stay green; clean shell, no `MAHALO_*` env; Windows PowerShell, `;` not `&&`)

Frontend (`frontend/`, Node 24 / npm 11):
- `npm ci`
- `npm run lint`
- `npm test -- --run` (vitest)
- `npm run build` (static export to `frontend/out/`)
Never run `npm run dev` or any watch/long-running process.

infra-cdk (`infra-cdk/`, `.venv` active):
- `cdk synth MahaloFrontendStack` exits 0 offline/Docker-free
- `cdk synth MahaloApiStack` exits 0 offline/Docker-free
- `cdk synth --all` still emits **11 templates**
- `pytest tests -q` green

Unaffected and must stay green: Python agent/api/tools-lambdas suites; zero
LangChain in the Python tree (`test_no_langchain_or_agent_in_api_source` still
passes â€” `auth.py` adds only a `fastapi` import, no `agent`/`langchain`);
`common/`, `agent/`, `runtime` are NOT in scope.

PowerShell examples:
```powershell
cd frontend; npm ci; npm run lint; npm test -- --run; npm run build
cd ..\infra-cdk; .\.venv\Scripts\Activate.ps1; cdk synth MahaloApiStack; cdk synth MahaloFrontendStack; cdk synth --all; pytest tests -q
```

---

## Files to change (exact)

| # | File (under mahalo-agentcore) | Change |
|---|---|---|
| 1 | `api/app/auth.py` | `current_identity(request)` reads `X-Mahalo-Persona`; add `_PERSONA_MAP`, `PERSONA_HEADER`; rewrite docstring |
| 2 | `infra-cdk/mahalo_infra/api_stack.py` | Function URL `AuthType=NONE`; CORS `allowed_origins=["*"]`, `allowed_headers=["Content-Type","X-Mahalo-Persona"]`; drop `FrontendOrigin` param; fix docstring/comments |
| 3 | `infra-cdk/mahalo_infra/frontend_stack.py` | Delete Cognito pool + unauth role + policy + attachment + `IdentityPoolId` output + `self.identity_pool`; drop `cognito`/`iam` imports; drop `api_stack` param; fix docstring |
| 4 | `infra-cdk/app.py` | Update `MahaloFrontendStack(...)` instantiation to drop `api_stack=` arg |
| 4b | `infra-cdk/tests/test_app.py` | Drop `api_stack=` from the `MahaloFrontendStack(...)` call; keep the `== 11` stacks assertion |
| 5 | `frontend/src/lib/personas.ts` | NEW â€” the one credential table + `authenticate()` |
| 6 | `frontend/src/services/api.ts` | Plain `fetch`; drop aws4fetch/Cognito; `post(â€¦, personaId?)` sends `X-Mahalo-Persona` |
| 7 | `frontend/src/contexts/AuthContext.tsx` | NEW â€” client-only persona provider (`sessionStorage`) |
| 8 | `frontend/src/components/common/ProtectedRoute.tsx` | NEW â€” gate shape ported from dock |
| 9 | `frontend/src/app/login/page.tsx` | NEW â€” userid/password + persona login |
| 10 | `frontend/src/app/(protected)/layout.tsx` | NEW â€” wraps segment in `ProtectedRoute` |
| 11 | `frontend/src/app/layout.tsx` | Wrap children in `AuthProvider` |
| 12 | `frontend/src/app/page.tsx` | Route to `/chat` or `/login` by persona |
| 13 | `frontend/src/app/(protected)/chat/page.tsx` | Use persona role for suggestions; send `personaId`; header + logout |
| 14 | `frontend/.env.example` | Keep `NEXT_PUBLIC_API_URL`; drop region + Cognito vars |
| 15 | `frontend/package.json` (+ lockfile) | Remove `aws4fetch`, `@aws-sdk/credential-providers` |
| 16 | `api/tests/test_api.py` | Add persona-header mapping + default tests; add `current_identity` unit test |
| 17 | `infra-cdk/tests/test_api_stack.py` | AWS_IAM->NONE; CORS headers/origin update |
| 18 | `infra-cdk/tests/test_frontend_stack.py` | Remove Cognito tests; `IdentityPoolId` absent; add no-Cognito count test; fix helper |
| 19 | `frontend/src/services/api.test.ts` | Mock `fetch`; preserve assertions; add header assertion |
| 20 | `frontend/src/lib/personas.test.ts` | NEW â€” credential table unit tests |

Not modified: `api/app/routers/chat.py`, `api/app/models.py`,
`api/app/runtime_client.py`, `api/app/config.py`, `frontend/src/lib/chatSuggestions.ts`,
anything under `mahalo-dock`, and all out-of-scope backend/runtime code.
