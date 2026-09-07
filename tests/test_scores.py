import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import event_table_slug
from app.main import app

TEST_EVENT_NAME = "__pytest_smoke_test_event__"
TEST_TEAM_NAME = "Team Maverick"
OTHER_TEAM_NAME = "Dookudu"


@pytest.fixture
def test_event():
    with TestClient(app) as client:
        response = client.post("/api/events/create", json={"event_name": TEST_EVENT_NAME})
    assert response.status_code == 201
    event = response.json()

    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        prior_points = dict(
            conn.execute(
                "SELECT team_name, points FROM leaderboard WHERE team_name IN (%s, %s);",
                (TEST_TEAM_NAME, OTHER_TEAM_NAME),
            ).fetchall()
        )

    # Other real events already contribute non-zero points to these teams'
    # leaderboard totals, so tests must assert against prior + delta, never
    # against the test event's raw points value.
    event["prior_points"] = prior_points

    yield event

    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute(f'DROP TABLE IF EXISTS "{event_table_slug(TEST_EVENT_NAME)}";')
        conn.execute("DELETE FROM events WHERE id = %s;", (event["id"],))
        for team_name, points in prior_points.items():
            conn.execute(
                "UPDATE leaderboard SET points = %s WHERE team_name = %s;",
                (points, team_name),
            )


def test_new_event_seeds_all_teams_at_zero(test_event):
    with TestClient(app) as client:
        response = client.get(f"/api/score/{test_event['id']}")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 8
    assert all(entry["points"] == 0 for entry in body)


def test_post_single_team_sets_score_and_syncs_leaderboard(test_event):
    with TestClient(app) as client:
        post_response = client.post(
            f"/api/{test_event['id']}/score",
            data={"team_name": TEST_TEAM_NAME, "points": "10"},
        )
        leaderboard_response = client.get("/api/leaderboard")

    assert post_response.status_code == 200
    body = post_response.json()
    assert len(body) == 1
    assert body[0]["points"] == 10

    entry = next(e for e in leaderboard_response.json() if e["team_name"] == TEST_TEAM_NAME)
    assert entry["points"] == test_event["prior_points"][TEST_TEAM_NAME] + 10


def test_post_bulk_multiple_teams_in_one_request(test_event):
    with TestClient(app) as client:
        post_response = client.post(
            f"/api/{test_event['id']}/score",
            data={"team_name": [TEST_TEAM_NAME, OTHER_TEAM_NAME], "points": ["10", "20"]},
        )
        scores_response = client.get(f"/api/score/{test_event['id']}")

    assert post_response.status_code == 200
    body = post_response.json()
    assert len(body) == 2

    scores = {e["team_name"]: e["points"] for e in scores_response.json()}
    assert scores[TEST_TEAM_NAME] == 10
    assert scores[OTHER_TEAM_NAME] == 20


def test_patch_updates_score_and_syncs_leaderboard(test_event):
    with TestClient(app) as client:
        client.post(f"/api/{test_event['id']}/score", data={"team_name": TEST_TEAM_NAME, "points": "10"})
        patch_response = client.patch(
            f"/api/{test_event['id']}/score",
            data={"team_name": TEST_TEAM_NAME, "points": "25"},
        )
        leaderboard_response = client.get("/api/leaderboard")

    assert patch_response.status_code == 200
    assert patch_response.json()[0]["points"] == 25

    entry = next(e for e in leaderboard_response.json() if e["team_name"] == TEST_TEAM_NAME)
    assert entry["points"] == test_event["prior_points"][TEST_TEAM_NAME] + 25


def test_unknown_team_name_returns_404_and_applies_nothing(test_event):
    with TestClient(app) as client:
        response = client.post(
            f"/api/{test_event['id']}/score",
            # "Team Mavrick" is a typo — not one of the 8 real teams
            data={"team_name": [TEST_TEAM_NAME, "Team Mavrick"], "points": ["50", "5"]},
        )
        scores_response = client.get(f"/api/score/{test_event['id']}")

    assert response.status_code == 404
    # atomic: the valid team_name earlier in the same batch must NOT have been applied
    scores = {e["team_name"]: e["points"] for e in scores_response.json()}
    assert scores[TEST_TEAM_NAME] == 0


def test_duplicate_team_name_in_one_request_returns_400(test_event):
    with TestClient(app) as client:
        response = client.post(
            f"/api/{test_event['id']}/score",
            data={"team_name": [TEST_TEAM_NAME, TEST_TEAM_NAME], "points": ["10", "20"]},
        )

    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_mismatched_team_name_and_points_counts_returns_400(test_event):
    with TestClient(app) as client:
        response = client.post(
            f"/api/{test_event['id']}/score",
            data={"team_name": [TEST_TEAM_NAME, OTHER_TEAM_NAME], "points": ["10"]},
        )

    assert response.status_code == 400


def test_get_score_for_unknown_event_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/score/999999")

    assert response.status_code == 404


def test_create_duplicate_event_returns_409(test_event):
    with TestClient(app) as client:
        response = client.post("/api/events/create", json={"event_name": TEST_EVENT_NAME})

    assert response.status_code == 409
