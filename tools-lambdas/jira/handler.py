"""Jira mock Lambda entrypoint: jira.handler.lambda_handler."""

import logging
import os

from botocore.exceptions import ClientError

from common import gateway_adapter
from common.dynamo_store import Store
from common.responses import error

from . import routes

logger = logging.getLogger()

_TOKEN = os.environ.get("MOCK_JIRA_TOKEN", "mock-jira-token-12345")
_TABLE_NAME = os.environ.get("TABLE_NAME", "mahalo-mock-jira")

_store = None
_router = None


def _get_router():
    global _store, _router
    if _router is None:
        _store = Store(_TABLE_NAME, seed_items=routes.seed_items)
        _router = routes.build_router(_store, _TOKEN)
    return _store, _router


def _gateway_tool_name(context):
    """Return the Gateway tool name if this is a Gateway invocation, else None."""
    custom = getattr(getattr(context, "client_context", None), "custom", None)
    if isinstance(custom, dict):
        return custom.get("bedrockAgentCoreToolName")
    return None


def lambda_handler(event, context):
    try:
        store, router = _get_router()
        store.ensure_seeded()
        tool_name = _gateway_tool_name(context)
        if tool_name is not None:
            return gateway_adapter.handle(tool_name, store, router, event, _TOKEN)
        return router.dispatch(event)
    except ClientError:
        logger.exception("DynamoDB error")
        return error(503, "Backend store unavailable")
    except Exception:
        logger.exception("Unhandled error")
        return error(500, "Internal error")
