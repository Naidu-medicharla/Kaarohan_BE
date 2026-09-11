from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query
from psycopg.rows import dict_row

from app.db import get_pool
from app.schemas import CarromMatchEntry, CarromRound

router = APIRouter(prefix="/carrom")


@router.get("/matches", response_model=list[CarromMatchEntry])
async def list_matches(round: Optional[CarromRound] = Query(None)) -> list[dict]:
    query = "SELECT id, round, player_a, player_b, winner FROM carrom_matches"
    params: list[str] = []
    if round is not None:
        query += " WHERE round = %s"
        params.append(round)
    query += " ORDER BY id;"

    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


# Form-encoded so every match can be created straight from Postman's Body ->
# form-data tab: round, player_a, player_b, winner. winner is a plain string
# ("NOT STARTED" by default) — there's no cross-check against player_a/
# player_b, so whatever text is sent is shown back as-is.
@router.post("/matches", response_model=CarromMatchEntry, status_code=201)
async def create_match(
    round: CarromRound = Form(...),
    player_a: str = Form(...),
    player_b: str = Form(...),
    winner: str = Form("NOT STARTED"),
) -> dict:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO carrom_matches (round, player_a, player_b, winner)
                VALUES (%s, %s, %s, %s)
                RETURNING id, round, player_a, player_b, winner;
                """,
                (round, player_a, player_b, winner),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row


# Create a whole round in one request: round applies to every match in the
# batch, and player_a/player_b/winner are repeated form fields — add the
# same key multiple times in Postman's form-data tab, one row per match,
# matched up by position. winner can be shorter than the other two
# (missing entries default to "NOT STARTED").
@router.post("/matches/bulk", response_model=list[CarromMatchEntry], status_code=201)
async def create_matches_bulk(
    round: CarromRound = Form(...),
    player_a: list[str] = Form(...),
    player_b: list[str] = Form(...),
    winner: list[str] = Form([]),
) -> list[dict]:
    if len(player_a) != len(player_b):
        raise HTTPException(
            status_code=400,
            detail=f"player_a has {len(player_a)} entries but player_b has {len(player_b)}",
        )
    if len(winner) > len(player_a):
        raise HTTPException(
            status_code=400,
            detail=f"winner has {len(winner)} entries but only {len(player_a)} matches were given",
        )
    winners = winner + ["NOT STARTED"] * (len(player_a) - len(winner))

    # One multi-row INSERT instead of one round trip per match — the Neon
    # DB is remote, so N sequential inserts meant N sequential round trips
    # and a bulk request of 8+ matches could take several seconds.
    values_clause = ", ".join(["(%s, %s, %s, %s)"] * len(player_a))
    params = []
    for a, b, w in zip(player_a, player_b, winners):
        params.extend([round, a, b, w])

    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                INSERT INTO carrom_matches (round, player_a, player_b, winner)
                VALUES {values_clause}
                RETURNING id, round, player_a, player_b, winner;
                """,
                params,
            )
            rows = await cur.fetchall()
        await conn.commit()
    return rows


# Also form-encoded. GET /matches first to see the current row (and its id),
# then PATCH only the fields that need correcting — every field is optional.
@router.patch("/matches/{match_id}", response_model=CarromMatchEntry)
async def update_match(
    match_id: int,
    round: Optional[CarromRound] = Form(None),
    player_a: Optional[str] = Form(None),
    player_b: Optional[str] = Form(None),
    winner: Optional[str] = Form(None),
) -> dict:
    updates = {
        "round": round,
        "player_a": player_a,
        "player_b": player_b,
        "winner": winner,
    }
    updates = {field: value for field, value in updates.items() if value is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Provide at least one field to update")

    set_clause = ", ".join(f"{field} = %s" for field in updates)
    params = [*updates.values(), match_id]

    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"UPDATE carrom_matches SET {set_clause} WHERE id = %s "
                "RETURNING id, round, player_a, player_b, winner;",
                params,
            )
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        await conn.commit()
    return row


@router.delete("/matches/{match_id}", status_code=204)
async def delete_match(match_id: int) -> None:
    async with get_pool().connection() as conn:
        cur = await conn.execute("DELETE FROM carrom_matches WHERE id = %s RETURNING id;", (match_id,))
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        await conn.commit()


# Clears a whole round in one call, e.g. before re-entering a bracket. The
# filter is required so a bare DELETE can't wipe every match by accident.
@router.delete("/matches", status_code=200)
async def delete_matches_by_round(round: CarromRound = Query(...)) -> dict:
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            "DELETE FROM carrom_matches WHERE round = %s RETURNING id;",
            (round,),
        )
        deleted_ids = [row[0] for row in await cur.fetchall()]
        await conn.commit()
    return {"deleted": len(deleted_ids), "ids": deleted_ids}
