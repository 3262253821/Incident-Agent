"""FastAPI entry point for the Incident Agent service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .incident_agent.core.config import get_settings
from .incident_agent.db.session import SessionLocal, check_database_connection
from .incident_agent.routers.auth import router as auth_router
from .incident_agent.routers.incidents import router as incidents_router
from .incident_agent.routers.runs import router as runs_router
from .incident_agent.services.storage import reclaim_stale_runs

settings = get_settings()

logger = logging.getLogger("incident_agent.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Reclaim runs abandoned by a previous process before serving traffic.

    ``create_run`` commits a ``running`` row before the graph runs, so a killed
    or reloaded process leaves rows that would otherwise stay ``running``
    forever. Failures here must not stop the service from starting: the API is
    still useful even if the cleanup could not run.
    """

    try:
        with SessionLocal() as db:
            reclaimed = reclaim_stale_runs(db)
        if reclaimed:
            logger.warning("回收了 %d 条中断的 running 记录", reclaimed)
        else:
            logger.info("没有需要回收的中断记录")
    except Exception:
        logger.exception("回收中断记录失败，服务继续启动")

    yield


app = FastAPI(
    title="Incident Agent API",
    version="0.1.0",
    description="面向研发和运维的故障初步分析 Agent API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.web_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router)
app.include_router(incidents_router)
app.include_router(runs_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Liveness endpoint that does not require MySQL or DevAtlas."""

    return {"status": "ok", "service": "incident-agent-api"}


@app.get("/health/db", response_model=None, tags=["system"])
def database_health_check() -> JSONResponse | dict[str, str]:
    """Check the independent Agent MySQL connection."""

    try:
        check_database_connection()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "service": "incident-agent-db"},
        )
    return {"status": "ok", "service": "incident-agent-db"}
