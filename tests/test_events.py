import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

TEST_EVENT_NAME = "__pytest_smoke_test_event__"


@pytest.fixture
def test_event():
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        row = conn.execute(
            "INSERT INTO events (event_name) VALUES (%s) RETURNING id;",
            (TEST_EVENT_NAME,),
        ).fetchone()
    yield {"id": row[0], "event_name": TEST_EVENT_NAME}
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute("DELETE FROM events WHERE event_name = %s;", (TEST_EVENT_NAME,))


def test_list_events_includes_seeded_event(test_event):
    with TestClient(app) as client:
        response = client.get("/api/events")

    assert response.status_code == 200
    names = [entry["event_name"] for entry in response.json()]
    assert TEST_EVENT_NAME in names


def test_post_lookup_returns_matching_event(test_event):
    with TestClient(app) as client:
        response = client.post("/api/events", json={"event_name": TEST_EVENT_NAME})

    assert response.status_code == 200
    assert response.json() == test_event


def test_post_lookup_missing_event_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/events", json={"event_name": "__definitely_not_a_real_event__"})

    assert response.status_code == 404
