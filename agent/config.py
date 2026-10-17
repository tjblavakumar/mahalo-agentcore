"""Environment-driven configuration for the local Strands agent.

Importing this module MUST NOT require live AWS credentials or network access.
Every value is read from the environment with a sensible default so the agent
works against the localhost SSH tunnel (ports 5001-5004) out of the box and can
be pointed at other hosts purely via env vars. AWS credentials are never baked
into code — they come from the `lava` AWS profile / standard credential chain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _getenv(name: str, default: str) -> str:
    return os.getenv(name, default)


def _getbool(name: str, default: str = "false") -> bool:
    """Tolerant boolean parse: ``1``/``true``/``yes`` (any case) -> True."""
    return _getenv(name, default).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    """Resolved configuration, populated from environment variables."""

    # --- Bedrock / AWS ---
    bedrock_model_id: str = field(
        default_factory=lambda: _getenv(
            "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )
    )
    aws_region: str = field(default_factory=lambda: _getenv("AWS_REGION", "us-east-1"))
    aws_profile: str = field(default_factory=lambda: _getenv("AWS_PROFILE", "lava"))
    # Large code-gen responses can exceed the 60s default, so read_timeout=300s.
    bedrock_read_timeout: int = field(
        default_factory=lambda: int(_getenv("BEDROCK_READ_TIMEOUT", "300"))
    )
    bedrock_connect_timeout: int = field(
        default_factory=lambda: int(_getenv("BEDROCK_CONNECT_TIMEOUT", "10"))
    )

    # --- Mock service base URLs + tokens (X-API-Token header) ---
    jira_url: str = field(default_factory=lambda: _getenv("JIRA_URL", "http://localhost:5001"))
    jira_token: str = field(
        default_factory=lambda: _getenv("JIRA_TOKEN", "mock-jira-token-12345")
    )

    confluence_url: str = field(
        default_factory=lambda: _getenv("CONFLUENCE_URL", "http://localhost:5002")
    )
    confluence_token: str = field(
        default_factory=lambda: _getenv("CONFLUENCE_TOKEN", "mock-confluence-token-12345")
    )

    github_url: str = field(default_factory=lambda: _getenv("GITHUB_URL", "http://localhost:5003"))
    github_token: str = field(
        default_factory=lambda: _getenv("GITHUB_TOKEN", "mock-github-token-12345")
    )

    servicenow_url: str = field(
        default_factory=lambda: _getenv("SERVICENOW_URL", "http://localhost:5004")
    )
    servicenow_token: str = field(
        default_factory=lambda: _getenv("SERVICENOW_TOKEN", "mock-servicenow-token-12345")
    )

    # --- HTTP ---
    http_timeout: float = field(
        default_factory=lambda: float(_getenv("HTTP_TIMEOUT", "10.0"))
    )

    # --- Tool mode (Task 4: DIRECT-HTTP default | Gateway-MCP opt-in) ---
    tool_mode: str = field(
        default_factory=lambda: _getenv("MAHALO_TOOL_MODE", "direct")
    )
    gateway_mcp_url: str = field(
        default_factory=lambda: _getenv("MAHALO_GATEWAY_MCP_URL", "")
    )
    gateway_region: str = field(
        default_factory=lambda: _getenv(
            "MAHALO_GATEWAY_REGION", _getenv("AWS_REGION", "us-east-1")
        )
    )

    # --- Memory (Task 5: AgentCore Memory session persistence, opt-in) ---
    # All default off/empty so DIRECT and GATEWAY behavior is byte-for-byte
    # unchanged when the toggle is not set.
    memory_enabled: bool = field(
        default_factory=lambda: _getbool("MAHALO_MEMORY_ENABLED")
    )
    memory_id: str = field(default_factory=lambda: _getenv("MAHALO_MEMORY_ID", ""))
    memory_region: str = field(
        default_factory=lambda: _getenv(
            "MAHALO_MEMORY_REGION", _getenv("AWS_REGION", "us-east-1")
        )
    )
    session_id: str = field(default_factory=lambda: _getenv("MAHALO_SESSION_ID", ""))

    # --- Identity (Task 5: AgentCore Identity credential brokering, opt-in) ---
    identity_enabled: bool = field(
        default_factory=lambda: _getbool("MAHALO_IDENTITY_ENABLED")
    )
    identity_jira_provider: str = field(
        default_factory=lambda: _getenv(
            "MAHALO_IDENTITY_JIRA_PROVIDER", "mahalo-jira-apikey"
        )
    )


settings = Settings()
