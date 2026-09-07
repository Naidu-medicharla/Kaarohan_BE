from psycopg_pool import AsyncConnectionPool

from app.config import settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS leaderboard (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_name   TEXT NOT NULL UNIQUE,
    position    INTEGER NOT NULL DEFAULT 0,
    points      INTEGER NOT NULL DEFAULT 0
);
"""

pool: AsyncConnectionPool | None = None


async def open_pool() -> None:
    # A closed psycopg_pool AsyncConnectionPool can't be reopened, so a fresh
    # instance is created on every startup (matters for tests, where the
    # lifespan runs through multiple open/close cycles in one process).
    global pool
    # Neon's given connection string is the pooled (PgBouncer, transaction-mode)
    # endpoint. psycopg3 auto-prepares statements after repeated use by default,
    # which can misbehave against transaction-mode pooling, so it's disabled here.
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=5,
        kwargs={"prepare_threshold": None},
        open=False,
    )
    await pool.open()


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


def get_pool() -> AsyncConnectionPool:
    assert pool is not None, "pool not initialized — open_pool() must run first"
    return pool


async def ensure_schema() -> None:
    async with get_pool().connection() as conn:
        await conn.execute(SCHEMA_SQL)
