from typing import Literal

from pydantic import BaseModel

TTCategory = Literal["Mens Singles", "Mens Doubles", "Womens Singles", "Womens Doubles", "Mixed Doubles"]
TTRound = Literal["Round 1", "Round 2", "Round 3", "Semi Finals", "Finals"]

CarromRound = Literal["Round 1", "Round 2", "Semi Finals", "Finals"]


class LeaderboardEntry(BaseModel):
    id: int
    team_name: str
    position: int
    points: int


class EventEntry(BaseModel):
    id: int
    event_name: str


class EventLookupRequest(BaseModel):
    event_name: str


class EventCreateRequest(BaseModel):
    event_name: str


class EventScoreEntry(BaseModel):
    id: int
    team_name: str
    points: int


class TTMatchEntry(BaseModel):
    id: int
    category: TTCategory
    round: TTRound
    player_a: str
    player_b: str
    winner: str


class CarromMatchEntry(BaseModel):
    id: int
    round: CarromRound
    player_a: str
    player_b: str
    winner: str


class TTTeamScoreEntry(BaseModel):
    team_name: str
    mens_singles: int
    mens_doubles: int
    womens_singles: int
    womens_doubles: int
    mixed_doubles: int
    total: int
