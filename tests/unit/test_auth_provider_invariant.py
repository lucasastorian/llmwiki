"""Hosted mode must verify JWTs and never wire the always-allow local auth provider."""

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

LOCAL_USER_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "local"))


def _request(app, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {"type": "http", "headers": raw_headers, "app": app}
    return Request(scope)


async def _run_local_lifespan_inner(tmp_path: Path):
    """Drive the real local-mode wiring; returns a stand-in app with state set."""
    from config import settings
    from main import _local_lifespan_inner

    app = SimpleNamespace(state=SimpleNamespace())
    # _local_lifespan_inner builds the workspace under settings.WORKSPACE_PATH.
    original = settings.WORKSPACE_PATH
    settings.WORKSPACE_PATH = str(tmp_path / "ws")
    try:
        db = await _local_lifespan_inner(app)
    finally:
        settings.WORKSPACE_PATH = original
    return app, db


async def test_local_mode_wires_local_auth_provider(tmp_path):
    import deps
    from infra.auth.local import LocalAuthProvider

    app, db = await _run_local_lifespan_inner(tmp_path)
    try:
        assert isinstance(app.state.auth_provider, LocalAuthProvider)
        user_id = await deps.get_user_id(_request(app))
        assert user_id == LOCAL_USER_ID
    finally:
        await db.close()


async def test_hosted_mode_never_uses_local_user():
    import deps

    app = SimpleNamespace(state=SimpleNamespace(auth_provider=None))

    with pytest.raises(HTTPException) as exc_info:
        await deps.get_user_id(_request(app))  # no Authorization header

    assert exc_info.value.status_code == 401
    # A LocalAuthProvider would have silently returned LOCAL_USER_ID instead.


async def test_hosted_mode_rejects_garbage_bearer_token():
    import deps

    app = SimpleNamespace(state=SimpleNamespace(auth_provider=None))
    request = _request(app, {"Authorization": "Bearer not-a-real-jwt"})

    with pytest.raises(HTTPException) as exc_info:
        await deps.get_user_id(request)

    assert exc_info.value.status_code == 401
