"""Centralized configuration for the Incident Agent MVP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote_plus

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Runtime configuration loaded from environment variables."""

    agent_host: str
    agent_port: int
    model: str
    model_base_url: str
    model_timeout_seconds: float
    request_timeout_seconds: float
    devatlas_base_url: str
    devatlas_timeout_seconds: float
    max_iterations: int
    default_top_k: int
    database_url: str
    web_origins: tuple[str, ...]
    # 模型行为参数（P1-2-2）：集中在配置里，不在业务函数里写死字面量。
    model_temperature: float = 0.1
    model_max_tokens: int | None = None
    model_max_retries: int = 0
    report_model: str = "deepseek-chat"
    # 历史保留期（P1-3-3）：0 表示不删除，默认保护演示数据。
    run_retention_days: int = 0


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少必要环境变量：{name}")
    return value


def _optional_int(raw: str | None) -> int | None:
    """Parse an optional integer env var; empty or invalid means "unset"."""

    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def load_settings() -> Settings:
    """Load settings without printing secrets."""

    load_dotenv()

    database_url = os.getenv("INCIDENT_DATABASE_URL")
    if not database_url:
        db_user = quote_plus(_required_env("INCIDENT_DB_USER"))
        db_password = quote_plus(_required_env("INCIDENT_DB_PASSWORD"))
        db_name = quote_plus(_required_env("INCIDENT_DB_NAME"))
        database_url = (
            "mysql+pymysql://"
            f"{db_user}:{db_password}@"
            f"{os.getenv('INCIDENT_DB_HOST', '127.0.0.1')}"
            f":{os.getenv('INCIDENT_DB_PORT', '3306')}"
            f"/{db_name}"
        )

    origins = os.getenv(
        "INCIDENT_WEB_ORIGINS",
        "http://127.0.0.1:5174",
    )

    return Settings(
        agent_host=os.getenv("INCIDENT_AGENT_HOST", "127.0.0.1"),
        agent_port=int(os.getenv("INCIDENT_AGENT_PORT", "8001")),
        model=os.getenv("INCIDENT_AGENT_MODEL", "deepseek-chat"),
        model_base_url=os.getenv(
            "INCIDENT_AGENT_BASE_URL",
            "https://api.deepseek.com",
        ),
        # 单次模型调用的连接/读取超时：默认 30 秒，绝不沿用 SDK 的 600 秒。
        model_timeout_seconds=float(
            os.getenv("INCIDENT_MODEL_TIMEOUT_SECONDS", "30")
        ),
        # 整个分析请求的预算：默认 90 秒，比前端 axios 的 120 秒留出余量。
        request_timeout_seconds=float(
            os.getenv("INCIDENT_REQUEST_TIMEOUT_SECONDS", "90")
        ),
        devatlas_base_url=os.getenv(
            "DEVATLAS_BASE_URL",
            "http://127.0.0.1:8000",
        ),
        devatlas_timeout_seconds=float(
            os.getenv("DEVATLAS_TIMEOUT_SECONDS", "20")
        ),
        max_iterations=int(os.getenv("INCIDENT_MAX_ITERATIONS", "4")),
        default_top_k=int(os.getenv("INCIDENT_DEFAULT_TOP_K", "5")),
        database_url=database_url,
        web_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        # 模型行为参数（P1-2-2）
        model_temperature=float(
            os.getenv("INCIDENT_AGENT_TEMPERATURE", "0.1")
        ),
        model_max_tokens=_optional_int(os.getenv("INCIDENT_AGENT_MAX_TOKENS")),
        model_max_retries=int(os.getenv("INCIDENT_MODEL_MAX_RETRIES", "0")),
        report_model=os.getenv(
            "INCIDENT_AGENT_REPORT_MODEL",
            os.getenv("INCIDENT_AGENT_MODEL", "deepseek-chat"),
        ),
        # 历史保留天数：0（默认）表示不删除任何记录。
        run_retention_days=_optional_int(
            os.getenv("INCIDENT_RUN_RETENTION_DAYS", "0"),
        )
        or 0,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one cached settings object for the process."""

    return load_settings()
