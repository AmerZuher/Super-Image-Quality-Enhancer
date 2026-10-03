"""Forge against a running stack: design, dataset, a short training run, pause/stop, publish to AI Lab.

Training runs on whatever the GPU worker has (CPU in CI), so runs here are tiny.
"""

import io
import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")
FINISHED = ("succeeded", "failed", "cancelled")

_projects: list[str] = []
_datasets: list[str] = []
_runs: list[str] = []
_assets: list[str] = []


def _remember(response: httpx.Response) -> None:
    request = response.request
    if request.method != "POST" or response.status_code != 201:
        return
    path = request.url.path
    response.read()
    if path in ("/api/forge/projects",) or path.endswith("/duplicate"):
        _projects.append(response.json()["id"])
    elif path == "/api/forge/datasets":
        _datasets.append(response.json()["id"])
    elif path.startswith("/api/forge/projects/") and path.endswith("/runs"):
        _runs.append(response.json()["id"])


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
        for run_id in _runs:
            c.post(f"/api/forge/runs/{run_id}/stop")
        for run_id in _runs:
            _wait_run(c, run_id, lambda r: r["state"] in FINISHED, seconds=300)
            c.delete(f"/api/forge/runs/{run_id}")
        for dataset_id in _datasets:
            c.delete(f"/api/forge/datasets/{dataset_id}")
        for project_id in _projects:
            c.delete(f"/api/forge/projects/{project_id}")
        for asset_id in _assets:
            c.delete(f"/api/assets/{asset_id}")


def _image(width: int, height: int) -> bytes:
    rng = np.random.default_rng(uuid.uuid4().int % 2**32)
    y, x = np.mgrid[0:height, 0:width] / max(width, height)
    f = 3 + rng.random() * 12
    pixels = (np.sin(2 * np.pi * f * (x * rng.random() + y * rng.random()))[..., None] + 1) * rng.random(3)
    out = io.BytesIO()
    Image.fromarray(np.clip(pixels * 127, 0, 255).astype(np.uint8)).save(out, "PNG")
    return out.getvalue()


def _upload(client: httpx.Client, width: int, height: int) -> str:
    r = client.post(
        "/api/assets",
        params={"filename": f"forgetest-{uuid.uuid4().hex[:8]}.png"},
        content=_image(width, height),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    asset_id = str(r.json()["asset"]["id"])
    _assets.append(asset_id)
    deadline = time.monotonic() + 180
    while client.get(f"/api/assets/{asset_id}").json()["status"] != "ready":
        if time.monotonic() > deadline:
            pytest.fail("upload never became ready")
        time.sleep(0.5)
    return asset_id


def _wait_job(client: httpx.Client, job_id: str, seconds: float = 600) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        job = dict(client.get(f"/api/jobs/{job_id}").json())
        if job["state"] in FINISHED:
            return job
        if time.monotonic() > deadline:
            pytest.fail(f"job stuck: {job}")
        time.sleep(1)


def _wait_run(client: httpx.Client, run_id: str, done: Any, seconds: float = 600) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        run = dict(client.get(f"/api/forge/runs/{run_id}").json()["run"])
        if done(run):
            return run
        if time.monotonic() > deadline:
            pytest.fail(f"run never got there: {run}")
        time.sleep(1)


@pytest.fixture(scope="module")
def dataset(client: httpx.Client) -> dict[str, Any]:
    asset_ids = [_upload(client, 320, 240) for _ in range(4)]
    body = {
        "name": f"Test {uuid.uuid4().hex[:6]}",
        "source": {"kind": "assets", "asset_ids": asset_ids},
        "settings": {"crop": 96, "crops_per_image": 3, "min_width": 200, "min_height": 200, "val_every": 2},
    }
    r = client.post("/api/forge/datasets", json=body)
    assert r.status_code == 201, r.text
    job = _wait_job(client, r.json()["job_id"])
    assert job["state"] == "succeeded", job
    out = next(d for d in client.get("/api/forge/datasets").json() if d["id"] == r.json()["id"])
    assert out["state"] == "succeeded"
    assert out["images"] == 4 and out["train_crops"] > 0 and out["val_crops"] > 0
    return dict(out)


def _project(client: httpx.Client, template: str) -> dict[str, Any]:
    r = client.post(
        "/api/forge/projects", json={"name": f"Test {uuid.uuid4().hex[:6]}", "template": template}
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_catalog_templates_and_checks(client: httpx.Client) -> None:
    types = {b["type"] for b in client.get("/api/forge/catalog").json()}
    assert {"input", "output", "conv", "res", "rdb", "d2s", "upsample"} <= types
    templates = client.get("/api/forge/templates").json()
    assert {t["id"] for t in templates} >= {"siqe-classic", "espcn", "edsr-lite"}
    assert all(t["params"] > 0 and t["scale"] for t in templates if t["id"] != "unet-denoise")

    # 16 filters feeding the output of a 1-channel (Y) model: the fix sets them to 1.
    graph: dict[str, Any] = {
        "blocks": [
            {"id": "in", "type": "input", "params": {"color": "y"}, "position": {"x": 0, "y": 0}},
            {"id": "c", "type": "conv", "params": {"filters": 16}, "position": {"x": 200, "y": 0}},
            {"id": "out", "type": "output", "params": {}, "position": {"x": 400, "y": 0}},
        ],
        "links": [{"source": "in", "target": "c"}, {"source": "c", "target": "out"}],
    }
    analysis = client.post("/api/forge/check", json={"graph": graph}).json()
    problem = next(p for p in analysis["problems"] if p["fix"])
    fixed_block = next(b for b in graph["blocks"] if b["id"] == problem["fix"]["block"])
    fixed_block["params"].update(problem["fix"]["params"])
    assert client.post("/api/forge/check", json={"graph": graph}).json()["problems"] == []


def test_projects_round_trip_and_code(client: httpx.Client) -> None:
    project = _project(client, "espcn")
    assert project["analysis"]["problems"] == [] and project["analysis"]["stats"]["scale"] == 3
    code = client.get(f"/api/forge/projects/{project['id']}/code").json()
    assert code["filename"].endswith(".py") and "class " in code["code"] and "nn.Module" in code["code"]
    renamed = client.put(f"/api/forge/projects/{project['id']}", json={"name": "Renamed"}).json()
    assert renamed["name"] == "Renamed"
    copy = client.post(f"/api/forge/projects/{project['id']}/duplicate").json()
    assert copy["name"] == "Renamed (copy)" and copy["graph"] == renamed["graph"]
    missing = client.post("/api/forge/projects", json={"name": "x", "template": "nope"})
    assert missing.status_code == 404 and missing.json()["code"] == "forge.template_not_found"
    assert client.get(f"/api/forge/projects/{uuid.uuid4()}").json()["code"] == "forge.project_not_found"


def test_dataset_preview_and_degradation(client: httpx.Client, dataset: dict[str, Any]) -> None:
    r = client.get(f"/api/forge/datasets/{dataset['id']}/preview", params={"scale": 2})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    preview = Image.open(io.BytesIO(r.content))
    assert (preview.width, preview.height) == (2 * 96 + 8, 3 * 96 + 16)  # three damaged/clean pairs
    changed = client.put(
        f"/api/forge/datasets/{dataset['id']}/degradation",
        json={"degradation": {"jpeg_chance": 0, "noise_chance": 0}},
    ).json()
    assert changed["degradation"]["jpeg_chance"] == 0


def test_runs_check_settings_first(client: httpx.Client, dataset: dict[str, Any]) -> None:
    unet = _project(client, "unet-denoise")
    r = client.post(
        f"/api/forge/projects/{unet['id']}/runs",
        json={"dataset_id": dataset["id"], "settings": {"patch": 33}},
    )
    assert r.status_code == 422 and r.json()["code"] == "forge.patch_multiple"
    espcn = _project(client, "espcn")
    r = client.post(
        f"/api/forge/projects/{espcn['id']}/runs",
        json={"dataset_id": dataset["id"], "settings": {"patch": 48}},
    )
    assert r.status_code == 422 and r.json()["code"] == "forge.patch_too_big"
    empty = client.post("/api/forge/projects", json={"name": "Empty"}).json()
    r = client.post(f"/api/forge/projects/{empty['id']}/runs", json={"dataset_id": dataset["id"]})
    assert r.status_code == 422 and r.json()["code"] == "forge.invalid"


def test_pause_resume_and_stop(client: httpx.Client, dataset: dict[str, Any]) -> None:
    project = _project(client, "espcn")
    settings = {"steps": 1_000_000, "batch": 2, "patch": 16, "val_every": 10_000}
    r = client.post(
        f"/api/forge/projects/{project['id']}/runs",
        json={"dataset_id": dataset["id"], "settings": settings},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    _wait_run(client, run_id, lambda run: run["step"] > 0)
    busy = client.delete(f"/api/forge/datasets/{dataset['id']}")
    assert busy.status_code == 409 and busy.json()["code"] == "forge.dataset_in_use"

    assert client.post(f"/api/forge/runs/{run_id}/pause").json()["paused"] is True
    # The running chunk finishes its step and saves a checkpoint, then nothing moves.
    held, deadline = -1, time.monotonic() + 60
    while (step := client.get(f"/api/forge/runs/{run_id}").json()["run"]["step"]) != held:
        assert time.monotonic() < deadline, "pausing never took effect"
        held = step
        time.sleep(3)
    time.sleep(4)
    assert client.get(f"/api/forge/runs/{run_id}").json()["run"]["step"] == held

    assert client.post(f"/api/forge/runs/{run_id}/resume").json()["paused"] is False
    _wait_run(client, run_id, lambda run: run["step"] > held)
    client.post(f"/api/forge/runs/{run_id}/stop")
    run = _wait_run(client, run_id, lambda run: run["state"] in FINISHED)
    assert run["state"] == "succeeded" and run["step"] < run["total_steps"]
    again = client.post(f"/api/forge/runs/{run_id}/pause")
    assert again.status_code == 409 and again.json()["code"] == "forge.not_running"


def test_train_publish_and_run_in_ai_lab(client: httpx.Client, dataset: dict[str, Any]) -> None:
    project = _project(client, "espcn")
    settings = {"steps": 60, "batch": 4, "patch": 24, "val_every": 30, "lr": 1e-3}
    r = client.post(
        f"/api/forge/projects/{project['id']}/runs",
        json={"dataset_id": dataset["id"], "settings": settings},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    early = client.post(f"/api/forge/runs/{run_id}/publish", json={"name": "Too soon"})
    assert early.status_code in (202, 409)  # 409 until the first validation saves weights

    run = _wait_run(client, run_id, lambda run: run["state"] in FINISHED)
    assert run["state"] == "succeeded", run
    assert run["step"] == 60 and run["best_psnr"] is not None and run["bicubic_psnr"] is not None
    detail = client.get(f"/api/forge/runs/{run_id}").json()
    kinds = {m["kind"] for m in detail["metrics"]}
    assert kinds == {"train", "val"}
    assert client.get(f"/api/forge/runs/{run_id}/sample").headers["content-type"] == "image/png"
    weights = client.get(f"/api/forge/runs/{run_id}/weights")
    assert weights.status_code == 200 and len(weights.content) > 20_000

    # Export to ONNX: checked against PyTorch, and it comes back in as your own ONNX model.
    assert client.get(f"/api/forge/runs/{run_id}/onnx").json()["code"] == "forge.no_onnx"
    exported = client.post(f"/api/forge/runs/{run_id}/onnx")
    assert exported.status_code == 202, exported.text
    job = _wait_job(client, exported.json()["job"]["id"])
    assert job["state"] == "succeeded", job
    onnx = client.get(f"/api/forge/runs/{run_id}").json()["run"]["onnx"]
    assert onnx["step"] == run["best_step"] and onnx["max_difference"] < 1e-3
    file = client.get(onnx["url"])
    assert file.status_code == 200 and 'onnx"' in file.headers["content-disposition"]
    added = client.post(
        "/api/models/onnx",
        params={"filename": "espcn.onnx", "name": f"Exported {uuid.uuid4().hex[:4]}"},
        content=file.content,
        headers={"Content-Type": "application/octet-stream"},
    )
    job = _wait_job(client, added.json()["job"]["id"])
    assert job["state"] == "succeeded" and job["result"]["scale"] == 3, job
    assert client.delete(f"/api/models/{added.json()['model_id']}").status_code == 204

    name = f"Test {uuid.uuid4().hex[:4]}"
    started = client.post(f"/api/forge/runs/{run_id}/publish", json={"name": name, "summary": "From a test"})
    assert started.status_code == 202, started.text
    job = _wait_job(client, started.json()["job"]["id"])
    assert job["state"] == "succeeded", job
    model_id = job["result"]["model_id"]
    model = next(m for m in client.get("/api/models").json() if m["id"] == model_id)
    assert model["source"] == "forge" and model["status"] == "installed" and model["scale"] == 3
    assert model["benchmark"]["psnr"] > 0
    assert client.get(f"/api/forge/runs/{run_id}").json()["run"]["model_id"] == model_id

    photo = _upload(client, 64, 48)
    started = client.post("/api/ai/runs", json={"asset_id": photo, "model_id": model_id})
    assert started.status_code == 201, started.text
    job = _wait_job(client, started.json()["job"]["id"])
    assert job["state"] == "succeeded", job
    result = client.get(f"/api/assets/{job['result']['asset_id']}").json()
    assert (result["width"], result["height"]) == (192, 144)
    _assets.append(result["id"])

    # Removing a Forge model's files removes it from AI Lab.
    assert client.delete(f"/api/models/{model_id}").status_code == 204
    assert model_id not in {m["id"] for m in client.get("/api/models").json()}
