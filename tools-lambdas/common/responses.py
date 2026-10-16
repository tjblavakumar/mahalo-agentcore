"""JSON response helpers producing the Lambda Function URL response shape."""

import json
from decimal import Decimal
from typing import Any, Dict

_JSON_HEADERS = {"content-type": "application/json"}


class _DecimalEncoder(json.JSONEncoder):
    """Encode DynamoDB ``Decimal`` numbers as plain ints/floats.

    boto3 returns every number as a ``Decimal``; the mock contract emits plain
    JSON numbers, so integral values serialize as ints and the rest as floats.
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        return super().default(o)


def json_response(status: int, body: Any) -> Dict[str, Any]:
    """Build a Function-URL response dict with a JSON-encoded body."""
    return {
        "statusCode": status,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps(body, cls=_DecimalEncoder),
    }


def error(status: int, detail: str) -> Dict[str, Any]:
    """Build an error response whose body is ``{"detail": detail}``."""
    return json_response(status, {"detail": detail})
