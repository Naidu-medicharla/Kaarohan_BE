import re

from psycopg import AsyncConnection, errors
from psycopg.sql import SQL, Identifier
from psycopg_pool import AsyncConnectionPool

from app.config import settings

RESERVED_TABLE_NAMES = {"events", "leaderboard"}

LEADERBOARD_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS leaderboard (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_name   TEXT NOT NULL UNIQUE,
    position    INTEGER NOT NULL DEFAULT 0,
    points      INTEGER NOT NULL DEFAULT 0
);
"""

EVENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_name  TEXT NOT NULL UNIQUE
);
"""

TT_SINGLES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tt_mens_singles (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_number  INTEGER NOT NULL UNIQUE,
    player_a      TEXT NOT NULL,
    player_b      TEXT NOT NULL,
    winner        TEXT
);
"""

TT_DOUBLES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tt_mens_doubles (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_number    INTEGER NOT NULL UNIQUE,
    pair_a_player1  TEXT NOT NULL,
    pair_a_player2  TEXT NOT NULL,
    pair_b_player1  TEXT NOT NULL,
    pair_b_player2  TEXT NOT NULL,
    winner_player1  TEXT,
    winner_player2  TEXT
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
        await conn.execute(LEADERBOARD_SCHEMA_SQL)
        await conn.execute(EVENTS_SCHEMA_SQL)
        await conn.execute(TT_SINGLES_SCHEMA_SQL)
        await conn.execute(TT_DOUBLES_SCHEMA_SQL)


def event_table_slug(event_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", event_name.strip().lower()).strip("_")
    if not slug:
        raise ValueError("event_name must contain at least one letter or digit")
    if slug[0].isdigit():
        slug = f"e_{slug}"
    if slug in RESERVED_TABLE_NAMES:
        raise ValueError(f"event_name '{event_name}' collides with a reserved table name")
    return slug


def event_scores_identifier(event_name: str) -> Identifier:
    # The table is named after the event itself (e.g. "Ethnic Day" -> ethnic_day)
    # rather than its numeric id, per request. Identifier() properly quotes the
    # slug so spaces/case are never an issue even though the slug itself is
    # already restricted to [a-z0-9_].
    return Identifier(event_table_slug(event_name))


async def create_event_score_table(conn: AsyncConnection, event_name: str) -> None:
    table = event_scores_identifier(event_name)
    try:
        await conn.execute(
            SQL(
                """
                CREATE TABLE {} (
                    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    team_name   TEXT NOT NULL UNIQUE,
                    points      INTEGER NOT NULL DEFAULT 0
                );
                """
            ).format(table)
        )
    except errors.DuplicateTable:
        raise ValueError(f"event_name '{event_name}' produces a table name that already exists")
    team_rows = await (await conn.execute("SELECT team_name FROM leaderboard ORDER BY team_name;")).fetchall()
    for (team_name,) in team_rows:
        await conn.execute(
            SQL("INSERT INTO {} (team_name) VALUES (%s);").format(table),
            (team_name,),
        )


async def sync_leaderboard_points(conn: AsyncConnection, team_name: str) -> None:
    event_names = [
        row[0] for row in await (await conn.execute("SELECT event_name FROM events ORDER BY id;")).fetchall()
    ]
    total = 0
    for event_name in event_names:
        table = event_scores_identifier(event_name)
        row = await (
            await conn.execute(SQL("SELECT points FROM {} WHERE team_name = %s;").format(table), (team_name,))
        ).fetchone()
        if row is not None:
            total += row[0]
    await conn.execute("UPDATE leaderboard SET points = %s WHERE team_name = %s;", (total, team_name))
