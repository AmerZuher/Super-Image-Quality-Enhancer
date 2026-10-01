"""Upload → prepare → edit → export → download, against a running stack.

Each run uploads a freshly generated image so the duplicate check never short-circuits it.
"""

import io
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import pyvips

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")
SAMPLES = Path(__file__).resolve().parents[3] / "samples"


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE, timeout=60) as c:
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


def _unique_jpeg(width: int = 640, height: int = 400) -> bytes:
    """A gradient with a random stripe, so its hash is new on every run."""
    stripe = uuid.uuid4().int % (height - 10)
    image = pyvips.Image.xyz(width, height)
    rgb = (image[0] / width * 255).bandjoin([image[1] / height * 255, (image[1] > stripe) * 180])
    return bytes(rgb.cast("uchar").copy(interpretation="srgb").jpegsave_buffer(Q=90))


def _upload(client: httpx.Client, data: bytes, name: str) -> httpx.Response:
    return client.post(
        "/api/assets",
        params={"filename": name},
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )


def _wait_job(client: httpx.Client, job_id: str, seconds: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            return dict(job)
        if time.monotonic() > deadline:
            pytest.fail(f"job stuck in {job['state']}: {job['message']}")
        time.sleep(0.5)


@pytest.fixture(scope="module")
def asset(client: httpx.Client) -> dict[str, Any]:
    response = _upload(client, _unique_jpeg(), "gradient test.jpg")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["duplicate"] is False
    assert body["asset"]["status"] == "processing"
    job = _wait_job(client, body["job"]["id"])
    assert job["state"] == "succeeded", job
    ready = client.get(f"/api/assets/{body['asset']['id']}").json()
    yield ready
    client.delete(f"/api/assets/{ready['id']}")


def test_catalog_lists_ops_and_formats(client: httpx.Client) -> None:
    catalog = client.get("/api/ops").raise_for_status().json()
    assert [op["id"] for op in catalog["ops"]][:3] == ["temperature", "tint", "exposure"]
    assert {f["id"] for f in catalog["formats"]} >= {"jpeg", "png", "webp", "avif", "tiff"}
    assert catalog["max_upload_mb"] > 0


def test_uploaded_image_becomes_ready_with_previews(client: httpx.Client, asset: dict[str, Any]) -> None:
    assert asset["status"] == "ready"
    assert (asset["width"], asset["height"]) == (640, 400)
    assert asset["original_name"] == "gradient test.jpg"
    for key in ("thumb_url", "preview_url"):
        response = client.get(asset[key])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
    dzi = client.get(asset["dzi_url"])
    assert dzi.status_code == 200
    assert b'TileSize="510"' in dzi.content


def test_same_file_twice_is_a_duplicate(client: httpx.Client, asset: dict[str, Any]) -> None:
    original = client.get(asset["original_url"]).raise_for_status().content
    again = _upload(client, original, "copy.jpg")
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["asset"]["id"] == asset["id"]


def test_unreadable_upload_is_rejected(client: httpx.Client) -> None:
    response = _upload(client, b"this is not an image " + uuid.uuid4().bytes, "notes.jpg")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "image.unreadable"


def test_deep_zoom_paths_cannot_escape(client: httpx.Client, asset: dict[str, Any]) -> None:
    response = client.get(f"/api/assets/{asset['id']}/dz/..%2F..%2F..%2Fetc%2Fpasswd")
    assert response.status_code == 404


def test_invalid_edits_are_rejected(client: httpx.Client, asset: dict[str, Any]) -> None:
    doc = {"version": 1, "ops": [{"id": "exposure", "params": {"ev": 99}}]}
    response = client.put(f"/api/assets/{asset['id']}/edits", json=doc)
    assert response.status_code == 422
    assert response.json()["code"] in ("edit.invalid", "request.invalid")


def test_edit_then_export_and_download(client: httpx.Client, asset: dict[str, Any]) -> None:
    doc = {
        "version": 1,
        "geometry": {"rotate": 90, "flip_h": False, "flip_v": False, "crop": None},
        "ops": [
            {"id": "exposure", "params": {"ev": 0.5}},
            {"id": "black_white", "params": {}},
        ],
    }
    saved = client.put(f"/api/assets/{asset['id']}/edits", json=doc).raise_for_status().json()
    assert [op["id"] for op in saved["ops"]] == ["exposure", "black_white"]
    assert client.get(f"/api/assets/{asset['id']}/edits").json() == saved

    started = client.post(f"/api/assets/{asset['id']}/exports", json={"format": "png", "max_side": 300})
    assert started.status_code == 201, started.text
    rendition = started.json()["rendition"]
    assert (rendition["width"], rendition["height"]) == (188, 300)
    job = _wait_job(client, started.json()["job"]["id"])
    assert job["state"] == "succeeded", job

    exports = client.get(f"/api/assets/{asset['id']}/renditions").json()
    ready = next(r for r in exports if r["id"] == rendition["id"])
    assert ready["status"] == "ready"
    download = client.get(ready["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/png"
    assert "gradient%20test-edited.png" in download.headers["content-disposition"]
    image = pyvips.Image.new_from_buffer(download.content, "")
    assert (image.width, image.height) == (188, 300)
    # Black and white: the three channels match.
    assert image[0].avg() == pytest.approx(image[1].avg(), abs=1)

    assert client.delete(f"/api/renditions/{rendition['id']}").status_code == 204
    assert client.get(ready["download_url"]).status_code == 404


def test_lossless_format_rejects_a_target_size(client: httpx.Client, asset: dict[str, Any]) -> None:
    response = client.post(f"/api/assets/{asset['id']}/exports", json={"format": "png", "target_kb": 50})
    assert response.status_code == 422
    assert response.json()["code"] == "export.invalid"


def test_sample_photo_exports_to_a_target_size(client: httpx.Client) -> None:
    data = (SAMPLES / "lake-pier.jpg").read_bytes()
    body = _upload(client, data, "lake-pier.jpg").json()
    if body["job"]:
        assert _wait_job(client, body["job"]["id"])["state"] == "succeeded"
    asset_id = body["asset"]["id"]
    client.put(f"/api/assets/{asset_id}/edits", json={"version": 1, "ops": []}).raise_for_status()
    started = client.post(f"/api/assets/{asset_id}/exports", json={"format": "webp", "target_kb": 40})
    assert started.status_code == 201, started.text
    assert _wait_job(client, started.json()["job"]["id"])["state"] == "succeeded"
    rendition = client.get(f"/api/assets/{asset_id}/renditions").json()[0]
    assert rendition["size_bytes"] <= 40 * 1024
    assert io.BytesIO(client.get(rendition["download_url"]).content).getbuffer().nbytes > 0
