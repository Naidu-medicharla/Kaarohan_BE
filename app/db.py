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

TT_MATCHES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tt_matches (
    id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category  TEXT NOT NULL,
    round     TEXT NOT NULL,
    player_a  TEXT NOT NULL,
    player_b  TEXT NOT NULL,
    winner    TEXT NOT NULL DEFAULT 'NOT STARTED'
);
"""

CARROM_MATCHES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS carrom_matches (
    id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    round     TEXT NOT NULL,
    player_a  TEXT NOT NULL,
    player_b  TEXT NOT NULL,
    winner    TEXT NOT NULL DEFAULT 'NOT STARTED'
);
"""

# TT scoring has a shape the generic per-event table (id, team_name, points)
# can't represent — each team's TT total is a breakdown across 5 categories.
# `total` is a stored generated column so it's always in sync automatically
# and sync_leaderboard_points can just read it like any other event's points.
TT_TEAM_SCORES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tt_team_scores (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_name       TEXT NOT NULL UNIQUE,
    mens_singles    INTEGER NOT NULL DEFAULT 0,
    mens_doubles    INTEGER NOT NULL DEFAULT 0,
    womens_singles  INTEGER NOT NULL DEFAULT 0,
    womens_doubles  INTEGER NOT NULL DEFAULT 0,
    mixed_doubles   INTEGER NOT NULL DEFAULT 0,
    total           INTEGER GENERATED ALWAYS AS (
                        mens_singles + mens_doubles + womens_singles + womens_doubles + mixed_doubles
                    ) STORED
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
    #
    # Neon also closes idle connections from its side well before this pool's
    # own max_idle would recycle them, which previously surfaced as random
    # "SSL connection has been closed unexpectedly" 500s on the first request
    # after a quiet spell. `check` pings each connection before handing it to
    # a request and transparently reopens it if that ping fails.
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=5,
        kwargs={"prepare_threshold": None},
        check=AsyncConnectionPool.check_connection,
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
        await conn.execute(TT_MATCHES_SCHEMA_SQL)
        await conn.execute(CARROM_MATCHES_SCHEMA_SQL)
        await conn.execute(TT_TEAM_SCORES_SCHEMA_SQL)
        await seed_tt_team_scores(conn)


async def seed_tt_team_scores(conn: AsyncConnection) -> None:
    team_rows = await (await conn.execute("SELECT team_name FROM leaderboard ORDER BY team_name;")).fetchall()
    for (team_name,) in team_rows:
        await conn.execute(
            "INSERT INTO tt_team_scores (team_name) VALUES (%s) ON CONFLICT (team_name) DO NOTHING;",
            (team_name,),
        )


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
    await sync_leaderboard_points_bulk(conn, [team_name])


# Bulk variant: computes every given team's total in one pass over the event
# tables (one query per event covering ALL requested teams, via = ANY(...))
# instead of one query per event per team. A caller resyncing all 8 teams
# after a batch score update previously meant 8 teams x ~8 queries = ~64
# sequential round trips to the remote DB; this cuts it to a small constant
# number regardless of how many teams are being resynced.
async def sync_leaderboard_points_bulk(conn: AsyncConnection, team_names: list[str]) -> None:
    if not team_names:
        return

    event_names = [
        row[0] for row in await (await conn.execute("SELECT event_name FROM events ORDER BY id;")).fetchall()
    ]
    totals = dict.fromkeys(team_names, 0)

    for event_name in event_names:
        table = event_scores_identifier(event_name)
        rows = await (
            await conn.execute(
                SQL("SELECT team_name, points FROM {} WHERE team_name = ANY(%s);").format(table),
                (team_names,),
            )
        ).fetchall()
        for team_name, points in rows:
            totals[team_name] += points

    # TT isn't a generic event (its score has a 5-category breakdown, not a
    # single points column) so it's folded in here rather than showing up
    # in the events loop above.
    tt_rows = await (
        await conn.execute(
            "SELECT team_name, total FROM tt_team_scores WHERE team_name = ANY(%s);",
            (team_names,),
        )
    ).fetchall()
    for team_name, total in tt_rows:
        totals[team_name] += total

    values_clause = ", ".join(["(%s, %s)"] * len(totals))
    params = []
    for team_name, total in totals.items():
        params.extend([team_name, total])

    await conn.execute(
        f"""
        UPDATE leaderboard AS l
        SET points = v.points
        FROM (VALUES {values_clause}) AS v(team_name, points)
        WHERE l.team_name = v.team_name;
        """,
        params,
    )
