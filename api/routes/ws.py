"""WebSocket endpoint for real-time document change notifications.

Replaces Supabase Realtime. The API listens to Postgres NOTIFY on the
'document_changes' channel and pushes events to connected clients.
"""

import asyncio
import json
import logging

import asyncpg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter()


class DocumentWSManager:
    """Tracks WebSocket connections and broadcasts document change events."""

    def __init__(self):
        self._connections: dict[tuple[str, str], set[WebSocket]] = {}

    async def connect(self, user_id: str, kb_id: str, ws: WebSocket):
        key = (user_id, kb_id)
        if key not in self._connections:
            self._connections[key] = set()
        self._connections[key].add(ws)
        logger.debug("WS connected: user=%s kb=%s (%d total)", user_id[:8], kb_id[:8], self._count())

    def disconnect(self, user_id: str, kb_id: str, ws: WebSocket):
        key = (user_id, kb_id)
        if key in self._connections:
            self._connections[key].discard(ws)
            if not self._connections[key]:
                del self._connections[key]

    async def broadcast(self, user_id: str, kb_id: str, event: dict):
        key = (user_id, kb_id)
        conns = self._connections.get(key)
        if not conns:
            return
        snapshot = list(conns)
        dead = []
        for ws in snapshot:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)

    def _count(self) -> int:
        return sum(len(s) for s in self._connections.values())


manager = DocumentWSManager()


async def setup_listener(database_url: str) -> asyncio.Task:
    """Start a supervised Postgres LISTEN loop that reconnects on failure."""

    async def _listen_loop():
        while True:
            conn = None
            try:
                conn = await asyncpg.connect(database_url)

                def on_notify(conn, pid, channel, payload):
                    asyncio.get_running_loop().create_task(_handle_notify(payload))

                await conn.add_listener("document_changes", on_notify)
                logger.info("Postgres LISTEN on 'document_changes' active")

                # Hold the connection open — asyncpg delivers notifications via its
                # internal reader loop. We just need to keep the coroutine alive.
                while True:
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                if conn and not conn.is_closed():
                    await conn.close()
                raise
            except Exception as e:
                logger.warning("LISTEN connection lost (%s), reconnecting in 5s", e)
                if conn and not conn.is_closed():
                    await conn.close()
                await asyncio.sleep(5)

    return asyncio.create_task(_listen_loop())


async def _handle_notify(payload: str) -> None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Bad NOTIFY payload: %s", payload[:100])
        return
    user_id = data.get("user_id")
    kb_id = data.get("knowledge_base_id")
    if user_id and kb_id:
        await manager.broadcast(user_id, kb_id, {
            "event": data.get("event"),
            "id": data.get("id"),
        })


@router.websocket("/v1/ws/documents/{kb_id}")
async def document_ws(websocket: WebSocket, kb_id: str):
    await websocket.accept()

    # First-message auth: client sends the token, we verify before registering.
    # Keeps the JWT out of URLs and logs.
    try:
        token = await asyncio.wait_for(websocket.receive_text(), timeout=5)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=4001, reason="Auth timeout")
        return

    try:
        user_id = await verify_token(token)
    except ValueError:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(user_id, kb_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, kb_id, websocket)
