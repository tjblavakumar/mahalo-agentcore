# Task 7d — Implementation Plan: Sidebar + agent-driven Dashboard + Connections (frontend-only)

Derived from the APPROVED design `docs/.agents/tasks/task7d-design.md` and investigation
`docs/.agents/tasks/task7d-investigation.md`. All paths are workspace-relative to
`<WORKSPACE_ROOT>` with forward slashes. Frontend-only; reuse the
deployed thin API (`POST /chat`); add NO backend/thin-API routes. The read-only sibling
`mahalo-dock` repo must never be edited — read it for shape only.

## Mandatory reading before writing any code

- `frontend/AGENTS.md` and the Next.js guides under `frontend/node_modules/next/dist/docs/`
  (this is Next 16.3.3 with breaking changes — read the static-export + App-Router + linking guides
  BEFORE writing route/layout code). The key file is
  `frontend/node_modules/next/dist/docs/01-app/02-guides/static-exports.md`.
- The design doc (`docs/.agents/tasks/task7d-design.md`) — it holds the exact prompt templates,
  class strings, and the resolved decisions. Do not re-decide architecture; follow it.

## Ground rules (from the design, verified against source)

- Every new page and the Sidebar is a `"use client"` component; all network/browser access lives in
  effects/handlers (static-export-safe, `output: "export"`). No `generateStaticParams`, no dynamic
  `[id]` segments, no route handlers/server actions.
- Base URL stays env-driven via `NEXT_PUBLIC_API_URL`, consumed only in `frontend/src/services/api.ts`.
  No new code hardcodes a URL; all I/O goes through `api.*`, and the only endpoint string introduced
  is `"/chat"`.
- Persona header: pass `persona.personaId` as the 3rd arg to `api.post`, exactly like the chat page.
- Tests are node-safe pure-logic `*.test.ts` under `frontend/src/lib/` (vitest env is `node`; no
  jsdom/testing-library — confirmed in `frontend/vitest.config.ts`). No React render tests. Never
  place tests under `frontend/src/app/**`.
- No new npm dependencies (no `react-grid-layout`/`react-resizable`). Reuse `react-markdown ^9`.
- Keep chat/login/persona flow functionally unchanged.

## Verified build/test commands (from `frontend/package.json`)

Run all from the `frontend/` directory: `npm ci` → `npm run lint` → `npm test -- --run` (vitest;
the `test` script is `vitest run`, so `-- --run` is harmless/idempotent) → `npm run build` (Next
static export to `frontend/out/`). The existing suite is 19 cases across `personas`, `api`,
`chatSuggestions` and must stay green.

---

# Implementation Plan

- [ ] 1. Promote the shared `/chat` wire types into `frontend/src/types/index.ts`.
      Add exported `Proposal` (`action`, `system`, `params: Record<string, unknown>`, `description`,
      `interrupt_id?`) and `ChatResponse` (`response: string`, `proposal: Proposal | null`,
      `systems_queried?: string[]`, `status: string`, `session_id: string`) interfaces, matching the
      chat page's current inline shapes verbatim. Keep `systems_queried?` optional (thin API never
      projects it; carried for shape parity only — do not render it on the dashboard).
      Files: `frontend/src/types/index.ts`
      Verify: from `frontend/`, `npm run build` still typechecks (no consumers yet; this item just
      adds types). Expected: build/export succeeds.

- [ ] 2. Rewire the chat page to the shared types with no behavior change.
      In `frontend/src/app/(protected)/chat/page.tsx`: remove the page-local `Proposal` and
      `ChatApiResponse` interface declarations, add `import type { Proposal, ChatResponse } from "@/types"`,
      and change the one call site `api.post<ChatApiResponse>(...)` to `api.post<ChatResponse>(...)`.
      Leave `Message` and `ActionResult` local (they are not wire types). Do NOT touch
      `frontend/src/components/chat/ProposalCard.tsx` — its local `Proposal` stays as-is and
      type-checks structurally (design Finding 2).
      Files: `frontend/src/app/(protected)/chat/page.tsx`
      Verify: from `frontend/`, `npm run lint` and `npm test -- --run` pass; `npm run build` typechecks.
      Expected: no new errors, existing 19 tests green.

- [ ] 3. Create the static seed project list + pure dashboard prompt-builder in `frontend/src/lib/projects.ts`.
      Export `interface SeedProject { key; name }`, `const SEED_PROJECTS` with exactly the five pairs
      `PAY/Payment Gateway`, `CART/Shopping Cart`, `AUTH/User Authentication`, `PROD/Product Catalog`,
      `ORD/Order Management`, and `function buildDashboardPrompt(input: { role: UserRole;
      selectedProjectKeys?: string[] }): string` importing `UserRole` from `@/types`. Behavior per
      design §B: developer/executive return their fixed templates and ignore `selectedProjectKeys`;
      product_manager with no/empty keys returns the "all projects" variant; with keys, resolve each
      key against `SEED_PROJECTS` to `Name (KEY)` pairs (unknown keys pass through uppercased as bare
      `KEY`), de-duplicate preserving order, and interpolate into the PM template. Use the four exact
      template strings from design §B "Exact prompt templates".
      Files: `frontend/src/lib/projects.ts`
      Verify: from `frontend/`, `npm run build` typechecks. Full assertion comes with item 4.

- [ ] 4. Add unit tests for the seed list and prompt-builder in `frontend/src/lib/projects.test.ts`.
      Cover (design "Testability" §1): `SEED_PROJECTS` keys are exactly `["PAY","CART","AUTH","PROD","ORD"]`;
      developer template returned with no project clause; executive template returned and ignores
      passed `selectedProjectKeys`; PM with no keys returns the "all of my projects" variant and
      contains no `(PAY)` token; PM with `["PAY","AUTH"]` injects `Payment Gateway (PAY)` and
      `User Authentication (AUTH)`; de-dup/order `["PAY","PAY","CART"]` lists PAY once before CART.
      Follow the `node`-env, `vi`-based style of `frontend/src/lib/chatSuggestions.test.ts`.
      Files: `frontend/src/lib/projects.test.ts`
      Verify: from `frontend/`, `npm test -- --run` — new `projects` tests pass alongside the existing 19.

- [ ] 5. Create the static connections constant + its unit test.
      In `frontend/src/lib/connections.ts` export `interface ServiceInfo { key: "jira"|"confluence"|"github"|"servicenow"; label; icon; description }`
      and `const SERVICES` with exactly the four entries from design §C (Jira 📋, Confluence 📄,
      GitHub 🐙, ServiceNow 🛠️, with the given descriptions). In `frontend/src/lib/connections.test.ts`
      assert `SERVICES.map(s => s.key)` equals `["jira","confluence","github","servicenow"]` and
      `SERVICES` has length 4 (node-safe, no render).
      Files: `frontend/src/lib/connections.ts`, `frontend/src/lib/connections.test.ts`
      Verify: from `frontend/`, `npm test -- --run` — new `connections` test passes.

- [ ] 6. Create the Sidebar component `frontend/src/components/common/Sidebar.tsx`.
      `"use client"`. Port the mahalo-dock visual shape (outer
      `<aside className="w-64 bg-gray-900 text-white flex flex-col min-h-screen">`, logo block, user
      block, nav) but rewire to agentcore: use `useAuth()` → `{ persona, logout }` (not `user`/`token`),
      show `persona.displayName`, `persona.personaLabel`, and initial via
      `persona.displayName.charAt(0).toUpperCase()`; "Sign out" calls `logout()` then
      `router.push("/login")` (via `next/navigation`). Nav array is Dashboard `/dashboard` 📊, Chat
      `/chat` 💬, Connections `/connections` 🔗 as `next/link` `<Link>`s; active state via
      `usePathname()?.startsWith(item.href)` → `bg-blue-600 text-white`, inactive →
      `text-gray-300 hover:bg-gray-800 hover:text-white`. DROP the Projects block, `useProjects`,
      `useRequiredConnections`, and the Sync button entirely. Null-guard `persona` defensively.
      Files: `frontend/src/components/common/Sidebar.tsx`
      Verify: from `frontend/`, `npm run lint` passes and `npm run build` typechecks (wired in item 7).

- [ ] 7. Wire the Sidebar into the protected layout `frontend/src/app/(protected)/layout.tsx`.
      Keep `<ProtectedRoute>` as the outer gate; inside it render
      `<div className="flex min-h-screen w-full"><Sidebar /><main className="flex-1 min-w-0 h-screen overflow-y-auto">{children}</main></div>`
      (the `w-full` is required — the root `<body className="min-h-full flex">` is a flex row; see
      design §A Finding 1). Do NOT add `"use client"` to the layout. Also change ONLY the chat page
      root wrapper `className` from `flex h-screen` to `flex h-full` in
      `frontend/src/app/(protected)/chat/page.tsx` (its height now comes from the new `<main>`); make
      no other chat-page change.
      Files: `frontend/src/app/(protected)/layout.tsx`, `frontend/src/app/(protected)/chat/page.tsx`
      Verify: from `frontend/`, `npm run build` — static export succeeds and the existing `/chat`
      route still prerenders into `frontend/out/`. `npm run lint` passes.

- [ ] 8. Create the PM project multi-select `frontend/src/components/dashboard/ProjectSelect.tsx`.
      `"use client"`. Renders only for `persona.role === "product_manager"`. A self-contained set of
      checkboxes/chips sourced from `SEED_PROJECTS` (no dropdown library). Props: the current selected
      `string[]` of keys and an `onToggle(key: string)` callback (selection state is owned by the
      Dashboard page, not here). Developer/Executive never see this control.
      Files: `frontend/src/components/dashboard/ProjectSelect.tsx`
      Verify: from `frontend/`, `npm run lint` passes and `npm run build` typechecks (wired via items 9-10).

- [ ] 9. Create the presentational dashboard body `frontend/src/components/dashboard/DashboardView.tsx`.
      `"use client"`. Takes everything via props (no network): persona, result (`ChatResponse | null`),
      `isLoading`, `error`, selected keys + `onToggle`, and `onRegenerate`. Renders: the `p-8` header
      (`text-3xl font-bold "Dashboard"` + welcome line keyed off `persona.personaLabel`), the blue
      scope pill (`All projects` / `Project: PAY` / `Aggregating N projects`), `ProjectSelect` (PM
      only), a Regenerate button (disabled while loading). Branch in this exact order BEFORE rendering
      markdown: (1) red error banner when `error`; (2) chat-style three-dot `animate-bounce` loading
      indicator + "Synthesizing your dashboard… this can take up to a minute" when `isLoading`;
      (3) empty-state note "The agent returned no content — try Regenerate." when
      `!result?.response || result.response.trim().length === 0`; (4) otherwise the full-width card
      `<div className="bg-white rounded-lg shadow p-6"><div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-strong:text-gray-900 prose-li:text-gray-700"><ReactMarkdown>{result.response}</ReactMarkdown></div></div>`
      (prose class string copied verbatim from `ChatMessage`; do NOT reuse the `ChatMessage` bubble,
      do NOT render `systems_queried` chips).
      Files: `frontend/src/components/dashboard/DashboardView.tsx`
      Verify: from `frontend/`, `npm run lint` passes and `npm run build` typechecks (wired via item 10).

- [ ] 10. Create the Dashboard route `frontend/src/app/(protected)/dashboard/page.tsx`.
      `"use client"`. Owns state: `result`, `isLoading`, `errorText`, `selectedKeys: string[]`,
      `dashboardSessionId: string | null` (OWN session, separate from chat), and a
      `const didBuild = useRef(false)` latch. Builder handler: set `isLoading`, call
      `api.post<ChatResponse>("/chat", { message: buildDashboardPrompt({ role: persona.role,
      selectedProjectKeys: selectedKeys }), session_id: dashboardSessionId, project_id: null },
      persona.personaId)`; on success store `session_id` and `result`, clear error; on `result.error`
      set `errorText` ("Couldn't build your dashboard: {error}") and `console.error`; clear
      `isLoading` in a finally-equivalent. Auto-build once on mount via a `useEffect` with empty deps
      that `if (didBuild.current) return;` then sets `didBuild.current = true` BEFORE the async call
      (guards React 19 dev double-invoke). Regenerate button calls the same handler directly (bypasses
      the latch). Changing PM selection does NOT auto-refetch. No artificial client timeout (matches
      chat). Delegate presentation to `DashboardView`.
      Files: `frontend/src/app/(protected)/dashboard/page.tsx`
      Verify: from `frontend/`, `npm run build` — the `/dashboard` route prerenders into
      `frontend/out/`. `npm run lint` passes.

- [ ] 11. Create the static Connections route `frontend/src/app/(protected)/connections/page.tsx`.
      `"use client"`. Reads `persona` for the header only; NO `api.*` calls. `p-8` header
      (`text-3xl font-bold "Connections"` + subtitle). Map over `SERVICES` (from
      `frontend/src/lib/connections.ts`) into four cards
      `bg-white rounded-lg shadow p-5 flex items-center justify-between`: left = `text-3xl` emoji +
      `font-medium` label + `text-sm text-gray-500` description; right = green "Connected" badge
      (`inline-flex items-center gap-1.5 px-3 py-1 bg-green-50 text-green-700 border border-green-200 rounded-full text-xs font-medium`
      with a `w-2 h-2 bg-green-500 rounded-full` dot). Use `service.key` as the React key. No
      Test/View/Remove buttons, no forms.
      Files: `frontend/src/app/(protected)/connections/page.tsx`
      Verify: from `frontend/`, `npm run build` — the `/connections` route prerenders into
      `frontend/out/`. `npm run lint` passes.

- [ ] 12. Run the full offline gate and confirm the new routes are prerendered.
      From `frontend/`, run in order: `npm ci`, then `npm run lint`, then `npm test -- --run`, then
      `npm run build`. If any step fails, fix the cause and re-run the gate from the failed step.
      Files: none (verification only; may touch files from items 1-11 if fixes are needed)
      Verify: all four commands exit 0; vitest shows the existing 19 cases plus the new `projects` and
      `connections` cases all passing; `npm run build` reports a successful static export and
      `frontend/out/dashboard/index.html` and `frontend/out/connections/index.html` exist (new routes
      prerendered), alongside the existing `frontend/out/chat` output. Chat/login still build and
      behave unchanged.

---

## Verification notes (offline gate — iteration 1)

Run from `frontend/` on Windows PowerShell, Node v24.13.0 / npm 11.6.2, with **no `MAHALO_*`
env vars set** (verified `Get-ChildItem Env: | Where Name -like 'MAHALO*'` returned nothing).

| Command | Result |
|---|---|
| `npm ci` | PASS (EXIT 0). Note: on this machine the install is very slow (on-access AV scanning of `node_modules` on D:); it was run to completion in the background after two foreground timeouts. All bins present afterwards: `next`, `vitest`, `eslint`, `react-markdown`. |
| `npm run lint` (`eslint`) | PASS (EXIT 0), no warnings/errors. |
| `npm test -- --run` (`vitest run`) | PASS (EXIT 0). **29 tests passed** across 5 files: existing `chatSuggestions` (10), `api` (4), `personas` (5) = 19; new `projects` (8) + `connections` (2) = 10. (The "CJS build of Vite's Node API is deprecated" line is a pre-existing Vite notice, not a failure.) |
| `npm run build` (`next build`, `output: "export"`) | PASS (EXIT 0). Compiled + TypeScript OK; static pages generated (8/8). Route table lists `/`, `/_not-found`, `/chat`, `/connections`, `/dashboard`, `/login` all as `○ (Static) prerendered`. |

**New routes prerendered into the export (`frontend/out/`):** with the repo's default
`trailingSlash: false`, Next emits flat `.html` files (not `<route>/index.html`). Confirmed present:
`out/dashboard.html` and `out/connections.html`, alongside the existing `out/chat.html`,
`out/login.html`, `out/index.html`, `out/404.html`, `out/_not-found.html`. So the new `/dashboard`
and `/connections` routes are in the static export.

Chat/login/persona auth: unchanged behavior — the only chat-page edits were the two type-import
swaps and the single `flex h-screen` → `flex h-full` wrapper class. Build + lint + existing tests
confirm no regression.

No `git commit`/`push` performed (per instructions). Temporary install log files created while
working around the slow-install timeout were removed.

## Notes / assumptions

- Decomposition decision: this task is NOT split into FEAT artifacts. The three features share one
  worktree, one build gate, and interdependent files (`types/index.ts`, the protected `layout.tsx`,
  the chat page). They are small and execute sequentially regardless, so a single ordered plan run by
  the existing build-loop is the right granularity (design + guideline favor fewer, larger units).
- Ordering rationale: shared types first (1-2) so dashboard/chat consume one definition; pure
  logic + tests (3-5) before the UI that uses them; Sidebar + layout (6-7) before the pages so routes
  render inside the shell; dashboard pieces (8-10) then connections (11); the offline gate last (12).
  Each item leaves the tree buildable.
- `mahalo-dock` is read-only reference; never edit it. Only files under the workspace root are
  created/modified.
