from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query
from psycopg.rows import dict_row

from app.db import get_pool, sync_leaderboard_points, sync_leaderboard_points_bulk
from app.schemas import TTCategory, TTMatchEntry, TTRound, TTTeamScoreEntry

router = APIRouter(prefix="/tt")


@router.get("/matches", response_model=list[TTMatchEntry])
async def list_matches(
    category: Optional[TTCategory] = Query(None),
    round: Optional[TTRound] = Query(None),
) -> list[dict]:
    query = "SELECT id, category, round, player_a, player_b, winner FROM tt_matches"
    conditions = []
    params: list[str] = []
    if category is not None:
        conditions.append("category = %s")
        params.append(category)
    if round is not None:
        conditions.append("round = %s")
        params.append(round)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id;"

    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


# Form-encoded so every match can be created straight from Postman's Body ->
# form-data tab: category, round, player_a, player_b, winner. winner is a
# plain string ("NOT STARTED" by default) — there's no cross-check against
# player_a/player_b, so whatever text is sent is shown back as-is.
@router.post("/matches", response_model=TTMatchEntry, status_code=201)
async def create_match(
    category: TTCategory = Form(...),
    round: TTRound = Form(...),
    player_a: str = Form(...),
    player_b: str = Form(...),
    winner: str = Form("NOT STARTED"),
) -> dict:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO tt_matches (category, round, player_a, player_b, winner)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, category, round, player_a, player_b, winner;
                """,
                (category, round, player_a, player_b, winner),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row


# Create a whole round in one request: category/round apply to every match
# in the batch, and player_a/player_b/winner are repeated form fields —
# add the same key multiple times in Postman's form-data tab, one row per
# match, matched up by position. winner can be shorter than the other two
# (missing entries default to "NOT STARTED").
@router.post("/matches/bulk", response_model=list[TTMatchEntry], status_code=201)
async def create_matches_bulk(
    category: TTCategory = Form(...),
    round: TTRound = Form(...),
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
    values_clause = ", ".join(["(%s, %s, %s, %s, %s)"] * len(player_a))
    params = []
    for a, b, w in zip(player_a, player_b, winners):
        params.extend([category, round, a, b, w])

    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                INSERT INTO tt_matches (category, round, player_a, player_b, winner)
                VALUES {values_clause}
                RETURNING id, category, round, player_a, player_b, winner;
                """,
                params,
            )
            rows = await cur.fetchall()
        await conn.commit()
    return rows


# Also form-encoded. GET /matches first to see the current row (and its id),
# then PATCH only the fields that need correcting — every field is optional.
@router.patch("/matches/{match_id}", response_model=TTMatchEntry)
async def update_match(
    match_id: int,
    category: Optional[TTCategory] = Form(None),
    round: Optional[TTRound] = Form(None),
    player_a: Optional[str] = Form(None),
    player_b: Optional[str] = Form(None),
    winner: Optional[str] = Form(None),
) -> dict:
    updates = {
        "category": category,
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
                f"UPDATE tt_matches SET {set_clause} WHERE id = %s "
                "RETURNING id, category, round, player_a, player_b, winner;",
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
        cur = await conn.execute("DELETE FROM tt_matches WHERE id = %s RETURNING id;", (match_id,))
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        await conn.commit()


# Clears a whole round/category in one call, e.g. before re-entering a
# bracket. Both filters are required so a bare DELETE can't wipe every
# match by accident.
@router.delete("/matches", status_code=200)
async def delete_matches_by_filter(
    category: TTCategory = Query(...),
    round: TTRound = Query(...),
) -> dict:
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            "DELETE FROM tt_matches WHERE category = %s AND round = %s RETURNING id;",
            (category, round),
        )
        deleted_ids = [row[0] for row in await cur.fetchall()]
        await conn.commit()
    return {"deleted": len(deleted_ids), "ids": deleted_ids}


# ------------------------------------------------------------------ scores --
# Team points for TT, broken down across 5 categories. Every team is seeded
# with all-zero scores at startup (see seed_tt_team_scores), so there's
# nothing to "create" — POST and PATCH both just set whichever category
# fields are given, same as everywhere else in this API. `total` is always
# the sum of the 5 categories and is what feeds the overall leaderboard.

TT_SCORE_COLUMNS = "team_name, mens_singles, mens_doubles, womens_singles, womens_doubles, mixed_doubles, total"


@router.get("/scores", response_model=list[TTTeamScoreEntry])
async def list_tt_scores() -> list[dict]:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(f"SELECT {TT_SCORE_COLUMNS} FROM tt_team_scores ORDER BY team_name;")
            return await cur.fetchall()


@router.get("/scores/{team_name}", response_model=TTTeamScoreEntry)
async def get_tt_score(team_name: str) -> dict:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {TT_SCORE_COLUMNS} FROM tt_team_scores WHERE team_name = %s;",
                (team_name,),
            )
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Team '{team_name}' not found")
    return row


# Set every team's full score row in one request instead of one call per
# team: repeat team_name/mens_singles/mens_doubles/womens_singles/
# womens_doubles/mixed_doubles as form fields, matched up by position — same
# convention as /matches/bulk. Unlike the single-team endpoints below, every
# category is required per team here (there's no "leave the rest alone" for
# a row that's being fully set in a batch). A single multi-row UPDATE does
# the whole batch in one round trip.
#
# Registered before /scores/{team_name} below so FastAPI doesn't match
# "bulk" as a literal team name.
async def _set_tt_scores_bulk(
    team_name: list[str],
    mens_singles: list[int],
    mens_doubles: list[int],
    womens_singles: list[int],
    womens_doubles: list[int],
    mixed_doubles: list[int],
) -> list[dict]:
    lengths = {
        "team_name": len(team_name),
        "mens_singles": len(mens_singles),
        "mens_doubles": len(mens_doubles),
        "womens_singles": len(womens_singles),
        "womens_doubles": len(womens_doubles),
        "mixed_doubles": len(mixed_doubles),
    }
    if len(set(lengths.values())) > 1:
        raise HTTPException(status_code=400, detail=f"all fields must have the same number of entries: {lengths}")

    duplicates = {name for name in team_name if team_name.count(name) > 1}
    if duplicates:
        raise HTTPException(
            status_code=400,
            detail=f"duplicate team_name in request: {', '.join(sorted(duplicates))} — "
            "each team can only appear once per request",
        )

    values_clause = ", ".join(["(%s, %s, %s, %s, %s, %s)"] * len(team_name))
    params = []
    for name, ms, md, ws, wd, mxd in zip(team_name, mens_singles, mens_doubles, womens_singles, womens_doubles, mixed_doubles):
        params.extend([name, ms, md, ws, wd, mxd])

    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                UPDATE tt_team_scores AS t
                SET mens_singles = v.mens_singles,
                    mens_doubles = v.mens_doubles,
                    womens_singles = v.womens_singles,
                    womens_doubles = v.womens_doubles,
                    mixed_doubles = v.mixed_doubles
                FROM (VALUES {values_clause})
                    AS v(team_name, mens_singles, mens_doubles, womens_singles, womens_doubles, mixed_doubles)
                WHERE t.team_name = v.team_name
                RETURNING t.{TT_SCORE_COLUMNS.replace(", ", ", t.")};
                """,
                params,
            )
            rows = await cur.fetchall()

            if len(rows) != len(team_name):
                matched = {row["team_name"] for row in rows}
                unknown = [name for name in team_name if name not in matched]
                await conn.rollback()
                raise HTTPException(
                    status_code=404,
                    detail=f"team_name(s) not found: {', '.join(unknown)} — check for typos against the "
                    "registered team names (see GET /api/tt/scores)",
                )

        await sync_leaderboard_points_bulk(conn, team_name)
        await conn.commit()
    return rows


@router.post("/scores/bulk", response_model=list[TTTeamScoreEntry])
async def set_tt_scores_bulk(
    team_name: list[str] = Form(...),
    mens_singles: list[int] = Form(...),
    mens_doubles: list[int] = Form(...),
    womens_singles: list[int] = Form(...),
    womens_doubles: list[int] = Form(...),
    mixed_doubles: list[int] = Form(...),
) -> list[dict]:
    return await _set_tt_scores_bulk(team_name, mens_singles, mens_doubles, womens_singles, womens_doubles, mixed_doubles)


@router.patch("/scores/bulk", response_model=list[TTTeamScoreEntry])
async def update_tt_scores_bulk(
    team_name: list[str] = Form(...),
    mens_singles: list[int] = Form(...),
    mens_doubles: list[int] = Form(...),
    womens_singles: list[int] = Form(...),
    womens_doubles: list[int] = Form(...),
    mixed_doubles: list[int] = Form(...),
) -> list[dict]:
    return await _set_tt_scores_bulk(team_name, mens_singles, mens_doubles, womens_singles, womens_doubles, mixed_doubles)


async def _set_tt_score(
    team_name: str,
    mens_singles: Optional[int],
    mens_doubles: Optional[int],
    womens_singles: Optional[int],
    womens_doubles: Optional[int],
    mixed_doubles: Optional[int],
) -> dict:
    updates = {
        "mens_singles": mens_singles,
        "mens_doubles": mens_doubles,
        "womens_singles": womens_singles,
        "womens_doubles": womens_doubles,
        "mixed_doubles": mixed_doubles,
    }
    updates = {field: value for field, value in updates.items() if value is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Provide at least one category score to set")

    set_clause = ", ".join(f"{field} = %s" for field in updates)
    params = [*updates.values(), team_name]

    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"UPDATE tt_team_scores SET {set_clause} WHERE team_name = %s RETURNING {TT_SCORE_COLUMNS};",
                params,
            )
            row = await cur.fetchone()
            if row is None:
                await conn.rollback()
                raise HTTPException(
                    status_code=404,
                    detail=f"Team '{team_name}' not found — check for a typo against the registered "
                    "team names (see GET /api/tt/scores)",
                )
        await sync_leaderboard_points(conn, team_name)
        await conn.commit()
    return row


@router.post("/scores/{team_name}", response_model=TTTeamScoreEntry)
async def set_tt_score(
    team_name: str,
    mens_singles: Optional[int] = Form(None),
    mens_doubles: Optional[int] = Form(None),
    womens_singles: Optional[int] = Form(None),
    womens_doubles: Optional[int] = Form(None),
    mixed_doubles: Optional[int] = Form(None),
) -> dict:
    return await _set_tt_score(team_name, mens_singles, mens_doubles, womens_singles, womens_doubles, mixed_doubles)


@router.patch("/scores/{team_name}", response_model=TTTeamScoreEntry)
async def update_tt_score(
    team_name: str,
    mens_singles: Optional[int] = Form(None),
    mens_doubles: Optional[int] = Form(None),
    womens_singles: Optional[int] = Form(None),
    womens_doubles: Optional[int] = Form(None),
    mixed_doubles: Optional[int] = Form(None),
) -> dict:
    return await _set_tt_score(team_name, mens_singles, mens_doubles, womens_singles, womens_doubles, mixed_doubles)
