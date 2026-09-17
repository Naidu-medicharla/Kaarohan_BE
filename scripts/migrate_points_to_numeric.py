"""
Migration: change all event score 'points' columns and leaderboard 'points'
from INTEGER to NUMERIC(10,2) to support decimal scores like 7.5.
"""
import psycopg

CONN_STR = (
    "postgresql://neondb_owner:npg_lh7VaCb5OGck@ep-falling-poetry-axd67x95-pooler"
    ".c-4.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

# Tables with a plain 'points' column
EVENT_TABLES = [
    "ad_mad",
    "beer_pong",
    "carrom",
    "cooking",
    "ethnic_day",
    "meme",
    "no_trouser_day",
    "post_it_art",
    "red_color_day",
    "retro_day",
    "tallest_tower",
]

with psycopg.connect(CONN_STR, prepare_threshold=None) as conn:
    # Alter every event score table
    for table in EVENT_TABLES:
        conn.execute(
            f"ALTER TABLE {table} ALTER COLUMN points TYPE NUMERIC(10,2);"
        )
        print(f"  altered {table}.points -> NUMERIC(10,2)")

    # Alter leaderboard (aggregates all event + TT scores)
    conn.execute(
        "ALTER TABLE leaderboard ALTER COLUMN points TYPE NUMERIC(10,2);"
    )
    print("  altered leaderboard.points -> NUMERIC(10,2)")

    print("\nMigration complete.")
