import psycopg

from app.config import settings
from app.db import SCHEMA_SQL

# Exact spellings from the frontend's src/content/teams.json (authoritative,
# already live on the site) — not the typo'd names typed in chat.
TEAM_NAMES = [
    "Keyboard Smashers",
    "La Mafia Corporativa",
    "Team Maverick",
    "Dookudu",
    "Unemployed Avengers",
    "Team Dhurandhars",
    "Team Zenith",
    "Infinity Squad",
]

INSERT_SQL = """
INSERT INTO leaderboard (team_name) VALUES (%s)
ON CONFLICT (team_name) DO NOTHING;
"""


def main() -> None:
    with psycopg.connect(settings.database_url, prepare_threshold=None) as conn:
        conn.execute(SCHEMA_SQL)
        for team_name in TEAM_NAMES:
            conn.execute(INSERT_SQL, (team_name,))
    print(f"seeded {len(TEAM_NAMES)} teams (existing rows left untouched)")


if __name__ == "__main__":
    main()
