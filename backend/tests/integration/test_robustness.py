"""8K and larger, against a running stack: admission, previews, exports, AI plans, the Library and flows.

Images are generated with libvips (streamed, so the test itself stays small) and are new on every
run. While the big ones are processed, the worker containers' memory is sampled with `docker stats`
(skipped where the Docker CLI isn't available) and must stay inside their Compose limits.
"""

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pyvips

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")
UNITS = {"b": 1, "kib": 2**10, "mib": 2**20, "gib": 2**30, "kb": 1e3, "mb": 1e6, "gb": 1e9}

_assets: list[str] = []
_flows: list[str] = []


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE, timeout=300) as c:
        deadline = time.monotonic() + 120
        while c.get("/api/health/ready").json().get("status") != "ok":
            if time.monotonic() > deadline:
                pytest.fail("stack did not become ready within 120 s")
            time.sleep(2)
        yield c
        for flow_id in _flows:
            c.delete(f"/api/flows/{flow_id}")
        for asset_id in _assets:
            c.delete(f"/api/assets/{asset_id}")


@pytest.fixture(scope="module")
def workdir() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="siqe-robust-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _photo(width: int, height: int) -> pyvips.Image:
    """Photo-like content (soft noise in three bands plus a random tint), never the same twice."""
    seed = uuid.uuid4().int % 1000
    bands = [
        pyvips.Image.perlin(width, height, cell_size=97 + seed % 50 + 13 * i, uchar=True) for i in range(3)
    ]
    rgb = bands[0].bandjoin(bands[1:]).linear([1, 0.9, 0.8], [seed % 40, 10, 30]).cast("uchar")
    return rgb.copy(interpretation="srgb")


def _upload_file(client: httpx.Client, path: Path) -> httpx.Response:
    with path.open("rb") as f:
        return client.post(
            "/api/assets",
            params={"filename": path.name},
            content=f,
            headers={"Content-Type": "application/octet-stream"},
        )


def _wait_job(client: httpx.Client, job_id: str, seconds: float = 600) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        job = dict(client.get(f"/api/jobs/{job_id}").json())
        if job["state"] in ("succeeded", "failed", "cancelled"):
            return job
        if time.monotonic() > deadline:
            pytest.fail(f"job stuck in {job['state']}: {job['message']}")
        time.sleep(1)


def _ingest(client: httpx.Client, path: Path, seconds: float = 900) -> dict[str, Any]:
    response = _upload_file(client, path)
    assert response.status_code == 201, response.text
    body = response.json()
    _assets.append(body["asset"]["id"])
    job = _wait_job(client, body["job"]["id"], seconds)
    assert job["state"] == "succeeded", job
    return dict(client.get(f"/api/assets/{body['asset']['id']}").json())


def _bytes(text: str) -> float:
    match = re.match(r"([\d.]+)\s*([a-zA-Z]+)", text.strip())
    if not match:
        return 0.0
    return float(match.group(1)) * UNITS.get(match.group(2).lower(), 1)


class MemoryWatch:
    """Peak memory per container (from `docker stats`) while a block runs."""

    def __init__(self, names: tuple[str, ...] = ("worker-1", "worker-gpu-1", "api-1")) -> None:
        self.names = names
        self.peak: dict[str, float] = {}
        self.limit: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.available = shutil.which("docker") is not None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                ).stdout
            except (OSError, subprocess.SubprocessError):
                self.available = False
                return
            for line in out.splitlines():
                name, _, usage = line.partition("\t")
                if not any(name.endswith(n) for n in self.names) or "/" not in usage:
                    continue
                used, limit = (_bytes(part) for part in usage.split("/"))
                self.peak[name] = max(self.peak.get(name, 0.0), used)
                self.limit[name] = limit

    def __enter__(self) -> "MemoryWatch":
        if self.available:
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self.available:
            self._thread.join(timeout=30)

    def check(self) -> None:
        for name, peak in self.peak.items():
            assert peak < self.limit[name] * 0.95, f"{name} peaked at {peak / 2**30:.2f} GiB of its limit"


@pytest.fixture(scope="module")
def photo_8k(client: httpx.Client, workdir: Path) -> dict[str, Any]:
    path = workdir / f"8k-{uuid.uuid4().hex[:6]}.jpg"
    _photo(7680, 4320).jpegsave(str(path), Q=90)
    with MemoryWatch() as memory:
        asset = _ingest(client, path)
    memory.check()
    return asset


def test_8k_photo_gets_previews_and_deep_zoom(client: httpx.Client, photo_8k: dict[str, Any]) -> None:
    assert (photo_8k["width"], photo_8k["height"]) == (7680, 4320)
    assert photo_8k["status"] == "ready"
    for key in ("thumb_url", "preview_url", "dzi_url"):
        assert client.get(photo_8k[key]).status_code == 200, key
    preview = pyvips.Image.new_from_buffer(client.get(photo_8k["preview_url"]).content, "")
    assert max(preview.width, preview.height) == 2048
    dzi = client.get(photo_8k["dzi_url"]).text
    assert 'Width="7680"' in dzi and 'Height="4320"' in dzi


def test_8k_exports_full_size_with_edits(client: httpx.Client, photo_8k: dict[str, Any]) -> None:
    doc = {"version": 1, "ops": [{"id": "exposure", "params": {"ev": 0.3}}, {"id": "sharpen", "params": {}}]}
    client.put(f"/api/assets/{photo_8k['id']}/edits", json=doc).raise_for_status()
    with MemoryWatch() as memory:
        for fmt in ("jpeg", "png"):
            started = client.post(f"/api/assets/{photo_8k['id']}/exports", json={"format": fmt})
            assert started.status_code == 201, started.text
            job = _wait_job(client, started.json()["job"]["id"])
            assert job["state"] == "succeeded", job
            rendition = started.json()["rendition"]
            assert (rendition["width"], rendition["height"]) == (7680, 4320)
            head = client.get(
                next(
                    r["download_url"]
                    for r in client.get(f"/api/assets/{photo_8k['id']}/renditions").json()
                    if r["id"] == rendition["id"]
                )
            )
            image = pyvips.Image.new_from_buffer(head.content, "", access="sequential")
            assert (image.width, image.height) == (7680, 4320)
    memory.check()


def test_8k_upscale_plan_stays_within_limits(client: httpx.Client, photo_8k: dict[str, Any]) -> None:
    plan = client.post(
        "/api/ai/plan", json={"asset_id": photo_8k["id"], "model_id": "realesr-general-x4v3"}
    ).json()
    assert (plan["output_width"], plan["output_height"]) == (30720, 17280)
    assert plan["output_megapixels"] == pytest.approx(530.8, abs=0.1)
    assert plan["tiles"] > 1
    assert plan["disk_bytes"] > 0


def test_8k_is_indexed_by_the_library(client: httpx.Client, photo_8k: dict[str, Any]) -> None:
    deadline = time.monotonic() + 300
    while not client.get(f"/api/assets/{photo_8k['id']}").json()["analysed"]:
        assert time.monotonic() < deadline, "the 8K image was never analysed"
        time.sleep(2)


def test_8k_runs_through_a_flow(client: httpx.Client, photo_8k: dict[str, Any]) -> None:
    document = {
        "version": 1,
        "nodes": [
            {"id": "in", "type": "input", "params": {}, "position": {"x": 0, "y": 0}},
            {"id": "size", "type": "resize", "params": {"size": 3840}, "position": {"x": 200, "y": 0}},
            {"id": "out", "type": "export", "params": {"format": "jpeg"}, "position": {"x": 400, "y": 0}},
        ],
        "edges": [
            {"source": "in", "target": "size", "port": "out"},
            {"source": "size", "target": "out", "port": "out"},
        ],
    }
    flow = client.post("/api/flows", json={"name": f"8K test {uuid.uuid4().hex[:6]}", "document": document})
    assert flow.status_code == 201, flow.text
    _flows.append(flow.json()["id"])
    assert flow.json()["problems"] == [], flow.json()["problems"]
    started = client.post(
        f"/api/flows/{flow.json()['id']}/runs",
        json={"source": {"kind": "assets", "asset_ids": [photo_8k["id"]]}, "dry_run": True},
    )
    assert started.status_code == 201, started.text
    run = started.json()
    deadline = time.monotonic() + 600
    while True:
        response = client.get(f"/api/flows/runs/{run['id']}")
        assert response.status_code == 200, response.text
        detail = response.json()
        if detail["run"]["state"] not in ("queued", "running"):
            break
        assert time.monotonic() < deadline, "flow run stuck"
        time.sleep(1)
    assert detail["run"]["state"] == "succeeded", detail["run"]
    assert detail["items"][0]["state"] == "done", detail["items"][0]


def test_240_megapixels_is_admitted_and_handled_in_bounded_memory(
    client: httpx.Client, workdir: Path
) -> None:
    path = workdir / f"240mp-{uuid.uuid4().hex[:6]}.jpg"
    _photo(16000, 15000).jpegsave(str(path), Q=80)
    with MemoryWatch() as memory:
        asset = _ingest(client, path, seconds=1800)
    memory.check()
    assert (asset["width"], asset["height"]) == (16000, 15000)
    assert client.get(asset["preview_url"]).status_code == 200


def test_over_the_limit_is_refused_from_the_header(client: httpx.Client, workdir: Path) -> None:
    """300 MP of black compresses to a small PNG; it must be refused without decoding it."""
    path = workdir / "too-big.png"
    pyvips.Image.black(20000, 15000, bands=3).cast("uchar").pngsave(str(path), compression=1)
    started = time.monotonic()
    response = _upload_file(client, path)
    assert response.status_code == 413, response.text
    assert response.json()["code"] == "image.too_large"
    assert time.monotonic() - started < 30


def test_extreme_panorama_is_handled(client: httpx.Client, workdir: Path) -> None:
    path = workdir / f"panorama-{uuid.uuid4().hex[:6]}.jpg"
    _photo(40000, 300).jpegsave(str(path), Q=85)
    asset = _ingest(client, path)
    assert (asset["width"], asset["height"]) == (40000, 300)
    preview = pyvips.Image.new_from_buffer(client.get(asset["preview_url"]).content, "")
    assert preview.width == 2048 and preview.height >= 1
    thumb = pyvips.Image.new_from_buffer(client.get(asset["thumb_url"]).content, "")
    assert max(thumb.width, thumb.height) <= 320


def test_truncated_8k_jpeg_is_rejected_cleanly(client: httpx.Client, workdir: Path) -> None:
    whole = _photo(7680, 4320).jpegsave_buffer(Q=90)
    path = workdir / "cut-off.jpg"
    path.write_bytes(whole[: len(whole) // 3])
    response = _upload_file(client, path)
    if response.status_code == 201:
        # Accepted at the door (the header is fine); preparing it must fail with a typed error.
        _assets.append(response.json()["asset"]["id"])
        job = _wait_job(client, response.json()["job"]["id"])
        assert job["state"] == "failed"
        assert job["error"]["code"] == "image.unreadable", job["error"]
    else:
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "image.unreadable"
