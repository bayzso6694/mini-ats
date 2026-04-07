import asyncio
import json
from collections import defaultdict
from typing import DefaultDict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: DefaultDict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, job_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections[job_id].add(websocket)

    async def disconnect(self, job_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            if job_id in self.active_connections:
                self.active_connections[job_id].discard(websocket)
                if not self.active_connections[job_id]:
                    del self.active_connections[job_id]

    async def broadcast(self, job_id: int, payload: dict) -> None:
        message = json.dumps(payload)
        async with self._lock:
            clients = list(self.active_connections.get(job_id, set()))

        disconnected: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        if disconnected:
            async with self._lock:
                for ws in disconnected:
                    self.active_connections[job_id].discard(ws)


manager = ConnectionManager()
