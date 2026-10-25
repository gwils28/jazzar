"""Accès base de données : moteur async SQLAlchemy + sessions + initialisation du schéma."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from jazzar.config import get_settings

_engine: AsyncEngine | None = None
_ro_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_size=10, max_overflow=10)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_ro_engine() -> AsyncEngine:
    """Moteur en lecture seule (rôle jazzar_ro) utilisé par le Text-to-SQL."""
    global _ro_engine
    if _ro_engine is None:
        _ro_engine = create_async_engine(get_settings().database_ro_url, pool_size=4, max_overflow=4)
    return _ro_engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


async def init_schema() -> None:
    """Crée extensions, tables et index. Idempotent."""
    from jazzar.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
        # Index HNSW pour la recherche vectorielle (cosinus) et GIN pour le plein-texte.
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw ON chunks "
                "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 128)"
            )
        )
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING gin (tsv)"))
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_documents_title_trgm ON documents USING gin (title gin_trgm_ops)")
        )
        # Le rôle lecture seule doit voir les nouvelles tables.
        await conn.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO jazzar_ro"))


async def dispose() -> None:
    global _engine, _ro_engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    if _ro_engine is not None:
        await _ro_engine.dispose()
    _engine = _ro_engine = _session_factory = None
