"""WebSocket push of Postgres NOTIFY 'document_changes' events to connected clients."""

import asyncio
import json
import logging
import uuid

import asyncpg
from auth import verify_token
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

WS_CLOSE_AUTH = 4001
WS_CLOSE_FORBIDDEN = 4003


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
            except Exception:  # noqa: BLE001 - any send failure means this socket is dead.
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)

    def _count(self) -> int:
        return sum(len(s) for s in self._connections.values())


manager = DocumentWSManager()

# Short enough that the pooler never idle-kills LISTEN and a dead socket surfaces within seconds.
KEEPALIVE_SECONDS = 30
RECONNECT_DELAY_SECONDS = 5


async def setup_listener(database_url: str) -> asyncio.Task:
    """Start a supervised Postgres LISTEN loop that reconnects on failure."""
    return asyncio.create_task(_supervise_listener(database_url))


async def _supervise_listener(database_url: str) -> None:
    """Reconnect forever around a single LISTEN connection's lifetime."""
    while True:
        try:
            await _listen_until_closed(database_url)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - listener supervision must recover from any asyncpg/socket failure.
            logger.warning("LISTEN connection lost (%s), reconnecting in %ds", e, RECONNECT_DELAY_SECONDS)
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


async def _listen_until_closed(database_url: str) -> None:
    """Hold one LISTEN connection open, pinging it so it stays alive and a drop surfaces."""
    conn = await asyncpg.connect(database_url)
    try:
        await conn.add_listener("document_changes", _on_notify)
        logger.info("Postgres LISTEN on 'document_changes' active")
        while True:
            await asyncio.sleep(KEEPALIVE_SECONDS)
            await conn.execute("SELECT 1")
    finally:
        if not conn.is_closed():
            await conn.close()


def _on_notify(conn: asyncpg.Connection, pid: int, channel: str, payload: str) -> None:
    asyncio.get_running_loop().create_task(_handle_notify(payload))


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


async def _kb_owned_by_user(websocket: WebSocket, user_id: str, kb_id: str) -> bool:
    pool = getattr(websocket.app.state, "pool", None)
    if pool is None:
        logger.warning("Rejecting WS connection without hosted DB pool")
        return False
    try:
        uuid.UUID(kb_id)
        uuid.UUID(user_id)
        return bool(await pool.fetchval(
            "SELECT 1 FROM knowledge_bases "
            "WHERE id = $1::uuid AND user_id = $2::uuid",
            kb_id,
            user_id,
        ))
    except (ValueError, asyncpg.PostgresError):
        logger.warning(
            "Rejecting WS connection for invalid kb/user scope: user=%s kb=%s",
            user_id[:8],
            kb_id[:8],
        )
        return False


@router.websocket("/v1/ws/documents/{kb_id}")
async def document_ws(websocket: WebSocket, kb_id: str):
    await websocket.accept()

    # Token arrives as the first message to keep the JWT out of URLs and logs.
    try:
        token = await asyncio.wait_for(websocket.receive_text(), timeout=5)
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=WS_CLOSE_AUTH, reason="Auth timeout")
        return

    try:
        user_id = await verify_token(token)
    except ValueError:
        await websocket.close(code=WS_CLOSE_AUTH, reason="Invalid token")
        return

    if not await _kb_owned_by_user(websocket, user_id, kb_id):
        await websocket.close(code=WS_CLOSE_FORBIDDEN, reason="Forbidden")
        return

    await manager.connect(user_id, kb_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, kb_id, websocket)
