# Sidebar + agent-driven Dashboard + Connections (frontend-only)

Restores three UI features the Task 7 port dropped: a persistent left-nav Sidebar wired into the protected layout, an agent-driven Dashboard that synthesizes a cross-service view by calling the already-deployed `POST /chat` with a persona-tailored prompt, and a static presentational Connections screen. The change is frontend-only — no new backend/thin-API routes, `mahalo-dock` untouched — and stays static-export-safe (`output: "export"`). The Dashboard reuses chat's `react-markdown`/`prose` rendering, carries its own session id distinct from chat, and lets the PM pick seed projects whose keys are interpolated into the prompt. Watch for: the `package-lock.json` churn (341 deletions) is pure removal of unused `@aws-sdk/*` transitive deps, not a new dependency (confirmed); and the Dashboard's "long client timeout" requirement resolves to deliberately matching chat's no-abort behavior rather than adding an explicit timeout (confirmed, intentional per design).

**Verdict**: APPROVED

## High-level view

The Sidebar is a client component hosted inside `(protected)/layout.tsx` as the left column of a flex row, with `<ProtectedRoute>` kept as the outer gate. It reads `persona` for the avatar/name/label, links Dashboard/Chat/Connections with `usePathname`-driven active state, and its Sign out calls `logout()` then routes to `/login`. The chat page keeps working via a single class swap (`h-screen` → `h-full`) so its height now comes from the new scrollable `<main>`.

The Dashboard owns all state and the `/chat` call, delegating presentation to `DashboardView`. It auto-builds once on mount behind a `useRef` latch (guards React 19 dev double-invoke), exposes Regenerate to re-run on demand, and keeps a `dashboardSessionId` separate from chat. The prompt comes from a pure `buildDashboardPrompt` in `lib/projects.ts`; the PM multi-select interpolates chosen keys as `Name (KEY)` clauses, and re-querying (Regenerate) re-runs with the current selection. Markdown renders in a full-width `prose` card copied verbatim from chat's assistant styling.

Connections is purely presentational — it maps the static `SERVICES` constant into four cards with green "Connected" badges and makes no `api.*` calls.

The whole change respects the static-export constraints: every new page and component is `"use client"`, there are no route handlers / server actions / `generateStaticParams`, and the base URL stays env-driven through `services/api.ts`. The existing chat/login/persona flow is unchanged apart from the two type-import swaps and the one class swap. The coder's recorded offline gate is green: lint clean, 29 vitest cases pass (19 existing + 8 `projects` + 2 `connections`), and the static build prerenders `/dashboard` and `/connections`.

<details>
<summary>Issues (0)</summary>

No blocking or non-blocking action items. Two informational notes are covered in the summary and details (lockfile dep removals; intentional no-timeout match to chat).

</details>

<details>
<summary>Details</summary>

### Sidebar wired into the protected layout without breaking chat

`layout.tsx` keeps `<ProtectedRoute>` as the outer gate and renders `<div className="flex min-h-screen w-full"><Sidebar /><main className="flex-1 min-w-0 h-screen overflow-y-auto">{children}</main></div>`. The `w-full` matters: the root `<body>` is a flex row, so without an explicit width directive the wrapper would size to content rather than span the viewport — the design traced this against the two existing body-child conventions (`app/page.tsx`, `login/page.tsx`) and the implementation follows it. The layout stays a Server Component (it only imports a client `Sidebar`), which is correct.

The chat page's lone edit is the root wrapper class `flex h-screen` → `flex h-full`, so its height now flows from the new `<main>` instead of nesting a second `h-screen`. Both chat children (the chat column and `<ContextPanel>`) are untouched and the inner `flex-1 overflow-y-auto` message scroll is preserved — the single vertical scrollbar lives on `<main>`. The chat page keeps its own in-page Logout, harmlessly redundant with the sidebar's Sign out since both call the same `logout()`.

The Sidebar reads `useAuth()` → `{ persona, logout }`, shows `persona.displayName`, `persona.personaLabel`, and the initial via `displayName.charAt(0).toUpperCase()`, and null-guards `persona` with a "Not signed in" fallback (defensive only, since `ProtectedRoute` blocks render without a persona). Sign out calls `logout()` (clears sessionStorage + AuthContext state) then `router.push("/login")` — the full logout contract. Active state is `pathname?.startsWith(item.href) ?? false`, so a null first-render pathname resolves to inactive and deep links highlight correctly. The dropped mahalo-dock coupling (`useProjects`, `useRequiredConnections`, Sync button, Projects block) is gone as the design required.

### Dashboard calls the existing /chat with a pure persona prompt

`dashboard/page.tsx` calls `api.post<ChatResponse>("/chat", { message: buildDashboardPrompt(...), session_id: dashboardSessionId, project_id: null }, persona.personaId)` — the same endpoint, same `X-Mahalo-Persona` header mechanism, same `project_id: null` the chat page uses. No new route string beyond `/chat`, no new backend. The response is consumed via the `ApiResponse` `{ data, error }` shape that `services/api.ts` actually returns, and `result.data.session_id` / `result.error` are handled correctly.

The prompt builder in `lib/projects.ts` is pure and side-effect free: developer and executive return fixed templates and ignore `selectedProjectKeys`; PM with no/empty keys returns the "all projects" variant; PM with keys resolves each against `SEED_PROJECTS` to `Name (KEY)` clauses, de-duplicates preserving order, uppercases and passes unknown keys through as bare tokens. The PM multi-select (`ProjectSelect`, rendered only for `role === "product_manager"`) owns no state itself — selection lives on the page and flows back through `onToggle` — so Regenerate re-runs with the current selection, which is exactly the "re-querying re-runs" requirement. Changing selection does not auto-refetch, matching the design's choice to avoid firing a 10-40s call per checkbox toggle.

The auto-build latch:

```tsx
useEffect(() => {
  if (didBuild.current) return;
  didBuild.current = true;
  void build();
}, []);
```

Setting the ref before the async call means React 19's dev double-invoke sees the latch already set and skips the duplicate `/chat` call. Regenerate calls `build()` directly, bypassing the latch. The session id starts `null` and adopts whatever the thin API returns (normalized to a Runtime-valid id), kept in `dashboardSessionId` state separate from chat's `sessionId` — synthesis never pollutes chat history.

On the "long client timeout" requirement: there is deliberately no `AbortController`. The design resolved "consistent with the chat page" to mean matching chat's no-artificial-abort behavior so a legitimately slow synthesis isn't cut off, with the in-flight `isLoading` flag as the only guard against concurrent calls. This is an intentional match, not an omission.

### Dashboard rendering and failure modes

`DashboardView` branches before handing anything to `<ReactMarkdown>`, in order: error banner (`bg-red-50 …` reading `Couldn't build your dashboard: {error}`), then the three-dot `animate-bounce` loading indicator with "Synthesizing your dashboard… this can take up to a minute", then an empty-state note gated on the explicit predicate `!result?.response || result.response.trim().length === 0` (so whitespace-only counts as empty), then the full-width markdown card. The `prose prose-sm max-w-none prose-headings:… prose-p:… prose-strong:… prose-li:…` class string is copied verbatim from chat's `ChatMessage`, so typography matches chat while the dashboard gets full-width presentation instead of the 80% chat bubble. `<ReactMarkdown>` is never handed an empty or whitespace string. The Regenerate button is disabled while loading. `systems_queried` is carried as optional on the shared type only for shape parity (the thin API strips it) and is correctly not rendered.

### Shared /chat wire type promoted to @/types

`Proposal` and `ChatResponse` move into `frontend/src/types/index.ts` as exported interfaces, and the chat page drops its inline `Proposal`/`ChatApiResponse` declarations in favor of `import type { Proposal, ChatResponse }`, switching the one `api.post<…>` call site to `ChatResponse`. The chat page's `Message` interface still references `Proposal`, now resolved from the import — no behavior change, single source of truth for both pages. `ProposalCard`'s local `Proposal` is deliberately left as-is (structurally compatible), keeping the chat-page edit minimal.

### Static-export safety

Every new page and component is `"use client"`; a repo-wide search finds no route handlers (`route.ts`), server actions (`use server`), `generateStaticParams`, or `getServerSideProps` anywhere under `frontend/src`. `next.config.ts` keeps `output: "export"` and `images.unoptimized`. The base URL is read only in `services/api.ts` from `process.env.NEXT_PUBLIC_API_URL` with a placeholder fallback — no new code hardcodes a URL. The coder's recorded build prerenders `/dashboard` and `/connections` (emitted as flat `out/dashboard.html` / `out/connections.html` because `trailingSlash` defaults to false), alongside the existing `/chat`, `/login`, `/` routes.

### Connections is static and presentational

`connections/page.tsx` reads `persona` for the header subtitle only and makes no `api.*` calls. It maps the `SERVICES` constant (Jira/Confluence/GitHub/ServiceNow, keyed in that order) into cards with a green `Connected` badge and status dot, using `service.key` as the React key. No Test/View/Remove affordances, no forms. The `connections.test.ts` asserts the four keys in order and length 4.

### Offline gate evidence

The plan's verification notes record the gate run from `frontend/` on Node 24.13.0 / npm 11.6.2 with no `MAHALO_*` env vars: `npm ci` PASS, `npm run lint` PASS (no warnings), `npm test -- --run` PASS with 29 tests across 5 files (existing `chatSuggestions` 10 + `api` 4 + `personas` 5 = 19; new `projects` 8 + `connections` 2 = 10), and `npm run build` PASS with 8/8 static pages and `/dashboard` + `/connections` listed as prerendered. The named unit tests exist and match the plan: `projects.test.ts` covers key list, developer/executive templates, PM all-projects vs injected keys, de-dup/order, and unknown-key pass-through; `connections.test.ts` covers the four-service list. No existing test was modified. Per instructions the suites were not re-run; the recorded evidence is present and internally consistent with the source read here.

### package-lock.json churn (informational)

The 341-line deletion in `frontend/package-lock.json` is entirely removals — 25 `node_modules/@aws-sdk/*` and smithy entries dropped, zero additions, and `package.json` itself is unchanged. This is the lockfile regenerating to shed AWS SDK transitive deps no longer referenced after the Task 7c shift to the AuthType=NONE plain-`fetch` client. Not a new dependency and not a concern; noted only because the `--stat` line count looks large.

</details>

<details>
<summary>File map</summary>

- `frontend/src/types/index.ts` — add exported `Proposal` + `ChatResponse` wire types.
- `frontend/src/app/(protected)/chat/page.tsx` — import shared types; `h-screen` → `h-full` wrapper.
- `frontend/src/app/(protected)/layout.tsx` — host `<Sidebar>` + scrollable `<main>` inside `<ProtectedRoute>`.
- `frontend/src/components/common/Sidebar.tsx` — new left-nav (persona block, nav links, Sign out).
- `frontend/src/lib/projects.ts` — `SEED_PROJECTS` + pure `buildDashboardPrompt`.
- `frontend/src/lib/projects.test.ts` — prompt-builder + PM key-injection tests.
- `frontend/src/lib/connections.ts` — static `SERVICES` constant.
- `frontend/src/lib/connections.test.ts` — connections list test.
- `frontend/src/components/dashboard/DashboardView.tsx` — presentational dashboard body.
- `frontend/src/components/dashboard/ProjectSelect.tsx` — PM-only project multi-select.
- `frontend/src/app/(protected)/dashboard/page.tsx` — dashboard route (state + `/chat` call).
- `frontend/src/app/(protected)/connections/page.tsx` — static connections route.
- `frontend/package-lock.json` — removal of unused `@aws-sdk/*` transitive deps (no additions).

Full diff: `git diff main` plus the untracked files listed above.

</details>
