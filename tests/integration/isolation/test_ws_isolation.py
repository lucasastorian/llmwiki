"""WebSocket tenant isolation tests.

Proves that document change events are never leaked across tenants.
The broadcast key is (user_id, kb_id) — both must match for delivery.
"""

import pytest
from unittest.mock import AsyncMock

from routes.ws import DocumentWSManager
from tests.helpers.jwt import make_token, seed_jwks_cache
from tests.integration.isolation.conftest import (
    USER_A_ID, USER_B_ID,
    KB_A_ID, KB_B_ID,
)

_EVENT = {"event": "UPDATE", "id": "doc-123"}


class TestBroadcastIsolation:
    """Unit tests for DocumentWSManager — no DB or HTTP needed."""

    @pytest.fixture
    def manager(self):
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

        app.state.pool = pool
        app.state.s3_service = None
        app.state.ocr_service = None
        app.state.auth_provider = None
        seed_jwks_cache()
        return TestClient(app)

    def test_valid_token_connects(self, ws_client):
        token = make_token(USER_A_ID)
        with ws_client.websocket_connect(f"/v1/ws/documents/{KB_A_ID}") as ws:
            ws.send_text(token)
            # Connection stays open — send a ping to verify
            # If auth failed, send_text would raise
            ws.close()

    def test_invalid_token_rejected(self, ws_client):
        with ws_client.websocket_connect(f"/v1/ws/documents/{KB_A_ID}") as ws:
            ws.send_text("garbage-token")
            # Server should close with 4001 after verify_token fails
            try:
                ws.receive_json()
                pytest.fail("Expected connection to be closed")
            except Exception:
                pass

    def test_wrong_audience_rejected(self, ws_client):
        token = make_token(USER_A_ID, aud="wrong-audience")
        with ws_client.websocket_connect(f"/v1/ws/documents/{KB_A_ID}") as ws:
            ws.send_text(token)
            try:
                ws.receive_json()
                pytest.fail("Expected connection to be closed")
            except Exception:
                pass
