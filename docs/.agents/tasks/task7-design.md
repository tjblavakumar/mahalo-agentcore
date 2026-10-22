# Task 7 — Design: Gitea backend + Next.js frontend hosting

**Status.** Revision pass (iteration 6). The latest review
`docs/.agents/tasks/task7-design-review.json` is present (verdict CHANGES_REQUESTED,
0 HIGH / 1 MEDIUM / 3 NIT); the review doc is `docs/.agents/tasks/task7-design-review.md`.
Its MEDIUM finding (the `buildSuggestions` arguments + empty-state UI after the three
contexts are dropped) is addressed in place below (§A.3 edit 3, §A.1/§A.2) and the three
NITs (SigV4 body signing §B.3, the root `page.tsx` export-safe redirect §A.3, citation
drift) are addressed in place; all four are itemized in the **Responses to design review
(iteration 6)** section at the end. The findings from the prior (iteration-2,
iteration-3, iteration-4, iteration-5) reviews remain resolved and are retained in their
respective **Responses to design review** sections for history.
Scope per `docs/PLAN.md`
Task 7: "Stand up self-hosted Gitea on an always-on host and deploy the Next.js
frontend." Grounded in `docs/.agents/tasks/task7-investigation.md` and re-reads of
`api/app/`, `agent/runtime_app.py`, `tools-lambdas/github/`, `infra-cdk/`, and the
read-only `mahalo-dock/frontend` + `mahalo-dock/mock-services`.

**Technology stack (LOCKED on approval).** Frontend: Next.js 16.3.3 / React 19 /
TypeScript 5 / Tailwind 4 / Vitest 2, package manager **npm** (`package-lock.json`).
Gitea: official `gitea/gitea:1.27.3` container (the mahalo-dock-proven pin,
`docker-compose.yml:146-185`; used verbatim everywhere in this document) on
**EC2 + EBS**, SQLite storage. GitHub Lambda
Gitea adapter: Python 3.13 + `httpx` (ported from `mahalo-dock/mock-services/github/
gitea_backend.py`). Secrets: AWS SSM Parameter Store (SecureString). IaC:
`aws-cdk-lib >=2.251,<3` (Python), matching `infra-cdk/requirements.txt`. Frontend
hosting: **S3 + CloudFront** serving a Next.js static export.

**House rules honored.** Deploy is DEFERRED to the operator; the automated gate is
OFFLINE only (`npm ci/lint/test/build` for the frontend; `cdk synth --all` + pytest
for infra). No commits/pushes, no `npm run dev`/watch, no deploys. All new write
targets are UNDER `mahalo-agentcore`; `mahalo-dock` is read-only. Frontend lands in
`frontend/`, Gitea assets in `gitea/`. The github-Lambda change keeps the 94
tools-lambda tests green and the mock path the default. Zero LangChain (frontend is
TS/Next). `cdk synth --all` stays Docker-free and cred-free via the existing
`-c buildImage=1` / `MAHALO_BUILD_IMAGE=1` flag gate and CfnParameter image URIs,
exactly as `runtime_stack.py:56-80` and `api_stack.py:47-73` already do. The ONE edit
Task 7 makes to an existing stack is adding a `FunctionUrlCorsOptions` block to
`MahaloApiStack`'s existing `add_function_url(auth_type=AWS_IAM)` call (§B.4); the auth
type is unchanged and no new template is added by it.

---

## Overview

Task 7 produces three deliverables, each additive and offline-gated:

1. **A ported, retargeted Next.js chat frontend** under `frontend/`, trimmed to the
   chat surface the Task-6 thin API actually serves (`POST /chat`, `POST /chat/approve`,
   `GET /healthz`), with the HITL UX rewired to the two-call protocol and the auth
   model swapped from JWT-bearer to the project's AWS_IAM/SigV4-now posture.
2. **A Gitea-backed path for the github Lambda**, ported from mahalo-dock's
   `GiteaBackend`, gated behind the existing `GITHUB_MODE` env (mock stays default),
   plus the CDK + EC2 host + bootstrap that makes Gitea "always-on" and reachable.
3. **CDK stacks** for Gitea hosting and frontend hosting, wired into
   `infra-cdk/app.py` by direct construct reference (the house pattern), synthing
   offline with no Docker build and no AWS calls.

The through-line decision is to mirror what the codebase already proved works rather
than invent: AWS_IAM/SigV4 at the edge with a thin server-side signer (as Tasks 4/6
did), `GITHUB_MODE`-selected backends (as mahalo-dock's `main.py:36-52` did),
EC2+Docker for Gitea (as mahalo-dock's compose did), and flag-gated image assets for
offline synth (as Tasks 5/6 did).

---

## A. Frontend port scope

### A.1 Decision: port the chat surface only; drop everything coupled to the old backend

The Task-6 thin API exposes exactly three routes (`api/app/main.py`, routers
`chat.py` + a health route): `POST /chat`, `POST /chat/approve`, `GET /healthz`.
Every other route the mahalo-dock frontend calls — `/auth/*`, `/integrations`,
projects, dashboard widgets, `/chat/suggestions` — has **no backend** in the target
(investigation §1.2). Stubbing those backends would mean building new Lambda surface
that Task 7 does not call for and that nothing downstream consumes. The smaller,
coherent choice is to port **only the chat experience** and drop the rest. This
preserves the chat UI/UX verbatim (the part the user validates end-to-end) while
removing dead dependencies.

**Scope of "verbatim" for the empty state (precise, resolves review Finding 1).** The
chat *conversation* surface (message list, `ChatMessage`, `ProposalCard`, `ChatInput`,
the typing indicator, the header title/subtitle) is preserved pixel-for-pixel. The parts
of the empty state that are *gated on dropped contexts* necessarily change, because the
gates themselves are removed — "verbatim" cannot mean preserving a code path that reads a
context that no longer exists. Concretely (full spec in §A.3 edit 3): the `!isConfigured`
"Connections Required" block is deleted (there is no `useRequiredConnections` and no
Connections page to link to), the `isConfigured` "How can I help you today?" starter
block becomes **unconditional**, the header scope chip (gated on `isConfigured`, reading
`scopedProject`/`selectedProjects`) is removed leaving only the "AI Assistant"
title/subtitle, and the "✨ Generate more" button is removed (its `/chat/suggestions`
route does not exist). The starter prompts themselves still render from the SAME
`buildSuggestions` template logic (ported verbatim, §A.2), fed fixed demo arguments
(§A.3 edit 3) rather than live context — so the empty state is visually the "How can I
help you today?" prompt grid the user validates, minus the connection gate and the
Generate-more affordance. This is the exact, intended empty state, not an
implementer-invented one.

### A.2 Files that port VERBATIM (copied unchanged from `mahalo-dock/frontend`)

- `src/components/chat/ProposalCard.tsx` — its `Proposal` and `result`
  (`{success, message}`) shapes already match the thin API's `proposal` dict and
  `ActionResult` minus `session_id` (verified against `ProposalCard.tsx:3-16` and
  `api/app/models.py:52-57`). One additive field only (see A.4); rendering is untouched.
- `src/components/chat/ChatInput.tsx`, `src/components/chat/ChatMessage.tsx`,
  `src/components/chat/ContextPanel.tsx` — presentational, backend-agnostic.
- `src/lib/chatSuggestions.ts` + `src/lib/chatSuggestions.test.ts` — pure template
  logic; the one existing vitest test ports as-is.
- Tooling/config: `package.json`, `package-lock.json`, `vitest.config.ts`,
  `tsconfig.json`, `postcss.config.mjs`, `eslint.config.mjs`, `src/app/globals.css`,
  `src/app/favicon.ico`, `frontend/AGENTS.md` (copy as-is; it is only rewritten by
  `next dev`, which we never run). `globals.css` today is `@import "tailwindcss";` only
  (verified) — it does NOT reference the `--font-geist-*` variables, which is what makes
  the font change in A.3 a visual no-op; it gains one small `@theme` font-stack block
  per A.3 edit, so it is "ported with a one-block addition," not strictly byte-verbatim.
- `src/types/index.ts` **ports WITH A TRIM** — it is NOT dropped (resolves iteration-2
  review Finding 1, correcting the prior revision's wrong claim). The chat page's own
  types (`Message`, `Proposal`, `ChatApiResponse`, `ActionResult`) are declared inline
  in `chat/page.tsx:17-41` and `ProposalCard.tsx:3-16`, but **two kept files DO import
  from `@/types`** (verified against the read-only source):
  - `src/lib/chatSuggestions.ts:18` — `import type { Project, UserRole } from "@/types"`,
    and both are used structurally: `UserRole` is the key type of
    `ROLE_TEMPLATES: Record<UserRole, SuggestionTemplate[]>` and the `role` field of
    `BuildSuggestionsInput`; `Project` drives
    `PLACEHOLDER_FIELDS: Record<string, keyof Project>` and the `project[field]`
    interpolation (reading `name`, `jira_project_key`, `github_repo_name`,
    `servicenow_service_name`, `confluence_space_key`).
  - `src/lib/chatSuggestions.test.ts:7` — `import type { Project } from "@/types"` and
    its `makeProject()` fixture constructs a **full** `Project` object
    (`id`, `user_id`, `name`, `description`, `goal`, `project_type`, `status`,
    `jira_project_key`, `confluence_space_key`, `github_repo_name`,
    `servicenow_service_name`, `generate_mock_data`, `is_active`, `is_selected`,
    `created_at`).

  Dropping `index.ts` would make `@/types` unresolvable in both files, so `tsc`/
  `next build` and `vitest run` would error — i.e. the declared offline gate
  (`npm run test; npm run build`) would go red. **Decision: port a TRIMMED
  `frontend/src/types/index.ts` that keeps exactly `UserRole` and the full `Project`
  interface, dropping only the surface-coupled types (`User`, `HealthStatus`,
  `Integration`, `ProjectProposal`).** The `Project` interface is kept with ALL its
  fields verbatim (not a subset) because the test fixture sets every field and TypeScript
  would otherwise flag excess properties / missing required fields — a subset would break
  the gate. After trimming, re-grep `@/types` across the whole kept set
  (`chatSuggestions.ts`, `chatSuggestions.test.ts`, `chat/page.tsx`, and the four chat
  components) to confirm no removed export is referenced; if a kept file imports a now-
  removed export, re-add that single type to the trimmed `index.ts`.

### A.3 Files that CHANGE

**`src/services/api.ts` — API client.** Keep the request/normalizeErrorMessage
plumbing and the `api.get/post/...` wrapper verbatim. Change the base URL and the
auth header:
- Base URL stays `process.env.NEXT_PUBLIC_API_URL` (the `const API_BASE_URL = ...`
  line, `api.ts:6` — the file opens with a JSDoc banner) but the default changes to the
  thin API Function URL convention (documented, not hardcoded to a localhost backend that
  no longer exists). See §D for how the value is injected.
- Remove the `sessionStorage.getItem("mahalo3_token")` → `Authorization: Bearer` block
  inside `request()` (≈`api.ts:51-57`) and replace it with the SigV4 request-signing path
  chosen in §B.

**`src/app/(protected)/chat/page.tsx` — chat page.** Three concrete edits:
1. **Thread the interrupt id (the single most important change).** The thin API's
   `ApprovalRequest` REQUIRES `interrupt_id` (`api/app/models.py:36-42`), and the
   Runtime returns it INSIDE the proposal dict: `agent/runtime_app.py:159` builds
   `proposal = {**itr.reason, "interrupt_id": itr.id}`, and the thin API passes
   `proposal` through verbatim into `ChatResponse.proposal`
   (`chat.py:66`, `models.py:28`). So `interrupt_id` arrives at the browser as
   `proposal.interrupt_id`. This resolves investigation Open Question A definitively —
   **no thin-API or Runtime change is needed; the id is already on the wire inside
   `proposal`.**

   **The exact access path (resolves review Finding 3, MEDIUM).** The current handlers
   are `handleApprove(msgId: string)` / `handleReject(msgId: string)` — they take only
   the message id and close over `sessionId`; the `proposal` is NOT in their scope
   (verified `chat/page.tsx:186-215`). The render site, however, already has the whole
   message object in scope: `onApprove={() => handleApprove(msg.id)}` /
   `onReject={() => handleReject(msg.id)}` inside `messages.map((msg) => ...)`
   (verified `chat/page.tsx:302-312`). So the change is:
   - Change the signatures to `handleApprove(msg: Message)` / `handleReject(msg: Message)`
     and update the render to `onApprove={() => handleApprove(msg)}` /
     `onReject={() => handleReject(msg)}`.
   - Inside the handler read `const interruptId = msg.proposal?.interrupt_id;` and
     POST `{ session_id: sessionId, interrupt_id: interruptId, approved: true|false }`.
     **This read requires the §A.4 additive `interrupt_id?: string` field on the
     *page-local* `Proposal` interface (`chat/page.tsx:23-28`), not only on
     `ProposalCard.tsx`** — `msg.proposal` is typed by that page-local interface, so
     without the field `msg.proposal?.interrupt_id` is a TS error and `tsc`/`next build`
     (the offline gate) goes red. A.3 edit 1 and the A.4 field are therefore ONE coupled
     edit: both interfaces gain the field together.
   - If `interruptId` is falsy, **early-return without calling the API** (this is the
     A.7 fail-safe guard) and leave the card disabled; a missing id would otherwise
     produce a thin-API 422. No `messages.find(...)` lookup is needed because the
     message is passed in directly.
2. **Treat `systems_queried` as optional AND drive the approve card off `status`
   (resolves review Finding 4, MEDIUM).** Two sub-points on the `ChatApiResponse` type
   and render logic:
   - `systems_queried`: the UI reads `result.data.systems_queried`
     (`chat/page.tsx:37,170`) but `ChatResponse` has no such field (`models.py:26-33`).
     **Make `ChatApiResponse.systems_queried` optional** (`systems_queried?: string[]`,
     at `chat/page.tsx:35-40`). `handleSend` assigns it to the stored
     `Message.systemsQueried` (already optional, so `string[] | undefined` type-checks),
     which the render site passes to `<ChatMessage systemsQueried={...}>`. Because the
     thin API never sends the field, `Message.systemsQueried` is **always `undefined`**,
     and **`ChatMessage` already renders no chip when the prop is absent/empty** —
     verified: `ChatMessage.tsx:30` guards on
     `!isUser && systemsQueried && systemsQueried.length > 0`. So **no change to
     `ChatMessage.tsx` is needed**; the "systems queried" chip simply never renders, and
     the "UI preserved verbatim" claim holds. (If a future `ChatMessage` edit drops that
     guard, re-add it as part of this edit.) No new backend.
   - `status`: on a proposed write the Runtime returns `status: "pending_approval"`
     (`runtime_app.py:~160`) and the thin API passes `status` through verbatim
     (`chat.py:60`, `models.py` `ChatResponse.status`). The current UI shows the
     approve/reject card purely on `proposal` being non-null, which happens to work but
     drops the one explicit backend signal. **Decision: add `status: string` to the
     `ChatApiResponse` type and render `ProposalCard` with Approve/Reject only when
     `status === "pending_approval"` AND `proposal` is present.** Any other status
     (`complete`, `error`) renders as a plain assistant message even if a `proposal`
     field is somehow non-null, so the UI can never mis-offer approval on a completed
     turn. The stored `Message.proposal` is set from the reply only on
     `pending_approval`.
3. **Remove the dropped-context dependencies and pin the static starter set
   (resolves review Finding 1, MEDIUM).** The page imports `useAuth`, `useProjects`,
   `useConnections`, `useRequiredConnections`, and calls `/chat/suggestions`
   (`chat/page.tsx:4-7` for the hooks, the `buildSuggestions` import at `:8`, and the
   `/chat/suggestions` POST inside `handleGenerateSuggestions` at ~`:140`). Remove these:
   the chat page no longer scopes by project (the thin API accepts but IGNORES
   `project_id` — `models.py:22`), no longer gates on "connections configured," and drops
   the "Generate more" LLM-suggestions button (its `/chat/suggestions` route does not
   exist). `project_id` is still sent as `null` for wire compatibility.

   **Exactly what is removed from the component (verified against `chat/page.tsx`):**
   - The four hook calls: `const { user } = useAuth();`,
     `const { activeProject, selectedProjects } = useProjects();`,
     `const { integrations } = useConnections();`, and
     `const { isConfigured, loading: connectionsLoading } = useRequiredConnections();`.
   - The derived values that read them: `scopedProject` (the `useMemo` over
     `selectedProjects`/`activeProject`), `scopedProjectId`, `connectedTypes` (the
     `useMemo` over `integrations`), `suggestionSignature`, `displayedSuggestions`, and
     the `llmSuggestions`/`generatingSuggestions` state + the whole
     `handleGenerateSuggestions` function. `activeProject`/`selectedProjects` are gone
     with `useProjects`.
   - In `handleSend`, the scope-change logic (`sessionScopeRef`, `scopeChanged`,
     `effectiveSessionId` derived from `scopedProjectId`) is simplified: the POST body
     becomes `{ message, session_id: sessionId, project_id: null }`, and
     `sessionScopeRef`/`scopeChanged` are dropped (the single-session demo never
     re-scopes). The returned `session_id` is still stored and resent.

   **The exact `buildSuggestions` call after the trim.** `buildSuggestions` is ported
   verbatim (§A.2) and still produces the starter grid. It is called with a FIXED demo
   context (no live role/project/connections):

   ```ts
   const templateSuggestions = useMemo(
     () => buildSuggestions({ role: "developer", project: null, connectedTypes: ["github", "jira"] }),
     []
   );
   ```

   **Why these exact arguments (not `{}`/empty).** Verified against
   `chatSuggestions.ts`: `buildSuggestions` defaults `role` to `developer`, then drops
   every template whose `requires:` list is not satisfied by `connectedTypes`, and drops
   every `needsProject`/placeholder template when `project` is null. With
   `connectedTypes: []` the result collapses to only `FALLBACK_SUGGESTIONS`
   ("What can you help me with?", "Give me a status overview of my projects") — a thin,
   un-representative empty state. Passing `connectedTypes: ["github", "jira"]` with
   `project: null` instead surfaces the role-`developer` templates that have those
   `requires` and NO `needsProject` placeholder — i.e. "Show open pull requests",
   "What issues are assigned to me?", and "What changed in the latest release?" (the
   project-scoped `{repo}`/`{jiraKey}` templates are still correctly dropped because
   `project` is null). That gives a meaningful, chat-tool-relevant starter grid that
   matches what the mahalo-dock demo showed for a developer with GitHub+Jira connected,
   which is the representative state the user validates. `limit` stays the default (4).
   `displayedSuggestions` is removed; the render uses `templateSuggestions` directly.

   **The empty-state render after the trim (what the two gated blocks become):**
   - The `!isConfigured` "Connections Required" block (the `🔗` / "Please configure
     Jira, Confluence, and GitHub" panel) is **deleted entirely** — there is no
     connection gate.
   - The `isConfigured` "How can I help you today?" block (the `💬` heading + the
     starter-prompt grid) becomes **unconditional**, gated only on
     `messages.length === 0` (the `!connectionsLoading` and `isConfigured` conditions are
     removed, as is `connectionsLoading` itself). Inside it, the grid maps
     `templateSuggestions` (not `displayedSuggestions`), and the "✨ Generate more"
     button + its spinner branch are deleted.
   - `ChatInput`'s `disabled` prop drops the `(!connectionsLoading && !isConfigured)`
     term, leaving `disabled={isLoading}`.
   - The header scope chip (the `isConfigured && (...)` blue "Scoped to …" box reading
     `scopedProject`/`selectedProjects`) is **removed**, leaving only the "AI Assistant"
     `<h1>` + the "Ask about your projects, sprints, documentation, and code" subtitle
     (consistent with the §A.5 Sidebar decision — the in-page header is the sole chrome).

**`src/app/layout.tsx` — root layout.** Two changes:
1. Drop the `AuthProvider` / `ConnectionsProvider` / `ProjectProvider` wrappers
   (`layout.tsx:4-6,33-39`); none of their backends exist. The ported tree renders the
   chat page directly.
2. **Remove the `next/font/google` imports — font decision (resolves review Finding 2,
   HIGH).** The source layout imports `Geist` and `Geist_Mono` from `next/font/google`
   (verified `layout.tsx:2`), which fetches font files from `fonts.gstatic.com` **at
   `next build` time**. That directly breaks the declared "no network" offline gate
   (`npm ci; npm run lint; npm run test; npm run build`), and `output: "export"` (§D)
   does NOT change it — font fetching happens during `next build` regardless of output
   mode. **Decision: drop `next/font` entirely and use a system font stack.** Delete the
   `Geist`/`Geist_Mono` imports and the two `geist*` `const` calls; replace the
   `html className={\`${geistSans.variable} ${geistMono.variable} ...\`}` binding with a
   static `className` and add a system font stack to `globals.css` (e.g.
   `@theme { --font-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
   sans-serif; --font-mono: ui-monospace, "SFMono-Regular", "Menlo", monospace; }` for
   Tailwind 4). This is a **visual no-op**: `globals.css` never referenced the
   `--font-geist-*` variables (verified — it is `@import "tailwindcss";` only), so the
   browser was already falling back to default sans/mono anyway. The system-font path
   (option (b) in the review) is chosen over `next/font/local` (option (a)) because it
   vendors no binary font files into the repo and needs zero network at any stage;
   it is chosen over documenting outbound `fonts.gstatic.com` access (option (c))
   because that would make the "no network" gate literally false. `globals.css` is thus
   the ONE config file in A.2's verbatim list that gains this small `@theme` addition.

**`src/app/page.tsx`** — redirect/landing to the chat page (today it depends on the
auth flow, pushing to `/dashboard` or `/login`). **Export-safe decision (resolves review
Finding 3, NIT).** Verified the source `page.tsx` is already a `"use client"` component
doing `router.push(...)` inside a `useEffect` (via `useRouter()` from
`next/navigation`) — a pattern that IS compatible with `output: "export"` (§D). Keep that
shape: strip the `useAuth` import and the `user`/`isLoading` branching, and make the
`useEffect` unconditionally `router.push("/chat")`, keeping the existing loading spinner
as the transient render. **Do NOT convert it to the server `redirect()` helper from
`next/navigation`** — a server redirect is not compatible with a fully static export and
would break `npm run build`. (Equivalent alternative, if the implementer prefers one
fewer route: render `<ChatPage/>` directly at `/` and drop the `/chat` route; either is
export-safe. The default is the client-side `useEffect` push to `/chat`.)

### A.4 `ProposalCard.tsx` additive field

The `Proposal` interface gains one optional field — `interrupt_id?: string` — in **both**
places it is declared: the **page-local** `Proposal` in `chat/page.tsx` (verified at
`chat/page.tsx:23-28`: `{action, system, params, description}`) **and** the `Proposal`
in `ProposalCard.tsx` (verified at `ProposalCard.tsx:3-8`). Both are required: the
page-local one so §A.3 edit 1's `msg.proposal?.interrupt_id` type-checks (that read is
the coupled consumer — see §A.3 edit 1), and the `ProposalCard` one so the prop shape
stays consistent. Rendering does not use the field (it is carried for the approve call
only), so `ProposalCard` is functionally verbatim. This is ONE coupled edit with §A.3
edit 1, not two independent ones.

### A.5 Files DROPPED (coupled to the old LangChain/full FastAPI backend)

- `src/app/login/page.tsx`, `src/app/register/page.tsx`, `src/app/(protected)/layout.tsx`
  (auth-gated shell), `src/components/common/ProtectedRoute.tsx` — the whole auth flow.
- `src/app/(protected)/dashboard/page.tsx` + all of `src/components/dashboard/**`
  (8 widgets + grid) — no dashboard backend; also drops `react-grid-layout` usage.
- `src/app/(protected)/connections/page.tsx`,
  `src/app/(protected)/connections/[id]/data/page.tsx` — the dynamic `[id]` route
  that otherwise complicates static export (§D); no connections backend.
- `src/contexts/AuthContext.tsx`, `src/contexts/ProjectContext.tsx`,
  `src/contexts/ConnectionsContext.tsx`, `src/hooks/useRequiredConnections.ts`,
  `src/components/common/ProjectMultiSelect.tsx`, and `src/components/common/Sidebar.tsx`.

**Sidebar decision (resolves review Finding 9).** The ported demo has exactly ONE
route (the chat page), so a navigation Sidebar has nothing to navigate to. **Decision:
drop `Sidebar.tsx` entirely; no navigation chrome.** The chat page already renders its
own header (`chat/page.tsx:217-224`: "AI Assistant" title + subtitle), which is kept as
the sole app-title chrome. No new static header component is introduced.

Dropping the `[id]` dynamic route is deliberate: it removes the one obstacle to a
clean Next static export (§D), so no `generateStaticParams` is needed.

### A.6 Env contract

The only runtime/build-time config the ported app needs is the thin-API base URL:

| Var | When | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | build-time (Next inlines `NEXT_PUBLIC_*`) | thin API Function URL, e.g. `https://<id>.lambda-url.us-east-1.on.aws` |
| `NEXT_PUBLIC_AWS_REGION` | build-time | region for the in-browser SigV4 signer (§B) |
| `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` | build-time | identity pool the browser exchanges for temp creds (§B) |

A `frontend/.env.example` documents these. No secret values are baked — the identity
pool id and region are public identifiers; temporary credentials are fetched at
runtime by the browser (§B).

### A.7 Validation rules (frontend inputs)

- Chat message: required, non-empty string, trimmed before send; empty input disables
  the send button (existing `ChatInput` behavior, preserved). The thin API also
  validates (pydantic → 422) but the UI should not send empties.
- `session_id`: optional on the first turn (server mints one, `chat.py:46`); the UI
  stores and resends the returned id. On failure the UI surfaces `result.error` as an
  assistant error bubble (existing behavior, preserved).
- `interrupt_id`: required for an approve/reject; the handler reads it from the passed
  `msg.proposal?.interrupt_id` (A.3 edit 1) and, if it is falsy, early-returns without
  calling the API and keeps the card disabled (fail safe — a missing id would produce a
  422 at the thin API). This is the new guard added with A.3 edit 1.
- Approve card visibility: shown only when `status === "pending_approval"` and
  `proposal` is present (A.3 edit 2); otherwise the turn renders as a plain assistant
  message.

---

## B. Frontend ↔ thin-API auth

### B.1 The constraint

The thin API Function URL is `AuthType=AWS_IAM` (`api_stack.py:103-105`). Every
request must be SigV4-signed with AWS credentials; a browser holds none by default
(investigation §3.4). The old frontend's `Authorization: Bearer` (`api.ts:48-54`)
targets a login backend that no longer exists.

### B.2 Decision: Cognito Identity Pool → temporary IAM creds → in-browser SigV4

Pick posture **1** from investigation §3.4. Reasoning, weighing "smallest coherent
*real* approach":

- It is the one option that keeps the edge exactly as Task 6 shipped it
  (`AuthType=AWS_IAM`), so no Function-URL auth downgrade and no divergence from the
  project's locked "AWS_IAM now, Cognito at dev-mode" stance (`docs/PLAN.md:128-130`,
  `runtime_stack.py:82`). The thin API's own identity stays the fixed dev identity
  (`auth.py:21-30`); Cognito here authenticates the *browser-to-edge* hop only.
- Posture 2 (CloudFront + Cognito user pool + WAF in front, Function URL possibly
  `NONE`) adds an edge auth layer AND changes the Function URL auth type — more moving
  parts and a divergence from the shipped edge.
- Posture 3 (Function URL `NONE`, or a second server-side signer/proxy Lambda) is
  demo-grade: `NONE` removes auth entirely, and a proxy means standing up and securing
  another Lambda. Either is more code or less safe than letting Cognito hand the
  browser scoped temp creds.

An **unauthenticated** Cognito Identity Pool is sufficient and the smallest real
form: the single-user demo does not need a user-pool login screen. The pool's
*unauthenticated* role is granted exactly `lambda:InvokeFunctionUrl` on the thin API
function ARN (least privilege). This keeps the browser credential-less at rest (it
fetches short-lived creds at runtime) while still forcing a signed, IAM-authorized
call at the edge. If a login screen is later desired, swapping the unauthenticated
role for an authenticated (user-pool-backed) role is the documented dev-mode upgrade
and does not change the signing code.

**Who provisions the pool (resolves review Finding 2, NIT) — it is CDK, inside
`frontend_stack.py`, not a manual step.** The identity pool and its unauthenticated
role are created by `MahaloFrontendStack` (§D.2), because that stack already references
the thin-API function (for the role's `lambda:InvokeFunctionUrl` policy ARN and for the
CORS `allowed_origins` wiring) and already owns the CloudFront domain the browser runs
on. The stack emits `CfnOutput IdentityPoolId`; the operator reads that output into
`NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` at frontend build time (§D.2 step 2). Because the
pool + role live **inside** `frontend_stack` (not a new stack), the `cdk synth --all`
template count stays at **10** (§E.1). This removes the only remaining "CDK or manual
operator step" fork in the auth story.

### B.3 Exact client change (replacing the Bearer header)

In `src/services/api.ts`:
- **Final pinned dependency list (resolves review Finding 6, NIT):** exactly two
  packages — `aws4fetch` (a single tiny dependency that bundles SigV4 signing for
  `fetch`; takes `{accessKeyId, secretAccessKey, sessionToken}` and signs a `Request`)
  **and** `@aws-sdk/credential-providers` (for `fromCognitoIdentityPool`, which fetches
  the temporary creds from the identity pool). `aws4fetch` alone is NOT sufficient
  because the credential provider still comes from the AWS SDK. The heavier
  `@aws-sdk/signature-v4` + `@aws-crypto/sha256-js` signing packages are NOT used —
  `aws4fetch` replaces them. Both deps are pinned to exact versions in
  `frontend/package.json` (`package-lock.json` regenerated by `npm ci`/`npm install`
  during the port).
- Flow per request: (1) obtain cached temp creds from the identity pool
  (`NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`, `NEXT_PUBLIC_AWS_REGION`) via
  `fromCognitoIdentityPool`, refreshing when near expiry; (2) construct the `aws4fetch`
  signer with those creds — `const aws = new AwsClient({ accessKeyId, secretAccessKey,
  sessionToken, service: "lambda", region: process.env.NEXT_PUBLIC_AWS_REGION })`;
  (3) issue the request with `aws.fetch(url, { method, headers, body })`.
- **Body signing (resolves review Finding 2, NIT).** The current `api.ts` `request()`
  helper passes the JSON string body through `fetch(url, { ...options, body:
  JSON.stringify(body) })` (verified: the `api.post/put` wrappers call
  `JSON.stringify(body)` and `request()` forwards `options.body`). For a SigV4 `POST` to
  an `AWS_IAM` Function URL the signature's `X-Amz-Content-Sha256` MUST hash exactly the
  bytes that are sent. So the serialized JSON body is passed **into** the `aws4fetch`
  call —`aws.fetch(url, { method, headers, body: JSON.stringify(body) })` — so the signer
  computes `X-Amz-Content-Sha256` over that exact string and emits all the SigV4 headers
  (`Authorization`, `X-Amz-Date`, `X-Amz-Security-Token`, `X-Amz-Content-Sha256`) itself.
  **Do NOT set or mutate `headers` or `body` after signing** (no post-sign
  `headers["Authorization"] = ...`, no swapping the body), or the recomputed signature at
  the edge will not match and Lambda returns 403. The signing service literal is
  `"lambda"` and the region comes from `NEXT_PUBLIC_AWS_REGION`; `Content-Type:
  application/json` stays part of the signed `headers`. Remove the `sessionStorage` token
  block entirely.
- Error surface is unchanged (`normalizeErrorMessage` on `detail`/`message`).

### B.4 CORS and the signing host — direct Function-URL calls (resolves review Finding 1, HIGH)

**The problem with the prior same-origin-through-CloudFront design.** SigV4 signs the
`Host` header. If the browser is on the CloudFront domain and the API is routed through
that same distribution to the Function URL origin, the signature cannot survive: sign
for the CloudFront host and the Function URL origin recomputes against its own host
(`<id>.lambda-url.<region>.on.aws`) → 403; sign for the Function URL host while the
real request `Host` is CloudFront's (which CloudFront rewrites on forward) → the signed
and forwarded values diverge → 403. The investigation flagged this exact friction. A
CloudFront-fronted API therefore cannot carry a browser-computed SigV4 signature
without moving auth to an edge layer (that would re-decide §B). So the same-origin claim
is **dropped**.

**Decision: the browser calls the thin-API Function URL DIRECTLY at its real host, and
CORS is solved explicitly.** The browser signs SigV4 for the Function URL's own host and
service `lambda` (correct and unambiguous — the signed `Host` equals the actual request
`Host`, no proxy rewrite in between). CloudFront serves ONLY the static frontend (§D);
it does NOT front the API. Cross-origin is handled by setting
`FunctionUrlCorsOptions` on the thin-API Function URL (CDK `add_function_url(cors=...)`):
- `allowed_origins`: the CloudFront distribution domain of the frontend (a
  `CfnParameter`/stack reference, not `*`, because signed requests carry credentials).
- `allowed_methods`: `POST`, `GET` (for `/healthz`), plus `OPTIONS` preflight.
- `allowed_headers`: `Authorization`, `X-Amz-Date`, `X-Amz-Security-Token`,
  `X-Amz-Content-Sha256`, `Content-Type` — the exact headers the SigV4 signer sets.
- `max_age`: a small cache (e.g. 300s) for the preflight.

This is a **change to `MahaloApiStack`** (adding the `cors` block to the existing
`add_function_url(auth_type=AWS_IAM)` call, `api_stack.py:103-105`) — the ONE small
edit Task 7 makes to the Task-6 API stack. The Function URL **auth type stays
`AWS_IAM`** (no downgrade; posture 2's edge-auth re-decision is not taken). Because
`FunctionUrlCorsOptions` makes Lambda answer the `OPTIONS` preflight itself WITHOUT
requiring SigV4 on the preflight, the known SigV4+CORS friction is avoided: the browser
preflights unsigned, then sends the signed `POST`/`GET`.

Consequence for config injection: since the API is NOT behind CloudFront,
`NEXT_PUBLIC_API_URL` must carry the real Function URL at build time (see §D.2, which is
updated to the two-phase operator build — the earlier "empty/relative URL" shortcut is
withdrawn along with the same-origin claim).

### B.5 Error handling (auth layer)

| Failure | Recoverable? | Caller receives | Logged |
|---|---|---|---|
| Identity-pool `GetCredentials` fails (misconfig/network) | fatal for the call | assistant error bubble "Could not authenticate to the API" | `console.error` (browser) |
| Temp creds expired mid-session | recoverable | transparent refresh + retry once | none unless retry fails |
| Function URL returns 403 (SigV4 mismatch / role lacks `lambda:InvokeFunctionUrl`) | fatal | assistant error bubble with status | `console.error` |
| CORS preflight fails (origin not in `allowed_origins`) | fatal (config error) | browser blocks the call; assistant error bubble "Network/CORS error" | `console.error` |
| Thin API 502 (Runtime invoke threw, `chat.py:62`) | recoverable at user discretion | assistant error bubble; user may resend | server-side (thin API already logs) |

No credentials or signatures are ever written to `sessionStorage`/`localStorage`;
temp creds live in memory only.

---

## C. Gitea hosting + persistence + Lambda reachability

### C.1 Decision: EC2 + EBS, single always-on instance running the Gitea container

Pick option 1 from investigation §2.3. Reasoning:

- It is the proven mahalo-dock path (`docker-compose.yml:146-214`) and matches the
  operational knowledge already captured (`aws-deploy-plan.md`).
- It satisfies the **first-admin-via-CLI** requirement cleanly:
  `mock-services/gitea-bootstrap/bootstrap.sh:2-10` notes the first admin can ONLY be
  created via the `gitea` CLI against the data dir — trivial on a single host, awkward
  on Fargate (option 2 would need a one-shot task into an EFS volume).
- SQLite storage on an EBS volume is sufficient for a single-user demo (Gitea's
  default; mahalo-dock used `DB_TYPE=sqlite3`), so no RDS and no EFS are needed.
- It is the cheapest always-on shape (t3.small/t3.micro; the prior t3.medium ran
  ~\$30/mo 24/7, less on a smaller instance), honoring "cost is low → go with the
  simple option" from the user's prior guidance.

Fargate+EFS (option 2) and App Runner (option 3) are explicitly set aside: more
moving parts and a worse fit for the CLI bootstrap / durable-writable-storage needs.

### C.2 CDK + host shape (`MahaloGiteaStack`)

New stack `infra-cdk/mahalo_infra/gitea_stack.py`, wired into `infra-cdk/app.py` by
direct construct reference like every other stack:

- `aws_ec2.Vpc` — a minimal VPC (1 public subnet, no NAT, to keep cost near zero) OR
  reuse the default VPC via `Vpc.from_lookup`. **Decision:** create a tiny dedicated
  VPC with a single public subnet (lookup-free so synth needs no account context —
  `from_lookup` triggers a context lookup that can break the offline gate). Cost of an
  empty VPC is \$0.
- `aws_ec2.Instance` — Amazon Linux 2023, t3.small, in the public subnet with a public
  IP. `UserData` installs Docker and runs `docker run -d -p 3000:3000 -v /data/gitea:/data
  gitea/gitea:1.27.3` (image **by reference**, no local build → no Docker at synth).
- `aws_ec2.SecurityGroup` — two ingress rules, egress open. **SSH (22):** restricted to
  a `CfnParameter` CIDR (`AdminCidr`, no `0.0.0.0/0` default — the operator supplies
  their IP). **Gitea HTTP/API (3000):** the stack **synthesizes a default ingress of
  `0.0.0.0/0`** (resolves iteration-2 review Finding 3). This is required and
  implementable: the github Lambda is non-VPC (§C.5) and so has **no fixed egress IP** to
  scope an SG rule to — "restrict to the Lambda's egress" is not expressible for a
  non-VPC Lambda, so the earlier wording is withdrawn. The internet-facing 3000 endpoint
  is protected by the **Gitea API token** (SSM SecureString, scoped
  `write:repository`/`write:user`/`read:organization` per `bootstrap.sh:93-109`), which
  every write call requires. An operator may harden this as a documented post-deploy
  step by binding 3000 to a managed prefix list or a known CIDR via a second
  `CfnParameter` (e.g. `GiteaIngressCidr`, defaulting to `0.0.0.0/0`); the **default the
  stack actually synthesizes is `0.0.0.0/0` on 3000**.
- Persistence: a dedicated gp3 `aws_ec2.BlockDeviceVolume` mounted at `/data`, so repo
  data survives instance stop/start. `RemovalPolicy` — the EBS volume follows the house
  `RemovalPolicy.DESTROY` style (`mock_service_stack.py:84`) with an explicit note that
  teardown wipes repos; this is acceptable because the data is fully re-seedable by
  `bootstrap.sh`. (An operator who wants to keep repos across a monthly reset can flip
  the volume to `RETAIN` via a CfnParameter — documented, defaulting to DESTROY.)
- Secrets: an `aws_ssm.StringParameter` (SecureString) holds the adapter API token and
  Gitea admin password. **These are created/owned by the operator at deploy time**, not
  synthesized with real values (the stack references parameter *names*, not literals),
  so no secret is committed.

TLS: for the demo, Gitea is served over HTTP on the instance; the browser never talks
to Gitea directly for API calls (the github Lambda does, §C.4), and browser-facing
repo *links* are produced by `_publicize` (§C.3). If HTTPS on the public URL is wanted,
the operator can front the instance with an ALB+ACM cert — documented as an optional
upgrade, not required for the demo.

### C.3 Bootstrap (gitea assets land in `gitea/`)

Port `mock-services/gitea-bootstrap/bootstrap.sh` + its Dockerfile into `gitea/`
(mahalo-agentcore). On EC2 the bootstrap runs as a one-shot `docker run` from the same
`gitea/gitea:1.27.3` image (so the `gitea` CLI and `/data` are available), invoked by
`UserData` after the server reports healthy. It is idempotent (§steps 1-5 of the
script): create admin (CLI), mint the adapter token (scopes
`write:repository`,`write:user`,`read:organization`), seed the `payment-service` repo
with real files, and write the token where the adapter reads it. On AWS the token is
pushed to the SSM SecureString parameter (replacing the Compose shared-volume
`GITEA_TOKEN_FILE`), which the github Lambda reads at cold start.

`GITEA_PUBLIC_URL` is set to the instance's browser-facing URL (public DNS/IP, or the
ALB URL if the HTTPS upgrade is taken) so `gitea_backend._publicize`
(`gitea_backend.py:76-80`) rewrites in-stack links to reachable ones.

### C.4 github Lambda: switch to Gitea-backed, mock stays default

Port `mahalo-dock/mock-services/github/gitea_backend.py` + `backend_base.py` into
`tools-lambdas/github/` as `gitea_backend.py` (and a small `backend_base.py` if not
already shared). The switch is **additive and behind the existing `GITHUB_MODE`**,
which `routes.build_router` already reads at `routes.py:49` but today only surfaces in
`/health` (`routes.py:67`) — mock-only (`routes.py:3`).

**Exact handler wiring (resolves review Finding 5, MEDIUM).** The current entrypoint
`handler.lambda_handler` unconditionally does, on every invocation (verified
`handler.py:28-46`): `_get_router()` → `Store(_TABLE_NAME, seed_items=routes.seed_items)`
+ `routes.build_router(store, _TOKEN)`, then `store.ensure_seeded()`, then dispatch. So
two concrete facts must be handled: (1) the DynamoDB `Store` is built and seeded BEFORE
any mode branch, and (2) `build_router(store, token)` has no parameter for Gitea config.
The design pins the following, keeping the mock path byte-identical:

- **Short-circuit the DynamoDB seed in real mode.** `handler._get_router` reads
  `_MODE = os.environ.get("GITHUB_MODE", "mock").strip().lower()` at module scope
  (alongside the existing `_TOKEN`/`_TABLE_NAME`). When `_MODE == "real"` it does NOT
  construct/seed the `Store` (skips `Store(...)` and the later
  `store.ensure_seeded()`); it builds a Gitea-backed router instead. When `_MODE` is
  unset or `"mock"` (the DEFAULT) it runs the existing `Store` + `ensure_seeded()` path
  **unchanged**. This avoids provisioning/granting a DynamoDB table the real path never
  reads, and keeps `ensure_seeded()` off the real path entirely. `lambda_handler`'s
  `store.ensure_seeded()` call (`handler.py:44`) becomes conditional on `store is not
  None` (real mode returns `store=None`).
- **Gitea env read location.** The `GiteaBackend` config is read at **module scope in
  `handler.py`** (same place as `_TOKEN`/`_TABLE_NAME`), not threaded through
  `build_router`'s `(store, token)` signature. New module-level constants:
  `_GITEA_URL` (`GITEA_URL`), `_GITEA_TOKEN` (resolved from SSM — see below, falling
  back to `GITEA_TOKEN`/`GITEA_TOKEN_FILE` for parity with the mahalo-dock contract),
  `_GITEA_OWNER` (`GITEA_ADMIN_USER`), `_GITEA_PUBLIC_URL` (`GITEA_PUBLIC_URL`),
  `_DEMO_DEVELOPER_ID` (`DEMO_DEVELOPER_ID`, default `dev-6`). These mirror
  `gitea_backend.py:56-74` verbatim.
- **Router construction in real mode.** Add `routes.build_gitea_router(backend)` that
  registers the SAME route table as `build_router` but delegates each route to the
  `GiteaBackend` instance (which already adapts Gitea REST `/api/v1` responses back to
  the mock's JSON shapes). `build_router(store, token)` itself is **not changed** — its
  signature and mock behavior are untouched, so no mock-path code is altered. In real
  mode `_get_router` returns `(None, build_gitea_router(GiteaBackend(...)))`.
- **94 tests stay green by construction.** Because mock mode touches zero changed lines
  (the new branch only runs when `GITHUB_MODE=real`, which no existing test sets), the
  `94 passed` tools-lambda suite is preserved (count confirmed in §C.4a). New tests
  cover the real branch with `httpx` mocked (no live Gitea), part of the offline gate.

**Token resolution from SSM.** The adapter token is NOT passed as a plaintext Lambda
env var. The real-mode stack injects `GITEA_TOKEN_PARAM` (the SSM SecureString
parameter *name*) and grants the Lambda role `ssm:GetParameter` +
`kms:Decrypt` on that parameter. At cold start `handler.py` resolves `_GITEA_TOKEN` by
calling `ssm.get_parameter(Name=_GITEA_TOKEN_PARAM, WithDecryption=True)` (boto3, which
is already in the Lambda runtime) and caches it at module scope. For local/unit tests
and parity with the mahalo-dock contract, if `GITEA_TOKEN_PARAM` is unset it falls back
to `GITEA_TOKEN` / `GITEA_TOKEN_FILE` (`gitea_backend.py:59,88-101`). The token value is
never logged.

The github `MockServiceStack` instance gains (only when the operator opts into real
mode) these env vars plus the SSM read grant. Enabling real mode is a context flag
(`-c giteaMode=real`) read once in `app.py` and threaded to the github instance only;
default synth is unchanged. See §C.4b for the exact `MockServiceStack` + `app.py` edit.

### C.4b `MockServiceStack` constructor + `app.py` threading (resolves iteration-4 review Finding 1, MEDIUM)

`MockServiceStack` is a **single generic construct instantiated four times** in
`app.py`'s loop over `("jira","confluence","github","servicenow")` (verified
`app.py:23-31`; the current signature is
`(scope, construct_id, *, service, default_token=None, **kwargs)` and the env dict is a
fixed `{"TABLE_NAME":..., token_env_key: token}` with the single grant
`table.grant_read_write_data(fn)` — `mock_service_stack.py:60-115`). "The github
instance gains X" is therefore NOT implementable without a specified branch, and an
unguarded edit would leak Gitea config into the jira/confluence/servicenow instances.
The design pins this exactly:

- **New optional kwargs on `MockServiceStack.__init__`** (all default to the no-op so
  the three non-github instances and the default github instance are untouched):
  `gitea_mode: bool = False`, `gitea_env: dict[str, str] | None = None`,
  `gitea_token_param_name: str | None = None`.
- **The new env/grant branch is guarded by `service == "github" and gitea_mode`** so it
  can only ever affect the github instance, never the loop's other three:

  ```python
  # mock_service_stack.py — inside __init__, building the env dict
  env = {"TABLE_NAME": table_name, token_env_key: token}
  if service == "github" and gitea_mode:
      env["GITHUB_MODE"] = "real"
      env.update(gitea_env or {})   # GITEA_URL, GITEA_ADMIN_USER, GITEA_PUBLIC_URL,
                                    # DEMO_DEVELOPER_ID, GITEA_TOKEN_PARAM
  # ... Function(... environment=env ...)

  # SSM read grant, same guard
  if service == "github" and gitea_mode and gitea_token_param_name:
      param = ssm.StringParameter.from_secure_string_parameter_attributes(
          self, "GiteaToken", parameter_name=gitea_token_param_name)
      param.grant_read(fn)          # ssm:GetParameter + kms:Decrypt
  ```

- **`app.py` reads the flag once and passes it to the github instance only**:

  ```python
  gitea_mode = app.node.try_get_context("giteaMode") == "real"
  for service in _SERVICES:
      stack_id = f"MahaloMock{service.capitalize()}Stack"
      mock_stacks[service] = MockServiceStack(
          app, stack_id, service=service, env=_ENV,
          gitea_mode=(gitea_mode if service == "github" else False),
          gitea_env=(_GITEA_ENV if service == "github" else None),
          gitea_token_param_name=(_GITEA_TOKEN_PARAM if service == "github" else None),
      )
  ```

  where `_GITEA_ENV` / `_GITEA_TOKEN_PARAM` are module-level constants in `app.py`
  (the Gitea URL/owner/public-URL/dev-id env and the SSM parameter name).

- **Default (`giteaMode` unset) leaves all four instances byte-identical to today.**
  With the flag absent, `gitea_mode` is `False`, every guard is skipped, and the github
  instance's env/grant are exactly the current `{TABLE_NAME, MOCK_GITHUB_TOKEN}` +
  `table.grant_read_write_data`. So `cdk synth --all` still emits the same 8 templates
  (10 after the two new Task-7 stacks, §E.1) and the 94 tools-lambda tests are
  unaffected (they never set `GITHUB_MODE=real`).

### C.4a Confirming the "94 tools-lambda tests" count (resolves review Finding 7, NIT)

The design guarantees the `94 passed` tools-lambda suite stays green. The count is
confirmed against the recorded project baseline rather than re-collected here (the
`moto` test dependency is not installed in this authoring environment, so a live
`pytest --collect-only` cannot run — it fails importing `conftest.py`'s `from moto
import mock_aws`). The `94 passed` figure is the stable, repeatedly-recorded baseline
across Tasks 4, 5, and 6: `docs/STATUS.md:39,41,42,47` ("tools-lambdas `94 passed`"),
`docs/PLAN.md:52,88,134`, and `docs/CONTINUATION.md:114,211,250`. So the number is
accurate and load-bearing; the implementation task re-runs `pytest tools-lambdas/tests
-q` (with the dev venv's `moto` installed) to confirm `94 passed` plus the new
real-mode unit tests before considering the github-Lambda change complete.

### C.5 Reachability (github Lambda → Gitea)

**Decision: public-HTTPS/HTTP reachability, no VPC on the Lambda.** The github Lambda
has no VPC today (`mock_service_stack.py` provisions a public Function-URL Lambda,
no VPC). Keep it that way: set `GITEA_URL` to the EC2 instance's **public** endpoint
and let the Lambda reach Gitea over the internet, authenticated by the Gitea API token
(SSM). Rationale: attaching a VPC to the Lambda would force VPC endpoints or a NAT for
its existing DynamoDB/Gateway access — heavy and costly for a single-user demo. Because
the Lambda is non-VPC it has no fixed egress IP, so the instance security group CANNOT
scope port 3000 to "the Lambda's egress"; the stack therefore synthesizes port 3000
ingress as `0.0.0.0/0` by default (§C.2), relying on the Gitea API token for protection,
with a documented operator hardening step to narrow it to a prefix list / known CIDR via
the `GiteaIngressCidr` parameter. This preserves the current no-VPC Lambda topology
exactly.

### C.6 Error handling (Gitea path)

`GiteaBackend` already raises `BackendError(status, detail)` which the adapter maps to
HTTP status codes (`main.py:_call`); the ported routes map `BackendError` to the
Lambda's `error(status, detail)` helper (`common/responses.py`). Concrete cases:

| Operation | Failure | Recoverable? | Caller receives | Logged |
|---|---|---|---|---|
| Any Gitea REST call | connection refused / timeout (instance down) | fatal for that call | HTTP 503 "Backend store unavailable" (reuse `handler.py` ClientError mapping style) | `logger.exception` in Lambda |
| Token missing/invalid in SSM | fatal | HTTP 502/401 depending on Gitea reply | `logger.exception`, no token value logged |
| Gitea 404 (repo/branch absent) | expected | passed through as the mock's 404 (`error(404, ...)`) | not logged (normal) |
| Gitea 409 (branch/PR exists) | expected | passed through as 409 | not logged |
| Write partial failure (e.g. commit after branch) | NOT auto-retried | surfaced as the Gitea error | `logger.warning` |

The token value is referenced by SSM parameter name and never echoed into logs or
responses.

### C.7 Testability

- github Lambda real-mode: **unit** tests with `httpx` transport mocked assert the
  contract translation (repo_id→name path, `_publicize` URL rewrite, author-id
  mapping) — offline, no live Gitea. Mock-mode tests unchanged (94 green).
- Bootstrap idempotency: tested by **integration** (live EC2) only — documented as an
  operator step, not part of the offline gate.
- Reachability (Lambda→public Gitea): **integration**, deferred operator step.

---

## D. Frontend hosting

### D.1 Decision: S3 + CloudFront, serving a Next.js static export

Pick S3+CloudFront (investigation §3.2). Reasoning:

- The ported app is, after §A trimming, **entirely client-rendered** with no SSR, no
  server actions, and — crucially — **no dynamic routes** (the one `[id]` route is
  dropped in §A.5). That removes the only obstacle to `output: "export"`.
- S3+CloudFront is the cheapest, simplest, "survives-a-monthly-reset" option and is
  pure CDK (no git-connected managed service). Amplify Hosting is lowest-effort for a
  *full* Next app but is git-connected and less "pure CDK"; a container on ECS/Fargate
  is heavier than static for a single-user demo. Neither buys us anything the static
  export lacks here.

**CloudFront serves the STATIC FRONTEND ONLY (consequence of review Finding 1).** The
earlier revision had CloudFront front both the app and the thin-API Function URL for a
"same-origin" CORS trick; §B.4 withdrew that because the SigV4 `Host`-header signature
cannot survive the CloudFront→Function-URL hop. So this distribution has a **single**
origin (the S3 bucket); the browser reaches the thin API directly at its Function URL
(§B.4), with CORS handled by `FunctionUrlCorsOptions` on the API. CloudFront is kept
purely for HTTPS + CDN of the static bundle.

Concrete frontend change: add `output: "export"` to `frontend/next.config.ts` (today
empty, `next.config.ts:3-6`). `next build` then emits a static `out/` directory. Set
`images.unoptimized: true` (static export cannot use the Next image optimizer) — the
chat UI uses emoji/Tailwind, not `next/image`, so this is a no-op guard.

### D.2 CDK (`MahaloFrontendStack`) + config injection

New stack `infra-cdk/mahalo_infra/frontend_stack.py`, wired into `app.py` by direct
construct reference:

- `aws_s3.Bucket` — private, `RemovalPolicy.DESTROY` + `auto_delete_objects=True`
  (house style), no public access; served only via CloudFront OAC.
- `aws_cloudfront.Distribution` — a **single** default behavior → S3 origin (OAC) with
  SPA-style 403/404→`index.html` handling. **No API/Function-URL origin** (removed per
  §B.4 / Finding 1). The frontend stack takes `api_stack` as a constructor arg **ONLY to
  reference the thin-API function ARN (`api_stack.function.function_arn`) for the
  unauthenticated role's `lambda:InvokeFunctionUrl` policy** (§B.2, and the identity-pool
  bullet below). It does NOT read any Function-URL string off `api_stack` — `api_stack`
  exposes `self.function` (the `Function` construct, so `.function_arn` is reachable) but
  **no `function_url` attribute** (the URL is a local `url = fn.add_function_url(...)`
  surfaced only via the `RuntimeApiUrl` CfnOutput). `NEXT_PUBLIC_API_URL` is set by the
  **operator** from the `RuntimeApiUrl` CfnOutput (§D.2 steps 1,3), and the API's CORS
  `allowed_origins` is set by **re-deploying `MahaloApiStack`** with the CloudFront domain
  (§D.2 step 5) — **neither is done by `frontend_stack`**, and `api_stack` is NOT wired as
  a CloudFront origin. (If an explicit ARN handle is preferred over reaching through the
  `Function` construct, add `self.function_arn = fn.function_arn` to `api_stack.py` and
  reference that.) Emit the distribution domain as `CfnOutput` **`FrontendUrl`** so the
  operator can set the API's CORS origin (§D.2 step 5) without a circular stack
  reference.
- `aws_s3_deployment.BucketDeployment` — uploads the built `out/` directory. This is
  the only construct that needs the built assets, and it is **flag-gated**: on the
  offline gate the source is an empty/placeholder asset (or the deployment construct is
  skipped) so `cdk synth` never requires a prior `next build`; on the operator branch
  (`-c buildFrontend=1` / `MAHALO_BUILD_FRONTEND=1`) it points at `frontend/out`. This
  mirrors the `-c buildImage=1` gate (§E).
- `aws_cognito.CfnIdentityPool` (`allow_unauthenticated_identities=True`) +
  `aws_iam.Role` for the unauthenticated identity, with a web-identity trust on
  `cognito-identity.amazonaws.com` and an inline policy granting exactly
  `lambda:InvokeFunctionUrl` on the thin-API function ARN (read from the `api_stack`
  constructor arg), plus `aws_cognito.CfnIdentityPoolRoleAttachment` binding the pool's
  `unauthenticated` role. These are the §B.2 auth resources; they live in this stack so
  the pool, the role→function-ARN policy, and the CloudFront origin are all wired in one
  place. Emit `CfnOutput` **`IdentityPoolId`** = the pool's `ref`, which the operator
  feeds into `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` at build time (§D.2 step 2). Adding
  these constructs to an existing stack does NOT add a template, so the count stays 10
  (§E.1).

**`NEXT_PUBLIC_API_URL` + `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` injection — ordered
operator build (the chicken-and-egg).**
Because the API is NOT behind CloudFront (§B.4), the build CANNOT use an empty/relative
URL; the bundle must carry the real Function URL. And because Next inlines
`NEXT_PUBLIC_*` at `next build` (`api.ts:5`), that URL must be known before the build.
**Decision: a deterministic operator deploy. The frontend build depends on two outputs
that both exist BEFORE the bundle is built** — `RuntimeApiUrl` (from `MahaloApiStack`)
and `IdentityPoolId` + the CloudFront domain (from `MahaloFrontendStack`). Because the
identity pool, the role, and the CloudFront distribution are infrastructure that do NOT
depend on the built `out/` bundle, `MahaloFrontendStack` is deployed FIRST with
`buildFrontend` OFF (placeholder/empty `BucketDeployment` source), which stands up the
pool + distribution and emits their outputs; the bundle upload is a later pass. Ordered:
1. `cdk deploy MahaloApiStack`; read its `RuntimeApiUrl` output (`api_stack.py:107`).
2. `cdk deploy MahaloFrontendStack` (**without** `-c buildFrontend=1`) — provisions the
   S3 bucket, CloudFront distribution, Cognito identity pool + unauthenticated role, and
   the empty bucket deployment. Read its `CfnOutput` **`IdentityPoolId`** and the
   CloudFront distribution domain (also a `CfnOutput`).
3. Set `NEXT_PUBLIC_API_URL=<RuntimeApiUrl>`, `NEXT_PUBLIC_AWS_REGION`, and
   `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID=<IdentityPoolId>`; run `npm run build` in
   `frontend/`.
4. `cdk deploy MahaloFrontendStack -c buildFrontend=1` — re-deploys the same stack,
   now uploading `frontend/out` to the existing bucket/distribution.
5. Re-deploy / update `MahaloApiStack` so its `FunctionUrlCorsOptions.allowed_origins`
   includes the now-known CloudFront domain from step 2. (The CloudFront domain is
   stable after step 2, so steps 3–5 have no further circular dependency; the operator
   may alternatively pin a custom domain via CfnParameter to decouple entirely —
   documented in the runbook.)

This is the deterministic, specified resolution — no "implementer confirms at deploy"
hand-off remains, and the pool id is available (step 2) before the build needs it
(step 3).

### D.3 Error handling (hosting)

Static hosting has no request-time failure modes the app owns beyond CloudFront's
standard 403/404 → `index.html` rewrite (SPA routing). API failures are handled in §B.5.

### D.4 Testability

- Static export correctness: `npm run build` producing `out/` with no errors is the
  offline gate assertion (a build that can't static-export fails here).
- Browser → direct Function-URL call + CORS preflight + SigV4: **integration**, deferred
  operator step.
- `frontend_stack` synth: pytest assertions in `infra-cdk/tests` that the distribution
  has a single S3 origin (no Function-URL origin) and the bucket is private — offline.
- `api_stack` CORS: pytest assertion that `add_function_url` carries the `cors` block
  with the expected methods/headers and the auth type is still `AWS_IAM` — offline.

---

## E. IaC + offline-safety

### E.1 New stacks and wiring

Two new stacks under `infra-cdk/mahalo_infra/`, added to `infra-cdk/app.py` by direct
construct reference (the house pattern — no `Fn.import_value`):
- `gitea_stack.py` → `MahaloGiteaStack` (VPC + EC2 + EBS + SG + SSM param refs).
- `frontend_stack.py` → `MahaloFrontendStack` (S3 + CloudFront single-origin + optional
  BucketDeployment + the Cognito identity pool/unauthenticated role), taking `api_stack`
  as a constructor arg **ONLY to reference the thin-API function ARN
  (`api_stack.function.function_arn`) for the unauthenticated role's
  `lambda:InvokeFunctionUrl` policy**. It does NOT read a Function-URL string from
  `api_stack` (none is exposed — only `self.function`, whose `.function_arn` is used), it
  does NOT set `NEXT_PUBLIC_API_URL` (the operator exports it from the `RuntimeApiUrl`
  CfnOutput, §D.2 steps 1,3), and it does NOT mutate the API's CORS (that is set by
  re-deploying `MahaloApiStack`, §D.2 step 5) — nor is the API wired as a CloudFront
  origin (§D.2).

`app.py` gains two constructor calls after `MahaloApiStack`, passing `env=_ENV`. The
github `MockServiceStack` instance optionally receives the Gitea env + SSM read grant
when `-c giteaMode=real` is set — via the explicit new `gitea_mode`/`gitea_env`/
`gitea_token_param_name` kwargs guarded on `service == "github"`, read once in `app.py`
and passed to the github instance only (full edit in §C.4b). Default off → the four
`MockServiceStack` instances synth byte-identical to today.

### E.2 Offline-safety gates (the automated gate stays OFFLINE)

- **Gitea image:** referenced as `gitea/gitea:1.27.3` in EC2 `UserData` (`docker run`)
  — a string, never a `DockerImageAsset`. No Docker at synth.
- **Bootstrap image:** if packaged as an asset, its build is flag-gated behind the SAME
  `-c buildImage=1` / `MAHALO_BUILD_IMAGE=1` switch used by `runtime_stack.py:56-80`
  and `api_stack.py:47-73`; on the offline branch it is referenced by image URI
  (CfnParameter, default placeholder) exactly like `runtime_stack.py`'s
  `AgentImageUri`. Since the bootstrap runs via `UserData docker run` from the public
  Gitea image, no custom image build is needed at all for the default path.
- **Frontend assets:** `BucketDeployment` is flag-gated behind
  `-c buildFrontend=1` / `MAHALO_BUILD_FRONTEND=1`; the offline synth uses a
  placeholder/empty source so it never requires a prior `next build`.
- **No context lookups:** the VPC is created (not `from_lookup`) so synth needs no
  account/region lookup. No `Vpc.from_lookup`, no `Repository.from_lookup`, no
  `fromLookup` anywhere in the new stacks.
- **Verification commands (offline):** `cdk synth --all` must stay exit 0 with no
  Docker and no creds (today 8 templates; after Task 7, 10). `infra-cdk/tests` pytest
  assertions cover the new stacks. Frontend gate: `cd frontend; npm ci; npm run lint;
  npm run test; npm run build`. tools-lambda gate: the existing 94 tests + new
  real-mode unit tests, all with `httpx` mocked.

### E.3 Teardown posture

All new persistent resources follow the house `RemovalPolicy.DESTROY`
(`mock_service_stack.py:84`): the Gitea EBS volume, the S3 bucket
(`auto_delete_objects=True`). The Gitea volume DESTROY is called out explicitly —
teardown wipes repos, acceptable because `bootstrap.sh` re-seeds them; an operator may
flip a `RetainGiteaData` CfnParameter to `RETAIN` to keep repos across a monthly reset.

### E.4 What the operator does live (documented, NOT run here)

A `docs/.agents/tasks/task7-deploy-runbook.md` (authored in the implementation task,
not now) will capture: create the SSM SecureString params; `cdk deploy MahaloGiteaStack`
(builds the EC2 host, UserData runs Gitea + bootstrap); confirm Gitea healthy and the
seed repo present; `cdk deploy MahaloMockGithubStack -c giteaMode=real` to flip the
github Lambda to Gitea. The Cognito identity pool + unauthenticated role are **CDK,
owned by `MahaloFrontendStack`** (§B.2/§D.2) — NOT a manual step — so the frontend
deploy is the specified ordering (§D.2): (1) `cdk deploy MahaloApiStack`, read
`RuntimeApiUrl`; (2) `cdk deploy MahaloFrontendStack` without `-c buildFrontend=1` to
stand up the bucket/distribution/identity-pool and read its `IdentityPoolId` +
CloudFront-domain outputs; (3) set `NEXT_PUBLIC_API_URL` + `NEXT_PUBLIC_AWS_REGION` +
`NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` and `npm run build` the frontend; (4)
`cdk deploy MahaloFrontendStack -c buildFrontend=1` to upload `frontend/out`; (5)
re-deploy `MahaloApiStack` so its Function-URL CORS `allowed_origins` includes the
CloudFront domain from step 2. Finally smoke-test chat + HITL write end-to-end
(browser → CloudFront static app → **direct** SigV4 call to the Function URL). None of
this runs in the offline gate.

---

## Summary of decisions (A–E)

- **A.** Port the **chat surface only**. Verbatim: `ProposalCard`, `ChatInput`,
  `ChatMessage`, `ContextPanel`, `chatSuggestions(+test)`, all tooling/config. Ported
  **with a trim**: `src/types/index.ts` (keep `UserRole` + the full `Project` interface
  used by `chatSuggestions.ts`/its test; drop `User`/`HealthStatus`/`Integration`/
  `ProjectProposal`) and `globals.css` (one `@theme` font-stack block). Change:
  `services/api.ts` (base URL + SigV4 auth), `chat/page.tsx` (thread `interrupt_id`
  from `proposal.interrupt_id`, make `systems_queried` optional, drop
  project/connection/suggestions deps), `layout.tsx` (drop providers), `page.tsx`
  (redirect to chat). Drop: auth flow, dashboard+widgets, connections (incl. the
  `[id]` dynamic route), all contexts. Env: `NEXT_PUBLIC_API_URL` (+ region, identity
  pool id). **No thin-API/Runtime change** — the interrupt id is already on the wire
  inside `proposal` (`runtime_app.py:159`).
- **B.** Cognito **unauthenticated Identity Pool** → temp IAM creds → **in-browser
  SigV4** (`aws4fetch` + `@aws-sdk/credential-providers`), keeping the edge at
  `AuthType=AWS_IAM`. Smallest real approach consistent with the "AWS_IAM now, Cognito
  at dev" stance. The browser calls the Function URL **directly** (NOT through
  CloudFront — signing for the CloudFront host would 403 on the `Host`-rewrite); CORS is
  solved by `FunctionUrlCorsOptions` on the thin API allowing the CloudFront origin and
  the SigV4 headers. (Resolves review Finding 1.)
- **C.** Gitea on **EC2 + EBS** (SQLite), single always-on instance, container by image
  reference; bootstrap ported into `gitea/` runs via `UserData` (CLI-first-admin).
  github Lambda gets a ported `GiteaBackend` behind **`GITHUB_MODE=real`** (mock stays
  default; 94 tests stay green); token via **SSM SecureString**; reachability is
  **public endpoint, Lambda stays non-VPC**.
- **D.** Frontend on **S3 + CloudFront** as a Next **static export** (`output:"export"`,
  enabled by dropping the dynamic route). CloudFront is a **single S3 origin** (serves
  the static bundle only — the API is reached directly, §B). The **Cognito identity pool
  + unauthenticated role live in `frontend_stack`** (`CfnOutput IdentityPoolId`), so the
  auth resources are pure CDK, not a manual step. `NEXT_PUBLIC_API_URL` carries the real
  Function URL via a specified operator sequence: deploy API → read `RuntimeApiUrl` →
  deploy frontend stack (no build flag) to stand up the pool/distribution and read
  `IdentityPoolId` + CloudFront domain → build frontend → re-deploy frontend
  `-c buildFrontend=1` → re-deploy API CORS with the CloudFront origin. `BucketDeployment`
  flag-gated. Fonts switched off `next/font/google` to a system stack so the
  `npm run build` offline gate needs no network.
- **E.** New `MahaloGiteaStack` + `MahaloFrontendStack` wired in `app.py` by direct
  construct reference (8 → 10 templates). `cdk synth --all` stays Docker/cred-free:
  images by reference, asset builds behind `-c buildImage=1`/`-c buildFrontend=1`, no
  `fromLookup`, VPC created not looked up. `RemovalPolicy.DESTROY` house style (Gitea
  volume overridable to RETAIN). Deploy is a documented, deferred operator runbook.

---

## Responses to design review (iteration 2)

Review: `docs/.agents/tasks/task7-design-review.md` /
`docs/.agents/tasks/task7-design-review.json` — verdict CHANGES_REQUESTED
(2 HIGH, 3 MEDIUM, 4 NIT). Every finding is ADDRESSED (none backlogged, none ignored);
all resolutions stay inside the original requirements (chat-surface-only port, mock
path default, AWS_IAM edge, offline gate, no deploy).

1. **[HIGH] Same-origin SigV4 ↔ CloudFront Host-header mismatch (§B.4, §D.2).**
   ADDRESSED by picking review fix (a): the API is **no longer routed through
   CloudFront**. The browser calls the Function URL **directly** and signs SigV4 for its
   real host; CORS is solved with `FunctionUrlCorsOptions` on the thin API allowing the
   CloudFront frontend origin + the `Authorization`/`X-Amz-*` headers (§B.4 rewritten).
   CloudFront is now a single-origin static distribution (§D.1/§D.2). The same-origin
   claim and the "implementer confirms at deploy" hand-off are removed; `NEXT_PUBLIC_API_URL`
   now carries the real Function URL via the specified two-phase operator build (§D.2).
2. **[HIGH] Offline `npm run build` vs `next/font/google` (§A, §D.1, §E.2).** ADDRESSED
   by review fix (b): `layout.tsx` drops the `Geist`/`Geist_Mono` `next/font/google`
   imports and uses a **system font stack** via a small `@theme` block in `globals.css`.
   Verified this is a visual no-op — `globals.css` is `@import "tailwindcss";` only and
   never referenced the `--font-geist-*` variables (§A.3 edit, §A.2 note). The "no
   network" gate becomes literally true.
3. **[MEDIUM] Approve handlers can't read `interrupt_id` without a lookup (§A.3).**
   ADDRESSED: handler signatures change to `handleApprove(msg: Message)` /
   `handleReject(msg: Message)` (the render site already has `msg` in scope —
   `onApprove={() => handleApprove(msg)}`), reading `msg.proposal?.interrupt_id`
   directly; no `messages.find(...)` needed. Early-returns when the id is absent
   (§A.3 edit 1, §A.7).
4. **[MEDIUM] `status: "pending_approval"` never mentioned (§A.3, §A.7).** ADDRESSED:
   `status: string` is added to the `ChatApiResponse` type and the approve/reject card
   renders only when `status === "pending_approval"` AND `proposal` is present; any
   other status renders as a plain assistant message (§A.3 edit 2, §A.7).
5. **[MEDIUM] Gitea real mode: unconditional DynamoDB Store/seed + no Gitea param on
   `build_router` (§C.4).** ADDRESSED: `handler._get_router` reads `GITHUB_MODE` at
   module scope and **short-circuits before the `Store`/`ensure_seeded()`** in real
   mode (returns `store=None`, so `lambda_handler`'s seed call is guarded); Gitea env is
   read at module scope in `handler.py` (named vars listed); a new
   `routes.build_gitea_router(backend)` is added while `build_router(store, token)` is
   left unchanged. Token comes from an SSM parameter *name* resolved via boto3 at cold
   start (§C.4).
6. **[NIT] `aws4fetch` vs `@aws-sdk/*` both "chosen" and "or" (§B.3).** ADDRESSED: final
   pinned deps are exactly `aws4fetch` **and** `@aws-sdk/credential-providers` (the
   latter for `fromCognitoIdentityPool`); the `@aws-sdk/signature-v4` +
   `@aws-crypto/sha256-js` packages are dropped (§B.3).
7. **[NIT] "94 tools-lambda tests" not confirmed (§C.4, §E.2).** ADDRESSED: the count is
   confirmed against the recorded baseline (`STATUS.md:39,41,42,47`, `PLAN.md:52,88,134`,
   `CONTINUATION.md:114,211,250` all cite "tools-lambdas 94 passed"); a live
   `pytest --collect-only` could not run here because `moto` is not installed in the
   authoring environment, so the implementation task re-runs the suite in the dev venv
   (new §C.4a).
8. **[NIT] `src/types/index.ts` trim list not concrete (§A.2).** The iteration-2 pass
   resolved this by proposing to **drop `src/types/index.ts` entirely** on the claim that
   no kept file imports it. **That claim was WRONG and the iteration-3 review (Finding 1)
   caught it** — `chatSuggestions.ts` and its test DO import `Project`/`UserRole` from
   `@/types`. See iteration-3 Response 1 below for the corrected decision (port a trimmed
   `index.ts`).
9. **[NIT] Sidebar deferred to implementer (§A.5).** ADDRESSED: **drop `Sidebar.tsx`
   entirely**; the one-route demo keeps only the chat page's existing in-page header as
   app-title chrome (§A.5).

---

## Responses to design review (iteration 3)

Review: `docs/.agents/tasks/task7-design-review.md` /
`docs/.agents/tasks/task7-design-review.json` — verdict CHANGES_REQUESTED
(0 HIGH, 1 MEDIUM, 2 NIT). All 3 findings are ADDRESSED (none backlogged, none ignored);
all resolutions stay inside the original requirements (chat-surface-only port, mock path
default, AWS_IAM edge, offline gate, no deploy).

1. **[MEDIUM] Dropping `src/types/index.ts` breaks the verbatim-ported
   `chatSuggestions.ts` and its test (§A.2).** ADDRESSED — the finding is factually
   correct (verified against the read-only source: `chatSuggestions.ts:18` imports
   `Project, UserRole` and uses both structurally; `chatSuggestions.test.ts:7` imports
   `Project` and builds a full `Project` fixture). **Decision reversed:**
   `src/types/index.ts` is now **ported WITH A TRIM**, not dropped — it keeps exactly
   `UserRole` and the full `Project` interface (all fields, because the test fixture sets
   every field and a subset would fail type-checking), dropping only `User`,
   `HealthStatus`, `Integration`, `ProjectProposal`. §A.2 relists it under "ports with a
   trim" (alongside `globals.css`), and adds the re-grep-`@/types`-after-trimming check.
   This keeps `npm run test`/`npm run build` green (the declared offline gate).
2. **[NIT] Gitea image pin stated inconsistently (stack block vs §C.1/C.2/E.2).**
   ADDRESSED: a single concrete tag — the mahalo-dock-proven **`gitea/gitea:1.27.3`** —
   is now used verbatim in the "Technology stack (LOCKED on approval)" block and in
   §C.2, §C.3, and §E.2. The `1.24` value and the `<pin>` placeholders are removed.
3. **[NIT] Gitea security-group default ingress posture unspecified (§C.2/§C.5).**
   ADDRESSED: §C.2 now states the **exact default the stack synthesizes** — SSH (22)
   restricted to the `AdminCidr` parameter, and Gitea HTTP/API (3000) defaulting to
   `0.0.0.0/0`, protected by the Gitea API token, with an optional `GiteaIngressCidr`
   parameter (default `0.0.0.0/0`) for operator hardening to a prefix list / known CIDR.
   §C.5 is corrected to note that a non-VPC Lambda has no fixed egress IP, so "restrict
   to the Lambda's egress" is not expressible and was withdrawn; the synthesized default
   is `0.0.0.0/0` on 3000.

---

## Responses to design review (iteration 4)

Review: `docs/.agents/tasks/task7-design-review.md` /
`docs/.agents/tasks/task7-design-review.json` — verdict CHANGES_REQUESTED
(0 HIGH, 1 MEDIUM, 3 NIT). All 4 findings are ADDRESSED (none backlogged, none ignored);
all resolutions stay inside the original requirements (chat-surface-only port, mock path
default, AWS_IAM edge, offline gate, no deploy). Each was verified against the real
source before editing.

1. **[MEDIUM] `MockServiceStack` is a shared loop construct — the github-only Gitea env +
   SSM grant was underspecified (§C.4, §E.1).** ADDRESSED — verified the finding
   (`mock_service_stack.py:60-115` is one generic construct built 4× in `app.py:23-31`'s
   loop; constructor `(service, default_token=None, **kwargs)`, fixed env dict, single
   `table.grant_read_write_data` grant). New **§C.4b** pins it: three new optional kwargs
   (`gitea_mode: bool = False`, `gitea_env: dict|None = None`,
   `gitea_token_param_name: str|None = None`), the env/SSM-grant branch **guarded by
   `service == "github" and gitea_mode`** (with the exact code), and `app.py` reading
   `-c giteaMode=real` **once** and passing the Gitea config to the github instance only.
   Stated explicitly that the default (flag unset) leaves all four instances
   byte-identical to today → 8-template synth (10 with the two new stacks) and 94
   tools-lambda tests unaffected. §C.4's closing paragraph and §E.1 now cross-reference
   §C.4b instead of hand-waving.
2. **[NIT] Cognito identity-pool provisioning owner left as "CDK or manual" (§B.2, §D.2,
   §E.4).** ADDRESSED — picked the recommended fork: the identity pool + unauthenticated
   role (granted `lambda:InvokeFunctionUrl` on the thin-API function ARN) are provisioned
   **in `frontend_stack.py`** as `aws_cognito.CfnIdentityPool` +
   `CfnIdentityPoolRoleAttachment` + an `aws_iam.Role`, emitting
   `CfnOutput IdentityPoolId`. §B.2 and §D.2 now name the constructs and the output; §D.2
   step 2 reads the output into `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` at build time; §E.4
   drops the "or manual step" wording. Confirmed the pool lives **inside** `frontend_stack`
   so the template count stays **10** (stated in §B.2, §D.2, §E.1). The §D.2 operator
   sequence is reordered so `frontend_stack` deploys FIRST without `-c buildFrontend=1`
   (standing up the pool/distribution and emitting their outputs) BEFORE the frontend
   build needs the pool id — removing the ordering gap the single-pass sequence had.
3. **[NIT] `interrupt_id` must also be on the page-local `Proposal` type; A.4 line
   citations drift (§A.3 edit 1, §A.4).** ADDRESSED — verified the page-local `Proposal`
   is at `chat/page.tsx:23-28` (not `27-32`) and has no `interrupt_id`. §A.3 edit 1 now
   cross-references the §A.4 additive field explicitly ("requires `interrupt_id?: string`
   on the page-local `Proposal` at `chat/page.tsx:23-28`, else `msg.proposal?.interrupt_id`
   fails `tsc`"), and §A.4 corrects the citation to `chat/page.tsx:23-28` and states the
   two are ONE coupled edit (field added to both the page-local and `ProposalCard`
   interfaces together).
4. **[NIT] `systems_queried` removal didn't state the chip's fate (§A.3 edit 2).**
   ADDRESSED — verified `ChatMessage.tsx:30` already guards the chip on
   `!isUser && systemsQueried && systemsQueried.length > 0`. §A.3 edit 2 now states:
   `ChatApiResponse.systems_queried` is made optional; the thin API never sends it so
   `Message.systemsQueried` is always `undefined`; `ChatMessage` already renders no chip
   when the prop is absent, so **no change to `ChatMessage.tsx` is needed** (with a note
   to re-add the guard if a future edit removes it). The "UI preserved verbatim" claim is
   now unambiguous.

---

## Responses to design review (iteration 5)

Review: `docs/.agents/tasks/task7-design-review.md` /
`docs/.agents/tasks/task7-design-review.json` — verdict CHANGES_REQUESTED
(0 HIGH, 1 MEDIUM, 0 NIT). The single finding is ADDRESSED (not backlogged, not ignored);
the resolution stays inside the original requirements (chat-surface-only port, mock path
default, AWS_IAM edge, offline gate, no deploy) and was verified against the real source
(`infra-cdk/mahalo_infra/api_stack.py`) before editing.

1. **[MEDIUM] §D.2 / §E.1 — stated reason for passing `api_stack` into `frontend_stack`
   is mechanically wrong (not implementable as written).** ADDRESSED — the finding is
   correct on all three points, verified against `api_stack.py`: (1) a CDK stack cannot
   set a shell env var for a later `npm run build`; (2) the CORS block lives on
   `MahaloApiStack`'s `add_function_url` call and is set by re-deploying that stack
   (§D.2 step 5), not by `frontend_stack`; (3) `api_stack` exposes `self.function` (so
   `.function_arn` is reachable) but **no `function_url` string attribute** — the URL is
   a local `url = fn.add_function_url(...)` surfaced only via the `RuntimeApiUrl`
   CfnOutput. **Both the §D.2 and §E.1 sentences are rewritten** to state the single real
   reason `frontend_stack` takes `api_stack`: to reference the thin-API function ARN
   (`api_stack.function.function_arn`) for the unauthenticated role's
   `lambda:InvokeFunctionUrl` policy. Both now state explicitly that
   `NEXT_PUBLIC_API_URL` is set by the **operator** from the `RuntimeApiUrl` CfnOutput
   (§D.2 steps 1,3) and the API's CORS `allowed_origins` is set by **re-deploying
   `MahaloApiStack`** (§D.2 step 5) — neither done by `frontend_stack`. The optional
   `self.function_arn = fn.function_arn` handle on `api_stack.py` is noted as an
   implementer convenience (not required, since the `Function` construct is already
   exposed). No other behavior changes; the §D.2 operator sequence and the 10-template
   synth count are unaffected.

---

## Responses to design review (iteration 6)

Review: `docs/.agents/tasks/task7-design-review.md` /
`docs/.agents/tasks/task7-design-review.json` — verdict CHANGES_REQUESTED
(0 HIGH, 1 MEDIUM, 3 NIT). All 4 findings are ADDRESSED (none backlogged, none ignored);
all resolutions stay inside the original requirements (chat-surface-only port, mock path
default, AWS_IAM edge, offline gate, no deploy). Each was verified against the real
read-only source (`mahalo-dock/frontend/src/app/(protected)/chat/page.tsx`,
`src/lib/chatSuggestions.ts`, `src/services/api.ts`, `src/app/page.tsx`) before editing.

1. **[MEDIUM] §A.3 edit 3 / §A.1 / §A.2 — `buildSuggestions` arguments and the
   empty-state UI left underspecified after the three contexts are dropped.** ADDRESSED
   — the finding is correct, verified against source:
   `templateSuggestions` calls `buildSuggestions({ role: user?.role, project:
   scopedProject, connectedTypes })` (all three from the dropped `useAuth`/`useProjects`/
   `useConnections`), and `buildSuggestions` collapses to `FALLBACK_SUGGESTIONS` when
   `connectedTypes` is empty; the empty-state also reads `!isConfigured` (the
   "Connections Required" block), `isConfigured` (the scope chip), and
   `/chat/suggestions` (the Generate-more button). **§A.3 edit 3 is rewritten to pin the
   exact call** — `buildSuggestions({ role: "developer", project: null, connectedTypes:
   ["github", "jira"] })` — with the reasoning for choosing a representative GitHub+Jira
   developer set over the empty-arguments collapse to the two generic fallbacks. It now
   **lists every state/derived value removed** (`user`, `activeProject`,
   `selectedProjects`, `integrations`, `isConfigured`, `connectionsLoading`,
   `scopedProject`, `scopedProjectId`, `connectedTypes`, `suggestionSignature`,
   `displayedSuggestions`, `llmSuggestions`, `generatingSuggestions`,
   `handleGenerateSuggestions`, `sessionScopeRef`/`scopeChanged`) and **specifies the
   empty state**: the `!isConfigured` "Connections Required" block is deleted, the
   `isConfigured` "How can I help you today?" block becomes unconditional (gated only on
   `messages.length === 0`) mapping `templateSuggestions`, the "✨ Generate more" button
   is removed, `ChatInput`'s `disabled` reduces to `isLoading`, and the header scope chip
   is removed leaving the "AI Assistant" title/subtitle. §A.1 gains a "Scope of verbatim
   for the empty state" paragraph making the preserved-vs-changed boundary explicit so
   the "UI preserved verbatim" claim is accurate.
2. **[NIT] §B.3 — in-browser SigV4 body-signing detail implicit.** ADDRESSED —
   verified the source `api.ts` `request()` forwards `options.body` and the
   `api.post/put` wrappers `JSON.stringify(body)`. §B.3 now states explicitly: pass the
   serialized JSON body **into** `aws.fetch(url, { method, headers, body:
   JSON.stringify(body) })` so the signed `X-Amz-Content-Sha256` covers it; do NOT set or
   mutate `headers`/`body` after signing (else a 403 at the edge). It names the signing
   service literal (`"lambda"`) and states the region comes from `NEXT_PUBLIC_AWS_REGION`.
3. **[NIT] §A.3 `src/app/page.tsx` "redirect/landing" vague for a static export.**
   ADDRESSED — verified the source `page.tsx` is a `"use client"` component doing
   `router.push(...)` in a `useEffect` (export-safe). §A.3 now states: keep it a
   `"use client"` component using `useRouter().push("/chat")` in a `useEffect`; do NOT
   use the server `redirect()` helper (not export-compatible). Notes the equivalent
   alternative (render `<ChatPage/>` at `/`, drop `/chat`) with the `useEffect` push as
   the default.
4. **[NIT] Minor line-citation drift.** ADDRESSED (no substantive design change, per the
   finding) — the citations touched in this pass are re-anchored to symbols and the
   corrected lines verified against source: `api.ts` base URL is in the
   `const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || ...` line (the file opens
   with a JSDoc banner, so it is line 6, not 5) and the Bearer block is the
   `sessionStorage.getItem("mahalo3_token")` → `Authorization` assignment inside
   `request()` (≈`:51-57`); `chatSuggestions.ts`'s `@/types` import is the
   `import type { Project, UserRole } from "@/types"` line (14); the github `handler.py`
   seed path is `_get_router`/`lambda_handler`'s `store.ensure_seeded()` call and
   `routes.py`'s `GITHUB_MODE` read is in `build_router`. Readers should treat cited line
   numbers as approximate and re-locate by the named symbol; every claim the citations
   support was re-verified and holds.
