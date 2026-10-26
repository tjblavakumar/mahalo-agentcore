# FEATURE (NEXT SESSION) — custom chart-based dashboard

Captured 2026-10-25 for a future session. NOT started. The current demo (real
Gitea + all four services) is complete and live; this is the next feature.

## What the user asked for (their words, paraphrased + confirmed)

The current agent dashboard only renders TEXT. The user wants a real,
chart-based, user-customizable dashboard:

1. Put a **chat textbox on the Dashboard screen**. The user types what they want
   to see (e.g. "story points per sprint for PAY", "open PRs by author").
2. The agent turns that request into a **chart or table** and renders it as a
   widget on the dashboard.
3. **STRICT output contract:** the dashboard only ever produces one of:
   **line chart, area chart, bar chart, or table. NO text/prose output** on the
   dashboard. (Text answers belong on the Chat screen, not here.)
4. The user can **SAVE** a produced chart/table as a persistent widget on their
   dashboard.
5. The user can **DELETE** a widget they no longer want.
6. Result: each persona builds and keeps their **own custom dashboard** of
   saved charts/tables.

## Reference: how mahalo-dock does it (and why this is NOT a straight port)

- mahalo-dock frontend: `<FALLBACK_ROOT>/mahalo-dock/frontend/src/components/dashboard/`
  — `DashboardGrid.tsx` + 8 FIXED widgets (KeyMetrics, MyPRs, MyStories,
  Portfolio, ProjectStatus, RecentCommits, SprintBoard, Velocity).
- It uses **react-grid-layout** for a draggable/resizable widget grid.
- CRITICAL: mahalo-dock has **NO charting library** (no recharts/d3/chart.js in
  package.json). Its "charts" are hand-rolled with CSS/divs (bar heights etc.),
  and the widget SET is fixed + hardwired to backend routes.
- So we CANNOT just port it: our ask is user-AUTHORED, chart-strict,
  save/delete-able widgets — more capable than mahalo-dock's fixed grid. Reuse
  the grid LAYOUT idea (react-grid-layout) if helpful, but the widget content and
  the "describe it in chat -> get a chart" flow are new.

## Current state of our dashboard (what's being replaced)

- `mahalo-agentcore/frontend/src/` — Next.js 16.3.3 static export (output:"export").
  The current Dashboard is the task7d "agent-driven dashboard": it calls the
  existing thin API `/chat` with a "build my dashboard" prompt and renders the
  synthesized **markdown/prose** result full-width. PM has a project multi-select
  (PAY/CART/AUTH/PROD/ORD, defaults to PAY). THAT prose rendering is what the
  user wants replaced with strict charts.
- Backend: thin API Function URL
  https://dkgwvy2h42xkejgmjc3tsvi4ku0qcyuz.lambda-url.us-east-1.on.aws/ , persona
  via X-Mahalo-Persona header, two-call HITL for writes. The agent runs on
  AgentCore Runtime over the four systems (mock Jira/Confluence/ServiceNow + real
  Gitea).

## USER DECISIONS SO FAR (2026-10-25)

- **Q1 (chart data contract): DECIDED — go with recommendation (a):** strict
  JSON-envelope over the existing /chat + client-side validation, no new backend
  for the viz data. Never fall back to text.
- **Q2 (charting library): DECIDED — go with recommendation:** pick a lib
  compatible with Next.js 16 static export + React 19 (recharts the likely
  candidate; verify compat before committing).
- **Q3 (persistence): DECIDED — DynamoDB per persona + 2 thin-API routes +
  seeded default dashboard.** Durable server-side store (never empty): a
  DynamoDB table keyed by personaId holds each persona's saved widgets (chart
  spec JSON + grid x/y/w/h). Two new thin-API routes: GET /dashboard/widgets
  (load on open) and PUT /dashboard/widgets (save on add/delete/move/resize).
  Seed a role-appropriate DEFAULT dashboard per persona so a first-time login is
  already populated; once the user customizes, their saved set replaces the
  default. Default starters (user approved "your assumption is good"):
    - PM (Marcus Chen): story points by sprint (bar); open PRs by project (bar).
    - Dev (Lava Dev): my open PRs (table); my stories by status (bar).
    - Exec (David Kim): delivery health by project (bar/line).
  Rejected: localStorage (per-browser, clearable); SQLite on the Gitea box
  (needs an API anyway + stateful store on a Gitea host); S3-JSON (viable but
  DynamoDB fits the existing stack better).
- **Q4 (layout): DECIDED — draggable + resizable grid** (use react-grid-layout,
  the same lib mahalo-dock uses; verify Next.js 16 static-export + React 19
  compat). Each widget is a card with a delete control; positions/sizes persist
  as part of the saved dashboard (so layout survives re-login too).
- **Q5 (strict-output enforcement): DECIDED.** If the user's dashboard request
  cannot be answered as a chart or table, the dashboard does NOT render prose —
  it shows a short message telling the user to use the main Chat for generic/
  text answers. The dashboard chatbox is EXPLICITLY scoped to
  creating/customizing charts & tables, and the UI must make clear that saved
  charts persist and are there on next login. (Add helper/placeholder text in the
  dashboard chatbox to set this expectation.)

## Key design decisions to make NEXT SESSION (confirm with user)

1. **How does the agent return chart DATA (not prose)?** The dashboard needs
   structured data, not markdown. Options:
   a. A dedicated prompt/contract: instruct the agent (via the dashboard's /chat
      call) to respond ONLY with a strict JSON envelope describing the viz, e.g.
      `{"type":"bar|line|area|table","title":...,"xKey":...,"series":[...],"rows":[...]}`
      and the frontend renders it. Reuse the existing /chat; no new backend route.
      Parse + validate the JSON; if it isn't valid chart JSON, show an error
      (never fall back to text — honor the strict contract). This is likely the
      lightest path and keeps the "no new backend" posture.
   b. A new thin-API route (e.g. /dashboard/spec) that wraps the agent with a
      structured-output system prompt + schema validation server-side. Cleaner
      contract but adds a backend route + redeploy.
   RECOMMENDATION to propose: start with (a) — a strict JSON-envelope prompt +
   client-side validation — unless structured output proves unreliable, then (b).

2. **Charting library.** Our frontend has NO chart lib today. Pick one that works
   with Next.js 16 static export + React 19. Candidates: recharts (simple, common),
   or a lightweight alternative. MUST verify SSR/static-export compatibility and
   React 19 support. (MUST read frontend/node_modules/next/dist/docs/ before
   Next.js code per frontend/AGENTS.md — this Next.js has breaking changes.)

3. **Where are saved dashboards persisted? (REOPENED — decide tomorrow.)**
   HARD REQUIREMENT from the user: saved widgets must persist so the user never
   sees an empty dashboard on return. So localStorage-only is OUT (per-browser,
   clearable). The frontend is a STATIC export on S3/CloudFront with NO server of
   its own, so "durable persistence" means a backend store the dashboard reads/
   writes via the thin API. Options to weigh:
   a. **DynamoDB keyed by personaId**, via two new thin-API routes
      (GET/PUT /dashboard/widgets). Fits the existing AWS stack (the mocks already
      use DynamoDB + CDK); survives across browsers/devices; naturally per-persona.
      Adds a small table + 2 routes + a thin-API redeploy. LIKELY RECOMMENDATION.
   b. **SQLite on the Gitea EC2 host** (or a tiny file) — the user mentioned
      sqlite. Possible but awkward: the frontend can't reach a DB directly; it'd
      still need an API in front, and we'd be adding a stateful store on a box
      meant for Gitea. Not recommended vs. (a).
   c. **A JSON file in S3 per persona**, read/written via a thin-API route (or a
      presigned GET for read + an API PUT for write). Simplest store, no table;
      slightly clunkier concurrency but fine for a single-user demo.
   d. **Seed a DEFAULT dashboard** (a few starter widgets per persona) so even a
      brand-new user sees a populated dashboard immediately — addresses the
      "never empty" ask directly, and composes with (a)/(c). Strongly consider
      combining a default-seed with whichever durable store we pick.
   RECOMMENDATION to propose tomorrow: (a) DynamoDB per persona via 2 thin-API
   routes, PLUS (d) a seeded default dashboard per persona so it's never empty.
   Confirm with the user; this adds a thin-API route + table + redeploy (accept).

4. **Widget layout:** fixed stacked cards vs. react-grid-layout draggable grid.
   Draggable is nicer but heavier; confirm whether drag/resize is wanted or if a
   simple responsive grid of cards (with a delete button per card) is enough.

5. **Strict-output enforcement:** if the user's request can't be answered as a
   chart/table (e.g. "summarize the sprint"), what happens? Proposal: the widget
   shows a clear "couldn't render this as a chart/table — try asking for a metric
   over a dimension" message, NOT prose data. Confirm.

## Scope / constraints to honor

- Demo-only; personas are hardcoded; mock data (+ real Gitea). Not security-
  sensitive.
- Keep it frontend-first where possible (reuse the deployed /chat). Avoid new
  backend unless decision #1b/#3b is chosen.
- Next.js 16 static export: MUST read frontend/node_modules/next/dist/docs/
  before writing Next.js code (frontend/AGENTS.md rule — breaking changes).
  vitest env is `node` (pure-logic tests only, no jsdom) unless that's changed.
- Frontend deploy is MANUAL via the builder (the builder --phase frontend is
  buggy): on the builder, cd frontend; export NEXT_PUBLIC_API_URL=<thin-api>
  NEXT_PUBLIC_AWS_REGION=us-east-1; npm install; npx next build; aws s3 sync out
  s3://mahalofrontendstack-frontendbucketefe2e19c-hgoxy5hs23db/ --delete; aws
  cloudfront create-invalidation --distribution-id E1SXSYT3Z9NSTZ --paths '/*'.
  (See docs/CONTINUATION.md for the full builder/credential dance.)

## Suggested delivery

A workflow: investigate the current Dashboard component + task7d design, decide
the 5 questions above (design loop), implement (chart lib + strict JSON contract
+ chat box + save/delete + persistence), offline-gate (npm build + lint +
vitest), then manual frontend deploy via the builder. Headline acceptance:
logged in as a persona, type a request on the Dashboard, get a strict
chart/table, SAVE it, see it persist on reload, DELETE it.
