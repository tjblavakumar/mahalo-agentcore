# Task 7 — Design Review (iteration 7, fresh read)

**Reviewed:** `docs/.agents/tasks/task7-design.md` (revision iteration 6).
**Context read:** `docs/.agents/tasks/task7-investigation.md`.
**Spot-checked against source:** `api/app/routers/chat.py`, `api/app/models.py`,
`agent/runtime_app.py`, `infra-cdk/mahalo_infra/api_stack.py`,
`infra-cdk/mahalo_infra/mock_service_stack.py`, `infra-cdk/mahalo_infra/runtime_stack.py`,
`infra-cdk/app.py`, `infra-cdk/tests/*`, `tools-lambdas/github/handler.py`,
`tools-lambdas/github/routes.py`, and the read-only `mahalo-dock/frontend/src/**`
(`app/(protected)/chat/page.tsx`, `services/api.ts`, `lib/chatSuggestions.ts`,
`lib/chatSuggestions.test.ts`, `types/index.ts`, `app/page.tsx`, `app/layout.tsx`,
`components/chat/ChatMessage.tsx`, `components/chat/ProposalCard.tsx`, `globals.css`,
`next.config.ts`).

This is a fresh review that takes none of the prior iterations' resolutions on faith; I
re-derived every load-bearing claim from source. The design is mature: all five open
questions (A–E) are resolved concretely with real, source-grounded approaches, and the
prior-iteration HIGH/MEDIUM findings genuinely hold up against the code. I verified the
one claim the step prompt singled out — that the browser has a real credential source
and does not "just SigV4-sign" — and it is satisfied (§B.2: Cognito unauthenticated
identity pool → temp IAM creds → in-browser SigV4). The residual findings are all NIT.

---

## Findings

1. **NIT — Line-number citation drift in several §A references.** The design cites
   `api.ts` base URL at "line 6" (acknowledged in iteration 6), `chatSuggestions.ts`'s
   `@/types` import at "line 14", and `ChatMessage.tsx`'s chip guard at "line 30".
   Verified actuals: `api.ts:6` is correct (`const API_BASE_URL = ...`, the file opens
   with a JSDoc banner); `chatSuggestions.ts` imports `import type { Project, UserRole }
   from "@/types"` at **line 16** (not 14); `ChatMessage.tsx`'s guard
   `!isUser && systemsQueried && systemsQueried.length > 0` is at **line 31** (not 30).
   The design already instructs readers to re-anchor by symbol, so this is cosmetic.
   CONCRETE FIX: change "`chatSuggestions.ts:18`/`:14`" to `chatSuggestions.ts:16` and
   "`ChatMessage.tsx:30`" to `ChatMessage.tsx:31`, or drop the exact line numbers and
   keep the symbol anchors only.

2. **NIT — `chat/page.tsx` imports `buildSuggestions` from `@/lib/chatSuggestions`, not
   `@/types`; the §A.3 removal list should name the `IntegrationType` import.** Verified:
   `chat/page.tsx:8` is `import { buildSuggestions, type IntegrationType } from
   "@/lib/chatSuggestions";` and the page uses `IntegrationType` only in the
   `connectedTypes` `useMemo` that §A.3 edit 3 removes. After the trim the page keeps the
   `buildSuggestions` import but no longer needs `IntegrationType` (the fixed call passes
   string literals, which are assignable to `IntegrationType[]`). The design's removal
   list enumerates the hooks/derived values but does not explicitly say to drop the now-
   unused `type IntegrationType` from the import, which would trip the `eslint`
   `no-unused-vars` leg of the offline gate.
   CONCRETE FIX: in §A.3 edit 3, add to the removal list: "reduce the
   `@/lib/chatSuggestions` import to `import { buildSuggestions } from
   '@/lib/chatSuggestions'` — drop the now-unused `type IntegrationType`."

3. **NIT — SSM SecureString construct API detail under-specified for feasibility.** §C.4b
   pins `ssm.StringParameter.from_secure_string_parameter_attributes(self, "GiteaToken",
   parameter_name=gitea_token_param_name)`. In `aws-cdk-lib`, that static method requires
   a `version` argument for a SecureString parameter (there is no no-version overload for
   `from_secure_string_parameter_attributes`); `param.grant_read(fn)` then wires
   `ssm:GetParameter`. The design asserts the grant covers `ssm:GetParameter` +
   `kms:Decrypt`, but `grant_read` on an imported parameter does NOT auto-add `kms:Decrypt`
   for a customer-managed key — it only adds `kms:Decrypt` when the construct knows the key.
   For the default SSM-managed key this is usually fine, but the design states the KMS
   grant as a fact.
   CONCRETE FIX: specify `from_secure_string_parameter_attributes(..., version=<n>)` (or
   switch to `from_string_parameter_attributes(..., type=ParameterType.SECURE_STRING)`
   where a version is not forced), and state that `kms:Decrypt` is only auto-granted for a
   non-default KMS key — if the SSM param uses a CMK, add an explicit
   `key.grant_decrypt(fn)`. Alternatively, resolve the token purely in `handler.py` via
   boto3 `ssm.get_parameter(WithDecryption=True)` (already the plan) and add the IAM
   actions directly to the function role rather than through `grant_read`.

4. **NIT — In-browser credential-provider wiring with `aws4fetch` left implicit.** §B.3
   pins the two deps (`aws4fetch` + `@aws-sdk/credential-providers`) and the per-request
   flow, but `fromCognitoIdentityPool(...)` returns an `AwsCredentialIdentityProvider`
   (an async function), whereas `new AwsClient({ accessKeyId, secretAccessKey,
   sessionToken, ... })` wants resolved string credentials. The design says "obtain cached
   temp creds ... refreshing when near expiry" but does not state that the provider must be
   **invoked** (`await credentialProvider()`) to get the `{accessKeyId, secretAccessKey,
   sessionToken, expiration}` fields before constructing/refreshing the `AwsClient`, nor
   where that cache lives. This is a real integration seam that an implementer could get
   wrong (passing the provider object instead of resolved creds).
   CONCRETE FIX: in §B.3, add: "hold the provider from `fromCognitoIdentityPool`; per
   request `const c = await provider();` and build `new AwsClient({ accessKeyId:
   c.accessKeyId, secretAccessKey: c.secretAccessKey, sessionToken: c.sessionToken,
   service: 'lambda', region })`. The SDK provider caches and auto-refreshes creds, so
   invoke it each call and let it return cached creds until `c.expiration` nears."

---

## Verdict inputs

HIGH findings: 0
MEDIUM findings: 0
NIT findings: 4

Per the mechanical rule (HIGH + MEDIUM > 0 ⇒ CHANGES_REQUESTED; else APPROVED), the
verdict is **APPROVED**. The four NITs are improvements an implementer can fold in
without reopening any design decision.

---

## Verified Assumptions (checked against source, found correct)

- **Interrupt id is already on the wire inside `proposal` (§A.3 edit 1).** VERIFIED:
  `agent/runtime_app.py` builds `proposal = {**itr.reason, "interrupt_id": itr.id}` and
  returns `status: "pending_approval"`; `api/app/routers/chat.py` passes `proposal` and
  `status` through verbatim into `ChatResponse`; `api/app/models.py` `ChatResponse` has
  `proposal: Optional[dict]` + `status: str`. No thin-API/Runtime change is needed — the
  design's central HITL claim is accurate.
- **`ApprovalRequest` requires `interrupt_id` (§A.3, §A.7).** VERIFIED:
  `models.py` `ApprovalRequest` has a non-optional `interrupt_id: str`; a missing id is a
  422, justifying the fail-safe early-return guard.
- **`ChatRequest.project_id` is `Optional[int]` (§A.3 edit 3 `project_id: null`).**
  VERIFIED: `models.py` `project_id: Optional[int] = None`; sending JSON `null` is valid.
- **Thin-API edge is `AuthType=AWS_IAM` and `self.function` is exposed, no
  `function_url` attr (§B, §D.2, §E.1).** VERIFIED in `api_stack.py`:
  `fn.add_function_url(auth_type=FunctionUrlAuthType.AWS_IAM)`, the URL is a local
  surfaced only via `CfnOutput RuntimeApiUrl`, and `self.function = fn` is the only handle
  — so `frontend_stack` can reach `.function_arn` but not a URL string, exactly as §D.2/§E.1
  describe. Adding a `cors=` block to this call is the single, correct edit.
- **`page-local` `Proposal` at `chat/page.tsx:23-28` is `{action, system, params,
  description}` with no `interrupt_id` (§A.4).** VERIFIED; the coupled additive field on
  both the page-local and `ProposalCard` interfaces is justified (`msg.proposal?.interrupt_id`
  would not type-check otherwise).
- **`ProposalCard.tsx` `Proposal`/`result` shapes (§A.2).** VERIFIED: `{action, system,
  params, description}` and `result?: {success, message} | null`; rendering never reads
  `interrupt_id`, so the field is carried-only.
- **`buildSuggestions({ role: "developer", project: null, connectedTypes:
  ["github","jira"] })` yields exactly the three advertised prompts (§A.3 edit 3).**
  VERIFIED by tracing `chatSuggestions.ts`: the `{repo}`/`{jiraKey}` `needsProject`
  templates drop on `project: null`, servicenow/confluence drop on missing connections,
  leaving "Show open pull requests", "What issues are assigned to me?", "What changed in
  the latest release?" (limit 4). The empty-`connectedTypes` collapse to `FALLBACK_SUGGESTIONS`
  is also correct, validating the design's rationale for the chosen args.
- **`src/types/index.ts` is imported by `chatSuggestions.ts` and its test (§A.2, iter-3
  Finding 1).** VERIFIED: `chatSuggestions.ts:16` imports `Project, UserRole` and uses
  both structurally (`ROLE_TEMPLATES: Record<UserRole,...>`, `PLACEHOLDER_FIELDS:
  Record<string, keyof Project>`); `chatSuggestions.test.ts:7` imports `Project` and
  `makeProject()` constructs a full `Project` (all 16 fields). The decision to port a
  TRIMMED `index.ts` keeping `UserRole` + the full `Project` (not a subset) is correct;
  dropping it would red the `test`/`build` gate.
- **`layout.tsx` imports `Geist, Geist_Mono` from `next/font/google` and binds their
  `.variable`s (§A.3, §D, iter-2 Finding 2).** VERIFIED; the fetch-at-build-time font
  breakage is real, and `globals.css` is `@import "tailwindcss";` only (VERIFIED), so the
  system-font swap is a genuine visual no-op.
- **`app/page.tsx` is a `"use client"` component doing `useRouter().push()` in a
  `useEffect` (§A.3 export-safe decision).** VERIFIED; the keep-the-shape, strip-`useAuth`,
  unconditional-push-to-`/chat` plan is export-safe and correct.
- **`ChatMessage.tsx` already guards the systems chip (§A.3 edit 2).** VERIFIED at
  `ChatMessage.tsx:31`; "no change needed, chip never renders" holds.
- **`next.config.ts` is empty, no `output: "export"` (§D.1).** VERIFIED; adding
  `output: "export"` + `images.unoptimized: true` is the right minimal change.
- **github `handler.py` builds `Store` + `build_router(store, token)` in `_get_router`
  and calls `store.ensure_seeded()` unconditionally in `lambda_handler` (§C.4).**
  VERIFIED exactly; the short-circuit-to-`store=None` + guarded `ensure_seeded()` plan is
  feasible and keeps the mock path untouched.
- **`routes.build_router(store, token)` reads `GITHUB_MODE` only for `/health`, mock-only
  (§C.4).** VERIFIED at `routes.py`; adding a sibling `build_gitea_router(backend)` while
  leaving `build_router` unchanged is sound.
- **`MockServiceStack` is one generic construct instantiated 4× in `app.py`'s loop;
  signature `(scope, construct_id, *, service, default_token=None, **kwargs)`, fixed env
  `{TABLE_NAME, token_env_key}`, single `table.grant_read_write_data(fn)` (§C.4b).**
  VERIFIED line-for-line; the three new guarded kwargs and the `service == "github" and
  gitea_mode` branch are the correct, minimal way to avoid leaking Gitea config into the
  other three instances. `app.py` loop at lines 23–31 matches the pinned edit.
- **Offline-safety flag-gate pattern (`buildImage`/`MAHALO_BUILD_IMAGE`, CfnParameter
  image URI, no `fromLookup`) (§E.2).** VERIFIED in `runtime_stack.py` and `api_stack.py`;
  the Gitea/frontend stacks mirroring it is consistent with house style.
- **`infra-cdk/tests` exists with CDK-assertions pytest (§D.4, §E.2).** VERIFIED
  (`test_synth.py`, `test_runtime_stack.py`, etc.); new per-stack assertions are a
  realistic offline gate.
- **The step-prompt's HIGH tripwire (browser "just SigV4-signs" with no credential
  source) is NOT present.** VERIFIED: §B.2 supplies a real credential source (Cognito
  unauthenticated identity pool → temp IAM creds), least-privileged to
  `lambda:InvokeFunctionUrl`, with the edge kept at `AWS_IAM`. This is a real approach,
  not hand-waving.

## Unverified / Wrong Assumptions

- **No design claims were found to be WRONG in this pass.** Every load-bearing assertion I
  spot-checked matched source. (The iteration-2 "drop `index.ts`" error was already caught
  and reversed in iteration 3; the current text correctly ports a trimmed `index.ts`.)
- **Deferred to live integration (correctly out of the offline gate, not a defect):**
  browser→Function-URL SigV4 + CORS preflight behavior end-to-end; Gitea bootstrap
  idempotency on EC2; github-Lambda→public-Gitea reachability; `cdk deploy` ordering. The
  design explicitly scopes these as operator/integration steps, consistent with Tasks 4–6.
- **Not independently re-collected:** the "94 tools-lambda tests" count (the `moto` dep is
  not installed in this review environment, same constraint the design notes in §C.4a).
  The figure is cited consistently across `STATUS.md`/`PLAN.md`/`CONTINUATION.md`; the
  implementation task re-runs `pytest tools-lambdas/tests -q` to confirm. Accepted as a
  documented, re-verifiable baseline, not a blocking gap.
