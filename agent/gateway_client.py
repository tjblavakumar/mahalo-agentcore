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

from typing import Callable, Optional

import httpx
from strands.tools.mcp import MCPClient

from agent.config import settings

# A factory returning an optional ``httpx.Auth`` to sign Gateway MCP requests.
# Overridable at the LIVE step; the offline default supplies no provider.
_auth_provider_factory: Callable[[], Optional[httpx.Auth]] = lambda: None


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
