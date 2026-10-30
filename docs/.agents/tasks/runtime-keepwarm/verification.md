# Runtime keep-warm: live acceptance verification

Account <AWS_ACCOUNT_ID>, us-east-1. Run 2026-10-30 (Fri), UTC times. MahaloKeepWarmStack created 16:43Z.
Rule: `cron(0/10 13-22 ? * MON-FRI *)`, ENABLED. Run time was inside the window.

## 1. Latency check: PASS

Fresh session ids (42 chars, `verify-kw-*` / `verify-kw2-*`), persona `pm`, via `POST {RuntimeApiUrl}chat`
with header `X-Mahalo-Persona: pm`. Sent at 17:03Z and 17:05Z, after two keep-warm cycles (16:50Z, 17:00Z).

| Request | Measured wall-clock | Runtime-side duration |
|---|---|---|
| "What is your role in one short sentence?" (no tools) | 9.1 s | 3.46 s |
| "Which stories should we prioritize next sprint?" (full data/tool pass) | **45.8 s** | 44.8 s |

Baselines: cold ~64 s+, warm ~45-55 s. The tool-heavy first call landed at 45.8 s, the warm range
and ~18 s under cold. No cold-start penalty seen.

Caveat: I did not capture a no-keep-warm control run in this session. The comparison is against the
previously recorded baselines. A single sample.

## 2. Cadence: PASS

- Lambda `MahaloKeepWarmStack-KeepWarmFn024040E8-ZqERD1mIvg0p` log group shows pings at 16:50:15Z and
  17:00:15Z, i.e. exactly the 10-minute cron ticks after deploy (16:43Z). Both logged `keep-warm ping OK`.
- CloudWatch `AWS/Events TriggeredRules` for the rule: Sum=2 in the hour bucket.
- (The 16:40 tick was before the stack existed, so no earlier ticks are expected.)

## 3. Cheap and isolated: PASS

- Lambda REPORT: 5.8-6.4 s duration, 128 MB, ~90 MB used, billed ~6.5-6.8 s.
- Runtime log group `/aws/bedrock-agentcore/runtimes/mahalo_agent_runtime-jtt0TpAcU6-DEFAULT`:
  ping invocations completed in **3.28 s** (16:50Z) and **3.03 s** (17:00Z), with no tool-call lines.
  Real overview pass: **44.8 s**. About 15x shorter than a real pass.
- Isolation: pings use sessionId `mahalo-keepwarm-DO-NOT-USE-20261030-000000` (daily rotating, 41 chars),
  persona developer dev-6 default. My test traffic used different session ids; the Runtime log keeps them
  distinct per `sessionId`. No real demo session id is shared.

## 4. Cost (documented, small)

About 1,320 trivial invokes/month (Mon-Fri 13:00-22:50 UTC, every 10 min). Lambda stays within free tier
(~6.5 s x 128 MB per ping). EventBridge schedule: $0. Real cost is Runtime + Bedrock time for ~3 s
single-turn pings: low single-digit dollars/month, weekday daytime only. Reversible by deleting
MahaloKeepWarmStack. See docs/aws-personal-cloud-deployment.md §9.

## Result

PASS. First call landed at warm time (45.8 s), the ping fires on cadence, is cheap (~3 s, no tool loop),
and is isolated by a throwaway session id.
