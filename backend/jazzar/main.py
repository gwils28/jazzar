"""Application FastAPI Jazzar."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from jazzar import __version__
from jazzar.api.routes import router
from jazzar.config import get_settings
from jazzar.db import dispose, init_schema
from jazzar.logging import configure_logging, get_logger

log = get_logger("jazzar.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_schema()
    log.info("jazzar.start", version=__version__)
    yield
    await dispose()


app = FastAPI(title="Jazzar API", version=__version__, lifespan=lifespan,
              description="Moteur de recherche, dossiers agentiques et data-journalisme sur les archives jazz.")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=rid, path=request.url.path)
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    response.headers["x-response-time-ms"] = str(int((time.perf_counter() - t0) * 1000))
    return response


app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "Jazzar", "version": __version__, "docs": "/docs"}
