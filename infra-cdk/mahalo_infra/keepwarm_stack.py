"""Runtime keep-warm (latency follow-up #3, design Option A).

``MahaloKeepWarmStack`` keeps the AgentCore Runtime micro-VM resident *ahead of*
likely demo hours so the first real demo message of the day skips the cold-start
penalty (~64s cold vs ~53s warm). It does this with a scheduled, deliberately
trivial ``InvokeAgentRuntime`` ping — NOT the full 21-tool agent loop.

CHOSEN OPTION — Option A (scheduled lightweight invoke).
    Option B (provisioned / always-warm capacity) is NOT available on the pinned
    L2 ``agentcore.Runtime`` construct: ``LifecycleConfiguration`` exposes only
    ``idle_runtime_session_timeout`` (default 900s) and ``max_lifetime`` (default
    28800s) — both already set in ``runtime_stack.py`` — and there is no
    provisioned-concurrency / min-capacity / always-warm property to set. So
    Option B cannot be expressed; Option A is the design decision. Fully
    reversible: delete this stack and behavior reverts to today.

MECHANISM.
    An EventBridge (CloudWatch Events) scheduled rule fires an inline Lambda shim
    every 10 minutes within a weekday demo window. The shim calls
    ``bedrock-agentcore:InvokeAgentRuntime`` directly on the Runtime ARN with a
    one-word ping prompt. A 10-min cadence sits comfortably inside the Runtime's
    15-min ``idle_runtime_session_timeout`` (5-min safety margin), so the instance
    stays resident across the window.

WHY A REAL INVOKE (not GET /ping).
    ``GET /ping`` is only a container liveness probe; it does not run
    ``build_and_attach`` / Bedrock init / Gateway MCP / Memory rehydrate and does
    not refresh the idle timer. Only a genuine ``InvokeAgentRuntime`` warms the
    cold path, so the ping must be a real (but trivial) invoke.

WHY IT STAYS CHEAP / NO TOOL LOOP.
    The agent's BASE_PROMPT only fires tools for data requests. The ping prompt
    ("reply with the single word OK and call no tools") is not a data request, so
    Claude answers in one short turn with zero tool calls: one small Bedrock round
    trip, no MCP fan-out. This invariant is model-driven (infra cannot force it)
    and is monitored via this Lambda's logs — a heavy pass would show as a long
    duration / Tool #N lines in the Runtime logs.

SESSION ISOLATION (hard requirement).
    The shim uses a dedicated throwaway ``runtimeSessionId`` that no browser will
    ever use, embedding the current UTC date so it rotates daily:
    ``mahalo-keepwarm-DO-NOT-USE-YYYYMMDD-000000``. This guarantees the ping never
    reads or writes a real demo persona's Memory, and daily rotation caps each
    keep-warm conversation at ~one day of ticks (~60 events) so per-ping rehydrate
    stays flat (a single constant id would grow without bound and slow every ping).

COST (small, always-on, documented here per task).
    ~1,320 trivial single-turn invokes/month (Mon–Fri 13:00–22:50 UTC, every
    10 min). Shim Lambda: 128 MB, well inside the Lambda free tier even at the
    pessimistic 60s-per-cold-ping bound (~10k GB-s/month vs 400k free). EventBridge
    scheduled rules: $0. The real (small) cost is the Runtime/Bedrock per-invoke
    time: order-of-magnitude low single-digit dollars/month, concentrated in
    weekday business hours only (nights/weekends are silent).

SCOPE.
    All changes are confined to ``infra-cdk``. No agent, thin-API, frontend, or
    dashboard code is changed; the ping goes DIRECT to the Runtime, not through
    the ``/chat`` route. No ``runtime_stack.py`` change (Option B has no knob).
"""

from __future__ import annotations

from aws_cdk import Duration, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

# Inline Lambda handler (boto3 only — ships in the Lambda runtime, so no Docker
# bundling, keeping the offline `cdk synth` gate green). The handler ignores the
# EventBridge event entirely and never raises on a warm-attempt failure: a missed
# ping only risks one cold real call (the pre-existing baseline), it must not page.
_SHIM_CODE = '''
import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Trivial single-turn ping. Matches the entrypoint contract in agent/runtime_app.py
# (_DEFAULT_DEVELOPER_ID="dev-6", _DEFAULT_ROLE="developer") so no persona wiring is
# needed. The wording asks for a one-word answer and no tools, so the model answers
# in one short Bedrock turn with zero MCP tool calls (keeps the ping cheap).
PING_BODY = {
    "action": "chat",
    "prompt": "ping \u2014 reply with the single word OK and call no tools",
    "developer_id": "dev-6",
    "role": "developer",
}


def handler(event, context):
    # Dedicated throwaway session id, rotated daily by UTC date so it never
    # collides with a real demo session and each keep-warm conversation is capped
    # at one day of ticks (bounds Memory rehydrate cost).
    session_id = f"mahalo-keepwarm-DO-NOT-USE-{datetime.now(timezone.utc):%Y%m%d}-000000"
    # 41 chars, must stay >= 33 (Runtime runtimeSessionId floor)
    arn = os.environ["MAHALO_RUNTIME_ARN"]
    client = boto3.client("bedrock-agentcore")
    try:
        client.invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=session_id,
            contentType="application/json",
            accept="application/json",
            payload=json.dumps(PING_BODY).encode("utf-8"),
        )
        logger.info("keep-warm ping OK (session=%s)", session_id)
    except Exception as exc:  # noqa: BLE001 - a missed warm-up must never page
        logger.warning("keep-warm ping failed (session=%s): %s", session_id, exc)
    return {"ok": True}
'''


class MahaloKeepWarmStack(Stack):
    """Scheduled trivial invoke that keeps the Runtime warm during demo hours."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        runtime_stack: "Stack",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        runtime = runtime_stack.runtime

        shim_fn = lambda_.Function(
            self,
            "KeepWarmFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="index.handler",
            # Inline code: boto3-only, no Docker bundling (offline synth gate).
            code=lambda_.Code.from_inline(_SHIM_CODE),
            timeout=Duration.seconds(60),
            memory_size=128,
            environment={
                # The exact Runtime ARN the thin API already consumes; flows via a
                # CloudFormation construct reference, so no ARN is committed here.
                "MAHALO_RUNTIME_ARN": runtime.agent_runtime_arn,
            },
        )

        # Keep-warm -> Runtime: InvokeAgentRuntime scoped to the Runtime ARN, the
        # same L2 grant the thin API uses. grant_invoke_runtime_for_user is NOT
        # needed (Identity off for the MVP; no runtimeUserId).
        runtime.grant_invoke_runtime(shim_fn)

        # EventBridge scheduled rule: every 10 min, Mon–Fri 13:00–22:50 UTC
        # (roughly 08:00–18:00 US Eastern demo band). Renders as
        # cron(0/10 13-22 ? * MON-FRI *). targets.LambdaFunction auto-creates the
        # AWS::Lambda::Permission allowing events.amazonaws.com to invoke the shim.
        events.Rule(
            self,
            "KeepWarmSchedule",
            schedule=events.Schedule.cron(
                minute="0/10", hour="13-22", week_day="MON-FRI"
            ),
            targets=[targets.LambdaFunction(shim_fn)],
        )

        self.function = shim_fn
