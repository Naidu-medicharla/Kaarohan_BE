from fastapi import APIRouter
from psycopg.rows import dict_row

from app.db import get_pool
from app.schemas import LeaderboardEntry

router = APIRouter()

# position is always computed fresh from points (standard competition ranking:
# ties share a rank, e.g. all-zero teams all rank #1) — never read from the
# stored `position` column, so it can never go stale.
RANK_QUERY = """
SELECT id, team_name,
       RANK() OVER (ORDER BY points DESC) AS position,
       points
FROM leaderboard
ORDER BY points DESC, team_name ASC;
"""


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard() -> list[dict]:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(RANK_QUERY)
            return await cur.fetchall()
