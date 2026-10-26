"""FastAPI app + Mangum handler for the thin API (design §B.2).

``handler`` is the Lambda entry point (Function-URL Lambda via Mangum). Importing
this module is offline-safe: the boto3 client in ``runtime_client`` is built
lazily, so neither FastAPI construction nor Mangum wrapping touches AWS.
"""

from __future__ import annotations

from fastapi import FastAPI
from mangum import Mangum

from app.routers.chat import router as chat_router
from app.routers.dashboard import router as dashboard_router

app = FastAPI(title="mahalo thin API", version="1.0.0")
app.include_router(chat_router)
app.include_router(dashboard_router)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe for the Function-URL Lambda."""
    return {"status": "ok"}


# Lambda entry point (handler="app.main.handler" in the CDK Lambda).
handler = Mangum(app)
