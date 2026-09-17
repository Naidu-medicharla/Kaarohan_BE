import psycopg

CONN_STR = (
    "postgresql://neondb_owner:npg_lh7VaCb5OGck@ep-falling-poetry-axd67x95-pooler"
    ".c-4.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

with psycopg.connect(CONN_STR, prepare_threshold=None) as conn:
    rows = conn.execute("SELECT id, event_name FROM events ORDER BY id;").fetchall()
    print("Events:")
    for r in rows:
        print(f"  id={r[0]}  name={r[1]}")
