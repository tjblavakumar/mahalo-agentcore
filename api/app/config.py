"""Environment-driven configuration for the thin API.

Importing this module requires no AWS creds or network. The Runtime ARN is wired
in by the CDK ``MahaloApiStack`` as ``MAHALO_RUNTIME_ARN`` (from the Runtime
stack's ``RuntimeArn`` CfnOutput).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _getenv(name: str, default: str) -> str:
    return os.getenv(name, default)


def _getbool(name: str, default: str = "false") -> bool:
    return _getenv(name, default).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    """Resolved thin-API configuration from environment variables."""

    runtime_arn: str = field(default_factory=lambda: _getenv("MAHALO_RUNTIME_ARN", ""))
    region: str = field(default_factory=lambda: _getenv("AWS_REGION", "us-east-1"))
    # Identity is OFF for the AWS_IAM MVP (design §D.4); when true the thin API
    # forwards runtimeUserId to invoke_agent_runtime.
    identity_enabled: bool = field(
        default_factory=lambda: _getbool("MAHALO_IDENTITY_ENABLED")
    )
    # DynamoDB table backing the custom dashboard (design §3.1); wired in by the
    # CDK MahaloApiStack as MAHALO_DASHBOARD_TABLE from the dashboard stack.
    dashboard_table: str = field(
        default_factory=lambda: _getenv("MAHALO_DASHBOARD_TABLE", "mahalo-dashboards")
    )


    # Mock-service Function URLs + API tokens, wired in by MahaloApiStack from the
    # mock stacks. Used ONLY server-side by the read-only viewer proxy and the
    # refresh endpoint; the tokens never reach the browser.
    jira_url: str = field(default_factory=lambda: _getenv("MAHALO_JIRA_URL", "").rstrip("/"))
    confluence_url: str = field(
        default_factory=lambda: _getenv("MAHALO_CONFLUENCE_URL", "").rstrip("/")
    )
    servicenow_url: str = field(
        default_factory=lambda: _getenv("MAHALO_SERVICENOW_URL", "").rstrip("/")
    )
    jira_token: str = field(default_factory=lambda: _getenv("MAHALO_JIRA_TOKEN", ""))
    confluence_token: str = field(default_factory=lambda: _getenv("MAHALO_CONFLUENCE_TOKEN", ""))
    servicenow_token: str = field(default_factory=lambda: _getenv("MAHALO_SERVICENOW_TOKEN", ""))


settings = Settings()
