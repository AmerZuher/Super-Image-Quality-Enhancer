"""API keys, the optional sign-in middleware, and the CLI's HTTP client."""

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from siqe.auth import keys, middleware
from siqe.auth.keys import KeyCheck
from siqe.cli.client import Client, ClientError, image_files

# ----------------------------------------------------------------------------- keys


def test_keys_are_long_random_and_stored_as_hashes() -> None:
    a, b = keys.new_secret(), keys.new_secret()
    assert a != b and a.startswith("siqe_") and len(a) >= 45
    assert keys.looks_like_key(a)
    assert not keys.looks_like_key("hunter2")
    assert keys.digest(a) == keys.digest(a) and len(keys.digest(a)) == 64 and a not in keys.digest(a)


def _scope(headers: dict[str, str], path: str = "/api/assets") -> dict[str, Any]:
    return {
        "type": "http",
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }


def test_credential_comes_from_bearer_header_x_api_key_or_cookie() -> None:
    assert middleware.credential(_scope({"Authorization": "Bearer siqe_abc"})) == "siqe_abc"
    assert middleware.credential(_scope({"X-API-Key": "siqe_def"})) == "siqe_def"
    assert middleware.credential(_scope({"Cookie": "theme=dark; siqe_session=siqe_ghi"})) == "siqe_ghi"
    assert middleware.credential(_scope({})) is None


def test_health_sign_in_and_the_web_app_stay_open() -> None:
    assert middleware.is_open("/api/health/live")
    assert middleware.is_open("/api/auth/session")
    assert middleware.is_open("/")  # the web app itself; its API calls are what's checked
    assert not middleware.is_open("/api/assets")
    assert not middleware.is_open("/api/keys")


def _app(enabled: bool, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    good = "siqe_" + "a" * 43

    async def fake_check(_session: Any, secret: str) -> KeyCheck | None:
        return KeyCheck(uuid.uuid4(), "laptop") if secret == good else None

    class FakeScope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(middleware, "check", fake_check)
    monkeypatch.setattr(middleware, "session_scope", FakeScope)
    app = FastAPI()

    @app.get("/api/assets")
    async def assets() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/health/live")
    async def live() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(middleware.ApiKeyAuth, enabled=enabled)
    return TestClient(app)


def test_middleware_asks_for_a_key_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    good = "siqe_" + "a" * 43
    client = _app(True, monkeypatch)
    missing = client.get("/api/assets")
    assert missing.status_code == 401
    assert missing.headers["content-type"] == "application/problem+json"
    assert missing.json()["code"] == "auth.required"
    wrong = client.get("/api/assets", headers={"Authorization": "Bearer siqe_" + "b" * 43})
    assert wrong.json()["code"] == "auth.invalid_key"
    assert client.get("/api/assets", headers={"Authorization": f"Bearer {good}"}).json() == {"ok": True}
    client.cookies.set("siqe_session", good)
    assert client.get("/api/assets").status_code == 200
    assert client.get("/api/health/live").status_code == 200
    assert _app(False, monkeypatch).get("/api/assets").status_code == 200


# --------------------------------------------------------------------------- client


FLOWS = [
    {"id": "f1", "name": "Web gallery", "document": {"nodes": []}, "problems": [], "watch_enabled": False},
    {"id": "f2", "name": "Wallpapers", "document": {"nodes": [1]}, "problems": [], "watch_enabled": False},
]


def _client(handler: Any) -> Client:
    return Client(
        "http://siqe.test", "siqe_key", transport=httpx.MockTransport(handler), sleep=lambda _s: None
    )


def test_flows_resolve_by_id_name_or_file(tmp_path: Path) -> None:
    imported: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer siqe_key"
        if request.url.path == "/api/flows" and request.method == "GET":
            return httpx.Response(200, json=FLOWS)
        if request.url.path == "/api/flows/import":
            imported.append(json.loads(request.content))
            return httpx.Response(201, json={**FLOWS[0], "id": "f3"})
        return httpx.Response(404)

    client = _client(handler)
    assert client.resolve_flow("f2")["name"] == "Wallpapers"
    assert client.resolve_flow("web GALLERY")["id"] == "f1"
    with pytest.raises(ClientError, match="No flow called"):
        client.resolve_flow("nope")
    same = tmp_path / "same.flow.json"
    same.write_text(json.dumps({"name": "Wallpapers", "document": {"nodes": [1]}}))
    assert client.resolve_flow(str(same))["id"] == "f2" and not imported  # reused, not imported again
    new = tmp_path / "new.flow.json"
    new.write_text(json.dumps({"name": "Mine", "document": {"nodes": [2]}}))
    assert client.resolve_flow(str(new))["id"] == "f3" and imported[0]["name"] == "Mine"


def test_errors_carry_the_servers_message_and_fix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"code": "flow.invalid", "detail": "This flow can't run yet.", "fix": "Fix the red blocks."},
        )

    with pytest.raises(ClientError) as err:
        _client(handler).start_run("f1", {"kind": "all"})
    assert err.value.message == "This flow can't run yet." and err.value.fix == "Fix the red blocks."


def test_a_missing_key_gets_a_hint() -> None:
    client = Client(
        "http://siqe.test", None, transport=httpx.MockTransport(lambda r: httpx.Response(401, json={}))
    )
    with pytest.raises(ClientError) as err:
        client.flows()
    assert err.value.fix is not None and "SIQE_API_KEY" in err.value.fix


def test_upload_waits_for_images_to_be_ready(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"jpeg-a")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.png").write_bytes(b"png-b")
    (tmp_path / "notes.txt").write_text("not an image")
    files = image_files([tmp_path])
    assert [f.name for f in files] == ["a.jpg", "b.png"]
    polls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            name = request.url.params["filename"]
            assert request.content in (b"jpeg-a", b"png-b")
            return httpx.Response(201, json={"asset": {"id": name}, "duplicate": False, "job": None})
        asset = request.url.path.rsplit("/", 1)[-1]
        polls[asset] = polls.get(asset, 0) + 1
        state = "processing" if polls[asset] < 2 else ("failed" if asset == "b.png" else "ready")
        return httpx.Response(200, json={"status": state})

    client = _client(handler)
    ids = client.upload(files)
    assert client.wait_ready(ids) == (["a.jpg"], ["b.png"])


def test_follow_until_finished_and_download_safely(tmp_path: Path) -> None:
    states = iter(["running", "running", "succeeded"])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("one.webp", b"1")
        zf.writestr("desktop/two.webp", b"2")
        zf.writestr("../escape.txt", b"no")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=buffer.getvalue())
        run = {"state": next(states), "done": 2, "failed": 0, "skipped": 0, "total": 2}
        return httpx.Response(200, json={"run": run, "items": []})

    client = _client(handler)
    seen = [r.run["state"] for r in client.follow("r1")]
    assert seen == ["running", "running", "succeeded"]
    out = tmp_path / "out"
    saved = client.download("r1", out)
    assert sorted(p.relative_to(out.resolve()).as_posix() for p in saved) == ["desktop/two.webp", "one.webp"]
    assert not (tmp_path / "escape.txt").exists()
    assert not list(out.glob(".siqe-run-*"))
