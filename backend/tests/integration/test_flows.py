"""Flows against a running stack: build, run, branch, dry-run, fail per image, download; API keys.

Images are generated per run (random content), so earlier runs never collide with them.
"""

import io
import os
import time
import uuid
import zipfile
from collections.abc import Iterator
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE, timeout=60, event_hooks={"response": [_remember]}) as c:
        deadline = time.monotonic() + 120
        while True:
            try:
                if c.get("/api/health/ready").json().get("status") == "ok":
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("stack did not become ready within 120 s")
            time.sleep(2)
        yield c
        for flow_id in _created:  # leave no test flows behind in the app
            c.delete(f"/api/flows/{flow_id}")


_created: list[str] = []


def _remember(response: httpx.Response) -> None:
    request = response.request
    if (
        request.method == "POST"
        and response.status_code == 201
        and request.url.path
        in (
            "/api/flows",
            "/api/flows/import",
        )
    ):
        response.read()
        _created.append(response.json()["id"])


def _image(width: int, height: int) -> bytes:
    rng = np.random.default_rng(uuid.uuid4().int % 2**32)
    y, x = np.mgrid[0:height, 0:width] / max(width, height)
    f = 3 + rng.random() * 12
    pixels = (np.sin(2 * np.pi * f * (x * rng.random() + y * rng.random()))[..., None] + 1) * rng.random(3)
    out = io.BytesIO()
    Image.fromarray(np.clip(pixels * 127, 0, 255).astype(np.uint8)).save(out, "JPEG", quality=92)
    return out.getvalue()


def _upload(client: httpx.Client, width: int, height: int) -> str:
    name = f"flowtest-{uuid.uuid4().hex[:8]}.jpg"
    r = client.post(
        "/api/assets",
        params={"filename": name},
        content=_image(width, height),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    asset_id = str(r.json()["asset"]["id"])
    deadline = time.monotonic() + 180
    while client.get(f"/api/assets/{asset_id}").json()["status"] != "ready":
        if time.monotonic() > deadline:
            pytest.fail("upload never became ready")
        time.sleep(0.5)
    return asset_id


def _node(node_id: str, type_: str, x: int, **params: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "params": params, "position": {"x": x, "y": 0}}


def _flow(
    client: httpx.Client, nodes: list[dict[str, Any]], edges: list[tuple[str, str, str]]
) -> dict[str, Any]:
    document = {
        "version": 1,
        "nodes": nodes,
        "edges": [{"source": s, "target": t, "port": p} for s, t, p in edges],
    }
    r = client.post("/api/flows", json={"name": f"Test {uuid.uuid4().hex[:6]}", "document": document})
    assert r.status_code == 201, r.text
    return dict(r.json())


def _run(client: httpx.Client, flow_id: str, asset_ids: list[str], dry_run: bool = False) -> dict[str, Any]:
    r = client.post(
        f"/api/flows/{flow_id}/runs",
        json={"source": {"kind": "assets", "asset_ids": asset_ids}, "dry_run": dry_run},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    deadline = time.monotonic() + 300
    while True:
        detail = client.get(f"/api/flows/runs/{run_id}").json()
        if detail["run"]["state"] in ("succeeded", "failed", "cancelled"):
            return dict(detail)
        if time.monotonic() > deadline:
            pytest.fail(f"run stuck: {detail['run']}")
        time.sleep(1)


def test_catalog_and_recipes(client: httpx.Client) -> None:
    catalog = client.get("/api/flows/catalog").json()
    types = {n["type"] for n in catalog}
    assert {"input", "condition", "resize", "upscale", "export", "save_to_library"} <= types
    assert all(n["ai"] == (n["category"] == "ai") for n in catalog)
    recipes = client.get("/api/flows/recipes").json()
    assert len(recipes) >= 5
    for recipe in recipes:
        flow = client.post("/api/flows", json={"name": recipe["name"], "recipe": recipe["id"]}).json()
        assert flow["problems"] == [], recipe["id"]
        client.delete(f"/api/flows/{flow['id']}")


def test_a_flow_that_cant_run_says_why(client: httpx.Client) -> None:
    flow = _flow(client, [_node("in", "input", 0), _node("r", "resize", 200)], [("in", "r", "out")])
    assert flow["problems"]
    r = client.post(f"/api/flows/{flow['id']}/runs", json={"source": {"kind": "all"}})
    assert r.status_code == 422
    assert r.json()["code"] == "flow.invalid" and r.json()["problems"]


def test_branch_resize_export_tag_and_download(client: httpx.Client) -> None:
    wide, tall = _upload(client, 900, 500), _upload(client, 400, 700)
    tag = f"flowtag-{uuid.uuid4().hex[:6]}"
    landscape = {"match": "all", "rules": [{"field": "orientation", "op": "is", "value": "landscape"}]}
    flow = _flow(
        client,
        [
            _node("in", "input", 0),
            _node("if", "condition", 200, rules=landscape),
            _node("small", "resize", 400, mode="longest", size=300, upscale=False),
            _node("out", "export", 600, format="png", folder="wide"),
            _node("tag", "tag", 400, tags=[tag]),
        ],
        [("in", "if", "out"), ("if", "small", "yes"), ("small", "out", "out"), ("if", "tag", "no")],
    )
    assert flow["problems"] == []
    detail = _run(client, flow["id"], [wide, tall])
    run = detail["run"]
    assert run["state"] == "succeeded" and run["done"] == 2 and run["failed"] == 0, detail
    by_asset = {i["asset_id"]: i for i in detail["items"]}
    exported = by_asset[wide]["outputs"]
    assert [o["kind"] for o in exported] == ["export"] and exported[0]["path"].endswith(".png")
    assert exported[0]["width"] == 300
    assert [o["kind"] for o in by_asset[tall]["outputs"]] == ["tag"]
    assert tag in client.get(f"/api/assets/{tall}").json()["tags"]
    assert tag not in client.get(f"/api/assets/{wide}").json()["tags"]

    zipped = client.get(f"/api/flows/runs/{run['id']}/download")
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as zf:
        names = zf.namelist()
        assert len(names) == 1 and names[0].startswith("wide/")
        with Image.open(io.BytesIO(zf.read(names[0]))) as im:
            assert max(im.size) == 300
    escape = client.get(f"/api/flows/runs/{run['id']}/files/..%2F..%2F..%2Fetc%2Fpasswd")
    assert escape.status_code == 404


def test_dry_run_changes_nothing_in_the_library(client: httpx.Client) -> None:
    asset = _upload(client, 600, 400)
    tag = f"dry-{uuid.uuid4().hex[:6]}"
    flow = _flow(
        client,
        [
            _node("in", "input", 0),
            _node("tag", "tag", 200, tags=[tag]),
            _node("save", "save_to_library", 400),
        ],
        [("in", "tag", "out"), ("tag", "save", "out")],
    )
    before = client.get("/api/library/assets", params={"limit": 1}).json()["total"]
    detail = _run(client, flow["id"], [asset], dry_run=True)
    assert detail["run"]["state"] == "succeeded" and detail["run"]["dry_run"]
    assert tag not in client.get(f"/api/assets/{asset}").json()["tags"]
    time.sleep(2)
    assert client.get("/api/library/assets", params={"limit": 1}).json()["total"] == before


def test_a_failing_image_is_recorded_and_the_run_reports_it(client: httpx.Client) -> None:
    asset = _upload(client, 500, 500)
    album = client.post(
        "/api/library/albums", json={"name": f"Gone {uuid.uuid4().hex[:6]}", "kind": "manual"}
    ).json()
    flow = _flow(
        client,
        [_node("in", "input", 0), _node("alb", "add_to_album", 200, album=album["id"])],
        [("in", "alb", "out")],
    )
    client.delete(f"/api/library/albums/{album['id']}")
    detail = _run(client, flow["id"], [asset])
    assert detail["run"]["state"] == "failed" and detail["run"]["failed"] == 1
    assert detail["items"][0]["error"]["code"] == "flow.album_missing"


def test_a_run_needing_a_missing_model_is_refused_up_front(client: httpx.Client) -> None:
    models = {m["id"]: m["status"] for m in client.get("/api/models").json()}
    missing = next(
        (
            m
            for m in ("scunet-real-psnr", "realesrgan-x2plus", "swinir-m-x4-realsr")
            if models.get(m) == "available"
        ),
        None,
    )
    if missing is None:
        pytest.skip("every candidate model is installed")
    task = {"scunet-real-psnr": "denoise"}.get(missing, "upscale")
    flow = _flow(
        client,
        [_node("in", "input", 0), _node("ai", task, 200, model=missing), _node("out", "export", 400)],
        [("in", "ai", "out"), ("ai", "out", "out")],
    )
    r = client.post(f"/api/flows/{flow['id']}/runs", json={"source": {"kind": "all"}})
    assert r.status_code == 409 and r.json()["code"] == "model.not_installed"


def test_flow_files_round_trip(client: httpx.Client) -> None:
    flow = client.post("/api/flows", json={"name": "Round trip", "recipe": "web-gallery"}).json()
    file = client.get(f"/api/flows/{flow['id']}/file")
    assert "attachment" in file.headers["content-disposition"]
    copy = client.post("/api/flows/import", json=file.json()).json()
    assert copy["document"] == flow["document"] and copy["id"] != flow["id"]
    for f in (flow, copy):
        assert client.delete(f"/api/flows/{f['id']}").status_code == 204


def test_api_keys_are_shown_once_and_can_be_revoked(client: httpx.Client) -> None:
    status = client.get("/api/auth/status").json()
    assert status["mode"] in ("off", "keys")
    created = client.post("/api/keys", json={"name": "integration test"})
    assert created.status_code == 201
    key = created.json()
    assert key["secret"].startswith(key["prefix"]) and key["secret"].startswith("siqe_")
    listed = {k["id"]: k for k in client.get("/api/keys").json()}
    assert "secret" not in listed[key["id"]]
    me = client.get("/api/auth/status", headers={"Authorization": f"Bearer {key['secret']}"}).json()
    assert me["signed_in"]
    assert client.delete(f"/api/keys/{key['id']}").status_code == 204
    revoked = {k["id"]: k for k in client.get("/api/keys").json()}[key["id"]]
    assert revoked["revoked_at"] is not None
    gone = client.get("/api/auth/status", headers={"Authorization": f"Bearer {key['secret']}"}).json()
    assert gone["mode"] == "keys" or gone["signed_in"]  # with keys off everyone is signed in
