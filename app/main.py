from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_pool, ensure_schema, open_pool
from app.routers.leaderboard import router as leaderboard_router


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
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(leaderboard_router, prefix="/api")


@app.get("/")
async def health() -> dict:
    return {"status": "ok"}
