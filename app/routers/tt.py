from fastapi import APIRouter, HTTPException
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.db import get_pool
from app.schemas import (
    DoublesMatchCreateRequest,
    DoublesMatchEntry,
    DoublesWinnerRequest,
    SinglesMatchCreateRequest,
    SinglesMatchEntry,
    SinglesWinnerRequest,
)

router = APIRouter(prefix="/tt")


async def _next_match_number(conn: AsyncConnection, table: str) -> int:
    row = await (await conn.execute(f"SELECT COALESCE(MAX(match_number), 0) + 1 FROM {table};")).fetchone()
    return row[0]


# ---------------------------------------------------------------- singles --


@router.get("/singles", response_model=list[SinglesMatchEntry])
async def list_singles_matches() -> list[dict]:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, match_number, player_a, player_b, winner FROM tt_mens_singles ORDER BY match_number;"
            )
            return await cur.fetchall()


@router.post("/singles/create", response_model=SinglesMatchEntry, status_code=201)
async def create_singles_match(payload: SinglesMatchCreateRequest) -> dict:
    async with get_pool().connection() as conn:
        match_number = await _next_match_number(conn, "tt_mens_singles")
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO tt_mens_singles (match_number, player_a, player_b)
                VALUES (%s, %s, %s)
                RETURNING id, match_number, player_a, player_b, winner;
                """,
                (match_number, payload.player_a, payload.player_b),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row


async def _set_singles_winner(match_id: int, winner: str) -> dict:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT player_a, player_b FROM tt_mens_singles WHERE id = %s;", (match_id,)
            )
            match = await cur.fetchone()
            if match is None:
                raise HTTPException(status_code=404, detail=f"Singles match {match_id} not found")
            if winner not in (match["player_a"], match["player_b"]):
                raise HTTPException(
                    status_code=400,
                    detail=f"'{winner}' is not a player in this match "
                    f"(expected '{match['player_a']}' or '{match['player_b']}')",
                )
            await cur.execute(
                "UPDATE tt_mens_singles SET winner = %s WHERE id = %s "
                "RETURNING id, match_number, player_a, player_b, winner;",
                (winner, match_id),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row


@router.post("/singles/{match_id}/winner", response_model=SinglesMatchEntry)
async def set_singles_winner(match_id: int, payload: SinglesWinnerRequest) -> dict:
    return await _set_singles_winner(match_id, payload.winner)


@router.patch("/singles/{match_id}/winner", response_model=SinglesMatchEntry)
async def update_singles_winner(match_id: int, payload: SinglesWinnerRequest) -> dict:
    return await _set_singles_winner(match_id, payload.winner)


# ---------------------------------------------------------------- doubles --


@router.get("/doubles", response_model=list[DoublesMatchEntry])
async def list_doubles_matches() -> list[dict]:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT id, match_number, pair_a_player1, pair_a_player2,
                       pair_b_player1, pair_b_player2, winner_player1, winner_player2
                FROM tt_mens_doubles ORDER BY match_number;
                """
            )
            return await cur.fetchall()


@router.post("/doubles/create", response_model=DoublesMatchEntry, status_code=201)
async def create_doubles_match(payload: DoublesMatchCreateRequest) -> dict:
    async with get_pool().connection() as conn:
        match_number = await _next_match_number(conn, "tt_mens_doubles")
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO tt_mens_doubles
                    (match_number, pair_a_player1, pair_a_player2, pair_b_player1, pair_b_player2)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, match_number, pair_a_player1, pair_a_player2,
                          pair_b_player1, pair_b_player2, winner_player1, winner_player2;
                """,
                (
                    match_number,
                    payload.pair_a_player1,
                    payload.pair_a_player2,
                    payload.pair_b_player1,
                    payload.pair_b_player2,
                ),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row


async def _set_doubles_winner(match_id: int, winner_player1: str, winner_player2: str) -> dict:
    winning_set = {winner_player1, winner_player2}
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT pair_a_player1, pair_a_player2, pair_b_player1, pair_b_player2 "
                "FROM tt_mens_doubles WHERE id = %s;",
                (match_id,),
            )
            match = await cur.fetchone()
            if match is None:
                raise HTTPException(status_code=404, detail=f"Doubles match {match_id} not found")

            pair_a = {match["pair_a_player1"], match["pair_a_player2"]}
            pair_b = {match["pair_b_player1"], match["pair_b_player2"]}
            if winning_set != pair_a and winning_set != pair_b:
                raise HTTPException(
                    status_code=400,
                    detail=f"{sorted(winning_set)} is not one of this match's two pairs "
                    f"(expected {sorted(pair_a)} or {sorted(pair_b)})",
                )

            await cur.execute(
                "UPDATE tt_mens_doubles SET winner_player1 = %s, winner_player2 = %s WHERE id = %s "
                "RETURNING id, match_number, pair_a_player1, pair_a_player2, "
                "pair_b_player1, pair_b_player2, winner_player1, winner_player2;",
                (winner_player1, winner_player2, match_id),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row


@router.post("/doubles/{match_id}/winner", response_model=DoublesMatchEntry)
async def set_doubles_winner(match_id: int, payload: DoublesWinnerRequest) -> dict:
    return await _set_doubles_winner(match_id, payload.winner_player1, payload.winner_player2)


@router.patch("/doubles/{match_id}/winner", response_model=DoublesMatchEntry)
async def update_doubles_winner(match_id: int, payload: DoublesWinnerRequest) -> dict:
    return await _set_doubles_winner(match_id, payload.winner_player1, payload.winner_player2)
