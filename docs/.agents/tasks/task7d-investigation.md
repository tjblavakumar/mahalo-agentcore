# Task 7d — Investigation: restore Sidebar + agent-driven Dashboard + Connections (frontend-only)

Read-only investigation. No code was edited; nothing was committed. All paths below are
workspace-relative to `<WORKSPACE_ROOT>` unless marked
`[mahalo-dock]` (the read-only fallback repo).

## 0. Scope recap & the one hard constraint

Add three UI features that Task 7 ("chat surface only") dropped:
1. a left-nav **Sidebar** (Dashboard / Chat / Connections),
2. an **agent-driven Dashboard** (headline feature) that calls the existing `/chat` with a
   persona-appropriate "build my dashboard" prompt and renders the synthesized result; the PM
   can **choose which projects** to synthesize,
3. a **Connections** screen showing the 4 services (Jira / Confluence / GitHub / ServiceNow) as
   connected.

**Frontend-only. Reuse the deployed thin API. Do NOT add thin-API/backend routes.** The deployed
thin API exposes only `POST /chat`, `POST /chat/approve`, `GET /healthz`. Confirmed in
`docs/CONTINUATION.md` (RESUME block) and in `api/app/routers/chat.py` / `api/app/models.py`.

**Fallback repo located:** `<FALLBACK_ROOT>` exists as a sibling
directory; its `frontend/src` is intact and readable. It was read for shape only and must never
be edited.

---

## 1. Next.js-version-specific conventions & static-export constraints

**Versions (`frontend/package.json`):** `next 16.3.3`, `react 19.2.8`, `react-dom 19.2.8`,
`react-markdown ^9.0.1`, `tailwindcss ^4` (+ `@tailwindcss/postcss`), `vitest ^2.1.8`,
`eslint-config-next 16.3.3`. **This is Next 16 (App Router), not a trained-on version** — the
`frontend/AGENTS.md` block warns of breaking changes and points at
`frontend/node_modules/next/dist/docs/` (read below).

**`frontend/next.config.ts`** is the whole config:
```ts
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
};
```

### Static-export rules that govern adding routes/layouts here
From `frontend/node_modules/next/dist/docs/01-app/02-guides/static-exports.md` (content rephrased
for licensing compliance):

- `output: 'export'` makes `next build` emit one static HTML file per route into `out/` — no
  Node server at runtime. The app behaves as a SPA after first load; client route transitions are
  pure client-side.
- **Unsupported in static export (App Router)** — do NOT use any of these when adding the new
  screens: Route Handlers that read the request, Server Actions, cookies/headers APIs, rewrites,
  redirects (config-level), proxy, middleware/proxy request logic, ISR, Image Optimization with
  the default loader, Draft Mode, Intercepting Routes, and dynamic routes without
  `generateStaticParams()` (or with `dynamicParams: true`). Using any of these fails under
  `next dev`/`next build`.
- **Client Components are prerendered to HTML at build time.** Browser-only APIs (`window`,
  `localStorage`, `sessionStorage`, `navigator`) must be accessed only inside `useEffect` /
  event handlers / lazy `useState` initializers — never during render/SSR. The existing code
  already follows this (AuthContext restores `sessionStorage` inside a `queueMicrotask` in an
  effect).
- **Client-side data fetching is the supported pattern** (the doc shows SWR; this project just
  uses a plain `fetch` wrapper in `src/services/api.ts`). All `/chat` calls happen from
  `"use client"` components at runtime, which is fully compatible.
- Links: use `next/link` `<Link href>` for client transitions (the dock Sidebar already does).

### Practical implications for the three new screens
- Every new page and the sidebar must be `"use client"` (they read AuthContext and call `/chat`).
- New routes slot into the existing App-Router group `src/app/(protected)/<name>/page.tsx`
  (e.g. `dashboard/page.tsx`, `connections/page.tsx`) — same mechanism already used by
  `(protected)/chat/page.tsx`. No dynamic route segments are needed.
- The sidebar belongs in `src/app/(protected)/layout.tsx` so it renders once around all protected
  pages (today that layout only wraps children in `<ProtectedRoute>`).
- No new npm dependency is needed for the agent-driven dashboard. In particular, the dock's
  dashboard grid uses `react-grid-layout` + `react-resizable` — **those are NOT in
  `frontend/package.json`** and should not be added; the agent-driven dashboard renders the
  `/chat` markdown result (via the existing `react-markdown`), not a draggable widget grid.
- `NEXT_PUBLIC_API_URL` is the only env input (`frontend/.env.example`). Base URL must stay
  env-driven via `src/services/api.ts`; never hardcode a Function URL.

---

## 2. Current frontend file shapes (the chat-surface-only port)

Full tree under `frontend/src`:
```
app/layout.tsx                      app/page.tsx              app/globals.css
app/login/page.tsx
app/(protected)/layout.tsx          app/(protected)/chat/page.tsx
components/chat/{ChatInput,ChatMessage,ContextPanel,ProposalCard}.tsx
components/common/ProtectedRoute.tsx
contexts/AuthContext.tsx
lib/{chatSuggestions,chatSuggestions.test,personas,personas.test}.ts
services/{api,api.test}.ts
types/index.ts
```
There is **no** `components/common/Sidebar.tsx`, no `components/dashboard/`, no
`contexts/ProjectContext.tsx` or `ConnectionsContext.tsx`, no `hooks/`, no dashboard/connections
pages. All three features must be built fresh (shape ported from mahalo-dock).

### `src/lib/personas.ts`
The single source of truth for the hardcoded demo login. Mirror of server `api/app/auth.py`
`_PERSONA_MAP`. Exports:
- `type PersonaId = "pm" | "dev" | "exec"`
- `interface Persona { personaId; userid; password; displayName; personaLabel; developerId; role }`
- `const PERSONAS: Record<PersonaId, Persona>`
- `function authenticate(userid, password): Persona | null`

Persona table (confirmed values):

| personaId | userid | password | displayName | personaLabel     | developerId | role             |
|-----------|--------|----------|-------------|------------------|-------------|------------------|
| pm        | pm     | pm123    | Marcus Chen | Product Manager  | dev-1       | product_manager  |
| dev       | dev    | dev123   | Lava Dev    | Developer        | dev-6       | developer        |
| exec      | exec   | exec123  | David Kim   | Executive        | dev-5       | executive        |

Only `personaId` is ever persisted / sent (as the `X-Mahalo-Persona` header). The password never
leaves the browser.

### `src/contexts/AuthContext.tsx`
`"use client"`. Holds the logged-in persona purely client-side. `STORAGE_KEY = "mahalo_persona"`
in `sessionStorage` (reload-survival only; React state is the source of truth).
```ts
interface AuthContextType {
  persona: Persona | null;
  isLoading: boolean;
  login: (userid, password) => string | null;  // pure client check; error string or null
  logout: () => void;
}
```
- `restoreSession` reads `sessionStorage`, rehydrates `PERSONAS[stored]`, sets `isLoading=false`;
  invoked via `queueMicrotask` inside a mount effect (static-export-safe).
- `login` runs `authenticate`, stores `personaId`, sets state. `logout` clears both.
- Exposes `useAuth()` (throws if used outside provider).
> NOTE the API difference vs mahalo-dock: this AuthContext exposes **`persona`** (not `user`) and
> **no `token`** (no server auth). Any ported dock component referencing `user`/`token` must be
> rewired to `persona` (+ `persona.role`, `persona.developerId`, `persona.displayName`).

### `src/components/common/ProtectedRoute.tsx`
`"use client"`. Gates children on `persona`; while `isLoading` shows a spinner; redirects to
`/login` via `useRouter().push` in an effect when not logged in; returns `null` until persona
present.

### `src/app/login/page.tsx`
`"use client"`. userid/password form + three "quick login" buttons (one per persona) that prefill
and submit. On success `router.push("/chat")`. Branded "MAHALO3". Tailwind card on `bg-gray-50`.

### `src/app/(protected)/chat/page.tsx`
`"use client"`. The chat surface. Relevant details:
- **Assistant markdown rendering:** delegated to `components/chat/ChatMessage.tsx`, which renders
  assistant content with `<ReactMarkdown>` wrapped in Tailwind `prose prose-sm …` classes; user
  messages render as plain `whitespace-pre-wrap`. This is the exact pattern the agent-driven
  dashboard should reuse to render the `/chat` synthesized result.
- **Loading state:** `isLoading` boolean drives an animated three-dot "typing" bubble
  (`animate-bounce`) while a `/chat` call is in flight. There is **no explicit client-side fetch
  timeout** anywhere in this page or in `services/api.ts` — the task brief's mention of a "client
  timeout" does not match the current code (the only timeout concern is the thin-API/Runtime side).
  The dashboard should plan for potentially long `/chat` latency with a clear in-progress state
  but cannot rely on an existing timeout helper.
- **`/chat` call shape:** `api.post<ChatApiResponse>("/chat", { message, session_id: sessionId,
  project_id: null }, persona?.personaId)`. Response type:
  `{ response: string; proposal: Proposal|null; systems_queried?: string[]; status: string;
  session_id: string }`.
- **Session handling:** stores `session_id` from the first response and re-sends it on subsequent
  turns (`setSessionId` when missing or changed). HITL: when `status === "pending_approval"` it
  renders a `ProposalCard`; approve/reject call `POST /chat/approve` with
  `{ session_id, interrupt_id, approved }`.
- Header shows `persona.personaLabel · persona.displayName` + a Logout button; empty state shows
  role-aware starter prompts from `buildSuggestions`.

### `src/services/api.ts`
Plain-`fetch` client. Key facts:
- `API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "https://<function-id>.lambda-url.us-east-1.on.aws"`
  — env-driven; placeholder default only. **Do not hardcode.**
- `request<T>(endpoint, options, personaId?)` sets `Content-Type: application/json` and, when a
  `personaId` is passed, the **`X-Mahalo-Persona`** header. No AWS creds / no SigV4 (thin-API
  Function URL is AuthType=NONE for the demo). Returns `{ data, error }`; `normalizeErrorMessage`
  flattens FastAPI `detail`/`msg`/`message` shapes.
- Exposes `api.get/post/put/delete` (each forwards `personaId`) and `API_BASE_URL`.
> **session_id normalization lives on the thin API, not the client.** `api/app/routers/chat.py`
> `_runtime_session_id()` normalizes any client value to a Runtime-valid id with floor
> `_MIN_RUNTIME_SESSION_LEN = 33` (missing/short → `"mahalo-" + uuid4().hex` = 39 chars) and echoes
> it back; the client just reuses whatever `session_id` the response carries. The new dashboard
> should follow the chat page: send whatever session id it has (or `null`) and adopt the returned
> one. (This normalization is the fix for the earlier "status → error"/502 the user hit.)

### `(protected)` layout & env usage
- `src/app/(protected)/layout.tsx` currently returns only `<ProtectedRoute>{children}</ProtectedRoute>`
  — **this is where the Sidebar must be inserted** (e.g. a flex row: `<Sidebar />` + a
  `flex-1` main that renders `children`). The root `src/app/layout.tsx` sets `<body class="min-h-full flex">`
  and wraps everything in `<AuthProvider>`.
- `src/app/page.tsx` redirects `/` → `/chat` (logged in) or `/login`.
- Env: only `NEXT_PUBLIC_API_URL` (see `.env.example`); consumed solely in `services/api.ts`.

### Thin-API request/response contracts (from `api/app/`)
- `POST /chat` body `ChatRequest { message: str; session_id?: str; project_id?: int }`. **`project_id`
  is accepted for frontend compatibility but is CURRENTLY UNUSED ("Out of Scope")** — see
  `api/app/models.py`. **Implication for PM project multi-select:** the chosen projects must be
  conveyed inside the `message` prompt text, NOT via `project_id`.
- `ChatResponse { response: str; proposal?: dict; session_id: str; status: str }`.
- Persona → identity mapping server-side (`api/app/auth.py` `_PERSONA_MAP`): `pm→(dev-1,
  product_manager)`, `dev→(dev-6, developer)` [default], `exec→(dev-5, executive)`. Header is
  trusted but can only select one of the known-good identities.

---

## 3. mahalo-dock reference shapes + what must be rewired

mahalo-dock `[mahalo-dock] frontend/src` tree (relevant parts):
```
app/(protected)/{layout,chat/page,dashboard/page,connections/page,connections/[id]/data/page}.tsx
app/{login,register}/page.tsx
components/common/{Sidebar,ProjectMultiSelect,ProtectedRoute}.tsx
components/dashboard/DashboardGrid.tsx
components/dashboard/widgets/{SprintBoard,Velocity,ProjectStatus,Portfolio,KeyMetrics,MyStories,MyPRs,RecentCommits}Widget.tsx
contexts/{AuthContext,ConnectionsContext,ProjectContext}.tsx
hooks/useRequiredConnections.ts
services/api.ts   types/index.ts   types/react-grid-layout.d.ts
```

### 3a. Sidebar — `[mahalo-dock] components/common/Sidebar.tsx`
**Visual shape (port this):** fixed left `<aside className="w-64 bg-gray-900 text-white flex flex-col min-h-screen">`.
- Top: logo block `p-6 border-b border-gray-700` — "MAHALO3" (`text-xl font-bold`) + subtitle
  "AI-Powered SDLC Platform" (`text-xs text-gray-400`).
- User block `p-4 border-b border-gray-700`: avatar circle (first initial, `bg-blue-600 rounded-full`)
  + name + role label; "Sign out" button.
- Projects block `p-4 border-b border-gray-700`: label "Projects", an "N/M in dash" counter, a
  "Sync" button, and the `<ProjectMultiSelect>` dropdown.
- Nav `flex-1 p-4 space-y-1`: array `[{Dashboard,📊,/dashboard},{Chat,💬,/chat},{Connections,🔗,/connections}]`
  rendered as `<Link>`s; active (via `usePathname().startsWith(href)`) → `bg-blue-600 text-white`,
  inactive → `text-gray-300 hover:bg-gray-800`.

**Data sources it uses → rewire:**
- `useAuth()` → dock's `{ user, logout }`. **Rewire to agentcore `{ persona, logout }`**; use
  `persona.displayName` for name/initial and `persona.personaLabel`/`ROLE_LABELS[persona.role]`.
- `useProjects()` (ProjectContext: `projects, selectedProjects, toggleProjectSelection, loading,
  syncing, syncProjects`) → **does not exist in agentcore.** Rewire to a **new static project
  source** (see §4) + local selection state (persona-scoped; PM multi-select). Drop `syncProjects`/
  "Sync" (there is no `/projects/sync`) — or keep the button as a no-op/removed.
- `useRequiredConnections()` (ConnectionsContext `isConfigured/loading`) → **rewire to a static
  "all four connected" constant** (no `/integrations` endpoint). The "configure connections"
  skeleton/empty states can be simplified since services are always connected in the demo.

**Decision for the design step:** the Projects multi-select belongs in the sidebar in the dock, but
per the user it only needs to drive the **PM dashboard synthesis**. Options the design must pick
between: (a) show the multi-select in the sidebar for all personas (dock-faithful), or (b) show
project selection only on the Dashboard page for the PM persona. Either way it feeds the dashboard
prompt, not `project_id`.

### 3b. Dashboard — `[mahalo-dock] app/(protected)/dashboard/page.tsx` + `components/dashboard/*`
**Dock behaviour (DO NOT port verbatim):** builds a **role-specific react-grid-layout widget grid**.
`buildRoleDashboard(role, selectedProjects, developerId)` returns `{widgets, layout}` per role:
- product_manager: SprintBoard, Velocity, ProjectStatus, KeyMetrics
- executive: Portfolio, KeyMetrics, Velocity, ProjectStatus, SprintBoard
- developer: MyStories, MyPRs, RecentCommits, SprintBoard, Velocity

Rendered through `components/dashboard/DashboardGrid.tsx` (a `react-grid-layout` `Responsive`
`WidthProvider` grid with drag/resize, localStorage layout persistence under
`mahalo3_dashboard_layout:<storageKey>`). **Each widget fetches live data from backend proxy routes**
e.g. `SprintBoardWidget` calls `GET /proxy/jira/projects` and `GET /proxy/jira/projects/{id}/board`.

**Why none of the widget/grid data path survives:** every widget's data source
(`/proxy/jira/...`, `/projects`, `/integrations`, `/auth/me`) is a **backend route that does not
exist in the thin API**, and `react-grid-layout`/`react-resizable` are **not dependencies** of
agentcore's frontend. Restoring the grid would require new backend routes (forbidden) + new deps.

**What to build instead (matches the user's explicit choice, msg #9/#10 and CONTINUATION):**
An **agent-driven** dashboard page that:
1. builds a persona-appropriate "build my dashboard" prompt (PM/Developer/Executive flavour, using
   the role templates in `src/lib/chatSuggestions.ts` as tone/wording reference),
2. for the PM, injects the **chosen project keys** (multi-select) into the prompt text,
3. POSTs it to the existing `/chat` with `persona.personaId` (+ session handling exactly like the
   chat page), and
4. renders `response` markdown with the existing `ChatMessage`/`react-markdown` `prose` styling,
   plus an in-progress state (reuse the chat typing indicator) and the `systems_queried` chips.

**Visual shell to port from the dock dashboard page** (the non-grid parts are reusable): page
padding `p-8`; header `text-3xl font-bold "Dashboard"` + welcome line with role; a small
blue info pill summarizing the project scope
(`No projects selected (showing all)` / `Project: X` / `Aggregating N selected projects`); a
loading spinner block while data settles. Card styling throughout is `bg-white rounded-lg shadow`.

**Dashboard data sources → rewire:** `useAuth().user`→`persona`; `useProjects().selectedProjects`→
static selected keys; `useRequiredConnections()`→static connected; `developerId` from
`persona.developerId`. All widget fetches → replaced by the single `/chat` call.

### 3c. Connections — `[mahalo-dock] app/(protected)/connections/page.tsx`
**Dock behaviour:** a full CRUD manager — lists `GET /integrations`, add/test/delete connections
(`POST /integrations`, `POST /integrations/{id}/test`, `DELETE /integrations/{id}`), create projects
with an AI proposal flow (`/projects/proposal`, `/projects`), toggle project selection
(`/projects/{id}/selection`). The service metadata table is reusable:
```
jira       📋  Jira        (mock-jira:5001)
confluence 📄  Confluence  (mock-confluence:5002)
github     🐙  GitHub      (mock-github:5003)
servicenow 🛠️  ServiceNow  (mock-servicenow:5004)
```
Per-service card shape: `bg-white rounded-lg shadow p-5 flex items-center justify-between` with a
3xl emoji icon, name/url, and status/action buttons (Test = `bg-green-50 text-green-700`, etc.).

**What to build instead (user msg #9/#10: "connections screen should be real, showing the 4
services as connected"):** a **read-only, static "all four connected"** screen. Port the service
table + card styling, drop every `api.*` call and all project/connection CRUD. Show each of the 4
services with a green "Connected" badge. No new endpoints.

**Connections data sources → rewire:** remove `useProjects`, `useRequiredConnections`, all
`/integrations` + `/projects*` calls; replace with a static `SERVICES` constant (icon + label +
"Connected").

### 3d. Dock contexts/hooks that are DROPPED and must be replaced by static data
| mahalo-dock source | backend route it needs | agentcore replacement |
|---|---|---|
| `contexts/ConnectionsContext.tsx` | `GET /integrations` | static "4 services connected" constant |
| `hooks/useRequiredConnections.ts` | (via ConnectionsContext) | static `isConfigured = true` |
| `contexts/ProjectContext.tsx` | `GET/POST/PUT /projects*`, `/projects/sync` | static project list + local selection state |
| `contexts/AuthContext.tsx` (`user`,`token`,`/auth/me`,`/auth/login`) | auth endpoints | existing agentcore `AuthContext` (`persona`, no token) |
| widgets' `GET /proxy/jira/...` etc. | proxy routes | single `/chat` "build my dashboard" call |

---

## 4. Seed project keys for the PM project multi-select

Confirmed from the repo seed source `tools-lambdas/jira/seed_data.py` (`PROJECTS`). There are
**five** projects (the brief's "e.g. PAY, AUTH, CART" is a subset):

| key   | name                  | lead  |
|-------|-----------------------|-------|
| PAY   | Payment Gateway       | dev-1 |
| CART  | Shopping Cart         | dev-2 |
| AUTH  | User Authentication   | dev-3 |
| PROD  | Product Catalog       | dev-4 |
| ORD   | Order Management      | dev-5 |

Cross-service alignment is confirmed in `tools-lambdas/servicenow/seed_data.py` and
`tools-lambdas/github/seed_data.py`:
- GitHub repos: `payment-service (repo-1/PAY)`, `cart-service (repo-2/CART)`,
  `auth-service (repo-3/AUTH)`, `product-service (repo-4/PROD)`, `order-service (repo-5/ORD)`.
- ServiceNow services mirror the same five `project_id`s (PAY/CART/AUTH/PROD/ORD).
- Confluence spaces are keyed differently (`ENG`, `SEC`, `PROD`, `API` — topic spaces, not per-
  project), so Confluence does not map 1:1 to the project keys.

**Recommendation for the design step:** hardcode a static project list of these five
`{ key, name }` pairs in the frontend (e.g. a new `src/lib/projects.ts`) as the multi-select
source. The selected keys/names get interpolated into the PM "build my dashboard" prompt (the
agent resolves them against the live seed data), since `/chat`'s `project_id` is ignored.

---

## 5. Open questions for the design step

1. **Prompt wording & persona variants.** Exact "build my dashboard" prompt text per persona
   (PM/Developer/Executive) is undecided. The role templates in `src/lib/chatSuggestions.ts`
   (`ROLE_TEMPLATES`) are a good tone reference. For the PM, decide how selected project
   keys/names are phrased in the prompt (e.g. "…across Payment Gateway (PAY) and User
   Authentication (AUTH)…"). Should "no projects selected" mean "all projects" (dock semantics)?
2. **Rendering the synthesized result.** Is plain markdown via `ChatMessage`/`react-markdown`
   sufficient (recommended, zero new deps), or does the design want light structure (cards/sections)
   parsed from the markdown? If the latter, the agent prompt may need to request a predictable
   format (headings/sections) — but keep it markdown-renderable.
3. **Dashboard re-run / caching.** Should the dashboard auto-build on page load, or require a
   "Build dashboard" button? Should the result persist (sessionStorage) across navigation, or
   re-call `/chat` each visit? (Latency matters — see no-client-timeout note in §2.)
4. **Session id strategy for the dashboard.** Share the chat session id, or use an independent
   dashboard session? (Memory continuity vs. isolation.) Either works with the thin-API
   normalization.
5. **Project multi-select placement & persona scope.** Sidebar (all personas, dock-faithful) vs.
   Dashboard-page only (PM). The user explicitly wants PM project choice; Developer/Executive may
   not need it. Confirm selection-state ownership (a small context vs. local page state).
6. **Where the static data lives.** New `src/lib/projects.ts` (five keys) and a static connections
   constant (4 services) — confirm file placement/naming conventions.
7. **Long-latency UX.** The agent-driven dashboard may take many seconds. Decide the in-progress
   affordance (reuse chat typing dots vs. skeleton) and any client-side guard, since there is no
   existing fetch timeout.
8. **Offline gate.** CONTINUATION specifies the gate: frontend `npm ci` / lint / `vitest --run` /
   `next build` (static export to `out/`) must stay green, plus infra synth. New code must keep the
   existing 12 vitest tests passing and add tests where practical (the repo already unit-tests
   `personas`, `chatSuggestions`, `api`).

---

## Appendix — key file references
- Current frontend: `frontend/src/{lib/personas.ts, contexts/AuthContext.tsx,
  components/common/ProtectedRoute.tsx, app/login/page.tsx, app/(protected)/layout.tsx,
  app/(protected)/chat/page.tsx, components/chat/ChatMessage.tsx, services/api.ts, types/index.ts}`,
  `frontend/next.config.ts`, `frontend/.env.example`, `frontend/AGENTS.md`.
- Thin API contracts: `api/app/models.py`, `api/app/routers/chat.py`, `api/app/auth.py`.
- Seed data: `tools-lambdas/{jira,github,servicenow,confluence}/seed_data.py`.
- Next docs read: `frontend/node_modules/next/dist/docs/01-app/02-guides/static-exports.md`,
  `.../01-getting-started/04-linking-and-navigating.md`.
- mahalo-dock (read-only): `[mahalo-dock] frontend/src/components/common/{Sidebar,ProjectMultiSelect}.tsx`,
  `.../app/(protected)/{dashboard,connections}/page.tsx`,
  `.../components/dashboard/{DashboardGrid,widgets/SprintBoardWidget}.tsx`,
  `.../contexts/{AuthContext,ConnectionsContext,ProjectContext}.tsx`,
  `.../hooks/useRequiredConnections.ts`, `.../services/api.ts`, `.../types/index.ts`.
- Task intent/constraints: `docs/CONTINUATION.md` (RESUME block).

_Content from documentation sources was rephrased for compliance with licensing restrictions._
