"""AgentCore Memory + Identity resources (Task 5, Decision D).

``MahaloMemoryIdentityStack`` provisions the three Task-5 resources with the
native, stable L1 constructs in ``aws_cdk.aws_bedrockagentcore`` (the same module
Task 4 used for the Gateway):

* ``CfnMemory`` — short-term-memory only (``event_expiry_duration=30`` days, NO
  ``memory_strategies``). This is the durable, session-keyed conversation store
  that replaces mahalo-dock's in-memory ``_sessions`` dict. An optional
  ``with_long_term`` ctor prop (default ``False``) would add strategies later; the
  Task-5 default and the entire offline gate assume STM only.
* ``CfnWorkloadIdentity`` — the foundational identity the Task-6 Runtime path will
  use to retrieve brokered credentials. The Task-5 LOCAL CLI demo does NOT consume
  this (the SDK dev-auth path self-provisions a local workload identity); it is
  provisioned here because every future Identity use needs it and it belongs in
  this destroyable stack.
* ``CfnApiKeyCredentialProvider`` — holds what is today the static Jira token. The
  key VALUE is supplied at deploy time via a ``no_echo`` ``CfnParameter`` so the
  secret is never committed to source, defaulting to the existing mock token so
  ``cdk synth`` has a value.

``CfnOutput``s plumb the values the agent needs via env, mirroring how
``GatewayMcpUrl`` feeds ``MAHALO_GATEWAY_MCP_URL``:
``MemoryId`` -> ``MAHALO_MEMORY_ID``, ``JiraApiKeyProviderName`` ->
``MAHALO_IDENTITY_JIRA_PROVIDER``, plus ``WorkloadIdentityArn``.

The stack is independent of the mock/gateway stacks (no cross-references), so
``cdk synth --all`` ordering is unaffected and ``gateway_stack.py`` stays frozen.
``RemovalPolicy.DESTROY`` is implicit for these L1 resources (no retain), matching
the Task-8 teardown requirement; ``cdk destroy`` removes them.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, CfnParameter, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from constructs import Construct

# Event retention (days) for the short-term event store. ``event_expiry_duration``
# is a REQUIRED CfnMemory prop in the installed CDK (no CDK default; the
# "Defaults to 30" in its docstring describes the AgentCore service). We pass 30
# explicitly so the provisioned retention is deterministic.
_EVENT_EXPIRY_DAYS = 30

# CfnMemory enforces a stricter name pattern than the other resources:
# ^[a-zA-Z][a-zA-Z0-9_]{0,47}$ — NO hyphens. Use an underscore so the name is
# valid at CloudFormation validate / deploy time (a hyphenated name synthesizes
# but fails the pattern check). The Workload Identity and credential-provider
# names allow hyphens, so they keep the design's hyphenated names.
_MEMORY_NAME = "mahalo_memory"
_WORKLOAD_IDENTITY_NAME = "mahalo-agent"
_JIRA_PROVIDER_NAME = "mahalo-jira-apikey"


class MahaloMemoryIdentityStack(Stack):
    """AgentCore Memory (STM) + Workload Identity + one API-key provider."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        with_long_term: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # The Jira API-key value is a deploy-time secret (never in source). It
        # defaults to the existing mock token so ``cdk synth`` has a value, and is
        # masked in the CloudFormation console via ``no_echo``.
        jira_api_key = CfnParameter(
            self,
            "JiraApiKey",
            type="String",
            no_echo=True,
            default="mock-jira-token-12345",
            description="API key value brokered for the Jira write path (no-echo).",
        )

        # (1) Short-term-memory store. STM is a bare CfnMemory: name +
        # event_expiry_duration, NO memory_strategies. ``with_long_term`` is a
        # future, additive toggle (default off) and is intentionally not wired to
        # strategies in Task 5 — the offline gate asserts STM-only.
        memory_kwargs: dict = {
            "name": _MEMORY_NAME,
            "event_expiry_duration": _EVENT_EXPIRY_DAYS,
        }
        # NOTE: ``with_long_term`` is reserved for a later task; when true it would
        # add ``memory_strategies=[...]`` here. Task 5 keeps STM-only.
        _ = with_long_term
        memory = agentcore.CfnMemory(self, "Memory", **memory_kwargs)

        # (2) Workload identity (for the Task-6 Runtime brokering path).
        workload_identity = agentcore.CfnWorkloadIdentity(
            self, "WorkloadIdentity", name=_WORKLOAD_IDENTITY_NAME
        )

        # (3) API-key credential provider holding the Jira token.
        agentcore.CfnApiKeyCredentialProvider(
            self,
            "JiraApiKeyProvider",
            name=_JIRA_PROVIDER_NAME,
            api_key=jira_api_key.value_as_string,
        )

        # (4) Outputs -> env plumbing (mirrors GatewayMcpUrl).
        CfnOutput(self, "MemoryId", value=memory.attr_memory_id)
        CfnOutput(
            self, "WorkloadIdentityArn", value=workload_identity.attr_workload_identity_arn
        )
        CfnOutput(self, "JiraApiKeyProviderName", value=_JIRA_PROVIDER_NAME)

        self.memory = memory
        self.workload_identity = workload_identity
