"""Library against a running stack: analysis, duplicates, rules, albums, quarantine, location.

Images are generated per run (random content) so earlier runs never collide with them.
"""

import io
import json
import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import numpy as np
import pytest
import pyvips
from PIL import Image

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
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


def _scene(kind: str, width: int = 900, height: int = 600) -> np.ndarray:
    """A new image each run. Kinds differ in content so they are never near-duplicates."""
    rng = np.random.default_rng(uuid.uuid4().int % 2**32)
    y, x = np.mgrid[0:height, 0:width] / max(width, height)
    if kind == "stripes":
        f = 6 + rng.random() * 10
        base = np.sin(2 * np.pi * f * (x + 0.3 * y))[..., None] * rng.random(3)
    elif kind == "checks":
        n = 4 + int(rng.random() * 6)
        base = (((x * n).astype(int) + (y * n).astype(int)) % 2)[..., None] * rng.random(3)
    else:  # blobs
        base = np.zeros((height, width, 3))
        for _ in range(12):
            cx, cy, r = rng.random(), rng.random() * height / width, 0.05 + rng.random() * 0.25
            base = base + rng.random(3) * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * r * r))[..., None]
    base = base - base.min()
    return np.clip(base / max(base.max(), 1e-6) * 255, 0, 255).astype(np.uint8)


def _jpeg(pixels: np.ndarray, quality: int = 92, exif: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="JPEG", quality=quality, exif=exif or b"")
    return buf.getvalue()


def _upload(client: httpx.Client, data: bytes, name: str) -> dict[str, Any]:
    r = client.post(
        "/api/assets",
        params={"filename": name},
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    if body["job"]:
        _wait_job(client, body["job"]["id"])
    return dict(body["asset"])


def _wait_job(client: httpx.Client, job_id: str, seconds: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            assert job["state"] == "succeeded", job
            return dict(job)
        if time.monotonic() > deadline:
            pytest.fail(f"job stuck in {job['state']}: {job['message']}")
        time.sleep(0.5)


def _asset(client: httpx.Client, asset_id: str) -> dict[str, Any]:
    return dict(client.get(f"/api/assets/{asset_id}").json())


def _until(check: Any, seconds: float = 120, what: str = "condition") -> Any:
    deadline = time.monotonic() + seconds
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(1)


def _rules(*rules: dict[str, Any], match: str = "all") -> str:
    return json.dumps({"match": match, "rules": list(rules)})


@pytest.fixture(scope="module")
def made(client: httpx.Client) -> Iterator[dict[str, dict[str, Any]]]:
    scene = _scene("blobs")
    copy = np.asarray(Image.fromarray(scene).resize((600, 400), Image.Resampling.LANCZOS))
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "Canon", "EOS R5"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (46.0, 34.0, 12.0), "E", (7.0, 59.0, 30.0)
    assets = {
        "original": _upload(client, _jpeg(scene), "library original.jpg"),
        "copy": _upload(client, _jpeg(copy, quality=60), "library copy.jpg"),
        "other": _upload(client, _jpeg(_scene("stripes", 600, 900)), "library portrait.jpg"),
        "located": _upload(client, _jpeg(_scene("checks"), exif=exif.tobytes()), "library located.jpg"),
    }
    for a in assets.values():
        _until(lambda a=a: _asset(client, a["id"])["analysed"], what=f"{a['original_name']} to be analysed")
    yield assets
    ids = [a["id"] for a in assets.values()]
    client.post("/api/library/quarantine", json={"asset_ids": ids})
    client.post("/api/library/delete", json={"asset_ids": ids})


def test_status_reports_counts(client: httpx.Client, made: dict[str, Any]) -> None:
    status = client.get("/api/library/status").json()
    assert status["counts"]["all"] >= 4
    assert status["search_model"] in ("available", "downloading", "installed", "failed")


def test_analysis_fills_in_measurements(client: httpx.Client, made: dict[str, Any]) -> None:
    a = _asset(client, made["original"]["id"])
    assert 0 <= a["sharpness"] <= 1
    assert a["color"] and a["color_hex"].startswith("#")
    located = _asset(client, made["located"]["id"])
    assert located["has_gps"] and located["gps"] == pytest.approx([46.57, 7.991667], abs=1e-5)
    assert located["exif"]["model"] == "EOS R5"


def test_resized_copy_is_grouped_and_ranked_below_the_original(
    client: httpx.Client, made: dict[str, Any]
) -> None:
    original, copy = made["original"]["id"], made["copy"]["id"]
    _until(lambda: _asset(client, copy)["duplicate_group"], what="the duplicate group")
    a, b = _asset(client, original), _asset(client, copy)
    assert a["duplicate_group"] == b["duplicate_group"]
    assert a["duplicate_rank"] < b["duplicate_rank"]  # the larger, sharper original is the keeper
    assert _asset(client, made["other"]["id"])["duplicate_group"] is None
    page = client.get("/api/library/assets", params={"view": "duplicates", "limit": 500}).json()
    assert {original, copy} <= {i["id"] for i in page["items"]}


def test_rules_filter_and_reject_bad_input(client: httpx.Client, made: dict[str, Any]) -> None:
    portrait = client.get(
        "/api/library/assets",
        params={"rules": _rules({"field": "orientation", "op": "is", "value": "portrait"}), "limit": 500},
    ).json()
    ids = {i["id"] for i in portrait["items"]}
    assert made["other"]["id"] in ids and made["original"]["id"] not in ids
    located = client.get(
        "/api/library/assets",
        params={"rules": _rules({"field": "has_gps", "op": "is", "value": True}), "limit": 500},
    ).json()
    assert made["located"]["id"] in {i["id"] for i in located["items"]}
    bad = client.get(
        "/api/library/assets", params={"rules": _rules({"field": "width", "op": "has", "value": 3})}
    )
    assert bad.status_code == 422 and bad.json()["code"] == "library.invalid_rules"
    named = client.get("/api/library/assets", params={"q": "library portrait"}).json()
    assert made["other"]["id"] in {i["id"] for i in named["items"]}


def test_tags_and_albums(client: httpx.Client, made: dict[str, Any]) -> None:
    target = made["other"]["id"]
    tag = f"trip-{uuid.uuid4().hex[:6]}"
    assert (
        client.post("/api/library/tags", json={"asset_ids": [target], "add": [tag.upper()]}).json()["changed"]
        == 1
    )
    assert tag in _asset(client, target)["tags"]  # stored lower-case

    smart = client.post(
        "/api/library/albums",
        json={
            "name": "Tagged",
            "kind": "smart",
            "rules": {"match": "all", "rules": [{"field": "tag", "op": "has", "value": tag}]},
        },
    ).json()
    assert smart["count"] == 1
    manual = client.post("/api/library/albums", json={"name": "Picks", "kind": "manual"}).json()
    r = client.post(f"/api/library/albums/{manual['id']}/assets", json={"asset_ids": [target, target]})
    assert r.json()["changed"] == 1
    page = client.get("/api/library/assets", params={"view": "album", "album_id": manual["id"]}).json()
    assert [i["id"] for i in page["items"]] == [target]
    assert client.get(f"/api/library/assets/{target}/albums").json() == [manual["id"]]
    refused = client.post(f"/api/library/albums/{smart['id']}/assets", json={"asset_ids": [target]})
    assert refused.status_code == 422 and refused.json()["code"] == "album.not_manual"
    renamed = client.patch(f"/api/library/albums/{manual['id']}", json={"name": "Best picks"}).json()
    assert renamed["name"] == "Best picks"
    for album in (smart, manual):
        assert client.delete(f"/api/library/albums/{album['id']}").status_code == 204
    assert (
        client.post("/api/library/tags", json={"asset_ids": [target], "remove": [tag]}).json()["changed"] == 1
    )


def test_quarantine_hides_and_restore_brings_back(client: httpx.Client, made: dict[str, Any]) -> None:
    target = made["other"]["id"]
    assert (
        client.post("/api/library/quarantine", json={"asset_ids": [target], "reason": "Test"}).json()[
            "changed"
        ]
        == 1
    )
    assert target not in {a["id"] for a in client.get("/api/assets", params={"limit": 1000}).json()}
    q = client.get("/api/library/assets", params={"view": "quarantine", "limit": 500}).json()
    assert target in {i["id"] for i in q["items"]}
    assert client.post("/api/library/restore", json={"asset_ids": [target]}).json()["changed"] == 1
    assert _asset(client, target)["quarantined_at"] is None
    # Deleting is only allowed from quarantine.
    assert client.post("/api/library/delete", json={"asset_ids": [target]}).json()["changed"] == 0


def test_remove_location_keeps_pixels_and_quarantines_the_original(
    client: httpx.Client, made: dict[str, Any]
) -> None:
    original = made["located"]
    before = pyvips.Image.new_from_buffer(client.get(original["original_url"]).content, "")
    r = client.post("/api/library/remove-location", json={"asset_ids": [original["id"]]})
    assert r.status_code == 201, r.text
    job = _wait_job(client, r.json()["id"])
    assert job["result"]["done"] == 1
    old = _asset(client, original["id"])
    assert old["quarantined_at"] and "without location" in old["quarantine_reason"]
    page = client.get(
        "/api/library/assets",
        params={"rules": _rules({"field": "name", "op": "contains", "value": "library located"})},
    ).json()
    clean = next(i for i in page["items"] if i["id"] != original["id"])
    made["clean"] = clean
    assert clean["has_gps"] is False and clean["gps"] is None
    assert clean["derivation"]["kind"] == "location_removed"
    data = client.get(clean["original_url"]).content
    after = pyvips.Image.new_from_buffer(data, "")
    assert "exif-ifd3-GPSLatitude" not in after.get_fields()
    assert after.get("exif-ifd0-Model").startswith("EOS R5")
    assert np.array_equal(before.numpy(), after.numpy())
    nothing = client.post("/api/library/remove-location", json={"asset_ids": [clean["id"]]})
    assert nothing.status_code == 422 and nothing.json()["code"] == "library.no_location"


def test_resolving_duplicates_quarantines_the_worse_copy(client: httpx.Client, made: dict[str, Any]) -> None:
    group = _asset(client, made["original"]["id"])["duplicate_group"]
    r = client.post("/api/library/duplicates/resolve", json={"groups": [group]})
    assert r.json()["changed"] >= 1
    copy = _asset(client, made["copy"]["id"])
    assert copy["quarantined_at"] and copy["quarantine_reason"].startswith("Duplicate of")
    assert _asset(client, made["original"]["id"])["quarantined_at"] is None


def test_search_by_description_when_clip_is_installed(client: httpx.Client, made: dict[str, Any]) -> None:
    if client.get("/api/library/status").json()["search_model"] != "installed":
        pytest.skip("CLIP search model not installed")
    page = client.get("/api/library/assets", params={"q": "a black and white checkerboard"}).json()
    assert page["mode"] == "text"
    scores = [i["score"] for i in page["items"]]
    assert scores == sorted(scores, reverse=True)
    similar = client.get("/api/library/assets", params={"similar_to": made["original"]["id"]}).json()
    assert similar["mode"] == "similar"
    assert made["original"]["id"] not in {i["id"] for i in similar["items"]}


def test_faces_filter_and_status(client: httpx.Client) -> None:
    status = client.get("/api/library/status").json()
    assert {"faces_ready", "faces_pending", "faces_model_id"} <= status.keys()
    people = {"match": "all", "rules": [{"field": "faces", "op": "gte", "value": 1}]}
    page = client.get("/api/library/assets", params={"rules": json.dumps(people), "limit": 200})
    assert page.status_code == 200
    # Only counted images with faces match; uncounted ones (faces null) never do.
    assert all((a["faces"] or 0) >= 1 for a in page.json()["items"])
    bad = {"match": "all", "rules": [{"field": "faces", "op": "is", "value": 1}]}
    assert client.get("/api/library/assets", params={"rules": json.dumps(bad)}).status_code == 422
