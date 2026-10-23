# Task 5 Design â€” AgentCore Memory & Identity

Technical design for adding Amazon Bedrock AgentCore **Memory** (session/conversation
persistence) and AgentCore **Identity** (tool credential brokering) to the existing
Strands agent. Every decision below is grounded in the Task-5 investigation
(`docs/.agents/tasks/task5-investigation.md`), the current architecture
(`docs/ARCHITECTURE.md`), the installed SDK/CDK source cited there, and the live repo
files it modifies. All artifact paths are workspace-relative forward-slash under the repo
root.

The automated gate for this task is **OFFLINE** (synth / unit tests / import). Creating
the Memory/Identity resources and running a live session that persists and reloads
history is **documented for the operator**, not executed here.

> **Revision note.** This is revision 3, authored in response to
> `docs/.agents/tasks/task5-design-review.md` / `.json` for revision 2 (verdict
> CHANGES_REQUESTED: 1 HIGH + 2 MEDIUM + 2 NIT). Every finding is addressed in the body;
> the point-by-point disposition is in the **Review responses** section at the end. The
> Memory config assembly, the Identity composition (`@requires_api_key` on a body-local
> `_inner`), the CDK stack, and the CLI flag-parsing spec were all confirmed correct by the
> review and are preserved. The revision-3 corrections are concentrated in the **hook
> registration API** used by `attach_memory` (the HIGH finding â€” `agent.hooks.add_hook(...)`,
> not `agent.add_hook(...)`), the **sync-mode `register_hooks` citation** (MEDIUM), the
> **local-vs-CDK workload-identity behavior** in the Identity slice (MEDIUM), and two NIT
> fixes (a `BuildResult` object replacing variable-arity tuples, and an exact
> `MAHALO_MEMORY_REGION` fallback).

---

## Overview

The agent today is a stateless CLI. `agent/strands_agent.py::build_agent` constructs a
fresh `strands.Agent` per invocation, and conversation history survives only in-process
via Strands' own `agent.messages` list (`agent/chat.py::_repl_loop`). There is no
cross-invocation persistence. Task 4 added the GATEWAY tool mode behind
`MAHALO_TOOL_MODE`, with an offline-safe `build_agent` that constructs â€” but never starts
â€” the MCP client. Task 5 follows that exact pattern: it adds two new **opt-in, additive**
capabilities that leave DIRECT and GATEWAY modes, and the full existing test baseline (55
passed, 1 skipped), untouched when the new toggles are off.

For Memory, the design plugs AgentCore Memory into Strands through the native, documented
`session_manager=` seam (`AgentCoreMemorySessionManager`, which subclasses Strands' own
`RepositorySessionManager`). This replaces the role that mahalo-dock's in-memory
`_sessions` dict played â€” a durable, managed, session-keyed conversation store â€” while
keeping the DIRECT CLI fully working. Task 5 delivers Memory as a **wired, testable
capability now**: a session-id-parameterized CLI that persists and reloads history across
invocations, which also serves as the integration seam Task 6's Runtime + thin API will
reuse (Decision A).

For Identity, the design scopes to the **smallest coherent real slice**: provision an
AgentCore workload identity and one API-key credential provider via CDK, and wire a single
representative outbound tool path (`jira_create_story`) to fetch its token at call time
behind a toggle, demonstrating call-time credential brokering without touching the Task-4
inbound SigV4 / `GATEWAY_IAM_ROLE` / `X-API-Token` chain that already works end to end.
Full per-service brokering and the Runtime-minted Workload Access Token path are explicitly
deferred to Task 6 (Decision B).

Resources are provisioned with CDK L1 constructs (`CfnMemory`, `CfnWorkloadIdentity`,
`CfnApiKeyCredentialProvider`) in a new destroyable stack, with `CfnOutput` â†’
environment-variable plumbing, mirroring `MahaloGatewayStack` (Decision D). Both
capabilities keep `build_agent(...)` offline-safe at construction. The precise reason it
stays offline-safe â€” pinned to the installed Strands 1.61.1 source â€” is the crux of
Decision D: **no network happens at import or at `build_agent(...)` construction; AWS is
reached only when a credential/history read is explicitly triggered** (the `attach_memory`
rehydrate, or an actual tool call fetching a credential).

---

## Technology stack (locked once approved)

- **Language / runtime:** Python 3, same interpreters already in the repo
  (`agent/.venv`, `infra-cdk/.venv`).
- **Agent framework:** `strands-agents==1.61.1`. Two distinct hook-registration APIs matter
  here and the design uses the correct one (verified against
  `agent/.venv/Lib/site-packages/strands`):
  - `Agent.add_hook(callback, event_type=None, *, order=...)` (`strands/agent/agent.py`,
    body ends `self.hooks.add_callback(event_type, callback, order=order)`) registers a
    **single callback function** and infers the event type from the callback's first-parameter
    type hint. It does **not** register a `HookProvider`'s callbacks â€” passing a provider here
    is wrong.
  - `HookRegistry.add_hook(hook: HookProvider)` (`strands/hooks/registry.py:287`) delegates to
    `hook.register_hooks(self)`, which is what installs a provider's callbacks. This is the
    method the design uses for the session manager, matching `Agent.__init__` itself, which
    calls `self.hooks.add_hook(self._session_manager)` (`strands/agent/agent.py` ~line 549,
    under `if self._session_manager:`). `Agent.__init__` also stores `session_manager` (param
    at line 225) and fires `AgentInitializedEvent` via `self.hooks.invoke_callbacks(...)` at
    the end of `__init__` (~line 609).
- **AgentCore SDK:** `bedrock-agentcore==1.24.1` â€” specifically
  `bedrock_agentcore.memory.integrations.strands.session_manager.AgentCoreMemorySessionManager`
  and its `register_hooks` override (verified in source). In the **default sync mode**
  (`async_mode=False`, which Task 5 uses), `register_hooks` delegates to
  `RepositorySessionManager.register_hooks(self, registry, **kwargs)`, which reaches the base
  `strands/session/session_manager.py::SessionManager.register_hooks` (lines ~48â€“57) â€” that
  base method is what registers `add_callback(AgentInitializedEvent, lambda e:
  self.initialize(e.agent))` **and** the per-turn `MessageAddedEvent` /
  `AfterInvocationEvent` persistence callbacks. The explicit
  `add_callback(AgentInitializedEvent, ...)` near line 984 of the AgentCore file is the
  **`async_mode` branch only** and is not used by Task 5. Also used:
  `AgentCoreMemorySessionManager.initialize(self, agent, **kwargs)` (the rehydrate),
  `...strands.config.AgentCoreMemoryConfig` / `RetrievalConfig`, and (Identity)
  `bedrock_agentcore.identity.auth.requires_api_key`.
- **IaC:** `aws-cdk-lib>=2.251,<3` (installed 2.273.0), module
  `aws_cdk.aws_bedrockagentcore` â€” `CfnMemory`, `CfnWorkloadIdentity`,
  `CfnApiKeyCredentialProvider`.
- **AWS:** profile `lava`, region `us-east-1`, account `<AWS_ACCOUNT_ID>`.
- **No LangChain** (unchanged repo constraint).

No new third-party dependency is introduced; every symbol above is already importable in
the existing venvs per the investigation and re-verified against source for this revision.

---

## Decision A â€” Memory scope & integration

**Decision: deliver Memory as a wired, testable capability NOW via a
session-id-parameterized CLI, which simultaneously is the integration seam Task 6 reuses.**

The investigation confirms (Â§1.4) the `AgentCoreMemorySessionManager` talks to AgentCore
Memory over boto3 data/control clients it builds itself and does **not** require Runtime â€”
it works from the local CLI exactly like the Task-4 Gateway client. So there is no reason
to ship Memory as a dormant seam; wiring it into the CLI now both proves the capability
offline-safely (construction) and live (operator step) and leaves Task 6 a clean, already-
exercised function to call with a real per-request `session_id`.

### What state is persisted and how it is keyed

We persist **short-term conversation turns** â€” the user/assistant message events that make
up a conversation â€” keyed by:

- `actor_id` â€” the user/agent identity. Defaults to the `developer_id` already threaded
  through `build_agent` (`dev-6`, the demo "Lava Dev"). Reusing one `actor_id` across a
  user's sessions is what lets long-term memory accumulate per user later; mahalo-dock's
  `services/identity.py` already maps all demo logins to `dev-6`, so this is consistent.
- `session_id` â€” one conversation. The CLI has **no real multi-user session** yet, so
  Task 5 owns session-id *provenance* explicitly (precedence spelled out below).

This is exactly the behavior mahalo-dock's in-memory store provided
(`get_or_create_session(session_id)` returning/creating a `ChatSession`), upgraded to a
durable managed store. The old `_sessions` dict and `clear_session` are replaced by
AgentCore Memory's event store keyed on `(memory_id, actor_id, session_id)`; "clear a
session" maps to starting a new `session_id`.

### Session-id resolution and CLI flag parsing (addresses review finding 3)

The current `agent/chat.py::main` does `args = sys.argv[1:]; ... _run_single(" ".join(args))`
â€” there is **no argparse**; every argv token is free-text message words. Introducing a
`--session-id` flag must not break the two existing invocations
(`python -m agent.chat "show my stories"` single-shot, and the bare-REPL
`python -m agent.chat`). The design therefore specifies the exact parser and the exact
resolution helper:

```python
# agent/chat.py
import argparse
import os
import uuid

def _resolve_session_id(flag_value: str | None) -> str | None:
    """Session-id precedence: --session-id flag > MAHALO_SESSION_ID env > uuid4.

    The uuid4 fallback is used ONLY when Memory is enabled and neither the flag nor
    the env var supplied an id; when Memory is off this returns None and the id is
    never used. Returns a stripped non-empty string or None.
    """
    if flag_value is not None and flag_value.strip():
        return flag_value.strip()
    env_value = os.getenv("MAHALO_SESSION_ID", "").strip()
    if env_value:
        return env_value
    if settings.memory_enabled:
        return uuid.uuid4().hex
    return None

def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="agent.chat", add_help=True)
    parser.add_argument("--session-id", dest="session_id", default=None)
    parser.add_argument("message", nargs="*")
    ns = parser.parse_args(args)
    session_id = _resolve_session_id(ns.session_id)
    if ns.message:
        _run_single(" ".join(ns.message), session_id=session_id)
    else:
        _run_repl(session_id=session_id)
```

Parsing contract, stated so an implementer cannot regress it:

- Message words after options are still **joined with a single space**, so
  `python -m agent.chat "show my stories"` sends exactly `show my stories` as today, and
  `python -m agent.chat` (no args) still enters the REPL. These two existing invocations
  are byte-for-byte unchanged in behavior.
- `--session-id` is an optional flag; when absent and Memory is off, `_resolve_session_id`
  returns `None` and nothing about sessions is printed or used (default output unchanged).
- A generated uuid is **not** persisted to disk by Task 5; durable resume is an explicit
  user action (re-supply the id via flag or `MAHALO_SESSION_ID`). The generated id is
  printed to the user (only when Memory is on) so they can pass it back next invocation.
- **Task 6:** the thin API supplies a real per-request `session_id` (and eventually a real
  `actor_id`) straight into the same `build_agent(..., memory=..., session_id=...)` call;
  no agent-side change is needed then.

`_resolve_session_id` is the named helper the unit tests target (monkeypatched
env/argv/`settings.memory_enabled`).

### Short-term only for Task 5 (long-term deferred behind a toggle)

Per investigation Â§5.2, Task 5 provisions a **bare `CfnMemory` (STM only, no memory
strategies)**. STM fully replaces the old in-memory session store at the lowest cost and
risk and requires no model-backed extraction. Long-term strategies (summary /
user-preference / semantic) are a deliberate, additive future enhancement; the CDK stack
exposes a `with_long_term` boolean prop (default `False`) that, when set, adds
`memory_strategies`, and the config layer exposes a matching `retrieval_config` knob â€” but
the Task-5 default and the entire offline gate assume STM only.

### HITL interaction safeguard

The Task-4 deferred-breadcrumb flush in `agent/chat.py::_ask` stays exactly as is: a
`[SYSTEM]` breadcrumb is appended to `agent.messages` only once a tool cycle fully closes.
With a session-manager attached, those appended messages are also persisted as events, so
the deferred flush is now doubly important â€” it prevents a half-open `toolUse`/`toolResult`
pair from being persisted and replayed on rehydrate. In addition, the design sets
`filter_restored_tool_context=True` on `AgentCoreMemoryConfig` (investigation Â§1.4 / Â§5.3),
which strips historical `toolUse`/`toolResult` blocks on restore. Net effect: reloaded
history carries the conversational text turns (and our `[SYSTEM]` breadcrumbs, which are
plain assistant text) but not stale tool-call scaffolding, so a resumed session cannot
replay or wedge a half-open tool cycle. This is a conservative default and is documented as
such; it can be revisited if a future task needs tool-result replay.

---

## Decision B â€” Identity scope

**Decision: provision a `CfnWorkloadIdentity` plus one `CfnApiKeyCredentialProvider`, and
wire ONE representative outbound tool path (`jira_create_story`) to fetch its token at call
time, behind an opt-in toggle. The `@requires_api_key` decorator is applied to a
body-local helper, NOT to the `@tool`-decorated function, and the toggle is a plain
body-level conditional. Defer per-service brokering and the Runtime WAT path to Task 6. Do
not touch Task-4 auth.**

The investigation (Â§2.3) establishes the critical delineation: Task 4 solved **inbound**
auth to the Gateway (agent SigV4-signs as `bedrock-agentcore` for the default `AWS_IAM`
authorizer). AgentCore Identity is about **outbound** credentials â€” what the agent or
Gateway presents to the backend tool. They do not overlap, and the user has explicitly
chosen to keep `AWS_IAM` now and defer Cognito to development mode. The four backends are
mocks guarded by a static `X-API-Token` that already works end to end.

Given that, full Identity brokering across all four services would be largely demonstrative
and would risk the working chain. So Task 5 ships the **minimum coherent, real, testable
slice**:

1. A **workload identity** (`CfnWorkloadIdentity`, name `mahalo-agent`) â€” the foundational
   resource the **Task-6 Runtime** path will use to retrieve brokered credentials (where the
   Runtime platform mints the Workload Access Token the agent runs under). Important nuance,
   verified against source and addressed in "Local vs. CDK workload identity" below: the
   **Task-5 local-CLI demo does NOT consume this resource** â€” the SDK's local dev-auth path
   self-provisions its own local workload identity. The `CfnWorkloadIdentity` is provisioned
   now because every future (Runtime) Identity use needs it and it belongs in the same
   destroyable stack, but Task 5 does not claim the local demo runs "under" it.
2. **One API-key credential provider** (`CfnApiKeyCredentialProvider`, name
   `mahalo-jira-apikey`) holding what is today the static `JIRA_TOKEN`.
3. A **single wired outbound path**: in DIRECT mode, `jira_create_story` (one representative
   write) fetches its token from Identity at call time when `MAHALO_IDENTITY_ENABLED` is on,
   instead of reading the static `settings.jira_token`.

### How the Identity slice is actually wired

The revision-2 review confirmed this composition is correct; it is preserved here verbatim.
Three hard constraints from source drive it:

- `@requires_api_key` (`bedrock_agentcore/identity/auth.py`) injects an `api_key=` keyword
  argument into the decorated function **at call time**, and constructs an `IdentityClient`
  (two boto3 clients) **at decorator-application time**.
- Strands' `@tool` (`strands/tools/decorator.py`) builds the LLM-facing Pydantic schema from
  `inspect.signature(func)` at decoration time.

Therefore the decorator must **not** wrap the `@tool`-decorated `jira_create_story`
(injecting `api_key=` would either raise `TypeError` on a function with no such parameter,
or leak `api_key` into the LLM schema if declared; and applying it at module scope would
build an `IdentityClient` at import, violating offline-at-import). The decorator also
**cannot be "conditionally un-applied"** at runtime â€” a decorator binds at import time.

The design resolves all of this with **one** mechanism: the credential fetch lives in a
body-local helper that is **defined and invoked only inside the tool body, only when the
toggle is on.** The `@tool` signature is untouched, no `IdentityClient` is built at import,
and the toggle is a plain conditional:

```python
# agent/tools/jira_write_tools.py  (only the create path changes; update path untouched)
from bedrock_agentcore.identity.auth import requires_api_key   # module-level import is safe

def _fetch_jira_token() -> str:
    """Fetch the brokered Jira API key via AgentCore Identity.

    The @requires_api_key decorator is applied to this INNER function (defined only
    when this helper runs), so the IdentityClient / boto3 clients are built only on a
    real call with identity enabled â€” never at import. The decorator injects api_key=.
    """
    @requires_api_key(provider_name=settings.identity_jira_provider, into="api_key")
    def _inner(*, api_key: str) -> str:
        return api_key
    return _inner()

@tool
def jira_create_story(project_id, title, description, priority="medium",
                      story_points=0, assignee=None) -> str:
    """... unchanged docstring / signature (LLM schema unchanged) ..."""
    body = {...}
    # Toggle is a plain body-level conditional; decorator is never "un-applied".
    try:
        token = _fetch_jira_token() if settings.identity_enabled else settings.jira_token
    except Exception as exc:                      # botocore ClientError / ValueError / etc.
        return f"âŒ Failed to create story: credential fetch failed ({type(exc).__name__})"
    try:
        data = make_request(settings.jira_url, token, endpoint="/stories",
                            method="POST", body=body)
    except (httpx.HTTPError, OSError) as exc:
        return f"âŒ Failed to create story: {exc}"
    if "error" in data:
        return f"âŒ Failed to create story: {data['error']}"
    return f"âœ… Story created successfully: **{data['id']}** - {data['title']}"
```

Key properties (all re-confirmed correct by the revision-2 review's "Verified Assumptions"):

- **Composition:** `@requires_api_key` wraps `_inner`, a trivial nested function, not the
  Strands tool. `jira_create_story`'s signature and `@tool` schema are byte-for-byte
  unchanged, so existing write-tool tests and the LLM-facing contract are untouched. The
  fetched key is a return value of a helper, never a tool parameter.
- **Toggle:** the only toggle mechanism is
  `token = _fetch_jira_token() if settings.identity_enabled else settings.jira_token`. No
  decorator is ever conditionally applied/un-applied (a decorator binds at import time). With
  `identity_enabled` false the body reads the static token exactly as today.
- **Offline import:** because `@requires_api_key` is applied to `_inner`, which is defined
  only when `_fetch_jira_token()` runs, importing `jira_write_tools` constructs no
  `IdentityClient` and no boto3 client. The module-level `from ... import requires_api_key`
  is a plain import (no network, no client). This is unit-asserted (see Testability).
- **Error handling:** the fetch can raise `ClientError`/`ValueError`, so it is wrapped in
  `try/except Exception` returning the existing `âŒ Failed to create story: ...` string shape
  (the tool contract is "never raise"). The message is **type-name only** and never contains
  the key value.

### Local vs. CDK workload identity (addresses review finding 3)

A source fact the previous revision glossed over: on a **local (non-Runtime) CLI call** with
Identity enabled, `requires_api_key`'s token fetch goes
`_get_workload_access_token â†’ _set_up_local_auth(client)` (verified in
`agent/.venv/.../bedrock_agentcore/identity/auth.py`). `_set_up_local_auth`:

- **creates its own** local workload identity via `client.create_workload_identity()` when
  none is cached, and
- **writes a `.agentcore.json`** file into the current working directory to cache that local
  identity.

It does **not** use the CDK-provisioned `CfnWorkloadIdentity name="mahalo-agent"`. This is a
**live-only** behavior â€” it has no effect on the offline gate â€” but the design must narrate it
accurately. **Decision (review option a):** keep the DIRECT-CLI live Identity demo, and
document explicitly that:

- The Task-5 **local CLI demo** uses the SDK's local dev-auth path, which self-provisions a
  local workload identity and writes `.agentcore.json` to the run directory. Operators should
  expect that file to appear (it is a dev-auth cache; it can be deleted to force
  re-provisioning). The runbook notes this.
- The CDK `CfnWorkloadIdentity name="mahalo-agent"` is provisioned for the **Task-6 Runtime**
  path (where the platform mints the Workload Access Token), **not** consumed by the Task-5
  local demo. The design no longer claims the local demo retrieves credentials "under" the
  provisioned identity.

The alternative (review option b â€” make Identity provision-only in Task 5 and defer the live
brokered call to Task 6) was rejected because the goal for Task 5 is a *real, testable*
Identity slice, and the SDK's local dev-auth path makes the live API-key brokering genuinely
exercisable from the CLI today (the credential provider and the fetched key are real); only
the *workload-identity provenance* differs from Runtime, which is now documented rather than
mis-stated.

### What is explicitly deferred to Task 6 / Runtime

With a note in the design and the operator runbook:

- Brokering the other services and the read tools.
- The Runtime-minted **Workload Access Token** path (`requires_wat`) â€” investigation Â§2.3
  confirms this is Runtime-coupled (raises when no WAT is in the request context) and cannot
  be exercised from the local CLI.
- Moving the Gateway target's `credential_provider_configurations` from `GATEWAY_IAM_ROLE`
  to an OAuth2/API-key provider. Task 4's `GATEWAY_IAM_ROLE` + `X-API-Token` chain stays
  **unchanged** in `infra-cdk/mahalo_infra/gateway_stack.py`; Task 5 adds no edit there.

### Why DIRECT mode for the Identity demo, not GATEWAY

The credential fetch runs inside our own `jira_create_story` Python function, so it only
exists on the DIRECT tool path. In GATEWAY mode the tool runs inside the Lambda behind the
Gateway, so the credential would have to be brokered at the Gateway target config layer â€”
the deferred Task-6 item above. Choosing the DIRECT tool as the demo path keeps the slice
real and offline-testable (mock `_inner`/`requires_api_key`, assert the injected value is
used, assert no key is logged).

---

## Decision C â€” Dual-mode / non-regression toggles

**Decision: Memory and Identity are OPT-IN and additive. Default behavior is byte-for-byte
unchanged; all new env vars default to "off"/empty, consistent with the `MAHALO_TOOL_MODE`
style.**

New settings added to `agent/config.py` `Settings` (same `_getenv`-with-default pattern):

| Env var | Setting field | Default | Meaning |
|---|---|---|---|
| `MAHALO_MEMORY_ENABLED` | `memory_enabled: bool` | `"false"` â†’ `False` | Master toggle for Memory. |
| `MAHALO_MEMORY_ID` | `memory_id: str` | `""` | The `CfnMemory` id (from the stack `CfnOutput`). |
| `MAHALO_MEMORY_REGION` | `memory_region: str` | `_getenv("MAHALO_MEMORY_REGION", _getenv("AWS_REGION", "us-east-1"))` | Region for the memory clients, mirroring `gateway_region` **verbatim** including the literal `"us-east-1"` final fallback. |
| `MAHALO_SESSION_ID` | `session_id: str` | `""` | Default conversation id (overridden by `--session-id`). |
| `MAHALO_IDENTITY_ENABLED` | `identity_enabled: bool` | `"false"` â†’ `False` | Master toggle for Identity credential brokering. |
| `MAHALO_IDENTITY_JIRA_PROVIDER` | `identity_jira_provider: str` | `"mahalo-jira-apikey"` | Credential-provider name for the demo path. |

Boolean parsing uses a small helper
(`_getenv(name, "false").strip().lower() in {"1","true","yes"}`) so values are tolerant and
documented.

> **Retention config dropped (carried over from the revision-1 review).** An earlier revision exposed a
> `MAHALO_MEMORY_EVENT_EXPIRY_DAYS` agent setting, but the agent never reads retention â€” it
> is a provisioning-time property owned by the CDK stack. Per the review's recommended
> option (a), this setting is **removed from the agent config**; `event_expiry_duration`
> lives only in the stack (see Decision D). Six new settings, not seven.

`build_agent(...)` gains three new keyword-only parameters, all defaulting to values that
reproduce today's behavior:

```python
def build_agent(
    role="developer", user_name="Lava Dev", user_role="Developer",
    developer_id="dev-6", tool_mode=None,
    *,
    memory: bool | None = None,       # None -> settings.memory_enabled; False forces off
    session_id: str | None = None,    # None -> settings.session_id (may be "")
    identity: bool | None = None,     # None -> settings.identity_enabled
) -> "BuildResult":
```

Rules that preserve the baseline:

- When `memory` resolves to `False` (the default, because `MAHALO_MEMORY_ENABLED` defaults
  off), **no `session_manager` is constructed, no hook is added, and nothing changes** â€” the
  existing tests that call `build_agent()` / `build_agent(tool_mode="gateway")` with no creds
  keep passing (DIRECT 42/1, Task-4 gateway/HITL). Memory composes with either tool mode.
- When `memory` is `True` but `memory_id` is empty, `build_agent` raises a `ValueError`
  with a clear message (mirroring the GATEWAY "requires `MAHALO_GATEWAY_MCP_URL`" guard),
  surfacing misconfiguration early rather than at first turn.
- When `identity` resolves to `False` (default), the decorated tool path reads the static
  `settings.jira_token` exactly as today (Decision B conditional).

`agent/chat.py` passes `memory=settings.memory_enabled` and the resolved `session_id`
through its construction calls, and prints a one-line "resuming session `<id>`" / "new
session `<id>`" notice **only** when Memory is enabled, so default output is unchanged.

### `build_agent` return shape: a `BuildResult` object (addresses review finding 4)

The revision-2 review flagged the previous variable-arity tuple return (`Agent`,
`(agent, session_manager)`, `(agent, mcp_client)`, or `(agent, mcp_client, session_manager)`)
as a latent trap: callers would have to branch on `len(result)`, and Task 6 is promised the
same function. **This revision replaces the tuples with a small result object** so callers
read attributes instead of decoding arity:

```python
# agent/strands_agent.py
from dataclasses import dataclass

@dataclass
class BuildResult:
    agent: "Agent"
    mcp_client: object | None = None        # set only in GATEWAY mode
    session_manager: object | None = None   # set only when memory is on (un-initialized)
```

`build_agent(...)` **always** returns a `BuildResult`. The attributes present per mode/toggle:

| Mode / toggle | `result.agent` | `result.mcp_client` | `result.session_manager` |
|---|---|---|---|
| DIRECT, memory off (today's default) | âœ“ | `None` | `None` |
| DIRECT, memory on | âœ“ | `None` | un-initialized manager |
| GATEWAY, memory off | âœ“ | constructed, not started | `None` |
| GATEWAY, memory on | âœ“ | constructed, not started | un-initialized manager |

**Caller-migration note (so the baseline is preserved):** the existing tests and
`agent/chat.py` unpack `build_agent()` as a bare `Agent` and `build_agent(tool_mode="gateway")`
as `(agent, mcp_client)`. Moving to `BuildResult` is a **breaking change to those call sites**,
so this revision updates them in the same change: `agent/chat.py` reads `result.agent` /
`result.mcp_client` / `result.session_manager`, and the three existing DIRECT/GATEWAY tests
that unpack the old shapes are updated to read the attributes. This keeps behavior identical
(same objects, same offline construction) while removing the arity trap; the net test count
stays 55/1 plus the new Task-5 tests. Task 6 reads `result.session_manager` and
`result.agent` directly â€” no arity branching. The CLI still calls
`attach_memory(result.agent, result.session_manager)` after construction when
`result.session_manager is not None` (symmetry with GATEWAY's
`attach_gateway_tools(result.agent, result.mcp_client)`).

---

## Decision D â€” IaC placement & offline-safety

**Decision: a new `MahaloMemoryIdentityStack` under `infra-cdk/mahalo_infra/`, wired in
`infra-cdk/app.py`, using CDK L1 constructs with `CfnOutput` â†’ env. No boto3 custom
resource. `build_agent(...)` with memory/identity enabled constructs offline-safe; the
network is reached only by the explicit `attach_memory` rehydrate or a real credential-using
tool call.**

### Stack: `infra-cdk/mahalo_infra/memory_identity_stack.py`

Follows `MahaloGatewayStack` conventions (per-feature `Stack` subclass, `env=_ENV`,
`CfnOutput`s, `RemovalPolicy.DESTROY` so it is torn down per the Task-8 teardown
requirement). Contents:

- `agentcore.CfnMemory` â€” `name="mahalo-memory"`, `event_expiry_duration=30` (STM only; no
  `memory_strategies` unless a `with_long_term=True` prop is passed). This is the durable
  store that replaces mahalo-dock's in-memory `_sessions`.
  - **Retention wording (carried over from the revision-1 review):** `event_expiry_duration` is a **required** `CfnMemory` prop in
    the installed CDK (no CDK default); the "Defaults to 30" in its docstring describes the
    *AgentCore service* behavior. We pass `30` explicitly so the provisioned retention is
    deterministic and documented. (The prior "CDK default 30" phrasing is corrected here.)
- `agentcore.CfnWorkloadIdentity` â€” `name="mahalo-agent"`.
- `agentcore.CfnApiKeyCredentialProvider` â€” `name="mahalo-jira-apikey"`; the API-key
  **value** is supplied at deploy time via a `CfnParameter` (`no_echo=True`) so the secret is
  never committed to source, defaulting to the existing mock token so synth has a value.
- `CfnOutput`s: `MemoryId` (â†’ `MAHALO_MEMORY_ID`), `WorkloadIdentityArn`,
  `JiraApiKeyProviderName` (â†’ `MAHALO_IDENTITY_JIRA_PROVIDER`) â€” mirroring how `GatewayMcpUrl`
  feeds `MAHALO_GATEWAY_MCP_URL`.

`infra-cdk/app.py` adds one line constructing `MahaloMemoryIdentityStack(app,
"MahaloMemoryIdentityStack", env=_ENV)`. The stack is independent of the mock/gateway stacks
(no cross-references), so `cdk synth --all` ordering is unaffected.

The exact optional-prop names (e.g. `api_key`/`api_key_secret_source`) will be read from
`infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py` (classes at the
lines cited in investigation Â§3) during implementation; the design commits to these
constructs, the required props (`name`, `event_expiry_duration`), and the STM-only shape.

### Offline-safety at construction (the crux â€” addresses review findings 1, 2)

The precise, source-verified mechanism (corrected from the revision-2 citation, which pointed
at the async-mode branch):

- In `strands/agent/agent.py`, `Agent.__init__` stores `self._session_manager =
  session_manager` and, **only if a manager was passed**, derives `self._session_id` from it
  and calls `self.hooks.add_hook(self._session_manager)` (~lines 547â€“549, inside
  `if self._session_manager:`). Note this is `self.hooks.add_hook(...)` â€” the
  **`HookRegistry.add_hook(provider)`** method, which runs `provider.register_hooks(...)`.
- At the **end** of `__init__` it calls
  `self.hooks.invoke_callbacks(AgentInitializedEvent(agent=self))` (~line 609). This
  synchronously fires `AgentInitializedEvent`.
- In **sync mode** (Task 5's mode), `AgentCoreMemorySessionManager.register_hooks` delegates
  to `RepositorySessionManager.register_hooks`, which reaches the base
  `strands/session/session_manager.py::SessionManager.register_hooks` (~lines 48â€“57). That
  base method registers `add_callback(AgentInitializedEvent, lambda event:
  self.initialize(event.agent))` (so the `AgentInitializedEvent` fired at ~line 609 would call
  `initialize`), plus the per-turn `MessageAddedEvent` (`append_message` + `sync_agent`) and
  `AfterInvocationEvent` (`sync_agent`) persistence callbacks. (The
  `add_callback(AgentInitializedEvent, ...)` near line 984 of the AgentCore file is the
  **`async_mode` branch only** and is irrelevant to Task 5.)
- **Net:** passing a live `session_manager=` into `Agent(...)` would â€” through
  `hooks.add_hook(manager)` â†’ sync-mode `register_hooks` â†’ the base
  `AgentInitializedEvent â†’ initialize` callback firing at construction â€” trigger the network
  rehydrate (`initialize`: `read_session`/`read_agent`/`list_messages`) **synchronously during
  construction**. That is exactly what would break offline construction.

The design therefore mirrors the Task-4 MCP-client "construct, do not start" pattern:

- A new module `agent/memory_client.py` exposes `build_memory_session_manager(session_id,
  actor_id, *, region) -> AgentCoreMemorySessionManager`. Like
  `gateway_client._build_gateway_mcp_client`, it **constructs** the manager and its
  `AgentCoreMemoryConfig` but performs **no network call itself**. boto3 is imported lazily
  inside the function body (as `SigV4Auth.auth_flow` does), so importing the module never
  requires boto3/creds. The config is assembled with `filter_restored_tool_context=True`,
  `batch_size=1`, the resolved `actor_id`/`session_id`, and STM-only (no `retrieval_config`
  unless `with_long_term` is wired later).
- `build_agent(memory=True)` constructs the bare `Agent` **without** passing
  `session_manager=` and **without** registering the manager as a hook. Because neither
  happens, the `AgentInitializedEvent` fired at ~line 609 reaches **no** memory callback, so
  **no rehydrate and no network occur at construction.** `build_agent` returns the
  un-initialized manager on `BuildResult.session_manager` (per the return-shape rule in
  Decision C).
- A new helper `attach_memory(agent, session_manager)` in `agent/strands_agent.py` (symmetric
  with `attach_gateway_tools`) is the **single place** that wires Memory live, and it does
  **both** required steps (addresses review finding 1):

  ```python
  def attach_memory(agent, session_manager) -> None:
      # HookRegistry.add_hook(provider) -> provider.register_hooks(...), which in sync mode
      # installs the AgentInitializedEvent->initialize AND the per-turn MessageAddedEvent /
      # AfterInvocationEvent persistence callbacks (base SessionManager.register_hooks,
      # strands/session/session_manager.py:48-57). This is the SAME call Agent.__init__
      # makes at agent.py:549.
      agent.hooks.add_hook(session_manager)
      # AgentInitializedEvent already fired during the bare construction and will NOT re-fire,
      # so perform the rehydrate exactly once, explicitly.
      session_manager.initialize(agent)
      # Match the agent's session id to the manager (the value Agent.__init__ would have
      # derived at ~agent.py:547 had a manager been passed in).
      agent._session_id = session_manager.session_id
  ```

  1. **`agent.hooks.add_hook(session_manager)`** â€” the **`HookRegistry`** method (not
     `Agent.add_hook`). `HookRegistry.add_hook(provider)` (`strands/hooks/registry.py:287`)
     calls `provider.register_hooks(...)`, which in sync mode installs both the
     `AgentInitializedEvent â†’ initialize` callback **and** the per-turn
     `MessageAddedEvent`/`AfterInvocationEvent` persistence callbacks (â†’ `append_message` â†’
     `create_event`) so future turns actually persist. Using `Agent.add_hook(session_manager)`
     here would be the HIGH bug the review caught: that method registers a *single callback*
     via `self.hooks.add_callback(...)` and infers the event type from the argument's type
     hint â€” a `HookProvider` is not a callback, so it would mis-register (or raise) and the
     per-turn persistence callbacks would **never** be installed, meaning Memory silently
     persists nothing.
  2. **`session_manager.initialize(agent)`** â€” called **exactly once** to perform the
     rehydrate, because `AgentInitializedEvent` already fired during the bare construction and
     will **not** re-fire (the manager was not attached at that point). Yes, step 1 also
     registers an `AgentInitializedEvent â†’ initialize` callback, but that callback only fires
     on a *future* `AgentInitializedEvent`, which does not happen for an already-constructed
     agent; hence the single explicit `initialize(agent)` call. Then it sets
     `agent._session_id = session_manager.session_id` so the agent's session id matches the
     manager.

  A bare `agent._session_manager = session_manager` assignment is explicitly **rejected**: it
  registers no callbacks and triggers no rehydrate, so it would silently persist nothing.

- **CLI teardown:** `batch_size=1` means there is nothing to flush (investigation Â§1.2), so
  Task 5 requires no context-manager/`close()` dance â€” one less failure mode. A
  `with_long_term`/batched future enhancement would add `close()` in a `finally`; noted, not
  built.

- **Identity offline-safety:** `from bedrock_agentcore.identity.auth import requires_api_key`
  at module scope is a plain import (no network, no client). The decorator is applied only to
  the body-local `_inner` inside `_fetch_jira_token()`, which runs only on a real
  `jira_create_story` call with `identity_enabled` true â€” so importing `jira_write_tools` and
  constructing `build_agent(identity=True)` both stay fully offline; no `IdentityClient`/boto3
  client is created until an actual brokered call. (On that real call, from the local CLI, the
  SDK's local dev-auth path self-provisions a workload identity and writes `.agentcore.json` â€”
  see Decision B "Local vs. CDK workload identity".)

---

## Files to create / modify

Create:

- `agent/memory_client.py` â€” `build_memory_session_manager(session_id, actor_id, *, region)`
  + `AgentCoreMemoryConfig` assembly (offline-safe construction; lazy boto3;
  `filter_restored_tool_context=True`, `batch_size=1`, STM).
- `infra-cdk/mahalo_infra/memory_identity_stack.py` â€” `MahaloMemoryIdentityStack`
  (`CfnMemory` STM, `CfnWorkloadIdentity`, `CfnApiKeyCredentialProvider`, `CfnParameter`
  no-echo API key, outputs).
- `infra-cdk/tests/test_memory_identity_stack.py` â€” offline synth assertions.
- `agent/tests/test_memory_mode.py` â€” offline agent-side Memory tests.
- `agent/tests/test_identity_mode.py` â€” offline agent-side Identity tests.

Modify:

- `agent/config.py` â€” add the **six** settings fields in the table above (defaults
  off/empty). No `MAHALO_MEMORY_EVENT_EXPIRY_DAYS` (retention lives only in the CDK stack).
- `agent/strands_agent.py` â€” a new `BuildResult` dataclass (`agent`, `mcp_client=None`,
  `session_manager=None`); new keyword-only params `memory` / `session_id` / `identity` on
  `build_agent`, which now **always returns a `BuildResult`** (Decision C); new
  `attach_memory(agent, session_manager)` helper that calls **`agent.hooks.add_hook(
  session_manager)`** (the `HookRegistry` method, not `Agent.add_hook`) + a single
  `session_manager.initialize(agent)` + set `agent._session_id`; the `ValueError` guard when
  `memory=True` and `memory_id` is empty. The existing `attach_gateway_tools` is unchanged;
  the `return agent, mcp_client` / `return Agent(...)` sites are converted to return
  `BuildResult(...)`. Default (all off) construction is identical to today.
- `agent/chat.py` â€” argparse-based `main` + `_resolve_session_id` (Decision A); read
  `BuildResult.agent` / `.mcp_client` / `.session_manager` instead of tuple-unpacking; thread
  `session_id` into `_run_single(message, session_id=...)` / `_run_repl(session_id=...)`; call
  `attach_memory(result.agent, result.session_manager)` after construction when
  `result.session_manager is not None`; print the resume/new-session notice only when memory
  on. GATEWAY/DIRECT single-shot/REPL flows otherwise unchanged (the deferred-breadcrumb flush
  stays verbatim). Existing argv invocations behave identically.
- `agent/tools/jira_write_tools.py` â€” the one representative Identity path: module-level
  `from bedrock_agentcore.identity.auth import requires_api_key`; a body-local
  `_fetch_jira_token()` helper (decorated `_inner`), called only when
  `settings.identity_enabled`; the fetch wrapped in `try/except` returning the existing
  error-string shape. `jira_create_story`'s `@tool` signature and `jira_update_story` are
  unchanged.
- `infra-cdk/app.py` â€” construct `MahaloMemoryIdentityStack`.
- `docs/ARCHITECTURE.md` â€” note that Memory is now session-id-keyed STM via the Strands
  session-manager and Identity brokers the one demo outbound path (keep the diagram; it
  already shows Memory and Identity).
- `docs/CONTINUATION.md` â€” operator runbook for the live steps (below).

No edit to `infra-cdk/mahalo_infra/gateway_stack.py`, `agent/gateway_client.py`, the mock
Lambdas, or `tools-lambdas/` â€” Task-4 auth and the mock chain stay frozen.

---

## Error handling (per operation)

| Operation | Failure condition | Recoverable? | Caller receives | Logged? |
|---|---|---|---|---|
| `build_agent(memory=True)` with empty `memory_id` | Misconfiguration | Fatal (fail fast) | `ValueError("MEMORY mode requires MAHALO_MEMORY_ID (the MemoryId CfnOutput)")` | n/a (raised to CLI) |
| `build_memory_session_manager(...)` construction | Bad config (empty `session_id`/`actor_id`; `AgentCoreMemoryConfig` enforces `min_length=1`) | Fatal | `pydantic`/`ValueError` surfaced to CLI with context | No (deterministic, local) |
| `attach_memory` rehydrate (`initialize`) â€” no AWS creds | `botocore` `NoCredentialsError` / SSO expired | Recoverable by `aws sso login` | CLI prints a one-line actionable message ("Memory enabled but AWS creds unavailable â€” run `aws sso login --profile lava`, or unset `MAHALO_MEMORY_ENABLED`") and **does not** silently fall back to a non-persisted session | Yes, WARNING to stderr |
| `attach_memory` rehydrate â€” memory id not found / access denied | Wrong `MAHALO_MEMORY_ID`, stack not deployed, or IAM | Recoverable (deploy / fix id) | CLI prints the AWS error summary + the id it tried | Yes, WARNING to stderr |
| Per-turn WRITE (`append_message`â†’`create_event`) fails mid-session | Transient AWS / throttling | Recoverable (next turn retries; boto adaptive retries already on) | The turn's assistant reply still returns to the user; a WARNING notes the turn may not be persisted | Yes, WARNING to stderr |
| "Second agent on same session" | Two agents share one `session_id` | Recoverable (warn + continue) | The SDK's own warning is surfaced; the CLI continues (investigation Â§1.2) | Yes (SDK warns) |
| `_fetch_jira_token()` credential fetch fails (provider missing / denied / no creds) | Identity stack not deployed or IAM / `ClientError` / `ValueError` raised by the decorator | Recoverable | The tool body's `try/except Exception` returns `âŒ Failed to create story: credential fetch failed (<ExcTypeName>)` â€” the existing error-string shape; **never** the token value | Yes, WARNING; **never log the key value** |
| CDK synth with missing required prop | Implementation error | Fatal at synth | `cdk synth` non-zero (caught by the offline gate) | n/a |

Guiding principle: Memory failures are **loud and non-silent** â€” we never degrade to an
unpersisted session without telling the user, because the whole point of the feature is
durability. Identity failures on the demo path degrade to the existing static-token error
shape so the agent UX is unchanged, and secret values are never logged. Catching broad
`Exception` in the credential-fetch path is justified because the `@tool` contract is "never
raise"; the message is type-name-only.

---

## Input validation (external inputs)

- `MAHALO_SESSION_ID` / `--session-id`: optional string. If supplied, must be non-empty after
  strip (`_resolve_session_id` strips and treats empty as "not supplied");
  `AgentCoreMemoryConfig` enforces `min_length=1` as a backstop. When Memory is off the id is
  unused. Max length is left to the SDK/service; we do not impose our own cap.
- `actor_id`: defaults to `developer_id` (`dev-6`); same non-empty rule.
- `MAHALO_MEMORY_ID`: optional string; **required only** when `MAHALO_MEMORY_ENABLED` is true
  (validated in `build_agent`). Format is not pre-validated client-side (the service is
  authoritative); a bad id surfaces as the "not found/denied" error above.
- `MAHALO_MEMORY_ENABLED` / `MAHALO_IDENTITY_ENABLED`: tolerant boolean parse
  (`{"1","true","yes"}` case-insensitive â†’ True, anything else â†’ False).
- `MAHALO_IDENTITY_JIRA_PROVIDER`: optional string, default `"mahalo-jira-apikey"`; used as
  `provider_name` only when the fetch runs.
- Jira API key value (CDK `CfnParameter`, `no_echo=True`): supplied at deploy time; synth uses
  the mock default. Never echoed.

## Invariant ownership

- **"Default behavior is unchanged when toggles are off"** â€” owned by `build_agent` and
  `agent/config.py` defaults. Enforced because, with the defaults, no session-manager is
  constructed, no hook is added, and the tool body reads the static token. Guarded by keeping
  the existing tests green (they call `build_agent()` with no creds) and by the argparse
  contract preserving existing argv invocations.
- **"Construction never touches AWS"** â€” owned by `agent/memory_client.py` / `build_agent` /
  `attach_memory`: construction constructs only; `build_agent(memory=True)` never passes
  `session_manager=` to `Agent(...)` nor registers the manager via
  `agent.hooks.add_hook(...)`, so the ~line-609 `AgentInitializedEvent` reaches no memory
  callback; the hook registration **and** the network rehydrate are both isolated in
  `attach_memory` (which uses the `HookRegistry.add_hook(provider)` method so the per-turn
  persistence callbacks are actually installed â€” review finding 1). For Identity, the
  `@requires_api_key` decoration is applied to a body-local `_inner` invoked only on a real
  enabled call, so no `IdentityClient`/boto3 client is built at import. Guarded by offline unit
  tests (below).
- **"History stays valid under HITL + Memory"** â€” owned by `agent/chat.py::_ask` (deferred
  breadcrumb flush, kept verbatim) and the `filter_restored_tool_context=True` config flag in
  `agent/memory_client.py`.
- **"Task-4 inbound auth is untouched"** â€” owned by the fact that Task 5 edits no Gateway
  file; guarded by the existing `infra-cdk/tests/test_gateway_stack.py` continuing to pass.
- **"Secrets never logged"** â€” owned by the tool/error-handling layer (log key *names*, not
  values; type-name-only fetch-failure message; `no_echo` on the CDK parameter).

---

## Testability

Unit-testable offline (the Task-5 gate):

- `agent/tests/test_memory_mode.py`:
  - `build_agent(memory=True, session_id="s1", memory_id set)` constructs with **no AWS creds
    and no network** (mirrors `test_build_agent_gateway_mode_offline`). The test monkeypatches
    `AgentCoreMemorySessionManager.initialize` to a sentinel and asserts it is **not** called
    during `build_agent(...)` (no `AgentInitializedEvent`-driven rehydrate at construction),
    and that `build_agent` neither passes `session_manager=` to `Agent` nor registers the
    manager as a hook at construction (e.g. the manager is absent from
    `result.agent.hooks` / `result.agent._session_manager is None`).
  - `attach_memory(agent, session_manager)` **registers the provider via the registry** â€”
    assert `agent.hooks.add_hook` ran / that `session_manager.register_hooks` was invoked (the
    per-turn persistence callbacks are installed), **not** `agent.add_hook` (review
    finding 1) â€” and calls the `initialize` sentinel **exactly once**, and sets
    `agent._session_id` to `session_manager.session_id`. A targeted assertion confirms the
    `MessageAddedEvent`/`AfterInvocationEvent` callbacks are present on the registry after
    `attach_memory` (so persistence is actually wired, which is the whole point of finding 1).
  - `build_agent(memory=True)` with empty `MAHALO_MEMORY_ID` raises `ValueError` (mirrors
    `test_build_agent_gateway_requires_url`).
  - `build_agent()` (memory off, default) returns `BuildResult(agent=<Agent>,
    mcp_client=None, session_manager=None)` and triggers **no** session-manager
    construction â€” the existing DIRECT 42/1 behavior preserved via `result.agent`.
  - `BuildResult` shape per mode/toggle is unit-asserted for each of the four rows in the
    Decision-C table (finding 4): the right attributes are set/`None` and the three updated
    existing DIRECT/GATEWAY tests read `result.agent` / `result.mcp_client` and still pass.
  - `build_memory_session_manager` builds an `AgentCoreMemoryConfig` with
    `filter_restored_tool_context=True`, `batch_size=1`, the right `actor_id`/`session_id`, and
    the STM shape.
  - Session-id resolution precedence (`--session-id` > `MAHALO_SESSION_ID` > generated uuid
    when memory on, else `None`) unit-tested against `agent/chat.py::_resolve_session_id` with
    monkeypatched env/argv/`settings.memory_enabled`; plus an assertion that
    `python -m agent.chat "show my stories"`-style argv still joins to the same message and the
    bare-REPL path is taken with no message (finding 3).
- `agent/tests/test_identity_mode.py`:
  - Importing `agent.tools.jira_write_tools` with identity off constructs **no**
    `IdentityClient` / boto3 client (monkeypatch `IdentityClient.__init__`/boto3 `client` to a
    sentinel and assert not called at import or at `build_agent(identity=True)`).
  - With `MAHALO_IDENTITY_ENABLED` off, `jira_create_story` uses the static token (existing
    behavior; existing write-tool tests keep passing; `@tool` signature unchanged).
  - With it on, `_fetch_jira_token` is invoked and the injected `api_key` is used
    (monkeypatch `requires_api_key` / `_inner` to inject a fake value â€” no AWS), and the token
    value is never logged. The test does **not** assert the CDK `CfnWorkloadIdentity` is used,
    because the local path self-provisions its own (review finding 3); it only asserts the
    fetched key flows into the request.
  - A credential-fetch exception is caught and returned as the `âŒ Failed to create story:
    credential fetch failed (<Type>)` string, with no key value in the message.
- `infra-cdk/tests/test_memory_identity_stack.py` (mirrors `test_gateway_stack.py` style with
  `Template.from_stack`):
  - exactly one `AWS::BedrockAgentCore::Memory`, STM (no `MemoryStrategies` by default),
    `EventExpiryDuration` present and equal to 30;
  - one `AWS::BedrockAgentCore::WorkloadIdentity`;
  - one `AWS::BedrockAgentCore::ApiKeyCredentialProvider`;
  - the `MemoryId` / provider-name `CfnOutput`s exist;
  - the API-key `CfnParameter` is `NoEcho`.
- Whole-repo offline gate stays green: `cdk synth --all` exit 0; `python -m pytest tests -q`
  in `infra-cdk`; `agent/.venv/Scripts/python.exe -m pytest agent -q` still **55 passed, 1
  skipped +** the new Task-5 tests (new count documented when implemented); `pytest
  tools-lambdas/tests -q` unaffected; zero LangChain.

Integration-testable only live (operator, documented â€” NOT run here):

- Deploy `MahaloMemoryIdentityStack`; set `MAHALO_MEMORY_ENABLED=true`,
  `MAHALO_MEMORY_ID=<MemoryId output>`.
- Run `python -m agent.chat --session-id demo-1 "remember my favorite repo is payment-service"`,
  then a **second** invocation `python -m agent.chat --session-id demo-1 "what's my favorite
  repo?"` and confirm the answer reflects reloaded history (STM persistence + rehydrate across
  invocations â€” the core acceptance).
- With `MAHALO_IDENTITY_ENABLED=true`, run a `jira_create_story` write and confirm it succeeds
  using the brokered API key (token fetched at call time, not from the static env).
- Teardown: `cdk destroy MahaloMemoryIdentityStack` (cost/teardown per investigation Â§6).

A design note on testability: because the only hard-to-test part (the live rehydrate) is
isolated behind `attach_memory`, everything else â€” config assembly, toggles, session-id
resolution, the Identity branch, and the whole CDK stack â€” is pure/offline and unit-covered.
That isolation is deliberate; if `attach_memory` had been fused into `build_agent`
construction, the offline gate could not exist.

---

## Operator runbook (documented, not executed)

To be appended to `docs/CONTINUATION.md`:

1. `aws sso login --profile lava`.
2. `cd infra-cdk && cdk deploy MahaloMemoryIdentityStack --profile lava` (supply the Jira
   API-key parameter or accept the mock default).
3. Export `MAHALO_MEMORY_ENABLED=true` and `MAHALO_MEMORY_ID=<MemoryId output>` (optionally
   `MAHALO_IDENTITY_ENABLED=true`).
4. Run the two-invocation persistence check and the Identity write above. **Note:** the first
   Identity-enabled run from the local CLI uses the SDK's local dev-auth path, which
   self-provisions a *local* workload identity and writes a `.agentcore.json` file into the
   run directory (it does **not** use the CDK `CfnWorkloadIdentity`, which is for the Task-6
   Runtime path). Expect that file to appear; it is a dev-auth cache and can be deleted to
   force re-provisioning. The brokered API key itself comes from the CDK
   `CfnApiKeyCredentialProvider` (`mahalo-jira-apikey`).
5. When done for the day, `cdk destroy MahaloMemoryIdentityStack` to stop Memory charges
   (and optionally delete `.agentcore.json`).

---

## Review responses

Disposition of every finding in the revision-2 review
(`docs/.agents/tasks/task5-design-review.json` / `.md`, CHANGES_REQUESTED: 1 HIGH + 2 MEDIUM +
2 NIT). All are **addressed** (none backlogged or ignored); each aligns with the original
Task-5 requirements (offline gate, opt-in/additive, do not break Task-4 auth). The findings
were independently re-verified against installed source before revising:
`strands/agent/agent.py` (`Agent.add_hook` â†’ `hooks.add_callback`; `Agent.__init__` â†’
`self.hooks.add_hook(self._session_manager)`), `strands/hooks/registry.py:287`
(`HookRegistry.add_hook` â†’ `register_hooks`), `strands/session/session_manager.py:48-57` (base
`register_hooks` installs the `AgentInitializedEvent â†’ initialize` + per-turn callbacks),
`bedrock_agentcore/.../strands/session_manager.py` (sync-mode `register_hooks` delegates to
`RepositorySessionManager`; the line-984 `add_callback` is async-mode only), and
`bedrock_agentcore/identity/auth.py` (`_set_up_local_auth` self-provisions a workload identity
+ writes `.agentcore.json`).

1. **HIGH â€” `attach_memory` used the wrong hook-registration API; Memory would persist
   nothing.** ADDRESSED. `attach_memory` now calls **`agent.hooks.add_hook(session_manager)`**
   (the `HookRegistry.add_hook(provider)` method, which runs `provider.register_hooks(...)` and
   installs the per-turn `MessageAddedEvent`/`AfterInvocationEvent` persistence callbacks),
   then `session_manager.initialize(agent)` once, then sets `agent._session_id`. The previous
   `agent.add_hook(session_manager)` (which registers a single callback via
   `hooks.add_callback` and would install no persistence callbacks) is removed everywhere it
   appeared: Technology stack (now distinguishes `Agent.add_hook` from
   `HookRegistry.add_hook`), Decision D (`attach_memory` code + prose), Files-to-modify,
   Invariant ownership, and Testability (the unit test now asserts `register_hooks` ran / the
   `MessageAddedEvent`/`AfterInvocationEvent` callbacks are present, not `agent.add_hook`).
2. **MEDIUM â€” misattributed `register_hooks` citation for the sync (default) path.**
   ADDRESSED. Technology stack and Decision D now cite the correct sync-mode chain:
   `AgentCoreMemorySessionManager.register_hooks` â†’ `RepositorySessionManager.register_hooks` â†’
   base `strands/session/session_manager.py::SessionManager.register_hooks` (~lines 48â€“57),
   which registers the `AgentInitializedEvent â†’ initialize` and the per-turn persistence
   callbacks. The line-984 `add_callback(AgentInitializedEvent, ...)` is explicitly noted as
   the **`async_mode` branch only**, unused by Task 5. The conclusion (a live `session_manager=`
   triggers a synchronous construction-time rehydrate) is retained but now rests on the right
   citation.
3. **MEDIUM â€” local `@requires_api_key` path provisions its OWN workload identity and ignores
   the CDK one.** ADDRESSED via the review's **option (a)**: a new "Local vs. CDK workload
   identity" subsection in Decision B documents that the local CLI demo uses the SDK dev-auth
   path (`_set_up_local_auth`), which self-provisions a local workload identity and writes
   `.agentcore.json` to the run directory, and that the CDK `CfnWorkloadIdentity` is for the
   Task-6 Runtime path, **not** consumed by the local demo. Decision B item 1's wording
   ("under which the agent retrieves brokered credentials") is corrected accordingly, the
   Identity offline-safety bullet in Decision D notes the `.agentcore.json` side effect, the
   operator runbook step 4 calls it out, and the Testability item no longer asserts the CDK
   identity is used locally. Option (b) was considered and rejected (reasoning in the
   subsection).
4. **NIT â€” variable-arity `build_agent` return shape is fragile.** ADDRESSED. `build_agent`
   now **always returns a `BuildResult(agent, mcp_client=None, session_manager=None)`
   dataclass**; callers read attributes instead of branching on `len(result)`. The four
   mode/toggle combinations are tabulated and each is unit-asserted; the three existing
   DIRECT/GATEWAY tests and `agent/chat.py` are migrated to read attributes in the same change
   (behavior unchanged, net test count 55/1 + new Task-5 tests). Task 6 reads
   `result.session_manager` / `result.agent` with no arity decoding.
5. **NIT â€” `MAHALO_MEMORY_REGION` default wording not exact vs. `gateway_region`.** ADDRESSED.
   The settings table now specifies the field verbatim:
   `_getenv("MAHALO_MEMORY_REGION", _getenv("AWS_REGION", "us-east-1"))`, including the literal
   `"us-east-1"` final fallback, truly mirroring `gateway_region`.

No fix changes DIRECT or GATEWAY default behavior: with both toggles off, `build_agent()`
returns `BuildResult(agent=<Agent>, mcp_client=None, session_manager=None)` and
`build_agent(tool_mode="gateway")` returns `BuildResult(agent, mcp_client=<constructed,
not started>, session_manager=None)` â€” the same objects constructed the same offline way as
today â€” the Identity tool reads the static token, and the argparse change preserves existing
argv invocations. The offline gate (`cdk synth --all`; the agent/infra/tools suites; 55/1
preserved; zero LangChain) remains achievable as corrected.

---

## Deliverable

This design: `docs/.agents/tasks/task5-design.md`.
