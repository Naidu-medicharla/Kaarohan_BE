import psycopg

from app.config import settings
from app.db import SCHEMA_SQL


def main() -> None:
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute(SCHEMA_SQL)
    print("leaderboard table ready")


if __name__ == "__main__":
    main()
