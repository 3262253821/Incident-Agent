"""SQLAlchemy engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """Base class for Agent ORM models."""


engine = create_engine(
    get_settings().database_url,
    # 用于检查连接是否有效，避免使用失效的 MySQL 连接
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield one database session and always close it."""

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()

