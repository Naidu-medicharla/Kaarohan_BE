import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def match():
    with TestClient(app) as client:
        response = client.post(
            "/api/carrom/matches",
            data={
                "round": "Round 1",
                "player_a": "__Test Player A__",
                "player_b": "__Test Player B__",
            },
        )
    assert response.status_code == 201
    created = response.json()
    yield created
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute("DELETE FROM carrom_matches WHERE id = %s;", (created["id"],))


def test_new_match_defaults_to_not_started(match):
    assert match["winner"] == "NOT STARTED"
    assert match["round"] == "Round 1"


def test_list_matches_includes_created_match(match):
    with TestClient(app) as client:
        response = client.get("/api/carrom/matches")

    entry = next(m for m in response.json() if m["id"] == match["id"])
    assert entry == match


def test_list_matches_filters_by_round(match):
    with TestClient(app) as client:
        same_round = client.get("/api/carrom/matches", params={"round": "Round 1"})
        other_round = client.get("/api/carrom/matches", params={"round": "Round 2"})

    assert any(m["id"] == match["id"] for m in same_round.json())
    assert all(m["id"] != match["id"] for m in other_round.json())


def test_patch_sets_winner_as_free_text(match):
    with TestClient(app) as client:
        response = client.patch(f"/api/carrom/matches/{match['id']}", data={"winner": "__Test Player A__"})

    assert response.status_code == 200
    assert response.json()["winner"] == "__Test Player A__"


def test_patch_only_changes_provided_fields(match):
    with TestClient(app) as client:
        response = client.patch(f"/api/carrom/matches/{match['id']}", data={"round": "Semi Finals"})

    body = response.json()
    assert body["round"] == "Semi Finals"
    assert body["player_a"] == match["player_a"]
    assert body["player_b"] == match["player_b"]


def test_patch_with_no_fields_returns_400(match):
    with TestClient(app) as client:
        response = client.patch(f"/api/carrom/matches/{match['id']}", data={})

    assert response.status_code == 400


def test_patch_unknown_match_returns_404():
    with TestClient(app) as client:
        response = client.patch("/api/carrom/matches/999999", data={"winner": "Anyone"})

    assert response.status_code == 404


def test_round_3_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/carrom/matches",
            data={
                "round": "Round 3",
                "player_a": "__Test Player A__",
                "player_b": "__Test Player B__",
            },
        )

    assert response.status_code == 422
