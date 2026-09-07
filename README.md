# Kaarohan Backend

FastAPI backend for the Kaarohan 2026 event site's leaderboard, backed by Neon Postgres. This is a separate repo from the frontend (`../kaarohan`).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes requirements.txt + pytest/httpx
```

Copy `.env.example` to `.env` and fill in the real Neon connection string:

```bash
cp .env.example .env
```

`DATABASE_URL` should be the Neon connection string (pooled `-pooler` endpoint is fine — `app/db.py` disables psycopg3's auto-prepared statements so it stays compatible with PgBouncer transaction pooling).

## Create the table and seed the 8 teams

```bash
python -m scripts.init_db   # CREATE TABLE IF NOT EXISTS leaderboard
python -m scripts.seed      # idempotent insert of the 8 teams, safe to re-run
```

## Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

Then:

```bash
curl http://localhost:8000/api/leaderboard
```

`position` is always computed fresh from `points` at request time (SQL `RANK()` — standard competition ranking, so tied teams share a rank). It is never read from the stored `position` column, which only exists to satisfy the table schema and starts at its default value.

## Tests

```bash
pytest -q
```

The smoke suite runs against the live dev database configured in `.env` (no test DB isolation yet — fine at this scale, worth revisiting if the suite grows).

## Roadmap

Score entry (writing `points`) isn't built yet. A future `PATCH /api/leaderboard/{team_name}` endpoint can drop in cleanly on top of this schema (`UPDATE leaderboard SET points = %s WHERE team_name = %s`), using the existing `UNIQUE(team_name)` constraint — no migration needed for it.
