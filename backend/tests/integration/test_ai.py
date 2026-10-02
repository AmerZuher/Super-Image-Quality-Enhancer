"""Model downloads and AI runs against a running stack (downloads ~185 MB from GitHub once)."""

import os
import time
import uuid
from typing import Any

import httpx
import pytest
import pyvips

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE, timeout=60) as c:
        deadline = time.monotonic() + 120
        while c.get("/api/health/ready").json().get("status") != "ok":
            if time.monotonic() > deadline:
                pytest.fail("stack did not become ready")
            time.sleep(2)
        yield c


def wait(client: httpx.Client, job_id: str, seconds: float = 900) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            return dict(job)
        if time.monotonic() > deadline:
            pytest.fail(f"job stuck in {job['state']}: {job['message']}")
        time.sleep(1)


def install(client: httpx.Client, model_id: str) -> dict[str, Any]:
    body = client.post(f"/api/models/{model_id}/install").raise_for_status().json()
    if body["job"]:
        assert wait(client, body["job"]["id"])["state"] == "succeeded"
    model = next(m for m in client.get("/api/models").json() if m["id"] == model_id)
    assert model["status"] == "installed"
    return dict(model)


@pytest.fixture(scope="module")
def photo(client: httpx.Client) -> dict[str, Any]:
    """A fresh 160×120 image with a bright square subject on a dark background."""
    xy = pyvips.Image.xyz(160, 120)
    inside = (xy[0] > 50) & (xy[0] < 110) & (xy[1] > 30) & (xy[1] < 90)
    noise = uuid.uuid4().int % 40
    rgb = inside.ifthenelse([230, 180, 60], [20 + noise, 30, 40]).cast("uchar").copy(interpretation="srgb")
    body = client.post(
        "/api/assets",
        params={"filename": "subject.png"},
        content=bytes(rgb.pngsave_buffer()),
        headers={"Content-Type": "application/octet-stream"},
    ).json()
    if body["job"]:
        wait(client, body["job"]["id"])
    yield body["asset"]
    for child in client.get("/api/assets", params={"parent_id": body["asset"]["id"]}).json():
        client.delete(f"/api/assets/{child['id']}")
    client.delete(f"/api/assets/{body['asset']['id']}")


def test_catalog_lists_commercial_safe_models(client: httpx.Client) -> None:
    models = client.get("/api/models").json()
    # Models you train in Forge are your own; everything shipped in the catalog is commercial-safe.
    shipped = [m for m in models if m["source"] == "catalog"]
    assert {m["license"] for m in shipped} <= {"MIT", "BSD-3-Clause", "Apache-2.0"}
    assert {"siqe-classic", "realesrgan-x4plus", "isnet-general"} <= {m["id"] for m in models}


def test_unknown_and_missing_models_are_typed_errors(client: httpx.Client, photo: dict[str, Any]) -> None:
    assert client.post("/api/models/nope/install").json()["code"] == "model.not_found"
    if (
        next(m for m in client.get("/api/models").json() if m["id"] == "swinir-m-x4-realsr")["status"]
        == "installed"
    ):
        pytest.skip("SwinIR already installed here")
    response = client.post("/api/ai/plan", json={"asset_id": photo["id"], "model_id": "swinir-m-x4-realsr"})
    assert response.status_code == 409
    assert response.json()["code"] == "model.not_installed"


def test_upscale_creates_a_linked_image(client: httpx.Client, photo: dict[str, Any]) -> None:
    install(client, "realesr-general-x4v3")
    request = {"asset_id": photo["id"], "model_id": "realesr-general-x4v3"}
    plan = client.post("/api/ai/plan", json=request).raise_for_status().json()
    assert (plan["output_width"], plan["output_height"]) == (640, 480)
    started = client.post("/api/ai/runs", json=request)
    assert started.status_code == 201, started.text
    job = wait(client, started.json()["job"]["id"])
    assert job["state"] == "succeeded", job
    result = client.get(f"/api/assets/{job['result']['asset_id']}").json()
    assert result["parent_id"] == photo["id"]
    assert (result["width"], result["height"], result["status"]) == (640, 480, "ready")
    assert result["derivation"]["model_id"] == "realesr-general-x4v3"
    assert result["original_name"].startswith("subject ×4")
    children = client.get("/api/assets", params={"parent_id": photo["id"]}).json()
    assert result["id"] in {c["id"] for c in children}


def test_siqe_classic_upscales_by_three(client: httpx.Client, photo: dict[str, Any]) -> None:
    install(client, "siqe-classic")
    started = client.post("/api/ai/runs", json={"asset_id": photo["id"], "model_id": "siqe-classic"})
    job = wait(client, started.raise_for_status().json()["job"]["id"])
    assert job["state"] == "succeeded", job
    result = client.get(f"/api/assets/{job['result']['asset_id']}").json()
    assert (result["width"], result["height"]) == (480, 360)


def test_background_removal_adds_transparency(client: httpx.Client, photo: dict[str, Any]) -> None:
    install(client, "isnet-general")
    started = client.post("/api/ai/runs", json={"asset_id": photo["id"], "model_id": "isnet-general"})
    job = wait(client, started.raise_for_status().json()["job"]["id"])
    assert job["state"] == "succeeded", job
    result = client.get(f"/api/assets/{job['result']['asset_id']}").json()
    assert result["has_alpha"] is True
    png = pyvips.Image.new_from_buffer(client.get(result["original_url"]).content, "")
    assert png.bands == 4
