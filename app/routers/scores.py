from fastapi import APIRouter, Form, HTTPException
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.sql import SQL

from app.db import event_scores_identifier, get_pool, sync_leaderboard_points_bulk
from app.schemas import EventScoreEntry

router = APIRouter()

EVENT_NAME_QUERY = "SELECT event_name FROM events WHERE id = %s;"


async def _get_event_name_or_404(conn: AsyncConnection, event_id: int) -> str:
    row = await (await conn.execute(EVENT_NAME_QUERY, (event_id,))).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    return row[0]


async def _apply_scores(
    conn: AsyncConnection,
    event_id: int,
    event_name: str,
    team_names: list[str],
    points_list: list[float],
) -> list[dict]:
    if len(team_names) != len(points_list):
        raise HTTPException(
            status_code=400,
            detail=f"got {len(team_names)} team_name value(s) but {len(points_list)} points value(s) — "
            "each team_name must be paired with exactly one points value",
        )

    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in team_names:
        (duplicates if name in seen else seen).add(name)
    if duplicates:
        raise HTTPException(
            status_code=400,
            detail=f"duplicate team_name in request: {', '.join(sorted(duplicates))} — "
            "each team can only appear once per request",
        )

    # Every event's table is seeded with exactly the 8 real teams at creation
    # time (see create_event_score_table) and nothing ever adds a 9th, so this
    # is always an UPDATE, never an INSERT — a typo'd/unknown team_name must
    # fail loudly (404) instead of silently creating a bogus extra row, which
    # is what INSERT ... ON CONFLICT DO UPDATE would otherwise do.
    table = event_scores_identifier(event_name)
    results: list[dict] = []
    async with conn.cursor(row_factory=dict_row) as cur:
        for team_name, points in zip(team_names, points_list):
            await cur.execute(
                SQL("UPDATE {} SET points = %s WHERE team_name = %s RETURNING id, team_name, points;").format(table),
                (points, team_name),
            )
            row = await cur.fetchone()
            if row is None:
                await conn.rollback()
                raise HTTPException(
                    status_code=404,
                    detail=f"Team '{team_name}' not found in event {event_id} — check for a typo "
                    "against the 8 registered team names (see GET /api/score/{event_id})",
                )
            results.append(row)

    await sync_leaderboard_points_bulk(conn, team_names)
    await conn.commit()
    return results


@router.post("/{event_id}/score", response_model=list[EventScoreEntry])
async def set_scores(
    event_id: int,
    team_name: list[str] = Form(...),
    points: list[float] = Form(...),
) -> list[dict]:
    async with get_pool().connection() as conn:
        event_name = await _get_event_name_or_404(conn, event_id)
        return await _apply_scores(conn, event_id, event_name, team_name, points)


@router.patch("/{event_id}/score", response_model=list[EventScoreEntry])
async def update_scores(
    event_id: int,
    team_name: list[str] = Form(...),
    points: list[float] = Form(...),
) -> list[dict]:
    async with get_pool().connection() as conn:
        event_name = await _get_event_name_or_404(conn, event_id)
        return await _apply_scores(conn, event_id, event_name, team_name, points)


@router.get("/score/{event_id}", response_model=list[EventScoreEntry])
async def get_event_scores(event_id: int) -> list[dict]:
    async with get_pool().connection() as conn:
        event_name = await _get_event_name_or_404(conn, event_id)
        table = event_scores_identifier(event_name)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(SQL("SELECT id, team_name, points FROM {table} ORDER BY id;").format(table=table))
            return await cur.fetchall()
