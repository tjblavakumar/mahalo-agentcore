# Task 7 — Investigation (STEP 0): Gitea + Frontend hosting

**Scope.** Task 7 = "Stand up self-hosted Gitea on an always-on host and deploy the
Next.js frontend" (`docs/PLAN.md` Task 7). This document is read-only investigation:
no design decisions are finalized here, but each open question is made answerable in
the design phase with concrete file:line citations and AWS doc URLs.

**Hard constraints (from the step prompt + `docs/CONTINUATION.md:18-24`).** Only ever
WRITE under `d:/<USER>/LavaCode/AI/mahalo-agentcore`. `mahalo-dock` is
READ ONLY (we read its frontend/Gitea to port, never edit). No commits/pushes, no
`npm run dev` / watch processes, no deploys. Task 7 is verified OFFLINE
(build/lint/unit tests + documented live-wiring steps); Gitea infra is authored as
CDK that synths offline. Runtime + thin API live deploy remain deferred operator
steps (`docs/STATUS.md:62-70`), NOT a Task-7 blocker.

> Content from external web sources below was rephrased for compliance with
> licensing restrictions; each claim links its source inline.

---

## 0. Repository landing zones (where Task 7 output goes)

- `frontend/` exists but is an empty placeholder — only `frontend/.gitkeep`
  (verified: `Get-ChildItem` shows one file). The ported Next.js app lands here.
- `gitea/` likewise is a placeholder — only `gitea/.gitkeep`. Gitea
  config/bootstrap assets land here.
- Both paths are already declared in `README.md:36` (`frontend/`) and
  `README.md:37` (`gitea/`) in the repo layout table, so the structure is
  pre-agreed.
- No `.kiro/steering/*`, no `AGENTS.md`, no `CONTRIBUTING.md` in
  mahalo-agentcore (searched — none found). The governing docs are
  `docs/CONTINUATION.md`, `docs/STATUS.md`, `docs/PLAN.md`, `docs/ARCHITECTURE.md`,
  plus per-task artifacts under `docs/.agents/tasks/`. The mahalo-dock frontend
  DOES carry a `frontend/AGENTS.md` (read below) — it matters for the port.

---

## 1. FRONTEND port surface

### 1.1 Build/test tooling and the offline gate

Source: `mahalo-dock/frontend/package.json`.

- Framework: **Next.js `16.3.3`** (`package.json:12`), **React `19.2.8`** +
  `react-dom 19.2.8` (`package.json:13-14`). Also `react-grid-layout ^1.4.4`
  (`:11`, dashboard) and `react-markdown ^9.0.1` (`:15`, chat rendering).
- Dev deps: `eslint ^9` + `eslint-config-next 16.3.3`, `tailwindcss ^4` +
  `@tailwindcss/postcss`, `typescript ^5`, `vitest ^2.1.8` (`package.json:17-27`).
- Package manager: **npm** — `package-lock.json` is present
  (`yarn.lock`/`pnpm-lock.yaml` are absent; verified via `Test-Path`). So
  `npm ci` is the install command.
- Scripts (`package.json:5-11`): `build` = `next build`, `lint` = `eslint`,
  `test` = `vitest run`, `test:watch` = `vitest`. `dev`/`start` are the dev
  server (`next dev` / `next start`) and MUST NOT be run per the step prompt.
- Vitest config: `environment: "node"`, includes `src/**/*.{test,spec}.{ts,tsx}`,
  and aliases `@` -> `./src` (`vitest.config.ts:5-14`). Only ONE test file exists
  today: `src/lib/chatSuggestions.test.ts` (plus `chatSuggestions.ts`).
- **Toolchain available (from `docs/CONTINUATION.md:~213`): Node 24, npm 11** —
  satisfies Next 16/React 19.

**Offline gate for Task 7 frontend = `npm ci; npm run lint; npm run test; npm run
build`** — all four run locally with no AWS and no long-running server. `next
build` is the compile step; `vitest run` is one-shot (not the watcher); `eslint`
is the linter. This matches the verification guideline (use the project's real
build/test commands, not grep).

**Next.js 16 caveat (mandatory reading).** `mahalo-dock/frontend/AGENTS.md:1-11`
is an auto-generated block warning that this Next.js has breaking changes vs
training data and that the real guides live under `node_modules/next/dist/docs/`.
Two consequences for the port: (a) when we touch routing/config we should read
those local docs, not assume older Next behavior; (b) the block is re-written by
`next dev` — but since we never run `next dev`, that is a non-issue for us; we
simply copy the file as-is.

### 1.2 The frontend's current backend contract (what it calls today)

API client: `mahalo-dock/frontend/src/services/api.ts`.
- Base URL from `process.env.NEXT_PUBLIC_API_URL`, default
  `http://localhost:8008` (`api.ts:5`). This is a **build-time inlined** public
  env var (Next bakes `NEXT_PUBLIC_*` at build).
- Auth: a **JWT bearer** read from `sessionStorage["mahalo3_token"]` and sent as
  `Authorization: Bearer <token>` on every request (`api.ts:48-54`).
- `Content-Type: application/json`; errors normalized from `detail`/`message`
  (`api.ts:40-74`). Thin wrapper `api.get/post/put/delete` (`api.ts:88-95`).

Routes the frontend uses today (grep of `api.*(` across `src/`), and whether the
Task-6 thin API provides them:

| Frontend call | File:line | Thin API has it? |
|---|---|---|
| `POST /chat` | `chat/page.tsx:159` | YES (`api/app/routers/chat.py:41`) |
| `POST /chat/approve` | `chat/page.tsx:197,212` | YES (`api/app/routers/chat.py:81`) |
| `POST /chat/suggestions` | `chat/page.tsx:140` | NO |
| `GET /auth/me` | `contexts/AuthContext.tsx:42,78` | NO |
| `POST /auth/login` | `AuthContext.tsx:60` | NO |
| `POST /auth/register` | `AuthContext.tsx:92` | NO |
| `GET /integrations` | `contexts/ConnectionsContext.tsx:43` | NO |
| (projects, dashboard widgets, connections data) | `contexts/ProjectContext.tsx`, `dashboard/*`, `connections/*` | NO |

So the frontend today is tightly coupled to the full mahalo-dock FastAPI backend
(auth, integrations, projects, dashboard). The Task-6 thin API exposes **only**
`/chat`, `/chat/approve`, `/healthz`.

### 1.3 The EXACT Task-6 thin-API contract (the target)

Source: `api/app/`.

- `POST /chat` (`routers/chat.py:41-71`, request `ChatRequest`
  `models.py:17-23`): body `{message: str, session_id?: str, project_id?: int}`.
  `project_id` is accepted for frontend compatibility but UNUSED (`models.py:22`,
  "Out of Scope"). Response `ChatResponse` (`models.py:26-33`):
  `{response: str, proposal?: dict, session_id: str, status: str}`. A new
  `session_id` is minted server-side when absent (`chat.py:46`).
- `POST /chat/approve` (`routers/chat.py:76-123`, request `ApprovalRequest`
  `models.py:36-49`): body `{session_id: str, interrupt_id: str, approved: bool,
  proposal?: dict}`. Response `ActionResult` (`models.py:52-57`):
  `{success: bool, message: str, session_id: str}`. `success=false` iff the
  Runtime returned `status=="error"` (`chat.py:116-122`).
- **Two-call HITL**: a `/chat` that proposes a write returns a `proposal` + an
  interrupt; the client surfaces it and makes a SECOND call to `/chat/approve`
  echoing `session_id` + `interrupt_id` (+ optional `proposal`). The Runtime
  derives the `[SYSTEM]` breadcrumb from its own restored interrupt state, so the
  `proposal` echo is NOT required for correctness (`chat.py:95-103`,
  `models.py:43-48`).
- Session id is forwarded as the Runtime `runtimeSessionId`
  (`runtime_client.py:44`, `chat.py:46`).
- Inbound auth: the thin API itself returns a FIXED dev identity
  (`dev-6`/`developer`, `auth.py:21-30`); the step prompt's "inbound auth
  AWS_IAM/SigV4" is enforced at the **Function-URL edge** —
  `MahaloApiStack` sets `FunctionUrlAuthType.AWS_IAM`
  (`infra-cdk/mahalo_infra/api_stack.py:103-105`). Identity/`runtimeUserId` is
  OFF for the MVP (`config.py:30-33`, `chat.py:38-40`).
- Error mapping: Runtime invoke throw -> HTTP 502 (`chat.py:62-64,110-112`);
  pydantic -> 422; approve is never auto-retried (`chat.py` module docstring).

### 1.4 Chat UI + propose/approve state (what we port)

Chat page: `mahalo-dock/frontend/src/app/(protected)/chat/page.tsx`.
- Local `Message` type carries an optional `proposal` (`chat/page.tsx:17-25`).
- `Proposal` shape the UI expects: `{action, system, params:
  Record<string,unknown>, description}` (`chat/page.tsx:27-32`,
  mirrored in `ProposalCard.tsx:3-8`).
- `handleSend` POSTs `/chat` with `{message, session_id, project_id}` and reads
  `response`, `proposal`, `systems_queried`, `session_id` off the reply
  (`chat/page.tsx:155-174`). It expects a `ChatApiResponse` with a
  **`systems_queried: string[]`** field (`chat/page.tsx:35-41`) — the thin API
  does NOT return this (see §1.5).
- `handleApprove`/`handleReject` POST `/chat/approve` with only
  **`{session_id, approved}`** (`chat/page.tsx:188-223`) — they do NOT send
  `interrupt_id`, which the thin API's `ApprovalRequest` REQUIRES
  (`models.py:36-42`). This is the single most important port change.
- `ProposalCard.tsx` renders `description`, `system`+`action`, iterates
  `params`, and shows Approve/Reject buttons + a success/failure `result`
  (`{success, message}`) card (`ProposalCard.tsx:28-99`). The `result` shape
  matches `ActionResult` minus `session_id`, so it ports cleanly.
- Session handling: a single `sessionId` state (`chat/page.tsx:46`), reset when
  the project scope changes (`chat/page.tsx:150-154,165-168`). No per-message
  interrupt id is tracked today.

Supporting chat components (port largely verbatim): `ChatInput.tsx`,
`ChatMessage.tsx`, `ContextPanel.tsx`, `lib/chatSuggestions.ts`(+`.test.ts`).

### 1.5 EXACTLY what must change vs. what ports verbatim

**Must change to target the thin API's two-call HITL:**
1. **Send `interrupt_id` on approve/reject.** The thin API requires it
   (`models.py:36-42`); the UI currently omits it (`chat/page.tsx:191-194,
   206-209`). The `/chat` reply's `proposal` must therefore also carry the
   interrupt id (or the id must be surfaced alongside it) and be threaded into
   the approve call. This needs a small Runtime/thin-API contract confirmation
   in design (where the interrupt id appears in the `/chat` reply — today
   `ChatResponse` exposes `proposal?: dict` + `status`, not an explicit
   `interrupt_id`; see Open Question A).
2. **Drop `systems_queried`.** The UI reads it (`chat/page.tsx:37,170`) but the
   thin `ChatResponse` has no such field (`models.py:26-33`). Make it optional /
   remove the "systems queried" chip, or have the Runtime add it (out of scope
   per `models.py`). Simplest: treat it as optional in the UI.
3. **Auth model swap.** Remove JWT-bearer (`api.ts:48-54`, `AuthContext.tsx`
   `/auth/*`) because the thin API is SigV4/AWS_IAM at the edge (Open Question B).
   The whole `/auth/login|register|me` flow and `ProtectedRoute` gating
   (`components/common/ProtectedRoute.tsx`) have no backend in the target.
4. **Remove/neutralize the non-chat data surfaces.** `/integrations`
   (`ConnectionsContext.tsx:43`), projects (`ProjectContext.tsx`), dashboard
   widgets (`components/dashboard/*`), connections pages
   (`app/(protected)/connections/*`), and `/chat/suggestions`
   (`chat/page.tsx:140`) all call routes the thin API lacks. Design decides:
   port only the chat route (minimal demo surface) vs. stub these backends. The
   chat page also depends on `useProjects`/`useConnections`
   (`chat/page.tsx:7-9`) for scoping/suggestions, so trimming the chat page's
   dependencies is part of the change.
5. **Base URL + env.** `NEXT_PUBLIC_API_URL` (`api.ts:5`) must point at the thin
   API Function URL at build time; CORS must allow the frontend origin
   (Open Question B/D).

**Ports largely verbatim (framework-agnostic / contract-compatible):**
- `ProposalCard.tsx` (proposal/result rendering) — matches `proposal` and
  `ActionResult` shapes.
- `ChatInput.tsx`, `ChatMessage.tsx`, `ContextPanel.tsx`,
  `lib/chatSuggestions.ts` (+ its vitest test).
- Tailwind setup, `globals.css`, `postcss.config`, `eslint.config`,
  `tsconfig.json`, `next.config.ts`, `frontend/AGENTS.md`, the Dockerfile
  (subject to the hosting decision, §3).
- The `/chat` + `/chat/approve` happy path already matches field-for-field
  (`message`/`session_id` out; `response`/`proposal`/`session_id`/`status` in).

### 1.6 Verification approach for the port (offline)

`cd frontend; npm ci; npm run lint; npm run test; npm run build` — all green with
no server and no AWS. New behavior (sending `interrupt_id`, treating
`systems_queried` optional, the SigV4/auth posture) gets unit tests under
`src/**/*.test.ts(x)` run by `vitest run`. Live wiring (pointing at a deployed
thin API) is a documented deferred step, consistent with Tasks 4-6.

---

## 2. GITEA hosting ("always-on host")

### 2.1 How the github Lambda is wired today (confirm additive)

- `tools-lambdas/github/handler.py:16-18` reads `MOCK_GITHUB_TOKEN` +
  `TABLE_NAME`; builds a DynamoDB-backed router (`handler.py:27-33`). Dispatch is
  Function-URL or Gateway-adapter (`handler.py:46-56`).
- `tools-lambdas/github/routes.py:3` states "Mock mode ONLY
  (`GITHUB_MODE=mock`); the Gitea backend is not ported." `GITHUB_MODE` is read
  (`routes.py:48`) but only surfaces in the `/health` body (`routes.py:67`) — it
  does NOT branch to a Gitea backend. So the current Lambda is **mock-only**;
  Gitea is a genuinely additive new path.
- The Lambda is provisioned by `MockServiceStack`
  (`infra-cdk/mahalo_infra/mock_service_stack.py`): DynamoDB table + `python3.13`
  Lambda (`:95-111`) + **Function URL `AuthType=NONE`** (`:131-133`, the Lambda
  enforces `X-API-Token` itself). **No VPC** — the function is a public
  Function-URL Lambda. Env today is just `TABLE_NAME` + `MOCK_GITHUB_TOKEN`
  (`:112-115`).

**Design implication.** Adding Gitea means: (a) port the real adapter (below)
into the github Lambda behind `GITHUB_MODE=real`, preserving the mock path
exactly; (b) inject Gitea env (`GITEA_URL`, token, owner, public URL); (c) make
the Lambda able to reach Gitea over the network (§2.3).

### 2.2 The real Gitea integration contract (read from mahalo-dock, to port)

`mahalo-dock/mock-services/github/` is the source:
- `main.py:36-52` selects the backend by `GITHUB_MODE` (`real` ->
  `GiteaBackend`, else `MockBackend`); the HTTP contract, auth, and response
  shapes are identical in both modes (`main.py:9-20`) — this is exactly the
  "additive, preserve the mock path" property Task 7 needs.
- `gitea_backend.py` is the full translator (MAHALO GitHub contract <-> Gitea
  REST `/api/v1`). Key facts for design:
  - Config from env: `GITEA_URL` (default `http://gitea:3000`,
    `gitea_backend.py:56-58`), `GITEA_TOKEN` or `GITEA_TOKEN_FILE`
    (`:59,88-101`), `GITEA_ADMIN_USER`/owner (`:60`), `DEMO_DEVELOPER_ID`
    default `dev-6` (`:68`), `GITEA_PUBLIC_URL` default `http://localhost:3001`
    (`:72-74`).
  - Repo identity: MAHALO `repo_id` == Gitea repo *name* under one owner
    (`:20-25`, `_repo_path` `:150-151`). This is the SAME name/id quirk called
    out in `docs/STATUS.md` known-issues — porting it faithfully is correct.
  - URL rewrite: Gitea returns in-stack URLs; `_publicize` rewrites `base_url`
    -> `public_url` (`:76-80`) so browser links resolve. In AWS this means the
    public URL env must be the real browser-facing Gitea URL.
  - Implements repos/branches/pulls/commits/readme/stats incl. real file writes
    via the Gitea contents API (`_write_file` `:393-406`).
- `backend_base.py` defines `GithubBackend`/`BackendError`; `mock_backend.py`
  is the in-memory store (already reimplemented as the DynamoDB routes in
  `tools-lambdas/github/`).

### 2.3 Hosting shape — options grounded in the existing infra + AWS docs

**What mahalo-dock did (reference, do not reuse directly):** one EC2 t3.medium
Ubuntu box running `docker compose` with a `gitea/gitea:1.27.3` service
(`mahalo-dock/docker-compose.yml:146-185`) persisting to a `gitea-data` named
volume (`:187-190`), plus a one-shot `gitea-bootstrap` container
(`:191-214`, Dockerfile `mock-services/gitea-bootstrap/Dockerfile`, script
`bootstrap.sh`) that creates the admin user via the Gitea CLI (the REST API
cannot create the first admin — `bootstrap.sh:9-10`), mints an adapter API
token, and seeds a `payment-service` repo with real files. The deploy runbook
(`mahalo-dock/aws-deploy-plan.md` §1,§3,§9) is EC2 + SSH tunnel, single-user
demo, ~\$30/mo if left on, ~\$2-3/mo EBS when stopped.

**Candidate "always-on host" shapes for mahalo-agentcore (CDK, aws-cdk-lib
`>=2.251,<3` per `infra-cdk/requirements.txt:1`):**

1. **EC2 instance running the Gitea container (or binary).** Closest to the
   proven mahalo-dock path. CDK constructs: `aws_ec2.Vpc`,
   `aws_ec2.Instance` (+ `UserData` to install Docker and run
   `gitea/gitea:1.27.3`), `aws_ec2.SecurityGroup`, optional
   `aws_ec2.BlockDeviceVolume` (gp3 EBS) for `/data`. Persistence = the EBS root
   or a dedicated EBS volume. Simplest/cheapest always-on single box; matches the
   mahalo-dock operational knowledge and the `bootstrap.sh` CLI-first-admin
   requirement (the CLI needs the data dir, trivial on a single host). Cost note
   from the prior run: t3.medium ~\$30/mo on 24/7 (`aws-deploy-plan.md:§1`).
2. **ECS on Fargate + EFS for repo data.** Serverless hosts; AWS documents ECS
   on Fargate as natively integrated with EFS for persistent, shared volumes
   ([ECS storage best practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/storage.html);
   [ECS task storage options](https://docs.aws.amazon.com/AmazonECS/latest/userguide/using_data_volumes.html)).
   A community guide deploys Gitea exactly this way — Fargate + EFS for repo
   storage (optionally RDS Postgres + ALB for HTTPS)
   ([Deploy Gitea with OpenTofu](https://oneuptime.com/blog/post/2026-03-20-deploy-gitea-opentofu/view)).
   CDK: `aws_ecs.FargateService` + `aws_efs.FileSystem` + `aws_ecs.Volume`
   (EFS) + an ALB (`aws_elasticloadbalancingv2`) for a stable HTTPS URL. More
   moving parts; the first-admin CLI bootstrap is awkward on Fargate (no shell
   into the data dir) — would need a one-shot task or an API-only bootstrap. Note
   Fargate also supports EBS for standalone tasks
   ([ECS storage best practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/storage.html)),
   but EFS fits a long-lived Gitea volume better.
3. **App Runner.** Good for stateless HTTP containers; Gitea needs durable
   writable storage (repos + SQLite/DB), which App Runner does not provide
   natively — so it is a poor fit unless paired with an external DB and object
   storage. Not recommended for the demo; note and set aside.

Persistence sub-options for the data: EBS (per-host, simplest; option 1), EFS
(shared/elastic, option 2), RDS (DB only — Gitea can use SQLite by default as in
`docker-compose.yml:181` `DB_TYPE=sqlite3`, so RDS is optional and heavier).

**Reachability (github Lambda -> Gitea).** The github Lambda has NO VPC today
(`mock_service_stack.py:131-133`, public Function URL). Two network postures for
design:
- **Public HTTPS Gitea URL**: Lambda reaches Gitea over the internet (set
  `GITEA_URL` to the public endpoint). No VPC wiring on the Lambda; simplest.
  Requires Gitea be internet-reachable (EC2 public IP / ALB / CloudFront) and
  protected by the Gitea API token (`bootstrap.sh:93-109` scopes
  `write:repository`,`write:user`,`read:organization`).
- **Private (VPC) Gitea**: put the github Lambda in the same VPC/subnets and
  reach Gitea privately (EC2 private IP or internal ALB). Tighter, but means
  attaching a VPC to the Lambda (and, if it still needs DynamoDB/Gateway, a VPC
  endpoint or NAT). Heavier for a single-user demo.

**URL/token mechanics to carry over:** `GITEA_PUBLIC_URL` must be the
browser-facing URL for `_publicize` (`gitea_backend.py:72-80`); the adapter token
comes from `GITEA_TOKEN`/`GITEA_TOKEN_FILE` (`:59,88-101`) — in AWS, prefer
Secrets Manager / SSM Parameter Store injected as the Lambda env, replacing the
shared-volume token file used in Compose. The first-admin-via-CLI requirement
(`bootstrap.sh:2-10`) shapes the bootstrap design on whichever host is chosen.

### 2.4 Offline-safety for the Gitea CDK

The existing stacks keep `cdk synth` Docker-free by flag-gating any asset build
(`runtime_stack.py:51-80`, `api_stack.py:47-73`: `-c buildImage=1` /
`MAHALO_BUILD_IMAGE=1`). A Gitea stack should follow the SAME pattern: use the
public `gitea/gitea:1.27.3` image by reference (EC2 UserData `docker run`, or
ECS `ContainerImage.from_registry`) so no local Docker build is needed for synth,
and gate any bootstrap-image build behind the same flag (Open Question E).

---

## 3. FRONTEND hosting

### 3.1 What the app is (shapes the hosting choice)

The ported app is a Next.js 16 **App Router** app (`src/app/**`,
`app/layout.tsx:21-43` wraps the tree in `AuthProvider`/`ConnectionsProvider`/
`ProjectProvider`). It is overwhelmingly **client-rendered**: every page/context
is `"use client"` (e.g. `chat/page.tsx:1`, `AuthContext.tsx:1`,
`ProtectedRoute.tsx:1`), reads/writes `sessionStorage`, and fetches data at
runtime from the API — there is no server-side data fetching or server actions in
the pages read. BUT `next.config.ts` is empty (`next.config.ts:3-6`) — there is
**no `output: "export"`**, and the mahalo-dock Dockerfile runs a full Next server
(`npm run build` then `npm start`, `frontend/Dockerfile:13-21`), i.e. it ships as
a server today, not a static export. There is also a dynamic route
(`app/(protected)/connections/[id]/data/page.tsx`) which static export supports
only with `generateStaticParams`.

### 3.2 Hosting options (AWS docs/community)

- **S3 + CloudFront (static export).** Only works if the app is converted to a
  static export (`output: "export"`), which disables SSR/dynamic server features;
  S3 can only serve static files
  ([Can a Next.js SSR app be hosted on S3?](https://www.quora.com/Can-a-Next-js-SSR-app-be-hosted-on-AWS-S3-Why)
  — rephrased: S3 serves only static assets, not SSR;
  [Hosting a Next.js App Router app on S3](https://dev.to/lanzone31/hosting-a-nextjs-app-router-app-on-amazon-s3-5al6)
  configures a static export + CloudFront). Because this app is client-only in
  practice (data at runtime, no SSR), a static export is *plausible* and is the
  cheapest, simplest, most "survives-a-reset" option — but requires the
  `output: "export"` conversion and handling the `[id]` dynamic route. Guidance:
  pick S3+CloudFront when the app is truly static
  ([CloudFront+S3 vs Amplify vs ECS](https://dev.to/muhammad_ahmad_khan/from-static-to-runtime-choosing-between-cloudfront-s3-amplify-and-ecs-for-frontends-on-aws-15i5)).
- **AWS Amplify Hosting.** Managed Next.js: static pages to CloudFront, SSR via
  managed Lambda, auto image optimization, git-based deploys
  ([Deploy Next.js on AWS](https://my-blog3.hashnode.dev/deploy-nextjs-on-aws);
  [Amplify Hosting](https://aws.amazon.com/amplify/hosting/)). Lowest-effort for
  a full Next app, but it is a git-connected managed service (less "pure CDK",
  and the repo is on GitHub).
- **Container on ECS/Fargate (same compute family as Gitea).** Run the existing
  `frontend/Dockerfile` server. Choose this when the frontend is really an
  application service
  ([CloudFront+S3 vs Amplify vs ECS](https://dev.to/muhammad_ahmad_khan/from-static-to-runtime-choosing-between-cloudfront-s3-amplify-and-ecs-for-frontends-on-aws-15i5)).
  Natural if Task 7 already stands up ECS/Fargate for Gitea (co-locate), but
  heavier than static hosting for a single-user demo.

### 3.3 How it gets the thin-API base URL + CORS/auth

- **Base URL**: `NEXT_PUBLIC_API_URL` is inlined at **build time**
  (`api.ts:5`). So the thin-API Function URL must be known at frontend build
  (chicken-and-egg with deploy order): either build the frontend after the API
  stack outputs `RuntimeApiUrl` (`api_stack.py:107`), or front the API with a
  stable custom domain. Design must pick (Open Question D).
- **CORS**: the thin API (`api/app/main.py`) sets NO CORS middleware today; a
  browser calling the Function URL cross-origin needs `Access-Control-Allow-*`.
  Lambda Function URLs can emit CORS headers via the url's `cors` config (CDK
  `FunctionUrlCorsOptions`) — but note **CORS and AWS_IAM together are a known
  friction** for browser calls
  ([CORS error with Cognito identity signing a Function URL](https://repost.aws/ja/questions/QUjmugNmXTQ3SWcuzKdSSseg/cors-error-using-cognito-identity-in-signed-request-to-lambda-function-url)).
  A common mitigation is to put CloudFront in front so the browser calls a
  same-origin path.

### 3.4 THE OPEN AUTH QUESTION — how a browser authenticates to a SigV4 endpoint

The thin API Function URL is `AuthType=AWS_IAM` (`api_stack.py:103-105`). A
browser cannot "just call it" — AWS_IAM requires every request be **SigV4-signed**
with AWS credentials; Lambda recomputes the signature and only runs the request
if they match
([Invoking Lambda function URLs](https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html)).
Investigated postures (do NOT assume a browser can SigV4-sign on its own — it has
no AWS credentials by default):

1. **Cognito Identity Pool -> temporary IAM creds -> in-browser SigV4.** The
   documented AWS pattern: the web UI obtains temporary credentials and signs
   each API request with SigV4 (and can carry a Cognito ID token in a signed
   header); API Gateway / Function URL then authorizes natively via IAM
   ([Innovation Sandbox auth mechanism](https://docs.aws.amazon.com/solutions/latest/innovation-sandbox-on-aws/authentication-mechanism.html);
   general IAM-temp-creds-to-invoke guidance in the
   [Serverless Lens IAM section](https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/identity-and-access-management.html)).
   For an IAM-protected Function URL specifically, using a Cognito **identity
   pool** to let authenticated users hit the endpoint is a documented approach
   ([Protected Lambda function URLs in user-facing apps](https://arpadt.com/_posts/2026-02-19-function-url-streaming-iam-protected)).
   In-browser signing uses a SigV4 signer (AWS ships standalone SigV4 signers;
   e.g. the .NET one, and JS equivalents exist in the AWS SDK)
   ([Standalone SigV4 signer](https://aws.amazon.com/blogs/developer/introducing-a-standalone-sigv4-signer-for-the-aws-sdk-for-net/)).
   This is the "real" secure option; cost is a Cognito identity pool + an
   authenticated IAM role granting `lambda:InvokeFunctionUrl`, plus client
   plumbing to replace the JWT-bearer header (§1.5).
2. **A public auth layer in front (CloudFront + Cognito user pool / WAF).** AWS
   documents securing Function URLs with Cognito + CloudFront + WAF
   ([Securing Lambda Function URLs with Cognito/CloudFront/WAF](https://aws.amazon.com/blogs/compute/securing-lambda-function-urls-using-amazon-cognito-amazon-cloudfront-and-aws-waf/)).
   Here the Function URL could even be `AuthType=NONE` behind an edge that
   enforces auth — but that diverges from the Task-6 `AWS_IAM` default and from
   the Runtime deploy posture.
3. **Documented dev/demo posture (switch the edge auth for the demo).** The
   Task-4/6 work already proved `AWS_IAM` SigV4 works from a *server-side* signer
   (`agent/gateway_client.py` SigV4, service `bedrock-agentcore`; thin API Lambda
   signs `InvokeAgentRuntime`). For a single-user browser demo, the lowest-effort
   option is to NOT have the browser sign at all: either (a) set the thin-API
   Function URL to `AuthType=NONE` for the demo and rely on obscurity/WAF (demo
   only), or (b) keep a tiny server-side signer between the browser and the
   AWS_IAM endpoint (a proxy that holds creds). This mirrors how mahalo-dock
   already ran as a single-user demo over an SSH tunnel
   (`aws-deploy-plan.md:§1`). This is explicitly a demo-grade tradeoff, to be
   chosen deliberately in design.

**This is a real open question (A/B).** The current frontend auth is JWT-bearer
to a backend that will not exist; the target edge is AWS_IAM. Design must pick one
of the three postures above and specify the exact client changes (replace
`api.ts`'s `Authorization: Bearer` with either a SigV4 signer fed by Cognito temp
creds, or nothing-at-the-browser + a signer/proxy).

---

## 4. IaC offline-safety (cross-cutting)

- CDK app wires stacks by direct construct reference in
  `infra-cdk/app.py` (mock x4, Gateway, Memory/Identity, Runtime, API). A Gitea
  stack (and any frontend-hosting stack) would be added here the same way.
- The offline gate is `cdk synth --all` exit 0 with NO Docker and NO creds
  (`docs/STATUS.md` baseline: 8 templates today). Any Task-7 stack must keep
  this: reference the public `gitea/gitea:1.27.3` image (no local build), gate
  any image build behind `-c buildImage=1`/`MAHALO_BUILD_IMAGE=1`
  (`runtime_stack.py:51-80`, `api_stack.py:47-73`), and avoid constructs that
  touch AWS at synth. `infra-cdk/tests` (pytest assertions) + `cdk synth --all`
  are the real verification commands (not grep).
- `RemovalPolicy.DESTROY` is the house style for clean monthly-reset teardown
  (`mock_service_stack.py:84`); Gitea persistence (EBS/EFS) and the frontend
  bucket should follow suit (with a conscious note that DESTROY on the Gitea
  volume wipes repos on teardown — acceptable for a re-seedable demo via
  `bootstrap.sh`).

---

## 5. Open design questions (A-E) — answerable in design

- **A. Frontend port scope.** Port only the chat surface (chat page + chat
  components + `services/api.ts` retargeted), dropping/stubbing auth, projects,
  connections, dashboard, and `/chat/suggestions` (routes the thin API lacks,
  §1.2/§1.5)? Or stub those backends? And where does the **interrupt id** surface
  in the `/chat` reply so the UI can send it on `/chat/approve` (`models.py:36-42`
  requires it; `ChatResponse` today exposes `proposal?`+`status`, not an explicit
  `interrupt_id`)? Decide the minimal demo surface and the interrupt-id threading.
- **B. Frontend <-> thin-API auth.** Which of the three §3.4 postures: (1) Cognito
  Identity Pool temp creds + in-browser SigV4; (2) CloudFront+Cognito/WAF edge;
  (3) demo-grade (Function URL `AuthType=NONE` or a server-side signer/proxy)?
  Specify the exact replacement for `api.ts`'s JWT-bearer header.
- **C. Gitea hosting + persistence + reachability.** EC2+EBS (proven,
  cheapest, matches `bootstrap.sh` CLI-admin), ECS/Fargate+EFS (serverless,
  heavier bootstrap), or App Runner (poor fit). Public-HTTPS vs VPC-private
  reachability from the github Lambda (which has no VPC today,
  `mock_service_stack.py:131-133`). Token/secret injection (Secrets Manager/SSM
  vs the Compose shared-volume file). Port the `GiteaBackend`
  (`mahalo-dock/.../gitea_backend.py`) into the github Lambda behind
  `GITHUB_MODE=real`, preserving the mock path.
- **D. Frontend hosting.** S3+CloudFront (needs `output: "export"` conversion +
  `[id]` route handling), Amplify Hosting (managed, git-connected), or a
  container on the same ECS/Fargate as Gitea. Plus how `NEXT_PUBLIC_API_URL`
  (build-time, `api.ts:5`) is resolved relative to the API deploy, and how
  CORS is handled for a browser->Function URL call.
- **E. IaC offline-safety.** How the Gitea (and frontend) stacks keep
  `cdk synth --all` Docker-free and cred-free (image-by-reference; flag-gate any
  build behind `-c buildImage=1`/`MAHALO_BUILD_IMAGE=1`), and the teardown posture
  for persisted Gitea data (`RemovalPolicy` choice).

---

## 6. Key file:line index (for the design phase)

- Thin API contract: `api/app/models.py:17-57`, `api/app/routers/chat.py:41-123`,
  `api/app/auth.py:21-30`, `api/app/config.py:26-37`,
  `api/app/runtime_client.py:35-50`, `api/app/main.py:18-27`.
- Thin-API edge auth (AWS_IAM): `infra-cdk/mahalo_infra/api_stack.py:103-107`.
- Frontend client/auth: `mahalo-dock/frontend/src/services/api.ts:5,48-54`,
  `src/contexts/AuthContext.tsx` (`/auth/*`), `src/contexts/ConnectionsContext.tsx:43`.
- Frontend chat/HITL: `src/app/(protected)/chat/page.tsx:27-41,155-223`,
  `src/components/chat/ProposalCard.tsx:3-8,28-99`.
- Frontend tooling: `mahalo-dock/frontend/package.json:5-27`,
  `vitest.config.ts`, `next.config.ts`, `frontend/Dockerfile`, `frontend/AGENTS.md`.
- github Lambda (mock-only today): `tools-lambdas/github/handler.py:16-56`,
  `tools-lambdas/github/routes.py:3,48,67`,
  `infra-cdk/mahalo_infra/mock_service_stack.py:95-133`.
- Real Gitea adapter (to port): `mahalo-dock/mock-services/github/main.py:36-52`,
  `mock-services/github/gitea_backend.py:56-80,150-151,393-406`,
  `mock-services/gitea-bootstrap/bootstrap.sh:1-10,93-109`,
  `mahalo-dock/docker-compose.yml:146-214`, `mahalo-dock/aws-deploy-plan.md` §1/§3/§9.
- IaC offline-safety pattern: `infra-cdk/mahalo_infra/runtime_stack.py:51-80`,
  `infra-cdk/mahalo_infra/api_stack.py:47-73`,
  `infra-cdk/mahalo_infra/mock_service_stack.py:84`, `infra-cdk/app.py`,
  `infra-cdk/requirements.txt:1`.

---

## Sources (web, rephrased for compliance)

- [Invoking Lambda function URLs (SigV4 required for AWS_IAM)](https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html)
- [Innovation Sandbox on AWS — authentication mechanism (web UI signs each request with SigV4 using temp creds)](https://docs.aws.amazon.com/solutions/latest/innovation-sandbox-on-aws/authentication-mechanism.html)
- [Serverless Applications Lens — IAM (AWS_IAM authz with temp IAM creds)](https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/identity-and-access-management.html)
- [Protected Lambda function URLs with Cognito identity pools](https://arpadt.com/_posts/2026-02-19-function-url-streaming-iam-protected)
- [Securing Lambda Function URLs with Cognito, CloudFront, WAF](https://aws.amazon.com/blogs/compute/securing-lambda-function-urls-using-amazon-cognito-amazon-cloudfront-and-aws-waf/)
- [Standalone SigV4 signer (AWS SDK)](https://aws.amazon.com/blogs/developer/introducing-a-standalone-sigv4-signer-for-the-aws-sdk-for-net/)
- [CORS error using Cognito identity signing a Function URL](https://repost.aws/ja/questions/QUjmugNmXTQ3SWcuzKdSSseg/cors-error-using-cognito-identity-in-signed-request-to-lambda-function-url)
- [Amazon ECS storage best practices (EFS/EBS integration)](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/storage.html)
- [Storage options for Amazon ECS tasks (EFS for horizontal scale)](https://docs.aws.amazon.com/AmazonECS/latest/userguide/using_data_volumes.html)
- [Deploy Gitea with OpenTofu (Fargate + RDS + EFS + ALB)](https://oneuptime.com/blog/post/2026-03-20-deploy-gitea-opentofu/view)
- [Choosing CloudFront+S3 vs Amplify vs ECS for frontends](https://dev.to/muhammad_ahmad_khan/from-static-to-runtime-choosing-between-cloudfront-s3-amplify-and-ecs-for-frontends-on-aws-15i5)
- [Deploy Next.js on AWS (Amplify Gen 2 SSR via Lambda)](https://my-blog3.hashnode.dev/deploy-nextjs-on-aws)
- [AWS Amplify Hosting](https://aws.amazon.com/amplify/hosting/)
- [Hosting a Next.js App Router app on Amazon S3 (static export)](https://dev.to/lanzone31/hosting-a-nextjs-app-router-app-on-amazon-s3-5al6)
- [Can a Next.js SSR app be hosted on S3? (no — static only)](https://www.quora.com/Can-a-Next-js-SSR-app-be-hosted-on-AWS-S3-Why)
