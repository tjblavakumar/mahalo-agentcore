# AgentCore Memory + Identity added to the Strands agent (Task 5)

Task 5 adds two opt-in, additive capabilities to the existing Strands CLI agent: AgentCore **Memory** (session-id-keyed short-term conversation persistence via the native Strands `session_manager` seam) and AgentCore **Identity** (call-time credential brokering for one representative outbound tool path, `jira_create_story`). Both are gated behind new env toggles that default off, so DIRECT and GATEWAY behavior is byte-for-byte unchanged when nothing is set. Resources are provisioned by a new destroyable CDK stack (`MahaloMemoryIdentityStack`) using L1 constructs with `CfnOutput` → env plumbing, mirroring the Task-4 Gateway stack. The implementation faithfully follows the approved revision-3 design, including the HIGH-finding hook-registration fix, with one deliberate, pre-approved relocation of the offline/online construction boundary.

Watch for: the design's literal "construct the session manager offline in `build_agent`" seam was **not achievable** — the installed `bedrock-agentcore 1.24.1` `AgentCoreMemorySessionManager.__init__` performs a live `ListEvents` read at construction (confirmed). The coder relocated construction into `attach_memory` behind a plain-data `MemorySessionSpec` and recorded this departure, which the parent session approved as "Option 1" (original user message #6). This preserves the brief's offline-build requirement and is documented in code, tests, and `task5-verification.md`. **Confidence: confirmed.**

**Verdict**: APPROVED

## High-level view

Memory plugs into Strands through the documented `session_manager` seam, but because the SDK manager constructor is not offline-safe, `build_agent(memory=True)` assembles only a lightweight `MemorySessionSpec` (session_id, actor_id, region, memory_id — no boto3, no network) and hangs it on `BuildResult.session_manager`. The single AWS touch is isolated in `attach_memory`, which builds the real manager, registers it via `agent.hooks.add_hook(manager)` (the `HookRegistry` provider method, so per-turn persistence callbacks are actually installed), calls `initialize` once, and sets `_session_id`. This is the correct fix for the revision-2 HIGH finding, verified against SDK source.

Identity brokers the Jira API key for exactly one write path. `@requires_api_key` is applied to a body-local `_inner` that only exists when `_fetch_jira_token()` runs under the toggle, so importing the module and building the agent construct no `IdentityClient`/boto3 client. The `@tool` signature is untouched, the fetch failure is caught and reported type-name-only, and no key value is ever logged.

The `build_agent` return shape is now a single `BuildResult` dataclass across all four mode/toggle rows, replacing the fragile variable-arity tuple. The three existing DIRECT/GATEWAY callers (two tests + `chat.py`) and the live integration test were migrated to read attributes, keeping behavior identical. The argparse-based `main` adds `--session-id` while preserving the exact existing `python -m agent.chat "..."` and bare-REPL invocations.

Task-4 inbound auth (Gateway SigV4 / `GATEWAY_IAM_ROLE` / the Lambda `X-API-Token`) is untouched: no edit to `gateway_stack.py`, `gateway_client.py`, or the Lambdas. The CDK stack is independent (no cross-references), STM-only, with a no-echo `CfnParameter` for the key value. The recorded offline gate shows 69 passed / 1 skipped (agent), 31 passed (infra), 94 passed (tools-lambdas), and `cdk synth` exit 0 — no regression.

<details>
<summary>Issues (0 blocking)</summary>

No blocking findings. Two non-blocking observations are noted in the detailed sections below (a `CfnMemory` name-pattern fix the coder already made and documented; a NIT on the unused `with_long_term` parameter). Neither requires action for this task.

</details>

<details>
<summary>Details</summary>

### The construction-boundary relocation (Option 1) is correct and matches intent

The approved design (Decision D, Overview, Testability) specifies that `build_agent(memory=True)` constructs the `AgentCoreMemorySessionManager` offline and `attach_memory` performs the single network rehydrate. The coder found — and a dummy-credential probe confirmed — that the SDK constructor chain `AgentCoreMemorySessionManager.__init__` → `RepositorySessionManager.__init__` → `read_session` → `ListEvents` reaches AWS *at construction*, before `initialize` is ever called. The design's literal seam is therefore unachievable with `bedrock-agentcore 1.24.1`, and keeping it would violate the brief's explicit "construct offline, only actual use hits AWS" requirement.

The resolution moves the construction boundary one function outward rather than abandoning the invariant: `build_agent` emits a frozen `MemorySessionSpec` (plain data), and `build_memory_session_manager(spec)` — the one non-offline-safe call — lives only inside `attach_memory`. The `BuildResult.session_manager` attribute keeps its name for Task-6 symmetry but now holds the deferred spec. This keeps `build_agent` genuinely offline (unit-asserted with a tripwire that fails if `build_memory_session_manager` runs at build time) and preserves "one isolated AWS touch." The departure is recorded in `task5-verification.md` and attributed to the parent session's Option-1 approval, which maps to original user message #6. **Confidence: confirmed** (verified SDK call chain exists and the tripwire test encodes the invariant).

### Memory hook registration uses the right API (the revision-2 HIGH fix)

`attach_memory` calls `agent.hooks.add_hook(manager)` — `HookRegistry.add_hook(hook: HookProvider)` at `strands/hooks/registry.py:287`, which invokes `provider.register_hooks(...)`. I confirmed against source that `AgentCoreMemorySessionManager.register_hooks(self, registry, **kwargs)` exists (session_manager.py:928) and `initialize(self, agent, **kwargs)` exists (line 1002). In sync mode `register_hooks` installs both the `AgentInitializedEvent → initialize` callback and the per-turn `MessageAddedEvent`/`AfterInvocationEvent` persistence callbacks, so future turns actually write to Memory. The code and docstring explicitly reject the `Agent.add_hook(manager)` trap (which would register a single callback and silently install no persistence). `initialize(agent)` is then called exactly once explicitly, because `AgentInitializedEvent` already fired during the bare `Agent(...)` construction and will not re-fire. The unit test asserts `register_hooks` ran and that the per-turn callbacks are present on the registry afterward — exactly the behavior finding 1 demanded. **Confidence: confirmed.**

### Identity slice is offline at import/build and leaks no secret

`from bedrock_agentcore.identity.auth import requires_api_key` at module scope is a plain import. The decorator binds only to `_inner`, defined inside `_fetch_jira_token()`, which runs solely when `settings.identity_enabled` is true on a real `jira_create_story` call — so no `IdentityClient`/boto3 client is built at import or at `build_agent(identity=True)`. The test `test_no_identity_client_built_at_import_or_build` makes this concrete by tripwiring `IdentityClient.__init__`. The toggle is a plain body conditional (`_fetch_jira_token() if settings.identity_enabled else settings.jira_token`), the `@tool` signature and `jira_update_story` are byte-for-byte unchanged, and the fetch failure path returns `❌ Failed to create story: credential fetch failed (<ExcTypeName>)` — type-name only, with a test asserting neither the key value nor the exception message leaks into the output. **Confidence: confirmed.**

### BuildResult migration preserves the baseline

`build_agent` always returns `BuildResult(agent, mcp_client=None, session_manager=None)`. The four rows (DIRECT/GATEWAY × memory off/on) are unit-asserted in `test_build_result_shapes_for_all_rows`. The three existing callers were migrated in the same change: `test_build_agent_gateway_returns_build_result` reads `result.agent`/`result.mcp_client` and additionally asserts `session_manager is None`; `test_integration_live.py` reads `build_agent().agent`; `chat.py` reads attributes throughout. The `ValueError` guard for `memory=True` with empty `MAHALO_MEMORY_ID` mirrors the GATEWAY URL guard and is tested. GATEWAY mode still constructs-not-starts the MCP client and `_run_single`/`_run_repl` keep the single-start-via-`attach_gateway_tools` + `finally: stop()` lifecycle, with `_wire_memory` slotted in after attach. **Confidence: confirmed.**

### CLI session-id parsing preserves existing invocations

`main` now uses argparse with `--session-id` and `message nargs="*"`, joining message words with a single space, so `python -m agent.chat "show my stories"` and the bare REPL behave identically. `test_main_argv_joins_message_and_bare_repl` covers both the multi-token and single quoted-arg cases plus the bare-REPL path. `_resolve_session_id` precedence (`--session-id` > `MAHALO_SESSION_ID` > uuid4 only when memory on, else `None`) is tested across all three branches. The resume/new-session notice prints only when Memory is on, keeping default output unchanged. The deferred-breadcrumb flush in `_ask` is preserved verbatim, which matters more now that appended messages get persisted. **Confidence: confirmed.**

### CDK stack: STM-only, no-echo key, independent, Task-4 frozen

`MahaloMemoryIdentityStack` provisions `CfnMemory` (STM: `event_expiry_duration=30`, no `memory_strategies`), `CfnWorkloadIdentity`, and `CfnApiKeyCredentialProvider` whose value comes from a `no_echo` `CfnParameter` defaulting to the mock token. Outputs `MemoryId`, `WorkloadIdentityArn`, `JiraApiKeyProviderName` plumb to env. The stack is wired into `app.py` with no cross-references, and `gateway_stack.py` is untouched. The synth-assertion test checks exactly-one of each resource, `EventExpiryDuration == 30`, absence of `MemoryStrategies`, presence of the three outputs, and `NoEcho: true` on the parameter. The coder found and fixed a real deploy-blocking issue: `CfnMemory` enforces `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` (no hyphens), so `mahalo-memory` became `mahalo_memory`; the hyphenated workload-identity and provider names are unaffected. This is a correct, documented fix, not a regression. **Confidence: confirmed** (recorded in verification note; name pattern is a known `CfnMemory` constraint).

### Verification evidence is present and sufficient; not re-run

`task5-verification.md` records the exact offline-gate commands and results: agent suite 69 passed / 1 skipped (55 baseline + 14 new), gateway subset 6 passed, run twice including `-p no:randomly`; infra `cdk synth "**"` exit 0 with `MahaloMemoryIdentityStack` present, `test_memory_identity_stack.py` 5 passed, whole infra suite 31 passed; tools-lambdas 94 passed; zero LangChain in repo source. Per the review brief I did not re-run these suites; the evidence is complete and internally consistent with the code I read. The only narrow spot-check I ran was confirming the SDK method names `register_hooks`/`initialize` and `HookRegistry.add_hook` exist, to validate the HIGH-finding fix against a real runtime concern (the tests use fakes). **Confidence: confirmed.**

### Non-blocking NIT — unused `with_long_term` parameter

`MahaloMemoryIdentityStack.__init__` accepts `with_long_term: bool = False` and immediately discards it (`_ = with_long_term`) with a comment that it is reserved for a later task. This matches the design, which explicitly defers long-term strategies and exposes the toggle as a future seam. It is dead-but-intentional and harmless; no action needed for Task 5. **Confidence: confirmed** (design-sanctioned).

</details>

<details>
<summary>File map</summary>

Created:
- `agent/memory_client.py` — `MemorySessionSpec` (offline plain data), `build_memory_session_spec` (offline), `build_memory_session_manager` (the single non-offline SDK constructor, lazy boto3, STM config).
- `agent/tests/test_memory_mode.py` — 10 offline Memory tests (spec-not-manager at build, attach registers hooks + initialize once, ValueError guard, four BuildResult rows, STM config, session-id resolution + argv).
- `agent/tests/test_identity_mode.py` — 4 offline Identity tests (no client at import/build, static vs brokered token, fetch-failure containment).
- `infra-cdk/mahalo_infra/memory_identity_stack.py` — `MahaloMemoryIdentityStack` (STM Memory, Workload Identity, API-key provider, no-echo param, outputs).
- `infra-cdk/tests/test_memory_identity_stack.py` — 5 synth assertions.
- `docs/.agents/tasks/task5-verification.md` — offline-gate evidence + the Option-1 boundary note.

Modified:
- `agent/config.py` — six opt-in settings + `_getbool` helper.
- `agent/strands_agent.py` — `BuildResult` dataclass; `build_agent` keyword-only `memory`/`session_id`/`identity` + ValueError guard, always returns `BuildResult`; `attach_memory` (build manager from spec, `hooks.add_hook`, `initialize` once, set `_session_id`).
- `agent/chat.py` — argparse `main` + `_resolve_session_id`; BuildResult attribute reads; session threading; `_wire_memory` + notice.
- `agent/tools/jira_write_tools.py` — body-local `_fetch_jira_token` + toggle in `jira_create_story`, type-name-only error handling.
- `agent/tests/test_gateway_mode.py`, `agent/tests/test_integration_live.py` — migrated to BuildResult attributes.
- `infra-cdk/app.py` — construct `MahaloMemoryIdentityStack`.
- `docs/ARCHITECTURE.md`, `docs/CONTINUATION.md` — Memory/Identity wiring notes + operator runbook.

Full diff: `git diff` (tracked) plus the untracked files above in the working tree at `d:/<USER>/LavaCode/AI/mahalo-agentcore`.

</details>
