"""GitHub mock/real Lambda entrypoint: github.handler.lambda_handler.

Mode is selected by ``GITHUB_MODE`` (default ``mock``):

- ``mock`` (default) — the DynamoDB-backed in-memory JSON store; the ``Store`` is
  built and seeded exactly as before. No behavior changes on this path.
- ``real`` — a Gitea-backed adapter (``gitea_backend.GiteaBackend``). The DynamoDB
  ``Store`` is NOT constructed or seeded; the router delegates to Gitea over HTTP.
  The adapter token is resolved once at cold start from an SSM SecureString
  parameter (``GITEA_TOKEN_PARAM``), falling back to ``GITEA_TOKEN`` /
  ``GITEA_TOKEN_FILE`` for local/unit parity. The token value is never logged.
"""

import logging
import os

from botocore.exceptions import ClientError

from common import gateway_adapter
from common.dynamo_store import Store
from common.responses import error

from . import routes

logger = logging.getLogger()

_TOKEN = os.environ.get("MOCK_GITHUB_TOKEN", "mock-github-token-12345")
_TABLE_NAME = os.environ.get("TABLE_NAME", "mahalo-mock-github")

# Mode + Gitea config (read at module scope; mirrors mahalo-dock gitea_backend).
_MODE = os.environ.get("GITHUB_MODE", "mock").strip().lower()
_GITEA_URL = os.environ.get("GITEA_URL", "http://gitea:3000")
_GITEA_OWNER = os.environ.get("GITEA_ADMIN_USER", "mahalo_admin")
_GITEA_PUBLIC_URL = os.environ.get("GITEA_PUBLIC_URL", "http://localhost:3001")
_DEMO_DEVELOPER_ID = os.environ.get("DEMO_DEVELOPER_ID", "dev-6")


def _resolve_gitea_token():
    """Resolve the Gitea adapter token once at cold start.

    Prefers the SSM SecureString parameter named by ``GITEA_TOKEN_PARAM`` (decrypted
    via boto3), then falls back to ``GITEA_TOKEN`` / ``GITEA_TOKEN_FILE`` so local
    and unit runs match the mahalo-dock contract. The token value is never logged.
    """
    param_name = os.environ.get("GITEA_TOKEN_PARAM")
    if param_name:
        import boto3

        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return resp["Parameter"]["Value"]

    token = os.environ.get("GITEA_TOKEN", "")
    if token:
        return token

    path = os.environ.get("GITEA_TOKEN_FILE", "")
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            logger.warning("GITEA_TOKEN_FILE not readable yet")
    return ""


_store = None
_router = None


def _get_router():
    global _store, _router
    if _router is None:
        if _MODE == "real":
            # Real mode: skip the DynamoDB Store/seed entirely and delegate to
            # Gitea. Import the adapter lazily so the mock path never loads httpx.
            from .gitea_backend import GiteaBackend

            backend = GiteaBackend(
                base_url=_GITEA_URL,
                token=_resolve_gitea_token(),
                owner=_GITEA_OWNER,
                public_url=_GITEA_PUBLIC_URL,
                demo_developer_id=_DEMO_DEVELOPER_ID,
            )
            _store = None
            _router = routes.build_gitea_router(backend)
        else:
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
        if store is not None:
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
