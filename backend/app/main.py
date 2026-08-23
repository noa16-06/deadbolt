"""FastAPI app: router registration, CORS, error handling, startup."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.db import SessionFactory, engine
from app.modules.auth.router import router as auth_router
from app.modules.planner.router import router as planner_router
from app.modules.servers import sampler
from app.modules.servers.router import router as servers_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The server manager samples in the background so no request has to wait a
    # second for a CPU delta. See app/modules/servers/sampler.py.
    sampler.start()
    yield
    await sampler.stop()
    # SIGTERM: close connections cleanly instead of letting them be torn down.
    await engine.dispose()


app = FastAPI(title="Homelab Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,  # never "*" together with cookies
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """Details to the log, only an id to the caller — no stack trace in the browser."""
    error_id = uuid.uuid4().hex[:12]
    log.exception("Unhandled error id=%s path=%s", error_id, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal error", "error_id": error_id},
    )


@app.get("/api/health")
async def health():
    """Checks the dependency too, not just whether the process is alive."""
    async with SessionFactory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(planner_router)
app.include_router(servers_router)
