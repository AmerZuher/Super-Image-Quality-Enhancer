"""Unusual inputs, against a running stack: each row of the input edge-case table in robustness.md.

Files are generated with libvips and are new on every run.
"""

import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import pyvips

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")
_assets: list[str] = []


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE, timeout=120) as c:
        deadline = time.monotonic() + 120
        while c.get("/api/health/ready").json().get("status") != "ok":
            if time.monotonic() > deadline:
                pytest.fail("stack did not become ready within 120 s")
            time.sleep(2)
        yield c
        for asset_id in _assets:
            c.delete(f"/api/assets/{asset_id}")


def _scene(width: int = 480, height: int = 320) -> pyvips.Image:
    """A colourful gradient with a random block, so every file is new."""
    xyz = pyvips.Image.xyz(width, height)
    seed = uuid.uuid4().int % 200
    red = xyz[0] / width * 255
    green = xyz[1] / height * 255
    blue = ((xyz[0] > seed) & (xyz[1] > seed // 2)).ifthenelse(200, 40)
    return red.bandjoin([green, blue]).cast("uchar").copy(interpretation="srgb")


def _ingest(client: httpx.Client, data: bytes, name: str) -> dict[str, Any]:
    response = client.post(
        "/api/assets",
        params={"filename": name},
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    _assets.append(body["asset"]["id"])
    deadline = time.monotonic() + 180
    while (job := client.get(f"/api/jobs/{body['job']['id']}").json())["state"] not in (
        "succeeded",
        "failed",
        "cancelled",
    ):
        assert time.monotonic() < deadline, job
        time.sleep(0.5)
    assert job["state"] == "succeeded", job
    return dict(client.get(f"/api/assets/{body['asset']['id']}").json())


def _export_png(client: httpx.Client, asset: dict[str, Any]) -> pyvips.Image:
    started = client.post(f"/api/assets/{asset['id']}/exports", json={"format": "png"})
    assert started.status_code == 201, started.text
    deadline = time.monotonic() + 180
    while (job := client.get(f"/api/jobs/{started.json()['job']['id']}").json())["state"] not in (
        "succeeded",
        "failed",
    ):
        assert time.monotonic() < deadline, job
        time.sleep(0.5)
    assert job["state"] == "succeeded", job
    rendition = next(
        r
        for r in client.get(f"/api/assets/{asset['id']}/renditions").json()
        if r["id"] == started.json()["rendition"]["id"]
    )
    return pyvips.Image.new_from_buffer(client.get(rendition["download_url"]).content, "")


def test_exif_rotation_is_applied(client: httpx.Client) -> None:
    image = _scene(480, 320).copy()
    image.set_type(pyvips.GValue.gint_type, "orientation", 6)  # rotate 90° clockwise to view
    asset = _ingest(client, image.jpegsave_buffer(Q=90), "rotated.jpg")
    assert (asset["width"], asset["height"]) == (320, 480)
    out = _export_png(client, asset)
    assert (out.width, out.height) == (320, 480)


def test_cmyk_jpeg_becomes_srgb(client: httpx.Client) -> None:
    rgb = _scene()
    cmyk = rgb.icc_export(output_profile="cmyk")
    asset = _ingest(client, cmyk.jpegsave_buffer(Q=92), "print.jpg")
    out = _export_png(client, asset)
    assert out.bands == 3
    # Colours survive the round trip through CMYK reasonably well.
    assert abs(out.avg() - rgb.avg()) < 20


def test_sixteen_bit_png_keeps_its_depth(client: httpx.Client) -> None:
    deep = (_scene().cast("ushort") * 257).cast("ushort").copy(interpretation="rgb16")
    asset = _ingest(client, deep.pngsave_buffer(), "deep.png")
    assert asset["bit_depth"] == 16
    out = _export_png(client, asset)
    assert out.format == "ushort"


def test_alpha_is_kept(client: httpx.Client) -> None:
    rgb = _scene()
    alpha = (pyvips.Image.xyz(rgb.width, rgb.height)[0] > rgb.width // 2).ifthenelse(255, 0).cast("uchar")
    asset = _ingest(client, rgb.bandjoin(alpha).pngsave_buffer(), "cutout.png")
    assert asset["has_alpha"] is True
    out = _export_png(client, asset)
    assert out.hasalpha()
    assert out[3].min() == 0 and out[3].max() == 255


@pytest.mark.parametrize(
    ("name", "make"),
    [
        ("grey.png", lambda img: img.colourspace("b-w").pngsave_buffer()),
        ("palette.png", lambda img: img.pngsave_buffer(palette=True, bitdepth=8)),
        ("one-bit.png", lambda img: (img.colourspace("b-w") > 128).pngsave_buffer(bitdepth=1)),
    ],
)
def test_grey_palette_and_one_bit_images_open(client: httpx.Client, name: str, make: Any) -> None:
    asset = _ingest(client, make(_scene()), name)
    assert (asset["width"], asset["height"]) == (480, 320)
    out = _export_png(client, asset)
    assert (out.width, out.height) == (480, 320)


def test_animated_gif_uses_the_first_frame(client: httpx.Client) -> None:
    frames = [_scene(), _scene().invert()]
    strip = pyvips.Image.arrayjoin(frames, across=1)
    strip = strip.copy()
    strip.set_type(pyvips.GValue.gint_type, "page-height", 320)
    asset = _ingest(client, strip.gifsave_buffer(), "animated.gif")
    assert (asset["width"], asset["height"]) == (480, 320)


@pytest.mark.parametrize(
    ("name", "kwargs"), [("photo.heic", {"compression": "hevc"}), ("photo.avif", {"compression": "av1"})]
)
def test_heic_and_avif_open(client: httpx.Client, name: str, kwargs: dict[str, Any]) -> None:
    try:
        data = _scene().heifsave_buffer(Q=60, **kwargs)
    except pyvips.Error as exc:
        pytest.skip(f"this libvips can't write {name}: {exc}")
    asset = _ingest(client, data, name)
    assert (asset["width"], asset["height"]) == (480, 320)


def test_tiny_image_runs_through_ai(client: httpx.Client) -> None:
    """Smaller than any tile: padded, processed, cropped."""
    asset = _ingest(client, _scene(24, 16).pngsave_buffer(), "tiny.png")
    models = {m["id"]: m for m in client.get("/api/models").json()}
    if models.get("realesr-general-x4v3", {}).get("status") != "installed":
        pytest.skip("Real-ESRGAN General v3 isn't installed")
    started = client.post("/api/ai/runs", json={"asset_id": asset["id"], "model_id": "realesr-general-x4v3"})
    assert started.status_code == 201, started.text
    deadline = time.monotonic() + 300
    while (job := client.get(f"/api/jobs/{started.json()['job']['id']}").json())["state"] not in (
        "succeeded",
        "failed",
    ):
        assert time.monotonic() < deadline, job
        time.sleep(1)
    assert job["state"] == "succeeded", job
    result = client.get(f"/api/assets/{job['result']['asset_id']}").json()
    _assets.append(result["id"])
    assert (result["width"], result["height"]) == (96, 64)
