from pydantic import BaseModel


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
