"""WebSocket tenant isolation tests.

Proves that document change events are never leaked across tenants.
The broadcast key is (user_id, kb_id) — both must match for delivery.
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, patch

from tests.helpers.jwt import make_token, seed_jwks_cache
from tests.integration.isolation.conftest import (
    USER_A_ID, USER_B_ID,
    KB_A_ID, KB_B_ID,
)


def _import_ws():
    """Lazy import to avoid sys.path collision with mcp/auth.py."""
    from routes.ws import DocumentWSManager, _handle_notify
    return DocumentWSManager, _handle_notify

_EVENT = {"event": "UPDATE", "id": "doc-123"}


class TestBroadcastIsolation:
    """Unit tests for DocumentWSManager — no DB or HTTP needed."""

    @pytest.fixture
    def manager(self):
        DocumentWSManager, _ = _import_ws()
        return DocumentWSManager()

    def _mock_ws(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    async def test_event_reaches_matching_connection(self, manager):
        ws = self._mock_ws()
        await manager.connect(USER_A_ID, str(KB_A_ID), ws)
        await manager.broadcast(USER_A_ID, str(KB_A_ID), _EVENT)
        ws.send_json.assert_called_once_with(_EVENT)

    async def test_event_does_not_cross_users(self, manager):
        ws_alice = self._mock_ws()
        ws_bob = self._mock_ws()
        await manager.connect(USER_A_ID, str(KB_A_ID), ws_alice)
        await manager.connect(USER_B_ID, str(KB_B_ID), ws_bob)

        await manager.broadcast(USER_A_ID, str(KB_A_ID), _EVENT)

        ws_alice.send_json.assert_called_once()
        ws_bob.send_json.assert_not_called()

    async def test_event_does_not_cross_kbs_same_user(self, manager):
        ws_kb_a = self._mock_ws()
        ws_kb_b = self._mock_ws()
        await manager.connect(USER_A_ID, str(KB_A_ID), ws_kb_a)
        await manager.connect(USER_A_ID, str(KB_B_ID), ws_kb_b)

        await manager.broadcast(USER_A_ID, str(KB_A_ID), _EVENT)

        ws_kb_a.send_json.assert_called_once()
        ws_kb_b.send_json.assert_not_called()

    async def test_subscribing_to_other_users_kb_receives_nothing(self, manager):
        """Alice subscribes to Bob's KB ID — she should never receive Bob's events."""
        ws_alice = self._mock_ws()
        await manager.connect(USER_A_ID, str(KB_B_ID), ws_alice)

        # Bob's document changes in Bob's KB
        await manager.broadcast(USER_B_ID, str(KB_B_ID), _EVENT)

        # Alice's connection is keyed (user_a, kb_b), event is for (user_b, kb_b) — no match
        ws_alice.send_json.assert_not_called()

    async def test_bidirectional_isolation(self, manager):
        """Events for Alice don't reach Bob, and vice versa."""
        ws_alice = self._mock_ws()
        ws_bob = self._mock_ws()
        await manager.connect(USER_A_ID, str(KB_A_ID), ws_alice)
        await manager.connect(USER_B_ID, str(KB_B_ID), ws_bob)

        await manager.broadcast(USER_B_ID, str(KB_B_ID), {"event": "INSERT", "id": "bob-doc"})
        ws_alice.send_json.assert_not_called()
        ws_bob.send_json.assert_called_once()

        ws_bob.send_json.reset_mock()

        await manager.broadcast(USER_A_ID, str(KB_A_ID), {"event": "DELETE", "id": "alice-doc"})
        ws_alice.send_json.assert_called_once()
        ws_bob.send_json.assert_not_called()

    async def test_multiple_connections_same_tenant(self, manager):
        """Multiple tabs for the same user+kb all receive the event."""
        ws1 = self._mock_ws()
        ws2 = self._mock_ws()
        await manager.connect(USER_A_ID, str(KB_A_ID), ws1)
        await manager.connect(USER_A_ID, str(KB_A_ID), ws2)

        await manager.broadcast(USER_A_ID, str(KB_A_ID), _EVENT)

        ws1.send_json.assert_called_once_with(_EVENT)
        ws2.send_json.assert_called_once_with(_EVENT)

    async def test_disconnect_stops_delivery(self, manager):
        ws = self._mock_ws()
        await manager.connect(USER_A_ID, str(KB_A_ID), ws)
        manager.disconnect(USER_A_ID, str(KB_A_ID), ws)

        await manager.broadcast(USER_A_ID, str(KB_A_ID), _EVENT)
        ws.send_json.assert_not_called()

    async def test_dead_connection_cleaned_on_broadcast(self, manager):
        ws_dead = self._mock_ws()
        ws_dead.send_json.side_effect = RuntimeError("connection closed")
        ws_alive = self._mock_ws()
        await manager.connect(USER_A_ID, str(KB_A_ID), ws_dead)
        await manager.connect(USER_A_ID, str(KB_A_ID), ws_alive)

        await manager.broadcast(USER_A_ID, str(KB_A_ID), _EVENT)

        ws_alive.send_json.assert_called_once()
        assert manager._count() == 1

    async def test_no_connections_broadcast_is_noop(self, manager):
        # Should not raise
        await manager.broadcast(USER_A_ID, str(KB_A_ID), _EVENT)


class TestWebSocketAuth:
    """Integration tests for WebSocket authentication flow."""

    @pytest.fixture
    def ws_client(self, pool):
        from starlette.testclient import TestClient
        from main import app
        from services.hosted import HostedServiceFactory

        app.state.pool = pool
        app.state.s3_service = None
        app.state.ocr_service = None
        app.state.auth_provider = None
        app.state.factory = HostedServiceFactory(pool)
        seed_jwks_cache()
        return TestClient(app)

    def test_valid_token_connects_and_stays_open(self, ws_client):
        """Valid token should authenticate and keep the connection open."""
        from starlette.websockets import WebSocketDisconnect
        token = make_token(USER_A_ID)
        with ws_client.websocket_connect(f"/v1/ws/documents/{KB_A_ID}") as ws:
            ws.send_text(token)
            # After auth, the server enters a receive loop. Sending another
            # message should NOT raise — proving the connection stayed open.
            ws.send_text("ping")
            ws.close()

    def test_invalid_token_rejected_with_4001(self, ws_client):
        """Garbage token should close the connection with code 4001."""
        from starlette.websockets import WebSocketDisconnect
        with ws_client.websocket_connect(f"/v1/ws/documents/{KB_A_ID}") as ws:
            ws.send_text("garbage-token")
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == 4001

    def test_wrong_audience_rejected_with_4001(self, ws_client):
        """Token with wrong audience should close the connection with code 4001."""
        from starlette.websockets import WebSocketDisconnect
        token = make_token(USER_A_ID, aud="wrong-audience")
        with ws_client.websocket_connect(f"/v1/ws/documents/{KB_A_ID}") as ws:
            ws.send_text(token)
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == 4001


class TestNotifyTriggerPayload:
    """Verify the Postgres NOTIFY trigger includes correct tenant identifiers.

    Tests the real trigger function (from 003_document_notify.sql) to ensure
    the payload includes user_id and knowledge_base_id for tenant-scoped routing.
    """

    @pytest.fixture
    async def notify_listener(self, pool):
        """Listen on document_changes and yield an asyncio.Queue of payloads."""
        conn = await pool.acquire()
        queue: asyncio.Queue = asyncio.Queue()

        def on_notify(conn, pid, channel, payload):
            queue.put_nowait(json.loads(payload))

        await conn.add_listener("document_changes", on_notify)
        yield queue
        await conn.remove_listener("document_changes", on_notify)
        await pool.release(conn)

    async def test_insert_trigger_includes_user_id(self, pool, notify_listener):
        """INSERT into documents fires NOTIFY with correct user_id and kb_id."""
        row = await pool.fetchrow(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, path, "
            "file_type, status, content, version) "
            "VALUES ($1, $2, 'trigger-test.md', '/wiki/', 'md', 'ready', 'test', 1) "
            "RETURNING id::text",
            KB_A_ID, USER_A_ID,
        )
        doc_id = row["id"]

        # Give the notification a moment to arrive
        payload = await asyncio.wait_for(notify_listener.get(), timeout=2)
        assert payload["event"] == "INSERT"
        assert payload["id"] == doc_id
        assert payload["user_id"] == str(USER_A_ID)
        assert payload["knowledge_base_id"] == str(KB_A_ID)

    async def test_update_trigger_includes_user_id(self, pool, notify_listener):
        """UPDATE on documents fires NOTIFY with correct user_id and kb_id."""
        from tests.integration.isolation.conftest import DOC_B_ID
        await pool.execute(
            "UPDATE documents SET content = 'updated' WHERE id = $1", DOC_B_ID,
        )

        payload = await asyncio.wait_for(notify_listener.get(), timeout=2)
        assert payload["event"] == "UPDATE"
        assert payload["id"] == str(DOC_B_ID)
        assert payload["user_id"] == str(USER_B_ID)
        assert payload["knowledge_base_id"] == str(KB_B_ID)


class TestHandleNotifyRouting:
    """Verify _handle_notify correctly routes to the broadcast manager."""

    async def test_valid_payload_broadcasts_to_correct_scope(self):
        _, _handle_notify = _import_ws()
        payload = json.dumps({
            "event": "INSERT",
            "id": "doc-123",
            "user_id": USER_A_ID,
            "knowledge_base_id": str(KB_A_ID),
        })
        with patch("routes.ws.manager") as mock_manager:
            mock_manager.broadcast = AsyncMock()
            await _handle_notify(payload)
            mock_manager.broadcast.assert_called_once_with(
                USER_A_ID, str(KB_A_ID),
                {"event": "INSERT", "id": "doc-123"},
            )

    async def test_missing_user_id_does_not_broadcast(self):
        _, _handle_notify = _import_ws()
        payload = json.dumps({
            "event": "INSERT",
            "id": "doc-123",
            "knowledge_base_id": str(KB_A_ID),
            # user_id intentionally missing
        })
        with patch("routes.ws.manager") as mock_manager:
            mock_manager.broadcast = AsyncMock()
            await _handle_notify(payload)
            mock_manager.broadcast.assert_not_called()

    async def test_malformed_json_does_not_broadcast(self):
        _, _handle_notify = _import_ws()
        with patch("routes.ws.manager") as mock_manager:
            mock_manager.broadcast = AsyncMock()
            await _handle_notify("not valid json {{{")
            mock_manager.broadcast.assert_not_called()
