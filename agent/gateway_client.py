"""Gateway-MCP client construction for the agent's GATEWAY tool mode (Task 4).

Builds a ``strands.tools.mcp.MCPClient`` pointed at the AgentCore Gateway MCP
endpoint. Construction is OFFLINE-SAFE: the client is created but NOT started, so
importing/building the agent in GATEWAY mode never touches AWS or the network —
only an actual invocation (inside ``with mcp_client:``) does.

The inbound-auth mechanism is pluggable behind ``_auth_provider_factory`` so the
LIVE-validated signing approach (SigV4-over-MCP for the default ``AWS_IAM``
authorizer, or a Cognito bearer token for the ``CUSTOM_JWT`` fallback) can be
swapped without touching ``build_agent``. The default factory returns ``None``
(no auth provider), which keeps offline construction dependency-free; the LIVE
operator step wires the concrete provider.
"""

from __future__ import annotations

from typing import Callable, Iterator, Optional

import httpx
from strands.tools.mcp import MCPClient

from agent.config import settings

# SigV4 signing service name for the AgentCore Gateway MCP endpoint. Validated
# LIVE (2026-10-16): signing as ``bedrock-agentcore`` is accepted by the default
# AWS_IAM authorizer (HTTP 200); ``bedrock`` is rejected (401). See
# docs/.agents/tasks/task4-verification.md.
_GATEWAY_SIGNING_SERVICE = "bedrock-agentcore"


class SigV4Auth(httpx.Auth):
    """``httpx.Auth`` that SigV4-signs each request for the AWS_IAM authorizer.

    Signs with the resolved AWS credentials (from the standard chain / the
    ``lava`` profile) against the ``bedrock-agentcore`` service. Credentials are
    read per request so refreshed SSO/STS sessions are picked up. The request
    body is required for signing, so this must sign the fully-built request.
    """

    def __init__(self, region: str, service: str = _GATEWAY_SIGNING_SERVICE) -> None:
        self._region = region
        self._service = service

    def auth_flow(self, request: httpx.Request) -> Iterator[httpx.Request]:
        # Imported lazily so offline construction never requires boto3 unless a
        # real GATEWAY invocation actually signs a request.
        import boto3
        from botocore.auth import SigV4Auth as _BotoSigV4Auth
        from botocore.awsrequest import AWSRequest

        creds = boto3.Session().get_credentials()
        if creds is None:
            raise RuntimeError(
                "No AWS credentials available to sign the Gateway MCP request "
                "(expected the `lava` SSO profile / standard credential chain)."
            )
        frozen = creds.get_frozen_credentials()

        body = request.content or b""
        aws_req = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=body,
            headers=dict(request.headers),
        )
        _BotoSigV4Auth(frozen, self._service, self._region).add_auth(aws_req)

        # Copy the signed headers (Authorization, X-Amz-Date, X-Amz-Security-Token)
        # back onto the outgoing httpx request.
        for key, value in aws_req.headers.items():
            request.headers[key] = value
        yield request


def _default_auth_provider_factory() -> Optional[httpx.Auth]:
    """Build the SigV4 provider for the AWS_IAM authorizer (the deployed default).

    Returns ``None`` only when no Gateway URL is configured, keeping offline
    construction dependency-free. When GATEWAY mode is actually used, a valid
    URL is set and this returns a live SigV4 signer.
    """
    if not settings.gateway_mcp_url:
        return None
    return SigV4Auth(region=settings.gateway_region)


# A factory returning an optional ``httpx.Auth`` to sign Gateway MCP requests.
# Defaults to the LIVE-validated SigV4 signer; overridable (e.g. to a Cognito
# bearer-token provider for the CUSTOM_JWT fallback) via ``set_auth_provider_factory``.
_auth_provider_factory: Callable[[], Optional[httpx.Auth]] = _default_auth_provider_factory


def set_auth_provider_factory(factory: Callable[[], Optional[httpx.Auth]]) -> None:
    """Install the auth-provider factory used when building the MCP client."""
    global _auth_provider_factory
    _auth_provider_factory = factory


def _build_gateway_mcp_client() -> MCPClient:
    """Construct (but do NOT start) the Gateway MCP client.

    Raises ``ValueError`` only if GATEWAY mode is selected without a configured
    ``MAHALO_GATEWAY_MCP_URL`` — surfacing a misconfiguration early rather than
    failing opaquely at first invocation.
    """
    url = settings.gateway_mcp_url
    if not url:
        raise ValueError(
            "GATEWAY tool mode requires MAHALO_GATEWAY_MCP_URL to be set "
            "(the GatewayMcpUrl CfnOutput from MahaloGatewayStack)."
        )
    auth_provider = _auth_provider_factory()
    return MCPClient(url=url, auth_provider=auth_provider)
