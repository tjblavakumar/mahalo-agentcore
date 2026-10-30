# Chat latency investigation — "Give me a delivery status overview" (PM)

READ-ONLY investigation. No code, config, or infra was changed. Live data pulled
via AWS SSO profile `lava` (account <AWS_ACCOUNT_ID>, us-east-1) on 2026-10-27.

---

## 1. Summary answer (the headline)

The ~2-minute response is **not** mock/tool I/O and **not** undersized Lambda
memory. Two things stack up:

1. **A huge model-driven tool fan-out.** One PM "delivery status overview" makes
   the agent run **~21 tool calls across ~5 sequential model round trips** on
   AgentCore Runtime. Nearly all of it is Claude Sonnet 4.5 "thinking/generation"
   time across that multi-turn loop plus a large final table synthesis. A single
   agent pass measured **53s warm / ~64s cold**.

2. **A retry storm that TRIPLES the work on a cold/slow pass.** The thin-API
   Lambda calls `invoke_agent_runtime` with the **default botocore config, whose
   `read_timeout` is 60s** and whose default retry mode auto-retries timeouts.
   When one agent pass exceeds 60s (which it does on a cold Runtime: ~64s), boto3
   silently re-invokes the SAME Runtime session — I measured **three** full agent
   passes (64.6s + 62.5s + 25.3s ≈ 152s) behind a single `/chat` call. That is
   where the "good 2 minutes" comes from.

So: **cold ≈ 147–152s** (retry storm) vs **warm ≈ 57s** (single pass, no retry).
The biggest, cheapest win is to stop the retry storm; the biggest structural win
is to cut the tool fan-out from ~21 calls / ~5 turns down to a handful.

What is MEASURED vs INFERRED is called out explicitly in every section. X-Ray
tracing is OFF on the Runtime (`tracing_enabled=False` in `runtime_stack.py`), so
there is no span-level breakdown and no token counts in logs — those stay
INFERRED.

---

## 2. Measured per-stage time budget

All numbers below are from CloudWatch Logs for two live requests I sent to the
thin API `/chat` (PM persona, body `{"message":"Give me a delivery status
overview", ...}`): one on a cold Runtime, one warm. Correlated by session id and
timestamp.

### Cold request (session `mahalo-latency-cold-…`)

| Stage | Measured | Source |
|---|---|---|
| Thin-API Lambda total wall time | **147,037 ms** (one invocation) | API Lambda `REPORT … Duration: 147037.02 ms` |
| Thin-API Lambda cold start (InitDuration) | ~898 ms (on the paired 58s invoke) | API Lambda `REPORT … Init Duration: 898.32 ms` |
| Runtime agent pass #1 | **64.570 s** | runtime log `Invocation completed successfully (64.570s)` |
| Runtime agent pass #2 (retry) | **62.454 s** | runtime log, same `sessionId` |
| Runtime agent pass #3 (retry) | **25.275 s** | runtime log, same `sessionId` |
| Sum of Runtime passes | **~152 s** | 64.6 + 62.5 + 25.3 |
| Per mock-Lambda tool execution | **63–185 ms each** | Jira mock `REPORT … Duration: 63–185 ms` |
| Mock Lambda memory used | 91 MB of 256 MB | Jira mock `REPORT` lines |

### Warm request (session `mahalo-latency-warm-…`)

| Stage | Measured | Source |
|---|---|---|
| Runtime agent pass (single, no retry) | **53.299 s** | runtime log `Invocation completed successfully (53.299s)` |
| Thin-API Lambda total wall time | **56,932 ms** | API Lambda `REPORT … Duration: 56932.73 ms` |
| Thin-API Lambda cold start (InitDuration) | 1,184 ms | API Lambda `REPORT … Init Duration: 1184.31 ms` |
| Runtime retries | **none** (pass < 60s) | only one completion line for the session |

### Interpretation of the budget

- **(a) Thin-API handling + Runtime invoke overhead:** small. The thin-API
  Lambda used **127–133 MB of 512 MB** and its own compute is trivial (it just
  serializes JSON and forwards). Its *wall time* is large only because it is
  blocked waiting on the Runtime. Thin-API cold start adds ~0.9–1.2 s — minor.
- **(b) Runtime / model "thinking" across the tool loop:** **this is the
  dominant cost.** ~53 s warm for a single pass, almost none of it tool I/O
  (see (c)). INFERRED: the time is Claude Sonnet 4.5 latency across ~5
  sequential model turns plus a large final markdown-table synthesis.
- **(c) Tool I/O (Gateway → Lambda → DynamoDB):** **cheap.** Each mock Lambda
  returns in **63–185 ms**, and the model issues tools in parallel batches
  (multiple `Tool #N` lines share a timestamp). ~21 calls × ~0.1 s ≈ 2–4 s of
  backend work total, overlapped. Not the bottleneck. (Gateway/MCP SigV4
  per-call overhead was not separable without X-Ray — INFERRED small relative to
  model time.)
- **(d) Cold starts:** The **Runtime cold start is the trigger** that tips a
  pass over the 60 s boto read_timeout and detonates the retry storm. Thin-API
  and mock-Lambda cold starts (≤ ~1.2 s) are negligible by themselves. No
  provisioned concurrency is configured on the thin-API Lambda (not present in
  `api_stack.py` / confirmed by cold-start InitDuration appearing on back-to-back
  invocations).

---

## 3. Tool-call count & sequence (MEASURED from runtime logs)

For the cold session the runtime log shows this exact sequence for one agent
pass (then it repeats, because of the retries in §4):

```
Tool #1  mock-jira___jira_list_projects
Tool #2  mock-servicenow___servicenow_get_stats
Tool #3  mock-servicenow___servicenow_deployment_status_by_project   <-- composite IS used
Tool #4  mock-github___github_list_repos
    (narration: "Now let me get sprint and board status for each project:")
Tool #5..#9   mock-jira___jira_get_sprint_info   (x5, one per project)
Tool #10..#14 mock-jira___jira_get_board         (x5, one per project)
    (narration: "Now let me get PR status across repositories:")
Tool #15..#19 mock-github___github_get_pull_requests  (x5, one per repo)
    (narration: "Let me also check for active incidents:")
Tool #20..#21 mock-servicenow___servicenow_list_incidents (x2)
```

**~21 tool calls per overview pass**, grouped into **~5 model round trips**
(each narration line marks a new model turn: initial batch → sprint/board batch →
PR batch → incident batch → final synthesis).

Key findings on the tool choices:

- **The ServiceNow composite IS used** (`servicenow_deployment_status_by_project`,
  Tool #3). `tools-lambdas/servicenow/composites.py::deployment_status` collapses
  services+deployments server-side. Good.
- **But the Jira and GitHub reads are NOT collapsed.** The model fans out
  `jira_get_sprint_info` ×5, `jira_get_board` ×5, and `github_get_pull_requests`
  ×5 — one call per project/repo — instead of a single coarse call. That is
  **15 of the 21 calls**. There is **no** server-side composite today for
  "sprint/board across all projects" or "PRs across all repos"; the existing
  Jira composites (`jira_search_stories`, `jira_get_stories_by_assignee` in
  `tools-lambdas/jira/composites.py`) cover story queries, not sprint/board/PR
  roll-ups, so the overview path cannot lean on them as-is.
- Are the calls sequential? **The model batches them in parallel** within a turn
  (same-timestamp `Tool #N` lines), so within a turn the fan-out overlaps. The
  **turns themselves are sequential** (model must see batch N's results before
  emitting batch N+1), which is the real serialization cost.

---

## 4. Root cause of the ~2 min: the botocore retry storm (MEASURED + corroborated)

- `api/app/runtime_client.py` builds the `bedrock-agentcore` client with **no
  custom botocore `Config`** → it uses the **default `read_timeout` of 60 s** and
  the **default retry policy (auto-retries timeouts)**. (botocore default
  read_timeout is 60 s and the default retry mode retries read timeouts; the AWS
  Bedrock/Nova and Neptune docs explicitly warn that a >60 s model/query response
  under the default SDK timeout causes a retry that re-runs the work. Sources
  below. Content was rephrased for compliance with licensing restrictions.)
- The runtime log shows **three `Invocation completed` lines for the single cold
  `/chat` session** (64.6 s + 62.5 s + 25.3 s). The thin-API only calls
  `invoke_agent_runtime` **once** (`runtime_client.invoke_runtime`), so those
  extra passes are boto3 retries firing because pass #1 exceeded the 60 s
  read_timeout — each retry re-runs the full tool loop on the same session.
- The warm request's single pass was **53.3 s (< 60 s)** → **no retry** → total
  ~57 s. This cold-vs-warm contrast is the direct evidence: the retry storm is
  triggered precisely when a pass crosses 60 s, which the Runtime cold start
  makes likely.

**This is the single biggest, lowest-risk lever.** Note it also risks
**double-applying writes** on the HITL `/chat/approve` path for the same reason
(a slow approve could be retried) — worth fixing for correctness, not just speed.

---

## 5. Answers to the five framed questions

1. **Where does the time go?** Measured: ~53 s (warm) / ~64 s (cold) per agent
   pass is overwhelmingly **model thinking across ~5 sequential tool-loop turns**
   (b). Tool I/O (c) is ~0.1 s/call and overlapped — negligible. Thin-API compute
   (a) and non-Runtime cold starts (d) are ≤ ~1.2 s. The jump from ~57 s (warm) to
   ~147–152 s (cold) is the **boto retry storm** in §4, triggered by the Runtime
   cold start pushing pass #1 over 60 s.
2. **Round trips / tool count / parallelizable / composites?** ~5 sequential
   model round trips, ~21 tool calls. Within a turn the model already parallelizes
   (batched tool calls). The composite `servicenow_deployment_status_by_project`
   is used; the 15 Jira-sprint/Jira-board/GitHub-PR calls are **not** collapsed
   and have no matching composite today — a new coarse composite (or prompt
   steering) is the way to cut round trips.
3. **direct or gateway mode?** **GATEWAY/MCP.** `infra-cdk/app.py` constructs
   `MahaloRuntimeStack(..., tool_mode="gateway")` and `runtime_stack._environment`
   sets `MAHALO_TOOL_MODE=gateway`. Tool names in the logs are prefixed
   `mock-jira___…` (MCP/Gateway target naming), confirming gateway at runtime.
   Per-call MCP/SigV4 overhead was **not separately measurable** (X-Ray off);
   INFERRED small next to model time given mock Lambdas return in ≤185 ms.
4. **Cold vs warm?** MEASURED. Cold total ≈ **147–152 s**; warm single pass ≈
   **53 s**, warm total ≈ **57 s**. Lambda memory is **not** a factor (thin-API
   127–133 MB of 512 MB; mocks 91 MB of 256 MB). **No provisioned concurrency**
   is configured anywhere.
5. **Model-level / prompt size?** The system prompt is large: `agent/prompts.py`
   `BASE_PROMPT` + PM role ≈ 5 KB of instructions, sent every turn, plus **all 25
   tool schemas** (`tools-lambdas/common/tool_schemas.py`, ~22 KB source) are
   advertised to the model on every turn. The overview prompt asks for an
   expensive **cross-system synthesis into a formatted table**. INFERRED (no
   token logging / X-Ray): this inflates input tokens on every one of the ~5
   turns and the final synthesis is a large output generation — a real
   contributor to the ~53 s, but secondary to the round-trip count and the retry
   storm.

---

## 6. Ranked, LOW-RISK candidate fixes (recommend, do NOT implement)

Ranked by impact-per-effort. All are reversible config/prompt changes.

### #1 — Kill the botocore retry storm (DO THIS FIRST)
- **What:** In `api/app/runtime_client.py`, build the `bedrock-agentcore` client
  with an explicit botocore `Config(read_timeout=<Lambda timeout or ~300s>,
  connect_timeout=10, retries={"max_attempts": 1, "mode": "standard"})`. This
  makes one `/chat` do **one** agent pass instead of three.
- **Impact:** HIGH — removes ~2× redundant work on cold/slow calls; cold total
  drops from ~150 s toward ~65 s. Also closes a **write-double-apply** risk on
  `/chat/approve`.
- **Effort:** LOW (a few lines, one file). **Risk:** LOW.

### #2 — Cut the tool fan-out with a coarse "overview" composite
- **What:** Add/route to a server-side composite that returns sprint+board status
  for all projects in one MCP call and PRs for all repos in one call (mirroring
  the pattern in `tools-lambdas/servicenow/composites.py` and the Jira composites
  in `tools-lambdas/jira/composites.py`). Point the PM overview at these so the
  loop drops from ~21 calls / ~5 turns to ~4 calls / ~2 turns.
- **Impact:** HIGH — fewer sequential model turns is the structural fix for the
  ~53 s; likely cuts warm latency substantially.
- **Effort:** MEDIUM (new composite handlers + schema entries + gateway target
  wiring; the composite scaffolding already exists). **Risk:** LOW–MEDIUM
  (new tool surface; needs the existing tool tests to stay green).

### #3 — Reduce Runtime cold-start frequency / cold penalty
- **What:** The Runtime already sets `idle_runtime_session_timeout=15 min`
  (`runtime_stack.py`), which helps keep warm within a session. Consider a light
  keep-warm (periodic cheap invoke) or, if the platform supports it, provisioned
  capacity for the Runtime. Independently, this matters less once #1 removes the
  retry amplification of a cold pass.
- **Impact:** MEDIUM (mainly first-call experience). **Effort:** LOW–MEDIUM.
  **Risk:** LOW (small always-on cost).

### #4 — Trim the per-turn prompt/tool-schema payload
- **What:** The overview only needs a subset of the 25 tools. Exposing a smaller,
  task-relevant tool set (or tightening `tool_schemas.py` descriptions and the
  `agent/prompts.py` BASE_PROMPT) shrinks input tokens on every turn.
- **Impact:** LOW–MEDIUM (token/latency trim; secondary). **Effort:** MEDIUM.
  **Risk:** MEDIUM (changing tool availability/prompt can alter agent behavior;
  must re-verify the agent test suite and the overview answer quality).

### #5 — (Explicitly NOT a fix) raise Lambda memory
- **Measured:** thin-API uses 127–133 MB of 512 MB; mocks 91 MB of 256 MB. CPU is
  not the bottleneck. **Do not raise memory for latency** — it would not help.

### What to implement first
Do **#1** (retry storm) first — lowest effort, highest and most certain impact,
and it also fixes a correctness risk. Then **#2** (coarse overview composite) for
the structural win on warm latency. #3/#4 are follow-ups.

---

## 7. What could NOT be measured / caveats

- **X-Ray is OFF** (`tracing_enabled=False`, runtime_stack.py) → no span-level
  split of model-think vs MCP/SigV4 vs tool time within a pass, and **no token
  counts** in logs. The model-vs-tool attribution in §2(b)/(c) is inferred from
  mock-Lambda durations (fast) vs total pass time (slow).
- The client-side harness I used (`Invoke-WebRequest` against the Function URL)
  held connections open past the server's completion on the cold call, so the
  **authoritative timings are the CloudWatch Runtime/Lambda `REPORT` lines**, not
  the client stopwatch. All numbers quoted here are CloudWatch-sourced.
- The three-pass retry count matches botocore's default behavior and the
  cold-vs-warm contrast, but I did not instrument botocore directly (read-only);
  the conclusion is corroborated, not traced.
- Only one cold and one warm sample were taken (per the brief). Numbers are
  representative, not a distribution.

---

## Sources (external, for the botocore default-timeout/retry claim)
- botocore Config reference — https://docs.aws.amazon.com/botocore/latest/reference/config.html
- AWS Bedrock/Nova "Complete request schema" (default SDK client ~1 min timeout; raise read_timeout) — https://docs.aws.amazon.com/nova/latest/userguide/complete-request-schema.html
- AWS Neptune best practices (default 60 s timeout + auto-retry re-runs long requests) — https://docs.aws.amazon.com/neptune/latest/userguide/best-practices-cli-sdk.html

_Content from external sources was rephrased for compliance with licensing restrictions._
