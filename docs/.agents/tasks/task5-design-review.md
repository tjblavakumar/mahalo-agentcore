# Task 5 Design Review — AgentCore Memory & Identity (revision 3)

Reviewer: design-review subagent, reading the design fresh and cross-checking every
load-bearing SDK/CDK/repo claim against the installed source and the current working tree.
Design under review: `docs/.agents/tasks/task5-design.md` (revision 3). Cited investigation:
`docs/.agents/tasks/task5-investigation.md`.

Verdict is mechanical: count HIGH + MEDIUM findings. There are **0 HIGH and 0 MEDIUM**
findings below (4 NITs), so the verdict is **APPROVED**.

The review responsibilities from the step were:
- Confirm all four open questions (A Memory scope, B Identity slice, C dual-mode toggles,
  D IaC + offline-safe build) are resolved concretely.
- Confirm Memory/Identity SDK/API claims are grounded in source, not guessed.
- Confirm the offline gate is achievable as designed.
- Flag anything that would force a user-visible change to DIRECT/GATEWAY defaults.

All four are resolved concretely, every load-bearing API claim was re-verified against
installed source (not merely the investigation's citations), the offline gate is achievable,
and **no finding forces a user-visible change to DIRECT or GATEWAY defaults.**

---

## What I verified against source (not taken on the design's word)

Each item below I opened and read; the design's claim matches.

1. **`HookRegistry.add_hook(hook: HookProvider)` delegates to `hook.register_hooks(self)`** —
   `agent/.venv/.../strands/hooks/registry.py`, method body is literally
   `hook.register_hooks(self)`. (Design cited `registry.py:287`; actual method starts ~line
   286 — immaterial.)
2. **`Agent.add_hook(callback, event_type=None, *, order=...)` ends in
   `self.hooks.add_callback(event_type, callback, order=order)`** —
   `strands/agent/agent.py:1190` + final body line. Confirms the design's HIGH-fix rationale:
   passing a `HookProvider` here registers it as a *single callback* and would NOT run
   `register_hooks`, so the per-turn persistence callbacks would never install. The design's
   choice of `agent.hooks.add_hook(provider)` (the registry method) is correct.
3. **`Agent.__init__` stores `session_manager` and, only when present, calls
   `self.hooks.add_hook(self._session_manager)`** — `agent.py:546` (`self._session_manager =
   session_manager`), `:547` (`if self._session_manager:`), `:549`
   (`self.hooks.add_hook(self._session_manager)`); and fires
   `self.hooks.invoke_callbacks(AgentInitializedEvent(agent=self))` at `:609`. Matches the
   design's offline-safety argument exactly (construct WITHOUT passing `session_manager=` →
   `AgentInitializedEvent` reaches no memory callback → no rehydrate at construction).
4. **Base `SessionManager.register_hooks` registers `AgentInitializedEvent → initialize`,
   `MessageAddedEvent → append_message` + `sync_agent`, `AfterInvocationEvent → sync_agent`** —
   `strands/session/session_manager.py`, the `register_hooks` body. (Design cited "lines
   48–57"; actual block is ~44–62 — immaterial.)
5. **AgentCore sync-mode `register_hooks` delegates to
   `RepositorySessionManager.register_hooks`, and the `add_callback(AgentInitializedEvent,
   ...)` at line 984 is the ASYNC branch only** —
   `bedrock_agentcore/.../strands/session_manager.py:928` the method; the sync branch
   (`if not self.config.async_mode:`) calls `RepositorySessionManager.register_hooks(self,
   registry, **kwargs)` then `return`s before line 984. The revision-3 citation correction is
   accurate; the revision-2 misattribution is genuinely fixed.
6. **`requires_api_key(*, provider_name, into="api_key")` builds `IdentityClient(_get_region())`
   at decorator-application time and injects `kwargs[into] = api_key` at call time** —
   `bedrock_agentcore/identity/auth.py:226`+. `IdentityClient(...)` is instantiated inside
   `decorator(func)` (line ~238), so applying the decorator to a body-local `_inner` defers
   client construction to call time. The sync wrapper path (`asyncio.run(_get_api_key())`)
   makes the design's non-async `_inner` work. Confirms offline-at-import.
7. **Local (non-Runtime) path self-provisions its OWN workload identity + writes
   `.agentcore.json`** — `auth.py:366` `_set_up_local_auth` calls
   `client.create_workload_identity()` and `json.dump(... .agentcore.json ...)`. Confirms the
   finding-3 narrative: the CDK `CfnWorkloadIdentity name="mahalo-agent"` is NOT consumed by
   the local CLI demo.
8. **CDK L1 constructs exist at the cited lines**: `CfnApiKeyCredentialProvider` (6890),
   `CfnMemory` (32551), `CfnWorkloadIdentity` (51726) in
   `infra-cdk/.venv/.../aws_cdk/aws_bedrockagentcore/__init__.py`. `CfnMemory`'s generated
   example confirms `event_expiry_duration` and `name` are REQUIRED and `memory_strategies`
   is optional — STM-only (`CfnMemory(name=..., event_expiry_duration=...)`) is valid, as the
   design states.
9. **Current repo premises** the design relies on:
   - `build_agent` today returns a bare `Agent` (DIRECT) and a `(agent, mcp_client)` tuple
     (GATEWAY) — `agent/strands_agent.py`. The variable-arity shape the `BuildResult` replaces
     is real, and `agent/chat.py::_run_single`/`_run_repl` unpack `agent, mcp_client =
     build_agent(tool_mode="gateway", ...)`, so the migration-to-`BuildResult` is a real
     breaking change the design correctly commits to absorbing.
   - `agent/chat.py::main` is `args = sys.argv[1:]; _run_single(" ".join(args))` with no
     argparse — matches the design's starting point.
   - `settings.gateway_region` is exactly
     `_getenv("MAHALO_GATEWAY_REGION", _getenv("AWS_REGION", "us-east-1"))` — the design's
     `MAHALO_MEMORY_REGION` default mirrors it verbatim (NIT-5 from rev-2 genuinely fixed).
   - The GATEWAY `ValueError` guard (`_build_gateway_mcp_client` raises when the URL is empty)
     exists; the design's `memory_id` guard mirrors it.
   - `jira_create_story` has exactly the signature the Identity snippet preserves, and the
     DIRECT body calls `make_request(settings.jira_url, settings.jira_token, endpoint=...,
     method="POST", body=body)` — the snippet's `token`-as-second-arg substitution is faithful.
   - The lazy-`import boto3`-inside-function pattern the design copies for `memory_client.py`
     is real (`agent/gateway_client.py::SigV4Auth.auth_flow`).

---

## Findings

### Decision coverage (the four open questions) — all resolved concretely

- **A (Memory scope):** Resolved. Wired-now via the native `session_manager=` seam, with the
  session-manager construction split from the rehydrate (`attach_memory`) so Task 6 reuses the
  same function; `actor_id = developer_id (dev-6)`; session-id provenance spelled out with an
  explicit precedence helper (`--session-id` > `MAHALO_SESSION_ID` > uuid4 when memory on,
  else `None`); the mahalo-dock in-memory `_sessions` replacement is stated and
  "clear session == new session_id" is defined. Concrete.
- **B (Identity smallest testable slice):** Resolved. One `CfnWorkloadIdentity` + one
  `CfnApiKeyCredentialProvider` + one wired DIRECT tool path (`jira_create_story`) behind
  `MAHALO_IDENTITY_ENABLED`, decorator on a body-local `_inner`, Task-4 SigV4/`GATEWAY_IAM_ROLE`/
  `X-API-Token` chain explicitly untouched (no edit to `gateway_stack.py`). The local-vs-CDK
  workload-identity nuance is now documented, not mis-stated. Concrete and non-breaking.
- **C (dual-mode toggles):** Resolved. Six off-by-default settings in the `MAHALO_*` style;
  three keyword-only `build_agent` params defaulting to reproduce today; `BuildResult` object
  removes arity branching; explicit "all off == byte-for-byte unchanged" invariant with the
  guarding tests named. Concrete.
- **D (IaC + offline-safe build):** Resolved. New `MahaloMemoryIdentityStack` under
  `infra-cdk/mahalo_infra/`, L1 constructs, `CfnOutput`→env, `RemovalPolicy.DESTROY`, wired in
  `app.py`; offline-safety mechanism pinned to the exact `agent.py` construction sequence and
  isolated behind `attach_memory`. Concrete and source-verified.

### NIT-1 — `_resolve_session_id` references `settings.memory_enabled` but the shown `main` snippet never passes memory state through; the attach wiring is prose-only

Where: Decision A, the `agent/chat.py` snippet (`main` / `_resolve_session_id`) and the
"Files to modify" bullet for `agent/chat.py`.

The `main` snippet shows `_run_single(" ".join(ns.message), session_id=session_id)` and
`_run_repl(session_id=session_id)` but does not show those functions threading `memory`/
`attach_memory(result.agent, result.session_manager)` — that behavior lives only in the
prose bullet. Since `_run_single`/`_run_repl` are the exact functions that must change (they
currently unpack tuples), the design would be stronger if the snippet (or a short companion
snippet) showed the post-construction `if result.session_manager is not None:
attach_memory(...)` call and the resume/new-session print, so an implementer cannot wire the
flag but forget the attach. This is not a correctness gap (the prose is unambiguous), hence
NIT.

Concrete fix: add to the Decision-A snippet a sketch of the updated `_run_single`:
```python
def _run_single(message: str, *, session_id: str | None) -> None:
    mode = settings.tool_mode.lower()
    result = build_agent(tool_mode=("gateway" if mode == "gateway" else None),
                         memory=settings.memory_enabled, session_id=session_id, **_IDENTITY)
    try:
        if result.mcp_client is not None:
            attach_gateway_tools(result.agent, result.mcp_client)
        if result.session_manager is not None:
            print(f"{'resuming' if _was_supplied(session_id) else 'new'} session {session_id}")
            attach_memory(result.agent, result.session_manager)
        print(_ask(result.agent, message))
    finally:
        if result.mcp_client is not None:
            result.mcp_client.stop(None, None, None)
```

### NIT-2 — "resuming" vs "new session" notice has no defined source of truth

Where: Decision A ("prints a one-line 'resuming session `<id>`' / 'new session `<id>`'
notice"), and Decision C ("prints a one-line 'resuming session `<id>`' / 'new session `<id>`'").

The design promises two different messages but never says how the CLI decides which to print.
A generated uuid is clearly "new"; a flag/env-supplied id is ambiguous (it may be a first use
OR a resume — the agent cannot know without asking Memory). The offline design cannot query
Memory to disambiguate, so the wording rule needs pinning or it will be guessed inconsistently.

Concrete fix: define it mechanically without a network call — "new session `<id>`" only when
the id was uuid4-generated this run (neither flag nor env supplied it); otherwise "using
session `<id>`" (avoid asserting "resuming", which implies prior history the CLI hasn't
confirmed). E.g. have `_resolve_session_id` also return whether it generated the id, or expose
a sibling predicate.

### NIT-3 — argparse `nargs="*"` + a message beginning with `-` will be mis-parsed as an option

Where: Decision A, the `argparse` snippet
(`parser.add_argument("message", nargs="*")`).

With `argparse`, a bare message token that begins with `-` (e.g.
`python -m agent.chat "-stuck on this bug"`) is treated as an unknown optional and argparse
errors out, whereas today `" ".join(sys.argv[1:])` passes it through verbatim. The design
asserts the two existing invocations are "byte-for-byte unchanged," which holds for the given
examples, but the broader claim "every argv token is free-text message words" (true today) is
narrowed by argparse. Low likelihood for this CLI, hence NIT, but worth a one-line guard so a
leading-dash prompt does not regress.

Concrete fix: either document the limitation, or parse with
`parser.parse_known_args()` / insert `--` handling, or (simplest) keep the message as the
remainder after a manual `--session-id` scan rather than delegating free text to argparse:
```python
# robust: pull --session-id out, treat the rest as the message verbatim
if "--session-id" in args:
    i = args.index("--session-id"); sid = args[i+1]; msg = args[:i] + args[i+2:]
else:
    sid = None; msg = args
```

### NIT-4 — `BuildResult.session_manager` type annotated `object | None`, losing the one attribute Task 6 reads

Where: Decision C, the `BuildResult` dataclass
(`session_manager: object | None = None`).

The dataclass types `mcp_client` and `session_manager` as `object | None`, which erases the
`AgentCoreMemorySessionManager` surface Task 6 and `attach_memory` depend on (`.session_id`,
`.initialize`, `.register_hooks`). This compiles and runs fine — hence NIT — but since the
design's whole return-shape improvement is about making callers read attributes safely, a
precise annotation (even under `TYPE_CHECKING` to keep import offline-safe) would carry the
intent. The design already imports lazily elsewhere, so a `TYPE_CHECKING` import of
`AgentCoreMemorySessionManager` / `MCPClient` costs nothing at runtime.

Concrete fix:
```python
if TYPE_CHECKING:
    from strands.tools.mcp import MCPClient
    from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

@dataclass
class BuildResult:
    agent: "Agent"
    mcp_client: "MCPClient | None" = None
    session_manager: "AgentCoreMemorySessionManager | None" = None
```

---

## Offline gate feasibility

Achievable as designed:
- **`cdk synth --all`:** the new stack uses only L1 constructs that exist in the installed CDK
  (verified), required props (`name`, `event_expiry_duration`) are supplied, the API key comes
  from a `CfnParameter(no_echo=True)` with a mock default so synth has a value, and the stack
  has no cross-stack references, so synth ordering is unaffected.
- **Offline `build_agent`:** verified against `agent.py` — not passing `session_manager=` into
  `Agent(...)` means the `AgentInitializedEvent` fired at `:609` reaches no memory callback, so
  no `initialize`/network at construction. Identity stays offline because `@requires_api_key`
  (which builds `IdentityClient` eagerly) is applied only to a body-local `_inner` invoked on a
  real enabled call; the module-level `from ... import requires_api_key` is inert.
- **`>=55 passed / 1 skipped` preserved:** with both toggles off no session-manager is built,
  no hook added, and the tool reads the static token; the three existing DIRECT/GATEWAY tests
  are migrated to read `BuildResult` attributes in the same change, keeping behavior identical.
  New Task-5 tests are additive.
- **Zero LangChain:** no new dependency introduced; every symbol is already importable in the
  existing venvs (verified for the SDK symbols, CDK constructs).

## User-visible DIRECT/GATEWAY default behavior

No finding forces a change. With `MAHALO_MEMORY_ENABLED` and `MAHALO_IDENTITY_ENABLED` unset
(defaults), `build_agent()` returns `BuildResult(agent, mcp_client=None, session_manager=None)`
and `build_agent(tool_mode="gateway")` returns the constructed-not-started MCP client with
`session_manager=None`; the Identity tool path reads `settings.jira_token` exactly as today.
The only behavioral surface the NITs touch is the new (memory-on-only) session notice and the
argparse edge case — neither alters DIRECT/GATEWAY output when the toggles are off. The
`BuildResult` migration changes the `build_agent` *return type* (an internal call-site
contract), not any end-user-observable CLI behavior.

---

## Verified Assumptions

- Strands `HookRegistry.add_hook(provider)` runs `provider.register_hooks()`; `Agent.add_hook`
  registers a single callback and would NOT — the HIGH-fix rationale is correct. (source §1,2)
- `Agent.__init__` only wires a session manager when one is passed, and fires
  `AgentInitializedEvent` at the end of `__init__`; building without `session_manager=` is
  genuinely offline at construction. (source §3)
- Base `SessionManager.register_hooks` installs the init + per-turn persistence callbacks, and
  AgentCore's sync-mode `register_hooks` delegates to it; the line-984 async branch is not on
  the sync path. (source §4,5)
- `requires_api_key` is keyword-only (`*, provider_name, into="api_key"`), constructs
  `IdentityClient` at decoration time, injects at call time, and has a working sync wrapper —
  so deferring decoration to a body-local `_inner` keeps import offline. (source §6)
- The local dev-auth path self-provisions its own workload identity and writes
  `.agentcore.json`; the CDK `CfnWorkloadIdentity` is not consumed by the local CLI demo.
  (source §7)
- `CfnMemory` / `CfnWorkloadIdentity` / `CfnApiKeyCredentialProvider` exist at the cited lines;
  `CfnMemory` STM-only shape (no `memory_strategies`) is valid; `event_expiry_duration` + `name`
  are required. (source §8)
- Current repo state (tuple-returning `build_agent`, no-argparse `main`, `gateway_region`
  default, `_build_gateway_mcp_client` guard, `jira_create_story` signature, lazy-boto3 pattern)
  matches every premise the design builds on. (source §9)

## Unverified / Wrong Assumptions

None. Every load-bearing Memory/Identity SDK claim and every CDK/repo premise in the design was
re-opened in source and matches. The citation line numbers are occasionally off by a few lines
(`registry.py:287` vs ~286; base `register_hooks` "48–57" vs ~44–62), but the symbols, methods,
and control flow are correct — not material enough to be a finding.

---

## Verdict

0 HIGH, 0 MEDIUM, 4 NIT → **APPROVED**. The design stands on its own, resolves all four open
questions concretely, grounds its SDK/CDK claims in source (independently re-verified), keeps
the offline gate achievable, and changes no DIRECT/GATEWAY default behavior. The four NITs are
polish — snippet completeness, a notice-wording rule, an argparse edge case, and a type
annotation — and none blocks implementation.
