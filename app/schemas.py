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


class SinglesMatchEntry(BaseModel):
    id: int
    match_number: int
    player_a: str
    player_b: str
    winner: str | None


class SinglesMatchCreateRequest(BaseModel):
    player_a: str
    player_b: str


class SinglesWinnerRequest(BaseModel):
    winner: str


class DoublesMatchEntry(BaseModel):
    id: int
    match_number: int
    pair_a_player1: str
    pair_a_player2: str
    pair_b_player1: str
    pair_b_player2: str
    winner_player1: str | None
    winner_player2: str | None


class DoublesMatchCreateRequest(BaseModel):
    pair_a_player1: str
    pair_a_player2: str
    pair_b_player1: str
    pair_b_player2: str


class DoublesWinnerRequest(BaseModel):
    winner_player1: str
    winner_player2: str
