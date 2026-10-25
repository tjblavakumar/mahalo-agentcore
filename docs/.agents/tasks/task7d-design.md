# Task 7d — Design: Sidebar + agent-driven Dashboard + Connections (frontend-only)

Authored from the investigation at `docs/.agents/tasks/task7d-investigation.md`. A design review
exists (`docs/.agents/tasks/task7d-design-review.json`, verdict `CHANGES_REQUESTED`, review doc
`docs/.agents/tasks/task7d-design-review.md`), so **this is a revision** that resolves every
finding. The latest review (revision 3) raised four findings (1 MEDIUM + 3 NIT), all addressed in
this revision; the earlier ten findings remain resolved. See "Review findings — responses" at the
end. All paths are workspace-relative to
`<WORKSPACE_ROOT>` and use forward slashes. This is a design-only
artifact: no application code was written and nothing was committed. The read-only `mahalo-dock`
sibling repo was read for component shape only and must never be edited.

---

## Overview

Task 7 ported MAHALO3's frontend down to a "chat surface only" SPA. This task restores three UI
features that the port dropped — a persistent **left-nav Sidebar**, an **agent-driven Dashboard**,
and a static **Connections** screen — entirely in the frontend, reusing the already-deployed thin
API (`POST /chat`) and adding **zero** new backend/thin-API routes. The headline feature is the
Dashboard: instead of mahalo-dock's `react-grid-layout` widget grid (which depended on backend
proxy routes and npm deps that no longer exist), the Dashboard sends a persona-tailored "build my
dashboard" prompt to `/chat` and renders the synthesized markdown with the chat page's existing
`react-markdown` rendering. The PM persona additionally picks which seed projects to synthesize,
and those keys are interpolated into the prompt text (never into the unused `project_id` field).

The whole thing stays static-export-safe (`output: "export"`): every new page and the sidebar are
Client Components that fetch at runtime; there are no server actions, route handlers, SSR-only
APIs, or dynamic `[id]` route segments. Technology stack is locked to what the repo already uses
(see below) — no new dependencies.

### Locked technology stack

- **Next.js 16.3.3** (App Router, `output: "export"`), **React 19.2.8**, **react-dom 19.2.8** — as
  in `frontend/package.json`. New routes use the existing `src/app/(protected)/<name>/page.tsx`
  App-Router group mechanism. No dynamic segments, no `generateStaticParams`, no new config.
- **react-markdown ^9.0.1** for rendering the agent's synthesized dashboard — the same dependency
  and the same `prose` class string the chat page's `ChatMessage` uses (the dashboard renders in its
  own full-width `prose` card rather than reusing the `ChatMessage` bubble — see §B / Finding 3).
  **No** `react-grid-layout` / `react-resizable` (not in `package.json`; must not be added).
- **tailwindcss ^4** for styling (ported class strings from mahalo-dock).
- **vitest ^2.1.8** for the new unit tests, matching the existing `*.test.ts` convention. The
  configured test environment is **`node`** (`frontend/vitest.config.ts` sets
  `environment: "node"`) and there is **no** jsdom / `@testing-library/react` dependency — so all
  new tests are **pure-logic, node-safe** (no React render harness), exactly like the existing
  suite (currently 19 cases across `personas`, `api`, `chatSuggestions`).
- **Data layer:** the existing `src/services/api.ts` plain-`fetch` client. Base URL stays
  env-driven via `NEXT_PUBLIC_API_URL`; never hardcoded. Persona asserted via the
  `X-Mahalo-Persona` header exactly as the chat page does.

---

## Files to create / modify

### Create

| Path | Purpose |
|---|---|
| `frontend/src/components/common/Sidebar.tsx` | Persistent left nav (ported shape from mahalo-dock, rewired to `persona`). |
| `frontend/src/lib/projects.ts` | Static seed project list (`SEED_PROJECTS`) + the pure dashboard prompt-builder (`buildDashboardPrompt`). |
| `frontend/src/lib/projects.test.ts` | Unit tests for the project list + prompt-builder. |
| `frontend/src/lib/connections.ts` | Static `SERVICES` constant (the four "connected" services). |
| `frontend/src/lib/connections.test.ts` | Node-safe unit test: `SERVICES` declares exactly the four connected services. |
| `frontend/src/components/dashboard/DashboardView.tsx` | Presentational dashboard body (header, project pill, markdown result, loading, regenerate) — extracted so it is unit-testable without the page's data wiring. |
| `frontend/src/components/dashboard/ProjectSelect.tsx` | PM-only multi-select of seed project keys. |
| `frontend/src/app/(protected)/dashboard/page.tsx` | Dashboard route: owns state, calls `/chat`, renders `DashboardView`. |
| `frontend/src/app/(protected)/connections/page.tsx` | Static Connections route rendering `SERVICES`. |

> **Test location convention (Findings 1 & 2):** all new tests live under `src/lib/` as node-safe
> `*.test.ts` — never under `src/app/` (route segments hold only `page.tsx` special files) and
> never as React render tests (the vitest env is `node`, no jsdom/testing-library). The two
> **required** named tests are therefore `src/lib/projects.test.ts` and `src/lib/connections.test.ts`.
> No `DashboardView.test.tsx` / `connections.test.tsx` render test is planned.

### Modify

| Path | Change |
|---|---|
| `frontend/src/app/(protected)/layout.tsx` | Wrap children in a flex row: `<Sidebar />` + a scrollable `<main className="flex-1">`. Keep `<ProtectedRoute>` as the outer gate. |
| `frontend/src/types/index.ts` | Add exported `Proposal` and `ChatResponse` interfaces (the shared `/chat` wire shape) so both the chat page and the dashboard page import one definition. (Finding 3.) |
| `frontend/src/app/(protected)/chat/page.tsx` | Two changes: (1) replace the page-local inline `Proposal` + `ChatApiResponse` declarations with `import type { Proposal, ChatResponse } from "@/types"` and use `ChatResponse` at the `api.post<…>` call site; (2) change only the root wrapper `className` from `flex h-screen` to `flex h-full`. (Details in §A / §B.) |
| `frontend/src/components/chat/ProposalCard.tsx` | **No change (deliberate, Finding 2).** It declares its own local `Proposal` interface (`action/system/params/description/interrupt_id?`), structurally identical to the promoted `@/types` `Proposal`. The chat page passes the shared-typed `Proposal` into it and it type-checks by structural compatibility. The design **chooses to leave this local copy as-is** rather than migrate it, so the chat-page edit stays a minimal two-line change; migrating `ProposalCard` to `import type { Proposal } from "@/types"` is an optional later cleanup, explicitly out of scope for this task so the implementer does not improvise. |

Nothing else changes. `login`, `AuthContext`, `ProtectedRoute`, `personas`, `services/api.ts`,
and the thin API are untouched.

---

## A. Left-nav Sidebar

### Component and placement

Create `frontend/src/components/common/Sidebar.tsx` as a `"use client"` component, porting the
mahalo-dock visual shape but stripped of the dropped data sources. It renders:

- **Logo block** — `p-6 border-b border-gray-700`: "MAHALO3" (`text-xl font-bold tracking-wide`) +
  subtitle "AI-Powered SDLC Platform" (`text-xs text-gray-400`). Ported verbatim.
- **User block** — `p-4 border-b border-gray-700`: avatar circle (`w-8 h-8 bg-blue-600 rounded-full`)
  showing `persona.displayName.charAt(0).toUpperCase()`, the `persona.displayName`, and
  `persona.personaLabel` beneath. A "Sign out" button that calls `logout()` then
  `router.push("/login")`.
- **Navigation** — `flex-1 p-4 space-y-1`: the three links from a `navigation` array
  `[{name:"Dashboard",href:"/dashboard",icon:"📊"},{name:"Chat",href:"/chat",icon:"💬"},{name:"Connections",href:"/connections",icon:"🔗"}]`,
  rendered as `next/link` `<Link>`s. Active state via `usePathname()?.startsWith(item.href)` →
  `bg-blue-600 text-white`; inactive → `text-gray-300 hover:bg-gray-800 hover:text-white`. Ported
  verbatim.

The outer shell is `<aside className="w-64 bg-gray-900 text-white flex flex-col min-h-screen">` —
same as the dock.

**Rewiring (mandatory):** the dock Sidebar uses `useAuth()` returning `{ user, logout }`,
`useProjects()`, and `useRequiredConnections()`. In agentcore:

- `useAuth()` returns `{ persona, logout }` (no `user`, no `token`). Use `persona.displayName`,
  `persona.personaLabel`, `persona.displayName.charAt(0)`. If `persona` is null the sidebar still
  renders inside `<ProtectedRoute>`, which already blocks render until a persona exists, so a
  null-guard that returns a minimal block is sufficient (defensive only).
- **Drop the Projects block entirely from the sidebar.** `useProjects()` / `ProjectMultiSelect`
  and the "Sync" button all depend on contexts/endpoints that do not exist. Per the user, project
  selection only needs to drive the PM dashboard synthesis, so it lives on the Dashboard page (see
  §B), not the sidebar. This is the chosen resolution to investigation open-question #5
  (**option (b): Dashboard-page-only, PM-scoped**). Rationale: it removes all dropped-context
  coupling from the global nav, keeps the sidebar identical for every persona, and puts the
  selection next to the thing it affects.
- **Drop `useRequiredConnections()`** — connections are statically "all connected"; the sidebar has
  no connection-dependent UI once the Projects block is gone.

### Hosting the sidebar without breaking chat

`frontend/src/app/(protected)/layout.tsx` currently is:

```tsx
return <ProtectedRoute>{children}</ProtectedRoute>;
```

Change it to host the sidebar as the left column of a flex row:

```tsx
import ProtectedRoute from "@/components/common/ProtectedRoute";
import Sidebar from "@/components/common/Sidebar";

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="flex min-h-screen w-full">
        <Sidebar />
        <main className="flex-1 min-w-0 h-screen overflow-y-auto">{children}</main>
      </div>
    </ProtectedRoute>
  );
}
```

The layout stays a Server Component by default (it imports a client `Sidebar`, which is allowed);
no `"use client"` needed on the layout itself. `Sidebar` and `ProtectedRoute` are the client
boundaries.

**Body-level composition (Finding 1, revision 3 — corrected).** The root layout
(`frontend/src/app/layout.tsx`) keeps `<html className="h-full">` and
`<body className="min-h-full flex">` **unchanged** — this design does not touch the root layout. The
body is therefore a flex **row**, so its **main axis is horizontal (width)** and its cross axis is
vertical (height). A flex item with no `flex-grow`/`flex-1`/explicit width sizes to its **content**
on the main (width) axis — it does **not** stretch to the row's full width (only the cross axis,
height, stretches by default). This is confirmed by the codebase's own convention: the two existing
direct-body flex children both add `w-full` precisely to span the viewport —
`frontend/src/app/page.tsx` and `frontend/src/app/login/page.tsx` are each
`<div className="min-h-screen flex items-center justify-center bg-gray-50 w-full">`.

Therefore the protected wrapper **must carry an explicit width directive**: this design uses
`<div className="flex min-h-screen w-full">` (the chosen option; `flex-1` would also work, but
`w-full` matches the two existing body-child conventions above, so it is the one picked). With
`w-full`, the wrapper spans the full body row width, and its two children — `<Sidebar className="w-64 …">`
(fixed) and `<main className="flex-1 min-w-0 h-screen overflow-y-auto">` (grows into the remaining
width) — fill it exactly. `children` is a block-level element inside the non-flex `<main>`, so it
spans `<main>` normally. There is no zero-width/zero-height column and no double scrollbar: the
single vertical scroll lives on `<main>`. The `/login` route is also a direct body flex child but is
**unaffected**, because it is outside the `(protected)` group and already carries its own
`w-full min-h-screen` centered card. With the wrapper width fixed, the only edit the chat page needs
is the height-class swap below.

**Chat-page interaction.** The chat page's root is today `<div className="flex h-screen">`. That
root flex row contains **two** children: the chat column (`<div className="flex-1 flex flex-col">`)
and the `<ContextPanel>` slide-over sibling. Dropping this root inside a
`<main className="flex-1 h-screen overflow-y-auto">` would nest two `h-screen` columns and double
the height. The surgical fix is a **single class change and nothing else**: change only the chat
page root `className` from `flex h-screen` to `flex h-full` (it now inherits height from the new
`<main>`). Both children — the chat column and `<ContextPanel>` — are unchanged; the internal
message scroll area (`flex-1 overflow-y-auto`) is preserved, so chat behavior is unchanged except
that the left edge is now the sidebar instead of the viewport edge. The chat page keeps its own
in-page header + Logout (harmless redundancy with the sidebar sign-out; both call the same
`logout()`). The chat page needs only the height-class swap; its full-width rendering depends on
the protected wrapper carrying `w-full`/`flex-1` (see §A layout markup above) — so if the chat
column ever appears collapsed, the cause is the wrapper width, not the chat page. Within the chat
page file itself the one class swap is the whole change. This satisfies the "keep chat working"
constraint.

Edge cases: `usePathname()` can be `null` during the first client render (optional-chained, so
active state simply resolves to inactive — acceptable). Deep links like `/dashboard` and
`/connections` highlight correctly via `startsWith`.

---

## B. Dashboard (agent-driven — headline feature)

### Route and component structure

- `frontend/src/app/(protected)/dashboard/page.tsx` — `"use client"`. Owns all state and the
  `/chat` call; delegates presentation to `DashboardView`.
- `frontend/src/components/dashboard/DashboardView.tsx` — `"use client"` presentational component:
  header, project-scope pill, `ProjectSelect` (PM only), the regenerate button, the loading
  indicator, and the rendered markdown. Takes everything via props so it can be rendered in tests
  without network.
- `frontend/src/components/dashboard/ProjectSelect.tsx` — `"use client"` multi-select of seed
  project keys (PM only).
- Markdown result rendering — chosen resolution to investigation open-question #2 and review
  **Finding 3 (revision 3)**: **reuse the same `react-markdown` + `prose` rendering the chat page
  uses, but in a dashboard-local full-width `prose` container — NOT the `ChatMessage` component.**
  Verified in `frontend/src/components/chat/ChatMessage.tsx`: an assistant message is wrapped in
  `<div className="flex justify-start"> … <div className="max-w-[80%] rounded-lg px-4 py-3 bg-white border …">`,
  i.e. a **left-aligned chat bubble capped at 80% width**. That bubble geometry is right for a chat
  transcript but wrong for a "headline dashboard", where the synthesized report should fill the
  content column. So `DashboardView` renders the result inside its own full-width card instead:

  ```tsx
  import ReactMarkdown from "react-markdown";
  // …inside DashboardView, for the non-empty result branch:
  <div className="bg-white rounded-lg shadow p-6">
    <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-strong:text-gray-900 prose-li:text-gray-700">
      <ReactMarkdown>{result.response}</ReactMarkdown>
    </div>
  </div>
  ```

  The `prose prose-sm max-w-none prose-headings:… prose-p:… prose-strong:… prose-li:…` class string
  is **copied verbatim** from `ChatMessage`'s assistant branch, so the typography matches chat
  exactly; only the bubble chrome (`flex justify-start` + `max-w-[80%]` + bubble padding/border) is
  dropped in favour of the full-width `bg-white rounded-lg shadow p-6` dashboard card. This keeps
  the "reuse the chat's assistant-markdown rendering" requirement (same dep `react-markdown ^9`,
  same `prose` styling, no new parsing, no new deps) while giving the headline screen full-width
  presentation. Rationale for choosing (b) over reusing `ChatMessage` verbatim: the dashboard is the
  headline feature and a 80%-width left-aligned bubble would read as a cramped chat reply; the only
  cost of (b) is a few duplicated Tailwind classes, which is cheaper than mis-presenting the
  headline. (If a future change prefers a shared renderer, the `prose` wrapper could be factored into
  a small `MarkdownBody` component used by both chat and dashboard — noted as optional out-of-scope
  cleanup, not done here.)
- **`systems_queried` chips are intentionally NOT a dashboard feature (Finding 1).** The deployed
  thin API does not project `systems_queried`: `api/app/models.py` `ChatResponse` declares only
  `response`/`proposal`/`session_id`/`status`, and `api/app/routers/chat.py` builds the reply under
  `response_model=ChatResponse`, which strips any extra key — so `result.systems_queried` is always
  `undefined` at runtime. The shared `ChatResponse` type (below) keeps `systems_queried?` as an
  **optional** field only to match the chat page's shape; the dashboard does **not** render chips.
  Because the dashboard now renders its own full-width `prose` card (Finding 3) rather than reusing
  `ChatMessage`, there is no chip row at all on the dashboard — the question of passing
  `systemsQueried` does not arise. (For reference, `ChatMessage` still gates its own chip row on
  `systemsQueried && systemsQueried.length > 0`, which stays `undefined`-safe on the chat page.) As
  of today the chips are latent by design, not a bug and not a promised visual. Should a demo ever
  want "systems" chips on the dashboard, derive them frontend-side (e.g. the four static `SERVICES`
  labels); do not attribute them to the `/chat` reply.
- **Render ordering (Finding 6, + empty-predicate Finding 4):** `<ReactMarkdown>` renders whatever
  string it is given, so an empty/whitespace string would produce a blank `prose` block rather than
  a helpful note. `DashboardView` therefore branches **before** rendering the markdown card, in this
  order: (1) error banner when `error` is set; (2) loading indicator when `isLoading`; (3)
  empty-state note ("The agent returned no content — try Regenerate.") when the response is empty by
  the explicit predicate **`!result?.response || result.response.trim().length === 0`** (so a single
  space `" "` counts as empty); (4) otherwise — and only then — the full-width `prose` markdown card
  (above) with `result.response`. `<ReactMarkdown>` is never handed `""` or whitespace-only content.

### Static seed project list

Create `frontend/src/lib/projects.ts`:

```ts
export interface SeedProject {
  key: string;   // Jira/GitHub/ServiceNow project key
  name: string;  // human-readable name
}

// The five cross-service-aligned seed projects (tools-lambdas/*/seed_data.py).
// Confluence spaces are topic-keyed, not per-project, so they are not mapped here.
export const SEED_PROJECTS: SeedProject[] = [
  { key: "PAY",  name: "Payment Gateway" },
  { key: "CART", name: "Shopping Cart" },
  { key: "AUTH", name: "User Authentication" },
  { key: "PROD", name: "Product Catalog" },
  { key: "ORD",  name: "Order Management" },
];
```

### Prompt-builder (pure, unit-testable)

Also in `frontend/src/lib/projects.ts`. Three persona templates; the PM template interpolates the
selected project keys/names. Signature:

```ts
import type { UserRole } from "@/types";

export interface DashboardPromptInput {
  role: UserRole;                 // product_manager | developer | executive
  selectedProjectKeys?: string[]; // only consulted for product_manager
}

/** Pure: (role [, selected PM project keys]) -> the "build my dashboard" prompt string. */
export function buildDashboardPrompt(input: DashboardPromptInput): string;
```

Behavior:

- **developer** and **executive** ignore `selectedProjectKeys` and return their fixed template.
- **product_manager**: if `selectedProjectKeys` is empty/undefined → the "all projects" variant
  (chosen resolution to open-question #1: **no selection means all projects**, matching dock
  semantics). If non-empty → the keys are resolved against `SEED_PROJECTS` and phrased as
  `"Name (KEY)"` pairs joined with commas, injected into the prompt. Unknown keys (not in
  `SEED_PROJECTS`) are passed through as bare `KEY` so a typed key still works, and the list is
  de-duplicated preserving order.

**Exact prompt templates** (the strings the builder returns; `{projects}` is the interpolated clause):

- **product_manager, with projects:**
  > "You are my product delivery assistant. Build a Product Manager dashboard for projects {projects}. Working across Jira, Confluence, GitHub and ServiceNow, summarize for each project: current sprint status and progress, open blockers and risks, team velocity, notable recent documentation changes, and any production incidents. Use clear Markdown with a short section heading per project and concise bullet points. Start with a one-paragraph executive summary across the selected projects."

  where `{projects}` = e.g. `Payment Gateway (PAY), User Authentication (AUTH)`.

- **product_manager, no selection (all):**
  > "You are my product delivery assistant. Build a Product Manager dashboard across all of my projects. Working across Jira, Confluence, GitHub and ServiceNow, summarize overall sprint status and progress, the top open blockers and risks, team velocity, notable recent documentation changes, and any production incidents. Use clear Markdown with section headings and concise bullet points. Start with a one-paragraph delivery summary."

- **developer:**
  > "You are my engineering assistant. Build a Developer dashboard for me. Working across Jira, GitHub and ServiceNow, summarize my assigned issues and their status, my open pull requests and review requests, recent commits and the latest release, and any production incidents or failed deployments that affect my work. Use clear Markdown with section headings and concise bullet points. Start with a one-paragraph summary of what needs my attention today."

- **executive:**
  > "You are my executive assistant. Build an Executive portfolio dashboard. Working across Jira, Confluence, GitHub and ServiceNow, give a portfolio health roll-up across all projects: overall delivery status and momentum, top risks and blockers, notable incidents, and delivery trends this quarter. Use clear Markdown with section headings and concise bullet points. Start with a one-paragraph portfolio health summary."

These intentionally echo the tone of `ROLE_TEMPLATES` in `src/lib/chatSuggestions.ts` (sprint
status / velocity / blockers for PM; my issues / PRs / incidents for dev; portfolio health / risks
for exec) so the synthesized output matches the role expectations.

### Project selection UI (PM only)

`ProjectSelect.tsx` renders only when `persona.role === "product_manager"`. It is a set of
checkboxes (or chips) sourced from `SEED_PROJECTS` — a self-contained list, no dropdown library
needed. Selection state (`string[]` of keys) is owned by the **page** (`useState`) and passed down
with an `onToggle(key)` callback, so re-running the dashboard with a different selection is a plain
state update + re-query. Developer/Executive never see this control. This directly satisfies the
requirement that the PM's chosen keys flow into the prompt.

### Call shape, session id, loading, and regenerate

- **Call:** `api.post<ChatResponse>("/chat", { message: prompt, session_id: dashboardSessionId,
  project_id: null }, persona.personaId)` — identical to the chat page, with `project_id: null`
  because the thin API ignores it; the project scope lives in `message`.
- **Shared wire type (chosen resolution to Finding 3):** the `/chat` response shape is **promoted to
  a single exported type** in `frontend/src/types/index.ts` rather than duplicated. Add there:

  ```ts
  export interface Proposal {
    action: string;
    system: string;
    params: Record<string, unknown>;
    description: string;
    interrupt_id?: string;
  }

  export interface ChatResponse {
    response: string;
    proposal: Proposal | null;
    systems_queried?: string[]; // OPTIONAL: matches the chat page's shape; the thin API does not
                                // project this today (see Finding 1), so it is always undefined at
                                // runtime. Kept optional only so the shared type is one definition.
    status: string;
    session_id: string;
  }
  ```

  The chat page's existing **inline, un-exported** `ChatApiResponse` and `Proposal` are replaced by
  `import type { Proposal, ChatResponse } from "@/types"` (its page-local `Message`/`ActionResult`
  stay local — they are not wire types). The dashboard page imports the same `ChatResponse`. This is
  a genuine single-source reuse (not a hand-synced re-declaration), chosen over the "re-declare
  locally" alternative because the dashboard depends on `response`, `status`, and
  `session_id` being *exactly* the chat shape, and a second definition is a silent-drift hazard.
  (`systems_queried?` is carried for shape-parity only; it is latent — see Finding 1.) The
  churn to the chat page is limited to the two type declarations and the one generic argument at the
  `api.post` call site; no behavior changes.
- **Session id (chosen resolution to open-question #4 — OWN session):** the dashboard keeps its own
  `dashboardSessionId` state, **distinct from chat**, so dashboard synthesis does not pollute chat
  history. It starts `null`; the first `/chat` response's `session_id` (which the thin API
  normalizes to a Runtime-valid id ≥33 chars) is stored and reused on regenerate. This is the exact
  "send what you have or null, adopt what comes back" normalization behavior the chat page uses —
  just on a separate id. No client-side session-id generation.
- **Build trigger (chosen resolution to open-question #3; guard mechanism per Finding 4):** the
  dashboard **auto-builds once on first mount**, giving the user an immediate result, and exposes a
  **"Regenerate" button** to re-run on demand. The "runs exactly once" guard is concrete: a
  `const didBuild = useRef(false)` latch. The mount `useEffect` (empty dependency array) checks
  `if (didBuild.current) return;`, immediately sets `didBuild.current = true` **before** starting
  the fetch, then invokes an `async` builder handler. Setting the ref before the async call means
  React 19's development double-invoke of effects (StrictMode-style) sees the latch already set on
  the second invocation and skips the duplicate `/chat` call — so the auto-build fires once even in
  dev, and an empty dep array alone (which does **not** protect against the double-invoke) is not
  relied upon. The same `async` builder handler is what the "Regenerate" button calls directly
  (bypassing the latch, since regenerate is an explicit user action).
  For the PM, changing the project selection does **not** auto-refetch (to avoid firing a 10-40s
  call on every checkbox toggle); instead the "Regenerate" button is the explicit re-query, and the
  project-scope pill shows the pending scope. The result is **not** persisted across navigation
  (re-build on each visit) — simplest, and avoids stale cross-persona data when switching logins.
- **Loading state (open-question #7):** while a call is in flight, `DashboardView` shows the same
  animated three-dot "typing" indicator the chat page uses (`animate-bounce` dots) plus a muted
  "Synthesizing your dashboard… this can take up to a minute" caption, because the agent can take
  10-40s. The Regenerate button is disabled while loading.
- **Client timeout:** the investigation confirms there is **no existing fetch-timeout helper** in
  `services/api.ts` or the chat page — the brief's "long client timeout consistent with the chat
  page" resolves to **consistent = no artificial client-side abort**, matching chat exactly, so a
  long agent call is allowed to complete. The design does **not** introduce an `AbortController`
  timeout (that would diverge from chat and risk cutting off a legitimately slow synthesis). The
  only guard is the in-flight flag preventing concurrent calls. (Noted explicitly so the reviewer
  sees this is a deliberate match to chat, not an omission.)

### Error handling (Dashboard)

Each failure mode is concrete:

- **`/chat` returns an error** (`result.error` non-null, e.g. non-2xx or network failure): recoverable.
  The page stores the error string in `errorText` state; `DashboardView` renders a red inline banner
  (`bg-red-50 border border-red-200 text-red-700`) reading
  `"Couldn't build your dashboard: {error}"` plus the Regenerate button. No throw, no crash. Logged
  at `console.error` level (browser console only — demo posture, no telemetry backend).
- **`/chat` returns `status === "pending_approval"`** (a proposal): the dashboard prompt is a
  read-only synthesis request, so this is not expected, but if it occurs the page renders the
  `response` markdown as-is and ignores the proposal (the Dashboard has no approve/reject affordance
  by design). Non-fatal.
- **Empty `response`:** `DashboardView` applies the explicit predicate
  `!result?.response || result.response.trim().length === 0` **before** rendering the markdown card,
  and on a true result renders an empty-state note ("The agent returned no content — try
  Regenerate.") instead of feeding `<ReactMarkdown>` an empty/whitespace string (which would show a
  blank `prose` block). Non-fatal. (Findings 4 & 6.)
- **No persona** (should be impossible inside `ProtectedRoute`): the mount effect no-ops; defensive
  only.

### Dashboard visual shell (ported, non-grid parts)

From the dock dashboard page: page padding `p-8`; header `text-3xl font-bold "Dashboard"` plus a
welcome line keyed off `persona.personaLabel`; a small blue scope pill
(`text-xs font-medium text-blue-700 bg-blue-50 px-3 py-1 rounded-full border border-blue-200`)
reading one of: "All projects" (no selection) / "Project: PAY" (one) / "Aggregating N projects"
(many). Card styling `bg-white rounded-lg shadow`. The `react-grid-layout` grid and all widget
components are **not** ported.

---

## C. Connections screen (static, presentational)

### Route and data

- `frontend/src/app/(protected)/connections/page.tsx` — `"use client"` (reads `persona` for the
  header; purely presentational otherwise). **No `api.*` calls**, no project/connection CRUD, none
  of the dock's forms.
- `frontend/src/lib/connections.ts`:

```ts
export interface ServiceInfo {
  key: "jira" | "confluence" | "github" | "servicenow";
  label: string;
  icon: string;        // emoji, ported from the dock table
  description: string; // short line under the name
}

export const SERVICES: ServiceInfo[] = [
  { key: "jira",       label: "Jira",       icon: "📋", description: "Issues, sprints & boards" },
  { key: "confluence", label: "Confluence", icon: "📄", description: "Docs & knowledge base" },
  { key: "github",     label: "GitHub",     icon: "🐙", description: "Repos, PRs & commits" },
  { key: "servicenow", label: "ServiceNow", icon: "🛠️", description: "Incidents & change mgmt" },
];
```

The emoji/label set is ported from the dock's `INTEGRATION_TYPES`. The `mock-*:500x` host URLs are
deliberately dropped (demo-irrelevant and infra-leaky); descriptions replace them.

### Layout

Header block ported from the dock: `p-8`, `text-3xl font-bold "Connections"` + a subtitle. Then a
list/grid of four cards, each
`bg-white rounded-lg shadow p-5 flex items-center justify-between`:

- Left: `text-3xl` emoji icon + `font-medium` service label + `text-sm text-gray-500` description.
- Right: a green "Connected" badge —
  `inline-flex items-center gap-1.5 px-3 py-1 bg-green-50 text-green-700 border border-green-200 rounded-full text-xs font-medium`
  with a small green dot (`w-2 h-2 bg-green-500 rounded-full`) and the text "Connected".

No Test / View data / Remove buttons, no add-connection form — those were CRUD against
`/integrations` and are out of scope. Static "all four connected" only, matching the user's ask.

### Error handling (Connections)

None required — there is no I/O. The page maps over a constant. The only defensive consideration is
a stable React `key` per card (`service.key`), which the design specifies.

---

## Invariants and ownership

- **Env-driven base URL:** owned by `services/api.ts` (`API_BASE_URL` from `NEXT_PUBLIC_API_URL`).
  New code calls only through `api.*`, so no new code references the URL. Enforced at the service
  layer; no page hardcodes it.
- **Persona header on every `/chat` call:** owned by the Dashboard page, which always passes
  `persona.personaId` as the third arg to `api.post`, exactly like chat. Enforced at the call site.
- **No new backend routes:** the Dashboard uses only `/chat`; Connections does no I/O. Enforced by
  the fact that no new `api.*` endpoint strings other than `"/chat"` are introduced.
- **Dashboard session isolation:** owned by the Dashboard page's own `dashboardSessionId` state,
  kept separate from the chat page's `sessionId` (different component instances, no shared store).
- **Static-export safety:** owned by each new page being `"use client"` with all browser/network
  access inside effects/handlers, and by using only non-dynamic route folders. No
  `generateStaticParams`, no `[id]`.

---

## Validation rules for external inputs

The only runtime external input is the PM project selection (user-chosen) and the `/chat` response.

- **Project selection:** each toggled value must be a `key` from `SEED_PROJECTS`. The UI only emits
  those keys (checkboxes bound to the constant), so invalid input cannot originate from the UI. The
  prompt-builder additionally de-duplicates and preserves order; unknown keys (only possible if a
  future "type a key" affordance is added) pass through as bare uppercased tokens. No length/limit
  cap is needed for the five-item demo list.
- **`/chat` response:** treated as untrusted display data. `response` is rendered through
  `react-markdown`, which sanitizes to safe elements by default (no raw HTML unless a plugin is
  added — none is). `systems_queried` is not consumed by the dashboard (it is never emitted by the
  thin API — Finding 1 — and no chips are rendered). `status` other than
  `pending_approval`/`complete` is treated as "render the response as-is". A missing/empty
  `response` triggers the empty-state note. Behavior on failure is the inline error banner (above).

---

## Testability

### Unit tests (vitest, node env, `*.test.ts` under `src/lib/` — matching repo convention)

All new tests are **node-safe, pure-logic** `*.test.ts` files under `src/lib/`. The vitest
environment is `node` (confirmed in `frontend/vitest.config.ts`) and there is no jsdom /
`@testing-library/react` dependency, so **no React render tests are planned** (doing so would
require adding devDeps the design explicitly avoids). Component-level correctness is covered
manually in the demo run (see "integration" below). Tests never live under `src/app/` — those route
folders hold only `page.tsx` special files, keeping `next build` / lint clean. (Findings 1 & 2.)

1. **`frontend/src/lib/projects.test.ts`** — the prompt-builder and seed list:
   - `SEED_PROJECTS` contains exactly the five expected keys (`PAY, CART, AUTH, PROD, ORD`).
   - `buildDashboardPrompt({ role: "developer" })` returns the developer template and does **not**
     contain any project-key clause.
   - `buildDashboardPrompt({ role: "executive" })` returns the executive template (portfolio
     wording) and ignores `selectedProjectKeys` even if passed.
   - `buildDashboardPrompt({ role: "product_manager" })` (no keys) returns the "all projects"
     variant (asserts the "all of my projects" phrasing, asserts no `(PAY)` token).
   - `buildDashboardPrompt({ role: "product_manager", selectedProjectKeys: ["PAY","AUTH"] })`
     injects `Payment Gateway (PAY)` and `User Authentication (AUTH)` into the returned string —
     this is the explicit "PM project-selection injects keys into the prompt" test required by the
     brief.
   - De-dup / order: `["PAY","PAY","CART"]` → prompt lists PAY once, before CART.

2. **`frontend/src/lib/connections.test.ts`** — the static services constant (node-safe, no render):
   - `SERVICES.map((s) => s.key)` equals `["jira","confluence","github","servicenow"]` (order and
     membership), and `SERVICES` has length 4. This is the required "connections list renders 4
     connected services" test, expressed as a pure assertion against the single source of truth the
     Connections page maps over — so the page rendering 4 connected services is guaranteed by
     construction without a DOM. Example:
     ```ts
     import { SERVICES } from "./connections";
     it("declares exactly the four connected services", () => {
       expect(SERVICES.map((s) => s.key)).toEqual(["jira", "confluence", "github", "servicenow"]);
       expect(SERVICES).toHaveLength(4);
     });
     ```

> Test-environment note: the existing suite (`personas.test.ts`, `api.test.ts`,
> `chatSuggestions.test.ts` — 19 cases total) is logic-only and runs under vitest's `node`
> environment with `vi.fn()` fetch mocks; none render React. The two **required** new tests
> (prompt-builder, connections constant) follow that exact convention and need no DOM, so the
> offline gate never depends on a jsdom/testing-library env that the project does not have.

### What is unit vs integration

- **Unit:** prompt-builder (pure), seed/connections constants. (`DashboardView`'s presentational
  states — loading / result / error / empty — would be render tests; they are left to the manual
  demo pass rather than automated, since the repo has no React render harness and the design adds
  no jsdom dep.)
- **Integration (manual for the demo / not automated here):** the live `/chat` round-trip, session
  normalization, and long-latency behavior — these depend on the deployed thin API and are
  exercised by running the app, not by the offline gate.

### Offline gate conformance

From `frontend/`: `npm ci` → `npm run lint` → `npm test -- --run` (vitest) → `npm run build`
(static export to `frontend/out/`). The design adds only client components and pure modules with no
new deps, so lint/build stay green; the new `/dashboard` and `/connections` routes are static,
non-dynamic App-Router pages and therefore **prerender into `frontend/out/`** like `/chat` does. The
two new `src/lib/*.test.ts` files are additive, node-safe, and do not touch the existing suite
(currently 19 cases across `personas`, `api`, `chatSuggestions`), so the suite stays green.

---

## Resolution of investigation open questions

1. **Prompt wording / PM "no selection":** resolved — four exact templates above; no selection ⇒
   all projects.
2. **Rendering:** resolved — reuse the chat's `react-markdown` + `prose` styling in a dashboard-local
   full-width card (not the `ChatMessage` bubble; see Finding 3), no new parsing or deps.
3. **Build trigger / caching:** resolved — auto-build once on mount + explicit Regenerate; no
   cross-navigation persistence.
4. **Session id:** resolved — dashboard owns its own session id, separate from chat.
5. **Project multi-select placement:** resolved — Dashboard page, PM-only (option b); removed from
   the sidebar.
6. **Static data location:** resolved — `src/lib/projects.ts` (seed list + builder) and
   `src/lib/connections.ts` (services).
7. **Long-latency UX:** resolved — reuse chat typing dots + caption; no artificial client timeout
   (matches chat).
8. **Offline gate:** addressed — see "Offline gate conformance".

---

## Constraints & non-goals honored

- No new thin-API/Lambda routes; Dashboard uses `/chat`, Connections is static.
- Dropped dock contexts/hooks/services (`ProjectContext`, `ConnectionsContext`,
  `useRequiredConnections`, `/integrations`, `/proxy/*`, auth endpoints, `react-grid-layout`) are
  **replaced** by static data + `/chat`, never restored.
- Existing chat page, login, and persona auth remain functionally unchanged (only the chat page's
  outer height class adapts to the shared layout).
- Static-export-safe: all-client pages, no route handlers, no dynamic `[id]` segment reintroduced.
- Demo-simple; security out of scope.
- Only files under the workspace root are created/modified; `mahalo-dock` is untouched.

---

## Review findings — responses

### Revision 4 — responses to review `task7d-design-review.md` (revision 3)

The revision-3 review (`docs/.agents/tasks/task7d-design-review.json` / `.md`, verdict
`CHANGES_REQUESTED`: 0 HIGH + 1 MEDIUM + 3 NIT) raised four findings. All four are **addressed**;
none backlogged or ignored. Each change was checked against source
(`frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`, `frontend/src/app/login/page.tsx`,
`frontend/src/components/chat/ChatMessage.tsx`).

1. **MEDIUM — the protected layout wrapper `<div className="flex min-h-screen">` has no width
   directive, so in the body's flex *row* the `flex-1` main column collapses to content width
   instead of spanning the viewport. → Addressed.** Verified against the codebase: `frontend/src/app/layout.tsx`
   is `<body className="min-h-full flex">` (a flex row, so width is the **main** axis), and both
   existing direct-body flex children — `frontend/src/app/page.tsx` and
   `frontend/src/app/login/page.tsx` — carry `w-full` for exactly this reason. The design now sets
   the wrapper to `<div className="flex min-h-screen w-full">` (the chosen directive, matching the
   two existing body-child conventions; `flex-1` noted as the equivalent alternative). The
   "Body-level composition" paragraph was rewritten: it no longer attributes full width to
   "cross-size", and instead correctly states that a row's main axis is width, that an item with no
   grow/width sizes to content on that axis, and that `w-full` is what makes `<main className="flex-1">`
   (and the chat/dashboard/connections content inside it) fill the viewport.

2. **NIT — "the one class swap is the whole change" could mislead an implementer when the column
   collapses. → Addressed.** §A "Chat-page interaction" now adds: "The chat page needs only the
   height-class swap; its full-width rendering depends on the protected wrapper carrying
   `w-full`/`flex-1` (see §A layout markup above) — so if the chat column ever appears collapsed,
   the cause is the wrapper width, not the chat page." The "whole change" claim is now explicitly
   scoped to *within the chat page file*.

3. **NIT — reusing `ChatMessage` verbatim inherits its left-aligned `max-w-[80%]` bubble geometry,
   unacknowledged. → Addressed (option (b)).** Verified the bubble markup in
   `frontend/src/components/chat/ChatMessage.tsx`. The design now **renders the dashboard result in
   a dashboard-local full-width `prose` card instead of reusing `ChatMessage`** — copying
   `ChatMessage`'s exact `prose prose-sm max-w-none prose-headings:… prose-p:… prose-strong:… prose-li:…`
   class string (so typography still matches chat and the "reuse the chat's assistant-markdown
   rendering" requirement holds) but dropping the `flex justify-start` + `max-w-[80%]` bubble chrome
   in favour of `bg-white rounded-lg shadow p-6`. §B states this choice and its rationale (the
   headline screen should be full-width, not a cramped 80% chat bubble). All downstream references
   (locked-stack note, render-ordering, systems_queried bullet, open-question #2) were updated to
   match.

4. **NIT — the empty-response branch lacked an explicit predicate. → Addressed.** §B "Render
   ordering" and the "Empty response" error-handling bullet now state the exact predicate
   **`!result?.response || result.response.trim().length === 0`** (so a single space `" "` is
   treated as empty), and specify that the full-width `prose` markdown card is rendered only when
   that predicate is false — `<ReactMarkdown>` is never handed `""` or whitespace-only content.

### Revision 3 — responses to review `task7d-design-review.md` (revision 2), retained for history

The revision-2 review (verdict `CHANGES_REQUESTED`:
0 HIGH + 1 MEDIUM + 3 NIT) raised four findings. All four were **addressed**; none backlogged or
ignored. Each change was checked against source (`api/app/models.py`, `api/app/routers/chat.py`,
`frontend/src/components/chat/ChatMessage.tsx`, `frontend/src/app/layout.tsx`,
`frontend/src/components/chat/ProposalCard.tsx`).

1. **MEDIUM — `systems_queried` chips are a dead feature: the thin API never returns that field.
   → Addressed (option (a)).** Verified against source: `api/app/models.py` `ChatResponse` declares
   only `response`/`proposal`/`session_id`/`status`, and `api/app/routers/chat.py` builds the reply
   under `response_model=ChatResponse`, which strips extras — so `result.systems_queried` is always
   `undefined` at runtime. The design **drops every claim** that the dashboard renders
   `systems_queried` chips: §B no longer passes `systemsQueried` to `ChatMessage` (it passes only
   `content={result.response}`), and the validation section no longer says chips are rendered. The
   field is **kept as optional** in the shared `ChatResponse` type purely for shape-parity with the
   chat page, with an inline comment and a dedicated §B bullet stating the chips are latent by design
   (not a bug), and that any future "systems" chips must be derived frontend-side, not attributed to
   the `/chat` reply. The shared-type rationale no longer lists `systems_queried` as a field the
   dashboard depends on. Consistent with the existing chat page, which also carries the optional
   field harmlessly.

2. **NIT — `Proposal`/`ChatResponse` promotion leaves a third copy (`ProposalCard`) undiscussed.
   → Addressed.** A row was added to the "Modify" table stating `frontend/src/components/chat/ProposalCard.tsx`
   **keeps its local `Proposal` interface unchanged** and relies on structural compatibility with
   the promoted `@/types` `Proposal` (the chat page passes the shared-typed value in; it type-checks).
   The choice (leave as-is, do not migrate) is called out explicitly so the implementer does not
   improvise on discovering the third copy; migrating it is noted as optional out-of-scope cleanup.

3. **NIT — layout height reasoning ignores the root `<body>` already being `flex`. → Addressed.**
   §A "Hosting the sidebar" gained a "Body-level composition (Finding 3)" paragraph confirming the
   root layout is **unchanged** (`<html className="h-full">`, `<body className="min-h-full flex">`),
   that the protected `<div className="flex min-h-screen">` is the body row's single flex item and
   takes full width (no explicit width), that `<Sidebar w-64>` + `<main flex-1 h-screen overflow-y-auto>`
   fill it so the single vertical scroll lives on `<main>` (no double scrollbar / zero-height
   column), and that the `/login` route (also a body flex child, outside the group) is unaffected
   because it renders its own `min-h-screen` centered card.

4. **NIT — auto-build-once-on-mount guard mechanism left to the implementer. → Addressed.** §B
   "Build trigger" now specifies the concrete guard: a `const didBuild = useRef(false)` latch that
   the mount `useEffect` (empty dep array) checks and sets to `true` **before** starting the fetch,
   so React 19's dev double-invoke skips the duplicate `/chat` call and the auto-build fires exactly
   once; an empty dep array alone is explicitly stated as insufficient. The same `async` builder
   handler backs the "Regenerate" button (which bypasses the latch as an explicit user action).

### Revision 2 — responses to the prior review (1 HIGH + 2 MEDIUM + 3 NIT), retained for history

All six prior findings were addressed in revision 2 and remain resolved:

1. **HIGH — required Connections render test cannot run in the `node` vitest env. → Addressed.**
   Confirmed `vitest.config.ts` is `environment: "node"` with no jsdom/testing-library dep. The
   required Connections test is a **pure node-safe assertion** against the `SERVICES` constant in
   `frontend/src/lib/connections.test.ts` (asserts keys `["jira","confluence","github","servicenow"]`
   and length 4). No render tests are planned. The required named tests are `projects.test.ts` and
   `connections.test.ts`, both node-safe.

2. **MEDIUM — `.test.tsx` inside the `app/(protected)/connections/` route folder. → Addressed.**
   All new tests live under `src/lib/` (`projects.test.ts`, `connections.test.ts`); `src/app/(protected)/**`
   holds only `page.tsx` special files, so `next build` / lint stay clean.

3. **MEDIUM — "reuses that interface (declared locally in the page)" is impossible. → Addressed.**
   Shared `Proposal` and `ChatResponse` are **exported from `src/types/index.ts`** and imported in
   both the chat page (replacing the inline declarations) and the dashboard page — a genuine single
   source. (Finding 2 above documents the untouched third copy in `ProposalCard`.)

4. **NIT — "existing 12 vitest tests" is wrong (actual 19). → Addressed.** All counts read
   "currently 19 cases across `personas`, `api`, `chatSuggestions`".

5. **NIT — chat-page height fix omits the `<ContextPanel>` sibling. → Addressed.** §A states the
   root flex row contains **two** children (chat column + `<ContextPanel>`) and the only edit is the
   single root `className` swap `flex h-screen` → `flex h-full`.

6. **NIT — empty-`response` note vs. `ChatMessage` always rendering markdown. → Addressed.** §B
   states the render ordering: `DashboardView` checks `result?.response` for blank/whitespace and
   renders the empty-state note (plus error/loading branches) **before** delegating, mounting
   `<ChatMessage>` only for non-empty content — `ChatMessage` is never handed `""`.
