import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def singles_match():
    with TestClient(app) as client:
        response = client.post(
            "/api/tt/singles/create",
            json={"player_a": "__Test Player A__", "player_b": "__Test Player B__"},
        )
    assert response.status_code == 201
    match = response.json()
    yield match
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute("DELETE FROM tt_mens_singles WHERE id = %s;", (match["id"],))


@pytest.fixture
def doubles_match():
    with TestClient(app) as client:
        response = client.post(
            "/api/tt/doubles/create",
            json={
                "pair_a_player1": "__Test P1__",
                "pair_a_player2": "__Test P2__",
                "pair_b_player1": "__Test P3__",
                "pair_b_player2": "__Test P4__",
            },
        )
    assert response.status_code == 201
    match = response.json()
    yield match
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute("DELETE FROM tt_mens_doubles WHERE id = %s;", (match["id"],))


def test_new_singles_match_has_no_winner(singles_match):
    assert singles_match["winner"] is None

    with TestClient(app) as client:
        response = client.get("/api/tt/singles")

    entry = next(m for m in response.json() if m["id"] == singles_match["id"])
    assert entry["winner"] is None


def test_set_singles_winner(singles_match):
    with TestClient(app) as client:
        response = client.post(
            f"/api/tt/singles/{singles_match['id']}/winner",
            json={"winner": "__Test Player A__"},
        )

    assert response.status_code == 200
    assert response.json()["winner"] == "__Test Player A__"


def test_patch_singles_winner_corrects_it(singles_match):
    with TestClient(app) as client:
        client.post(f"/api/tt/singles/{singles_match['id']}/winner", json={"winner": "__Test Player A__"})
        response = client.patch(
            f"/api/tt/singles/{singles_match['id']}/winner",
            json={"winner": "__Test Player B__"},
        )

    assert response.status_code == 200
    assert response.json()["winner"] == "__Test Player B__"


def test_set_singles_winner_with_unknown_name_returns_400(singles_match):
    with TestClient(app) as client:
        response = client.post(
            f"/api/tt/singles/{singles_match['id']}/winner",
            json={"winner": "__Someone Else__"},
        )

    assert response.status_code == 400


def test_set_singles_winner_for_unknown_match_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/tt/singles/999999/winner", json={"winner": "Anyone"})

    assert response.status_code == 404


def test_new_doubles_match_has_no_winner(doubles_match):
    assert doubles_match["winner_player1"] is None
    assert doubles_match["winner_player2"] is None


def test_set_doubles_winner(doubles_match):
    with TestClient(app) as client:
        response = client.post(
            f"/api/tt/doubles/{doubles_match['id']}/winner",
            json={"winner_player1": "__Test P1__", "winner_player2": "__Test P2__"},
        )

    assert response.status_code == 200
    body = response.json()
    assert {body["winner_player1"], body["winner_player2"]} == {"__Test P1__", "__Test P2__"}


def test_set_doubles_winner_order_independent(doubles_match):
    # Same pair, names given in the opposite order — should still match pair_b.
    with TestClient(app) as client:
        response = client.post(
            f"/api/tt/doubles/{doubles_match['id']}/winner",
            json={"winner_player1": "__Test P4__", "winner_player2": "__Test P3__"},
        )

    assert response.status_code == 200


def test_patch_doubles_winner_corrects_it(doubles_match):
    with TestClient(app) as client:
        client.post(
            f"/api/tt/doubles/{doubles_match['id']}/winner",
            json={"winner_player1": "__Test P1__", "winner_player2": "__Test P2__"},
        )
        response = client.patch(
            f"/api/tt/doubles/{doubles_match['id']}/winner",
            json={"winner_player1": "__Test P3__", "winner_player2": "__Test P4__"},
        )

    assert response.status_code == 200
    body = response.json()
    assert {body["winner_player1"], body["winner_player2"]} == {"__Test P3__", "__Test P4__"}


def test_set_doubles_winner_with_unknown_pair_returns_400(doubles_match):
    with TestClient(app) as client:
        response = client.post(
            f"/api/tt/doubles/{doubles_match['id']}/winner",
            json={"winner_player1": "__Test P1__", "winner_player2": "__Test P3__"},
        )

    assert response.status_code == 400


def test_set_doubles_winner_for_unknown_match_returns_404():
    with TestClient(app) as client:
        response = client.post(
            "/api/tt/doubles/999999/winner",
            json={"winner_player1": "A", "winner_player2": "B"},
        )

    assert response.status_code == 404
