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

3. **Where are saved dashboards persisted?** Options:
   a. **Browser localStorage per persona** (simplest; demo-only; no backend). Each
      persona's saved widgets live in the browser. RECOMMENDED for a demo.
   b. Backend persistence (DynamoDB keyed by persona) — survives across browsers/
      devices but adds a thin-API route + table + redeploy. Only if the user wants
      cross-device persistence.
   RECOMMENDATION to propose: (a) localStorage keyed by personaId, unless the user
   wants server-side persistence.

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
