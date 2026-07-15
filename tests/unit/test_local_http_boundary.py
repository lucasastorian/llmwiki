"""Security boundary tests for the unauthenticated local HTTP API."""

import importlib.machinery
import importlib.util
from pathlib import Path

import httpx
import pytest
from infra.local_http import LocalHTTPBoundaryMiddleware, is_allowed_local_origin
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


async def _endpoint(request):
    return JSONResponse({"ok": True})


def _app() -> Starlette:
    app = Starlette(
        routes=[Route("/", _endpoint, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])]
    )
    app.add_middleware(
        LocalHTTPBoundaryMiddleware,
        app_origin="http://localhost:3000",
    )
    return app


async def _request(
    method: str = "GET",
    *,
    host: str = "localhost:8000",
    origin: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    headers = {"host": host, **(extra_headers or {})}
    if origin is not None:
        headers["origin"] = origin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://localhost:8000",
    ) as client:
        return await client.request(method, "/", headers=headers)


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
async def test_accepts_only_explicit_loopback_hosts(host):
    assert (await _request(host=host)).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "attacker.example:8000",
        "workspace.localhost:8000",
        "127.0.0.2:8000",
        "",
        "[::1]:bad",
        f"localhost:{'9' * 5000}",
    ],
)
async def test_rejects_dns_rebinding_and_malformed_hosts(host):
    response = await _request(host=host)
    assert response.status_code == 400
    assert response.text == "Invalid Host header"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_allows_local_web_ui_mutations(method):
    response = await _request(method, origin="http://localhost:3000")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef",
        "moz-extension://d28b2a6e-2456-4f45-9f65-e11c8ea1e65d",
    ],
)
async def test_allows_browser_extension_mutations(origin):
    assert is_allowed_local_origin(origin, "http://localhost:3000")
    assert (await _request("POST", origin=origin)).status_code == 200


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "http://localhost:3001"])
async def test_rejects_foreign_browser_mutations(origin):
    response = await _request("POST", origin=origin)
    assert response.status_code == 403
    assert response.text == "Origin not allowed"


def test_configured_app_origin_must_itself_be_loopback():
    assert not is_allowed_local_origin(
        "https://attacker.example",
        "https://attacker.example",
    )


async def test_non_browser_mutation_without_origin_still_works():
    assert (await _request("POST")).status_code == 200


async def test_cross_site_browser_mutation_cannot_hide_missing_origin():
    response = await _request("POST", extra_headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 403


async def test_foreign_origin_is_harmless_on_safe_get():
    assert (await _request("GET", origin="https://attacker.example")).status_code == 200


def test_cli_launches_api_on_ipv4_loopback(tmp_path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader(
        "llmwiki_cli_for_test",
        str(Path(__file__).resolve().parents[2] / "llmwiki"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    cli = importlib.util.module_from_spec(spec)
    loader.exec_module(cli)

    workspace = tmp_path / "workspace"
    (workspace / ".llmwiki").mkdir(parents=True)
    (workspace / ".llmwiki" / "index.db").touch()

    launches: list[list[str]] = []

    class _Process:
        def terminate(self):
            pass

    def fake_popen(args, **kwargs):
        launches.append(args)
        return _Process()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/npm")
    monkeypatch.setattr(cli, "_supervise", lambda *_args: None)

    cli.cmd_serve(str(workspace), open_browser=False)

    api_command = launches[0]
    assert api_command[api_command.index("--host") + 1] == "127.0.0.1"
