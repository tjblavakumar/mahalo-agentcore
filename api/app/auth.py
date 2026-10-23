"""Request-identity extraction for the thin API (design §A.3 / §B.5).

For the demo the thin-API Function URL is ``AuthType=NONE`` (the SCP-blocked
Cognito identity pool is removed), so the browser calls it with no AWS
credentials and asserts the active persona via the ``X-Mahalo-Persona`` header.
``current_identity`` maps that header to the fixed ``{developer_id, role}`` pair
the Runtime already consumes.

Demo-only posture (explicitly accepted): the browser is trusted — the header is
not verified. Because the mapping is a fixed table, a malformed or hostile
header can only ever select one of three known-good identities or the safe
developer default; it can never inject an arbitrary developer_id/role. This
dependency stays the single swap point for OKTA JWT-claim extraction in the
GovCloud production path later.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

# The one server-side persona table (mirror of frontend/src/lib/personas.ts).
# X-Mahalo-Persona value -> (developer_id, role). Keep in sync by hand.
_PERSONA_MAP: dict[str, tuple[str, str]] = {
    "pm": ("dev-1", "product_manager"),
    "dev": ("dev-6", "developer"),
    "exec": ("dev-5", "executive"),
}
_DEFAULT = ("dev-6", "developer")
PERSONA_HEADER = "X-Mahalo-Persona"


@dataclass(frozen=True)
class Identity:
    developer_id: str = "dev-6"
    role: str = "developer"


def current_identity(request: Request) -> Identity:
    """Map the ``X-Mahalo-Persona`` header to a fixed ``{developer_id, role}``.

    Demo-only: the browser asserts the persona with no verification. The header
    is optional and compared case-insensitively after ``strip()``; the only
    accepted values are ``pm`` / ``dev`` / ``exec``. Any other value (absent,
    empty, unknown) falls back silently to the developer identity — a demo user
    mistyping a header must never see a 4xx; the safe default is correct.
    """
    raw = request.headers.get(PERSONA_HEADER, "").strip().lower()
    developer_id, role = _PERSONA_MAP.get(raw, _DEFAULT)
    return Identity(developer_id=developer_id, role=role)
