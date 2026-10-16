"""Static X-API-Token enforcement, mirroring the mahalo-dock mocks.

The mock services compare the ``X-API-Token`` header value with ``!=`` against
the configured token, so a missing or mismatched token (including ``None``)
yields a 401 with body ``{"detail": "Invalid API token"}``. Only the header
*key* lookup is case-insensitive (Function URL event headers are lower-cased);
the *value* comparison is exact (no trimming or case-folding).
"""

from typing import Optional

from common.router import Request


def _header_value(request: "Request", key: str) -> Optional[str]:
    """Case-insensitive header-KEY lookup; returns the value or ``None``."""
    target = key.lower()
    for header_key, header_value in request.headers.items():
        if header_key.lower() == target:
            return header_value
    return None


def require_token(request: "Request", expected: str) -> bool:
    """Return ``True`` when the request carries the exact expected token."""
    return _header_value(request, "x-api-token") == expected
