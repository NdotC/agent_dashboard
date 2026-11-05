"""Engine, Session-Factory und Migrationen."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _set_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def create_engine(db_url: str) -> AsyncEngine:
    engine = create_async_engine(db_url, connect_args={"timeout": 30})
    event.listen(engine.sync_engine, "connect", _set_pragmas)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def alembic_config(sync_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


def run_migrations(db_path: Path) -> None:
    """Bringt die Datenbank auf den neuesten Stand (synchron, beim Start)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(f"sqlite:///{db_path}"), "head")
