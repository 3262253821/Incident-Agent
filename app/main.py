"""FastAPI entry point for the Incident Agent service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .incident_agent.core.config import get_settings
from .incident_agent.db.session import check_database_connection
from .incident_agent.routers.auth import router as auth_router
from .incident_agent.routers.incidents import router as incidents_router
from .incident_agent.routers.runs import router as runs_router


settings = get_settings()

app = FastAPI(
    title="Incident Agent API",
    version="0.1.0",
    description="面向研发和运维的故障初步分析 Agent API",
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
