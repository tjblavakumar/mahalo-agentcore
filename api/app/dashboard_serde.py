"""Numeric (de)serialization boundary for the dashboards DynamoDB table (§3.3a).

The boto3 **resource** client (used by the dashboard router, mirroring the
tools-lambdas store) refuses native Python ``float`` on write (``TypeError:
Float types are not supported``) and hands back ``Decimal`` on read, which the
default JSON encoder can't serialize. These two pure functions own the
conversion in both directions and are unit-tested with a float round-trip.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def _decimalize(obj: Any) -> Any:
    """Turn every JSON float in ``obj`` into ``Decimal`` (write side, pre-PutItem).

    Walks the whole nested structure once via ``json`` with ``parse_float=Decimal``
    so floats become ``Decimal`` while ``int``/``str``/``bool``/``None`` stay as-is.
    """
    return json.loads(json.dumps(obj), parse_float=Decimal)


def _undecimalize(obj: Any) -> Any:
    """Turn every ``Decimal`` back into ``int``/``float`` (read side, post-GetItem).

    A ``Decimal`` with no fractional part becomes ``int``; otherwise ``float``.
    Recurses into lists and dicts; all other values pass through unchanged.
    """
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, list):
        return [_undecimalize(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _undecimalize(value) for key, value in obj.items()}
    return obj
