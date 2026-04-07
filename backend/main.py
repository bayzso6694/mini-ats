import asyncio
import json
import os
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from database import Base, engine
from realtime import manager
from routers.candidates import router as candidates_router
from routers.jobs import router as jobs_router

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
PUBSUB_CHANNEL = os.getenv("RANKING_CHANNEL", "ranking_updates")


def ensure_schema_updates() -> None:
    # Lightweight safety migration for existing Docker volumes.
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE candidates "
                "ADD COLUMN IF NOT EXISTS shortlist_status VARCHAR(20) NOT NULL DEFAULT 'none'"
            )
        )


async def redis_listener(stop_event: asyncio.Event) -> None:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(PUBSUB_CHANNEL)
    try:
        while not stop_event.is_set():
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message:
                await asyncio.sleep(0.05)
                continue
            try:
                payload = json.loads(message["data"])
                job_id = int(payload.get("job_id"))
            except Exception:
                continue
            await manager.broadcast(job_id, payload)
    finally:
        await pubsub.unsubscribe(PUBSUB_CHANNEL)
        await pubsub.close()
        await client.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema_updates()

    stop_event = asyncio.Event()
    listener_task = asyncio.create_task(redis_listener(stop_event))
    app.state.listener_stop_event = stop_event
    app.state.listener_task = listener_task

    yield

    stop_event.set()
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Mini ATS API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(candidates_router)


@app.get("/")
def health():
    return {"status": "ok", "service": "mini-ats-backend"}


@app.websocket("/ws/{job_id}")
async def websocket_rankings(websocket: WebSocket, job_id: int):
    await manager.connect(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(job_id, websocket)
    except Exception:
        await manager.disconnect(job_id, websocket)
