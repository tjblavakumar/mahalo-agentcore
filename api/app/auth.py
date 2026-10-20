"""Request-identity extraction for the thin API (design §B.5).

For the AWS_IAM MVP this returns a fixed dev identity (``dev-6`` / ``developer``),
faithfully matching the Task-1/2 demo. SigV4 is enforced at the Function-URL edge;
this dependency is the single swap point for Cognito JWT-claim extraction later —
nothing else changes when Cognito lands.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    developer_id: str = "dev-6"
    role: str = "developer"


def current_identity() -> Identity:
    """FastAPI dependency: the fixed dev identity for the MVP."""
    return Identity()
