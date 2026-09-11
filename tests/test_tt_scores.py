import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

TEST_TEAM_NAME = "Team Maverick"


@pytest.fixture
def reset_score():
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        prior = conn.execute(
            "SELECT mens_singles, mens_doubles, womens_singles, womens_doubles, mixed_doubles "
            "FROM tt_team_scores WHERE team_name = %s;",
            (TEST_TEAM_NAME,),
        ).fetchone()
        prior_leaderboard_points = conn.execute(
            "SELECT points FROM leaderboard WHERE team_name = %s;", (TEST_TEAM_NAME,)
        ).fetchone()[0]

    yield

    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute(
            "UPDATE tt_team_scores SET mens_singles = %s, mens_doubles = %s, womens_singles = %s, "
            "womens_doubles = %s, mixed_doubles = %s WHERE team_name = %s;",
            (*prior, TEST_TEAM_NAME),
        )
        conn.execute(
            "UPDATE leaderboard SET points = %s WHERE team_name = %s;",
            (prior_leaderboard_points, TEST_TEAM_NAME),
        )


def test_list_scores_includes_all_eight_teams():
    with TestClient(app) as client:
        response = client.get("/api/tt/scores")

    assert response.status_code == 200
    assert len(response.json()) == 8


def test_get_one_team_score(reset_score):
    with TestClient(app) as client:
        response = client.get(f"/api/tt/scores/{TEST_TEAM_NAME}")

    assert response.status_code == 200
    assert response.json()["team_name"] == TEST_TEAM_NAME


def test_get_unknown_team_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/tt/scores/__no_such_team__")

    assert response.status_code == 404


def test_patch_sets_one_category_and_computes_total(reset_score):
    with TestClient(app) as client:
        response = client.patch(f"/api/tt/scores/{TEST_TEAM_NAME}", data={"mens_singles": "10"})

    assert response.status_code == 200
    body = response.json()
    assert body["mens_singles"] == 10
    assert body["total"] == 10


def test_patch_only_changes_provided_categories(reset_score):
    with TestClient(app) as client:
        client.patch(f"/api/tt/scores/{TEST_TEAM_NAME}", data={"mens_singles": "10"})
        response = client.patch(f"/api/tt/scores/{TEST_TEAM_NAME}", data={"womens_doubles": "5"})

    body = response.json()
    assert body["mens_singles"] == 10
    assert body["womens_doubles"] == 5
    assert body["total"] == 15


def test_patch_syncs_leaderboard_total(reset_score):
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        prior_points = conn.execute(
            "SELECT points FROM leaderboard WHERE team_name = %s;", (TEST_TEAM_NAME,)
        ).fetchone()[0]

    with TestClient(app) as client:
        client.patch(f"/api/tt/scores/{TEST_TEAM_NAME}", data={"mens_singles": "7", "mens_doubles": "3"})
        leaderboard_response = client.get("/api/leaderboard")

    entry = next(e for e in leaderboard_response.json() if e["team_name"] == TEST_TEAM_NAME)
    assert entry["points"] == prior_points + 10


def test_patch_unknown_team_returns_404():
    with TestClient(app) as client:
        response = client.patch("/api/tt/scores/__no_such_team__", data={"mens_singles": "10"})

    assert response.status_code == 404


def test_patch_with_no_fields_returns_400(reset_score):
    with TestClient(app) as client:
        response = client.patch(f"/api/tt/scores/{TEST_TEAM_NAME}", data={})

    assert response.status_code == 400


def test_post_behaves_the_same_as_patch(reset_score):
    with TestClient(app) as client:
        response = client.post(f"/api/tt/scores/{TEST_TEAM_NAME}", data={"mixed_doubles": "8"})

    assert response.status_code == 200
    assert response.json()["mixed_doubles"] == 8
