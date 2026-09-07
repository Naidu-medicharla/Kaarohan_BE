from fastapi.testclient import TestClient

from app.main import app

EXPECTED_TEAM_NAMES = {
    "Keyboard Smashers",
    "La Mafia Corporativa",
    "Team Maverick",
    "Dookudu",
    "Unemployed Avengers",
    "Team Dhurandhars",
    "Team Zenith",
    "Infinity Squad",
}


def test_leaderboard_returns_all_teams():
    with TestClient(app) as client:
        response = client.get("/api/leaderboard")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 8
    assert {entry["team_name"] for entry in body} == EXPECTED_TEAM_NAMES


def test_tied_points_share_the_same_position():
    with TestClient(app) as client:
        response = client.get("/api/leaderboard")

    body = response.json()
    points_to_positions = {}
    for entry in body:
        points_to_positions.setdefault(entry["points"], set()).add(entry["position"])

    for positions in points_to_positions.values():
        assert len(positions) == 1
