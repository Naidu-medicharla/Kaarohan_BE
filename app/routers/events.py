from fastapi import APIRouter, HTTPException
from psycopg import errors
from psycopg.rows import dict_row

from app.db import create_event_score_table, get_pool
from app.schemas import EventCreateRequest, EventEntry, EventLookupRequest

router = APIRouter()

LIST_QUERY = "SELECT id, event_name FROM events ORDER BY id;"
LOOKUP_QUERY = "SELECT id, event_name FROM events WHERE event_name = %s;"
INSERT_QUERY = "INSERT INTO events (event_name) VALUES (%s) RETURNING id, event_name;"


@router.get("/events", response_model=list[EventEntry])
async def list_events() -> list[dict]:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(LIST_QUERY)
            return await cur.fetchall()


@router.post("/events", response_model=EventEntry)
async def get_event_details(payload: EventLookupRequest) -> dict:
    async with get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(LOOKUP_QUERY, (payload.event_name,))
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Event '{payload.event_name}' not found")
    return row


@router.post("/events/create", response_model=EventEntry, status_code=201)
async def create_event(payload: EventCreateRequest) -> dict:
    async with get_pool().connection() as conn:
        try:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(INSERT_QUERY, (payload.event_name,))
                row = await cur.fetchone()
            await create_event_score_table(conn, row["event_name"])
            await conn.commit()
        except errors.UniqueViolation:
            await conn.rollback()
            raise HTTPException(status_code=409, detail=f"Event '{payload.event_name}' already exists")
        except ValueError as exc:
            await conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
    return row
