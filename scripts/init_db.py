import psycopg

from app.config import settings
from app.db import EVENTS_SCHEMA_SQL, LEADERBOARD_SCHEMA_SQL


def main() -> None:
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute(LEADERBOARD_SCHEMA_SQL)
        conn.execute(EVENTS_SCHEMA_SQL)
    print("leaderboard and events tables ready")


if __name__ == "__main__":
    main()
