"""bedrock-agentcore data-plane forwarder: InvokeAgentRuntime (design §B.4).

The boto3 client is built LAZILY (not at import) so this module imports with no
AWS creds — the offline gate relies on that. ``invoke_runtime`` is a thin wrapper:
it serializes the body to JSON, sets the session-id/content-type/accept members,
optionally sets ``runtimeUserId`` (only when Identity is enabled — off for the
MVP), and returns the parsed unary JSON response.

Confirmed against installed botocore ``bedrock-agentcore/2024-02-28``: the request
members are ``agentRuntimeArn``, ``runtimeSessionId`` (session header),
``contentType``/``accept`` (MIME headers), ``payload`` (body), and the optional
``runtimeUserId``; the response payload member is ``response`` (a ``ResponseStream``
whose ``.read()`` yields the unary JSON bytes).
"""

from __future__ import annotations

import json

from app.config import settings

_client = None

# A cold agent pass on AgentCore Runtime can take ~64s, which exceeds botocore's
# DEFAULT read_timeout of 60s. With the default retry policy that read timeout is
# retried, SILENTLY re-invoking the SAME runtime session — so one /chat call runs
# the agent two or three times (the measured "~2 minute" response), and because
# the retried pass sees the earlier pass's answer in per-session Memory it replies
# with déjà-vu phrasing on a user's FIRST ask. The same retry on /chat/approve
# could re-run a slow approve and DOUBLE-APPLY a write. Both paths go through this
# single client, so an explicit Config fixes both:
#   - read_timeout=300 matches the agent's model read_timeout so a single cold
#     pass never times out,
#   - connect_timeout=10 bounds connection setup,
#   - retries max_attempts=1 (botocore counts the TOTAL attempts, so 1 = the
#     initial call only, NO retries) guarantees EXACTLY ONE invocation.
_RUNTIME_READ_TIMEOUT = 300
_RUNTIME_CONNECT_TIMEOUT = 10
_RUNTIME_MAX_ATTEMPTS = 1


def _get_client():
    """Build the boto3 ``bedrock-agentcore`` client once, on first use (not import)."""
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        config = Config(
            read_timeout=_RUNTIME_READ_TIMEOUT,
            connect_timeout=_RUNTIME_CONNECT_TIMEOUT,
            retries={"max_attempts": _RUNTIME_MAX_ATTEMPTS, "mode": "standard"},
        )
        _client = boto3.client(
            "bedrock-agentcore", region_name=settings.region, config=config
        )
    return _client


def invoke_runtime(*, session_id: str, body: dict, runtime_user_id: str | None = None) -> dict:
    """Invoke the Runtime for one request; return the parsed JSON reply dict."""
    kwargs = dict(
        agentRuntimeArn=settings.runtime_arn,
        runtimeSessionId=session_id,
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(body).encode("utf-8"),
    )
    if runtime_user_id:
        # Only set on the Identity-enablement path (§D.4); off for the AWS_IAM MVP.
        kwargs["runtimeUserId"] = runtime_user_id

    resp = _get_client().invoke_agent_runtime(**kwargs)
    return json.loads(resp["response"].read())
