from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_pool, ensure_schema, open_pool
from app.routers.events import router as events_router
from app.routers.leaderboard import router as leaderboard_router
from app.routers.scores import router as scores_router
from app.routers.tt import router as tt_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    await ensure_schema()
    yield
    await close_pool()


app = FastAPI(title="Kaarohan 2026 Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

app.include_router(leaderboard_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(scores_router, prefix="/api")
app.include_router(tt_router, prefix="/api")


@app.get("/")
async def health() -> dict:
    return {"status": "ok"}
