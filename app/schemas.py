from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    id: int
    team_name: str
    position: int
    points: int
