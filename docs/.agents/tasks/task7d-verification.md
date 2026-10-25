# task7d — OFFLINE GATE Verification

**Scope:** task7d demo-frontend features (Dashboard + Connections screens, left-nav Sidebar, agent-driven synthesized dashboard reusing the existing `/chat` endpoint).

**Nature of this document:** This is **OFFLINE verification only**. It confirms that the new frontend code installs, lints, tests, and builds to a static export (`frontend/out/`) on a clean local shell with **no `MAHALO_*` environment variables set**. The live deploy (building and publishing via the EC2 builder) is a **separate operator step performed afterward** and is **not** covered here.

- **Workspace root:** `<WORKSPACE_ROOT>`
- **Runner dir:** `frontend/`
- **Shell:** Windows PowerShell
- **Node:** v24.13.0
- **npm:** 11.6.2
- **Env:** clean shell, confirmed **no `MAHALO_*` variables present** (`Get-ChildItem Env: | Where-Object { $_.Name -like 'MAHALO*' }` returned nothing)
- **Git:** no commits/pushes performed as part of this gate.

---

## Gate result summary

| # | Command (run from `frontend/`) | Result | Key output |
|---|--------------------------------|--------|------------|
| 1 | `npm ci` | **PASS** | `added 475 packages` (lockfile was auto-corrected — see note) |
| 2 | `npm run lint` | **PASS** | eslint clean, zero errors/warnings |
| 3 | `npm test -- --run` | **PASS** | `Test Files 5 passed (5)`, `Tests 29 passed (29)` |
| 4 | `npm run build` | **PASS** | static export, 6 routes prerendered as static content |

**Routes present in export:** `/dashboard` and `/connections` are prerendered — confirmed in both the build route listing and the emitted files under `frontend/out/`.

**Overall: GATE GREEN.** All four steps pass; new routes prerender; existing tests still pass; zero backend changes.

---

## Command-by-command detail (real output)

### 1. `npm ci`

```
> npm ci
added 475 packages in 14m
```

Exit code: `0` — **PASS**.

**Note on the lockfile:** `npm ci` succeeded (it did **not** fail, so the `npm install` fall-back was not needed). However, it **rewrote `frontend/package-lock.json`** (341 deletions). Reason: the committed lockfile at `HEAD` still listed two dependencies — `@aws-sdk/credential-providers@3.1154.0` and `aws4fetch@1.0.20` — that are **not** present in the committed `frontend/package.json`. In other words, the lockfile was committed **out of sync** with `package.json` (those deps had been removed from `package.json` but the lockfile was not regenerated). `npm ci` installed the set defined by `package.json` and dropped the stale entries, producing a corrected lockfile. `package.json` itself is unchanged vs `HEAD`. This is a pre-existing inconsistency, not a change introduced by the gate. The corrected lockfile is left as an **uncommitted working-tree change** (no commit was made per instructions).

> Operational note: the very first `npm ci` invocation was killed by the command-runner timeout mid-install, leaving a partial `node_modules` and an orphaned `node` process holding file locks (surfaced as `ENOTEMPTY` / access-denied on retry). Recovery: stopped the orphaned process, removed `node_modules`, and re-ran `npm ci` cleanly to the `added 475 packages` result above. This is an environment/timeout artifact, not a code problem — no source files were changed to resolve it.

### 2. `npm run lint`

```
> frontend@0.1.0 lint
> eslint
```

Exit code: `0` — **PASS**. No lint errors or warnings.

### 3. `npm test -- --run` (vitest)

```
> frontend@0.1.0 test
> vitest run --run

 RUN  v2.1.9 <WORKSPACE_ROOT>/frontend
 ✓ src/lib/chatSuggestions.test.ts (10 tests) 14ms
 ✓ src/services/api.test.ts (4 tests) 64ms
 ✓ src/lib/projects.test.ts (8 tests) 11ms
 ✓ src/lib/personas.test.ts (5 tests) 6ms
 ✓ src/lib/connections.test.ts (2 tests) 7ms

 Test Files  5 passed (5)
      Tests  29 passed (29)
   Duration  4.77s
```

Exit code: `0` — **PASS**. All 29 tests across 5 files pass. This covers both the **new** task7d suites (`projects.test.ts`, `connections.test.ts`) and the **pre-existing** suites (`chatSuggestions.test.ts`, `api.test.ts`, `personas.test.ts`) — confirming nothing existing was broken.

(A `Vite CJS Node API is deprecated` line appears on stderr; it is an informational deprecation warning only and does not affect the result — exit code `0`.)

### 4. `npm run build` (static export to `frontend/out/`)

```
> frontend@0.1.0 build
> next build

▲ Next.js 16.3.3 (Turbopack)
✓ Running next.config.ts took 203ms
  Creating an optimized production build ...
✓ Compiled successfully in 6.3s
  Running TypeScript ...
  Finished TypeScript in 7.4s
  Collecting page data ...
✓ Generating static pages (8/8) in 915ms
  Finalizing page optimization ...

Route (app)
┌ ○ /
├ ○ /_not-found
├ ○ /chat
├ ○ /connections
├ ○ /dashboard
└ ○ /login
○  (Static)  prerendered as static content
```

Exit code: `0` — **PASS**. `next.config.ts` uses `output: "export"`, so the build emits a static export into `frontend/out/`.

---

## New routes present in the export

The build route listing above shows `/connections` and `/dashboard` (and `/chat`, `/login`) all marked `○ (Static) — prerendered as static content`.

Both new screens live under the `src/app/(protected)/` route group:
- `frontend/src/app/(protected)/dashboard/page.tsx`
- `frontend/src/app/(protected)/connections/page.tsx`
- Left-nav: `frontend/src/components/common/Sidebar.tsx` (rendered via `frontend/src/app/(protected)/layout.tsx`)

**Emitted static files in `frontend/out/`** (this Next.js version emits flat `<route>.html` files rather than `<route>/index.html`):

```
out/404.html
out/chat.html
out/connections.html   <-- Connections screen, prerendered
out/dashboard.html     <-- Dashboard screen, prerendered
out/index.html
out/login.html
out/_not-found.html
```

Both `out/dashboard.html` and `out/connections.html` contain real prerendered route payloads that reference the `(protected)/dashboard` and `(protected)/connections` route segments respectively (verified by inspecting the embedded RSC flight data in each file).

**Confirmation:** the new Dashboard, Connections, and Sidebar features **build successfully**, and `/dashboard` and `/connections` are **prerendered in the static export**.

---

## Regression / scope confirmations

- **Existing frontend tests still pass:** yes — 29/29 across 5 suites, including the pre-existing `chatSuggestions`, `api`, and `personas` suites. Nothing broken.
- **Zero backend changes:** confirmed. `git status` shows all changes confined to `frontend/` (new Dashboard/Connections/Sidebar components, `lib/projects.*`, `lib/connections.*`, modified `chat/page.tsx`, `layout.tsx`, `types/index.ts`, and the auto-corrected `package-lock.json`) and `docs/.agents/tasks/`. No files under the backend (e.g. agent/Lambda/infra) were touched. The read-only `mahalo-dock` repo was not touched.

---

## Reminder — this is OFFLINE only

This gate verifies the local offline build/test/lint/export only. **The live deploy (building and publishing via the EC2 builder) is a separate operator step performed afterward** and is explicitly out of scope for this document.
