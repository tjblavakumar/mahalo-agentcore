"""DynamoDB-backed collection store with lazy, seed-once initialization.

One table per service, keyed by ``pk`` (collection name) + ``sk`` (natural id).
Each item stores its record under a ``data`` attribute by default; GitHub's
dict-keyed ``BRANCHSET``/``STATS`` collections store their per-repo list under a
``value`` attribute instead.

Seeding is lazy: on first access the store checks a sentinel item
(``pk="_meta", sk="seeded"``). If absent, it deep-copies every seed item into
the table via batched writes, then sets the sentinel with a conditional put
(``attribute_not_exists(pk)``) so concurrent cold starts cannot double-seed.

``ClientError`` is allowed to propagate so the handler layer can map it to a
503 ``{"detail": "Backend store unavailable"}``.
"""

import copy
from typing import Any, Callable, Dict, Iterable, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

_META_PK = "_meta"
_SEEDED_SK = "seeded"


class Store:
    """A thin DynamoDB wrapper over a single ``pk``/``sk`` table."""

    def __init__(
        self,
        table_name: str,
        seed_items: Optional[Callable[[], Iterable[Dict[str, Any]]]] = None,
    ) -> None:
        """``seed_items`` yields dicts ``{"pk","sk","attr","record"}`` to seed."""
        self.table_name = table_name
        self._seed_items = seed_items
        self._table = boto3.resource("dynamodb").Table(table_name)
        self._seed_checked = False

    # --- Seeding ---

    def ensure_seeded(self) -> None:
        """Seed the table exactly once (idempotent across cold starts)."""
        if self._seed_checked:
            return
        existing = self._table.get_item(Key={"pk": _META_PK, "sk": _SEEDED_SK})
        if "Item" in existing:
            self._seed_checked = True
            return
        if self._seed_items is not None:
            items = [copy.deepcopy(item) for item in self._seed_items()]
            self._write_seed_items(items)
        try:
            self._table.put_item(
                Item={"pk": _META_PK, "sk": _SEEDED_SK},
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as exc:
            # Another cold start won the race; that is fine.
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        self._seed_checked = True

    def _write_seed_items(self, items: List[Dict[str, Any]]) -> None:
        with self._table.batch_writer() as batch:
            for item in items:
                attr = item.get("attr", "data")
                batch.put_item(
                    Item={"pk": item["pk"], "sk": item["sk"], attr: item["record"]}
                )

    # --- Reads ---

    def get(self, pk: str, sk: str, attr: str = "data") -> Optional[Any]:
        """Return the stored record under ``attr`` for the item, or ``None``."""
        resp = self._table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        if item is None:
            return None
        return item.get(attr)

    def exists(self, pk: str, sk: str) -> bool:
        """Return ``True`` when an item with this key exists."""
        resp = self._table.get_item(
            Key={"pk": pk, "sk": sk}, ProjectionExpression="pk"
        )
        return "Item" in resp

    def query(self, pk: str, attr: str = "data") -> List[Any]:
        """Return every stored record under a collection ``pk``."""
        records: List[Any] = []
        kwargs: Dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk)}
        while True:
            resp = self._table.query(**kwargs)
            for item in resp.get("Items", []):
                if attr in item:
                    records.append(item[attr])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return records

    def count(self, pk: str) -> int:
        """Return the number of items in a collection ``pk`` (== mock ``len``)."""
        total = 0
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk),
            "Select": "COUNT",
        }
        while True:
            resp = self._table.query(**kwargs)
            total += resp.get("Count", 0)
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return total

    # --- Writes ---

    def put(self, pk: str, sk: str, record: Any, attr: str = "data") -> None:
        """Store ``record`` under ``attr`` for the ``pk``/``sk`` item."""
        self._table.put_item(Item={"pk": pk, "sk": sk, attr: record})

    def delete(self, pk: str, sk: str) -> None:
        self._table.delete_item(Key={"pk": pk, "sk": sk})

    def batch_write(self, items: Iterable[Dict[str, Any]]) -> None:
        """Batch-write items ``{"pk","sk","attr"?,"record"}``."""
        with self._table.batch_writer() as batch:
            for item in items:
                attr = item.get("attr", "data")
                batch.put_item(
                    Item={"pk": item["pk"], "sk": item["sk"], attr: item["record"]}
                )
