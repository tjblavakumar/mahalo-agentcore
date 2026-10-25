# Task 7d — Design Review (revision 4 of the design)

Reviewer: design-review subagent. Reviewed fresh, without the context that produced the design.
Design under review: `docs/.agents/tasks/task7d-design.md`. Context consulted:
`docs/.agents/tasks/task7d-investigation.md`. All claims about source were re-verified against the
actual files in the workspace (listed in "Verified Assumptions" below). No code was written and
nothing was committed.

**Verdict: APPROVED** — 0 HIGH, 0 MEDIUM, 3 NIT.

The design is concrete and buildable. It respects every constraint the brief enumerated: it is
static-export-safe, reuses `/chat` only (no new backend routes), injects PM project keys into the
prompt (not `project_id`), wires the sidebar into the protected layout without breaking chat,
keeps Connections purely static, replaces the dropped dock data sources with static data + `/chat`,
and gives the offline gate a credible path with two named node-safe tests. The three NITs are
polish items that do not block implementation.

---

## Findings

### 1. NIT — `UserRole` is imported for `buildDashboardPrompt` but the design never states where the dashboard page derives it from, and `personas.Persona.role` is already `UserRole`

Where: §B "Prompt-builder" (`DashboardPromptInput.role: UserRole`) and §B "Project selection UI".

The prompt-builder signature takes `role: UserRole`. The design shows `ProjectSelect` gating on
`persona.role === "product_manager"`, which confirms `persona.role` is the source — and I verified
`frontend/src/lib/personas.ts` declares `role: UserRole` on `Persona`, so the type already lines up
with `@/types` `UserRole`. This is correct, but the design never spells out the one-line binding
("the page passes `persona.role` as `buildDashboardPrompt({ role: persona.role, selectedProjectKeys })`").
An implementer will infer it, but stating it removes the last gap between "persona" and "prompt".

Concrete fix: in §B "Call shape", add one sentence: "The page computes the prompt as
`buildDashboardPrompt({ role: persona.role, selectedProjectKeys: selected })` where `persona.role`
is the `UserRole` from `personas.ts` and `selected` is the PM checkbox state (empty for
dev/exec)."

### 2. NIT — the executive/developer "ignore selectedProjectKeys" rule is asserted but the PM-only UI already guarantees the array is empty for them; the test for "executive ignores keys even if passed" is good, but the design should note the page never passes keys for non-PM

Where: §B "Prompt-builder" behavior bullets + Testability test list (executive "ignores
`selectedProjectKeys` even if passed").

The builder defensively ignores `selectedProjectKeys` for dev/exec, and there is a unit test for
that — good, that is the right place for the guard. But §B "Project selection UI" says
Developer/Executive never see the control and selection state is owned by the page. It is worth
one explicit sentence that the page passes `selectedProjectKeys: undefined` (or `[]`) for non-PM
personas, so the defensive builder branch and the UI invariant are documented as consistent rather
than leaving a reader to wonder whether a stale PM selection could leak across a persona switch
(the "result is not persisted across navigation / re-build on each visit" rule already covers the
switch, but the selection-state ownership on persona change is not spelled out).

Concrete fix: in §B "Project selection UI", add: "Selection state resets when the persona changes
(the page keys its `useState` default to `[]`); for Developer/Executive the page passes no keys to
`buildDashboardPrompt`, so the builder's ignore-keys branch is belt-and-braces."

### 3. NIT — `ServiceInfo` adds a `description` field that mahalo-dock's table did not have, and the connections test asserts only `key`, not `description`

Where: §C `connections.ts` (`description` field) and Testability test 2.

The design replaces the dock's `mock-*:500x` host URLs with new `description` strings
(e.g. "Issues, sprints & boards"). This is a reasonable, infra-safe substitution and is within
scope. The connections test asserts `SERVICES.map(s => s.key)` and length 4, which locks the
membership that the "4 connected services" requirement needs. Minor: the `description` strings are
free-form new content not traceable to any source, so there is nothing to verify them against —
fine for a demo, but the test does not pin them, meaning a typo in a description would ship
silently. Not worth a render test; just note it.

Concrete fix: optionally extend the `connections.test.ts` assertion to check each service also has
a non-empty `label` and `description` (`SERVICES.forEach(s => { expect(s.label).toBeTruthy();
expect(s.description).toBeTruthy(); })`), so the static content is minimally guarded without a DOM.

---

## Verified Assumptions

Each design claim below was checked against the actual source file and found correct.

1. **`frontend/src/app/(protected)/layout.tsx` currently returns only
   `<ProtectedRoute>{children}</ProtectedRoute>`.** Verified — the file is exactly that. The design's
   modification (flex row with `<Sidebar />` + `<main>`) is a clean superset.
2. **Root layout is `<html className="h-full antialiased">` + `<body className="min-h-full flex">`
   wrapping `<AuthProvider>`.** Verified in `frontend/src/app/layout.tsx`. The design's revision-4
   claim that the body is a flex **row** (so width is the main axis and an item without
   grow/width sizes to content) is correct, and its stated remedy (`w-full` on the protected
   wrapper) is the right fix.
3. **Both existing direct-body flex children carry `w-full`.** Verified:
   `frontend/src/app/page.tsx` and `frontend/src/app/login/page.tsx` are each
   `<div className="min-h-screen flex items-center justify-center bg-gray-50 w-full">`. The design
   cites these as precedent for adding `w-full` to the protected wrapper — accurate.
4. **The chat page root is `<div className="flex h-screen">` with two children (chat column +
   `<ContextPanel>`).** Verified in `frontend/src/app/(protected)/chat/page.tsx`. The single
   class swap to `flex h-full` is the correct minimal edit, and the inner
   `flex-1 overflow-y-auto` message scroll area is present as described.
5. **`ChatMessage` renders the assistant branch as a left-aligned `max-w-[80%]` bubble with the
   exact `prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700
   prose-strong:text-gray-900 prose-li:text-gray-700` class string.** Verified in
   `frontend/src/components/chat/ChatMessage.tsx`. The design's decision to copy only that `prose`
   string into a full-width dashboard card (dropping `flex justify-start` + `max-w-[80%]`) is
   faithful to the source and correctly motivated.
6. **The thin API `ChatResponse` declares only `response` / `proposal` / `session_id` / `status`
   — no `systems_queried`.** Verified in `api/app/models.py`. And `api/app/routers/chat.py`
   builds the reply under `@router.post("", response_model=ChatResponse)`, so FastAPI strips any
   extra key. Finding-1's premise ("`systems_queried` is always `undefined` at runtime, chips are
   latent by design") is correct. I also confirmed the current chat page still reads
   `result.data.systems_queried` and passes `systemsQueried` to `ChatMessage` — harmless and
   undefined-safe, exactly as the design states.
7. **`project_id` is accepted but unused.** Verified in `api/app/models.py` (`project_id:
   Optional[int] = None`, commented "Accepted for frontend compatibility; currently unused"). The
   design's rule to inject PM project keys into `message`, never `project_id`, is correct and the
   dashboard call sends `project_id: null`.
8. **Session-id normalization lives server-side with a ≥33 floor.** Verified in
   `api/app/routers/chat.py` (`_MIN_RUNTIME_SESSION_LEN = 33`, `_runtime_session_id`, echoes the id
   back). The design's "send what you have or null, adopt what comes back; no client-side id
   generation" matches the chat page and the server contract.
9. **`vitest.config.ts` sets `environment: "node"` and `include: src/**/*.{test,spec}.{ts,tsx}`;
   no jsdom / testing-library dependency.** Verified. So the design's insistence on node-safe
   pure-logic `*.test.ts` under `src/lib/` (no render tests) is required, not merely preferred, and
   its two named tests (`projects.test.ts`, `connections.test.ts`) run under the existing env.
10. **`ProposalCard.tsx` declares its own local `Proposal` interface
    (`action/system/params/description/interrupt_id?`).** Verified — structurally identical to the
    `Proposal` the design promotes to `@/types`. The design's choice to leave `ProposalCard`
    untouched (structural compatibility) is sound; the chat page passes the shared-typed value in
    and it type-checks.
11. **`frontend/src/types/index.ts` today exports `UserRole` and `Project` but NOT `Proposal` /
    `ChatResponse`.** Verified. The design's plan to add exported `Proposal` and `ChatResponse`
    and replace the chat page's inline `ChatApiResponse` / `Proposal` is a genuine single-source
    change, not a re-declaration. `UserRole` is already `"product_manager" | "developer" |
    "executive"`, matching the prompt-builder's role domain.
12. **`src/lib/chatSuggestions.ts` `ROLE_TEMPLATES` tone.** Verified — PM templates reference
    sprint status / velocity / blockers; developer references PRs / assigned issues / incidents;
    executive references risks / portfolio status. The design's four prompt templates echo this
    tone, as claimed.
13. **`personas.ts` `Persona.role` is typed `UserRole` with the three personas mapping to
    `product_manager` / `developer` / `executive`.** Verified. `ProjectSelect` gating on
    `persona.role === "product_manager"` is valid.
14. **`api.ts` is env-driven via `NEXT_PUBLIC_API_URL`, sets `X-Mahalo-Persona` when a
    `personaId` is passed, and exposes `api.post<T>(endpoint, body, personaId)`.** Verified. The
    dashboard call shape `api.post<ChatResponse>("/chat", {...}, persona.personaId)` is exactly the
    supported signature.
15. **Login / AuthContext / persona flow unchanged by the design.** Verified against
    `frontend/src/app/login/page.tsx` (quick-login, `router.push("/chat")`) and the "Modify" table,
    which lists only `layout.tsx`, `types/index.ts`, and the two-line chat-page change. Nothing in
    the design touches login, AuthContext, ProtectedRoute, personas, or `api.ts`.

## Unverified / Wrong Assumptions

None. Every source-dependent claim in the design was verifiable against the workspace files and
was found accurate. The design explicitly limits reads of the `mahalo-dock` sibling repo to
component shape and never edits it; that constraint is restated in "Constraints & non-goals
honored" and is consistent with the file list (all created/modified paths are under
`frontend/src/` in this workspace).

---

## Checklist against the review brief

1. **Static-export / Next 16 conventions** — PASS. All new pages + sidebar are `"use client"`;
   routes slot into `src/app/(protected)/<name>/page.tsx` with no dynamic `[id]`, no
   `generateStaticParams`, no route handlers, no server actions, no SSR-only APIs. No new deps
   (no `react-grid-layout`). Base URL stays env-driven.
2. **Dashboard reuses `/chat` only, persona prompt-builder, PM multi-select → prompt** — PASS.
   `buildDashboardPrompt` is pure and PM-scoped; keys interpolated into `message`; `project_id:
   null`. No new backend route (only `"/chat"` endpoint string introduced).
3. **Sidebar wired into `(protected)/layout.tsx` without breaking chat** — PASS. Flex row with
   `w-full` wrapper; chat page changes by a single height class; ContextPanel accounted for.
4. **Connections purely static / presentational** — PASS. No `api.*`, maps over a `SERVICES`
   constant, green "Connected" badges only.
5. **Data-source rewirings for dropped backend routes** — PASS. Static `SEED_PROJECTS`,
   `SERVICES`, AuthContext `persona` (no `user`/`token`), `/chat` replacing widget proxy routes;
   `ProjectContext` / `ConnectionsContext` / `useRequiredConnections` all replaced by static data.
6. **Offline gate (lint, vitest, static build with `/dashboard` + `/connections` prerendered) and
   named unit tests** — PASS. `projects.test.ts` (prompt-builder incl. the required "PM keys inject
   into prompt" case) and `connections.test.ts` (four connected services) are node-safe and named;
   routes are static and prerender into `out/`.
7. **Chat/login/persona flow unchanged; mahalo-dock never touched** — PASS. Only the two-line
   chat-page edit; mahalo-dock read-only.
