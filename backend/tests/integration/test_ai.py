"""Model downloads and AI runs against a running stack (downloads ~185 MB from GitHub once)."""

import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import pyvips

from siqe.ai.manifest import COMMERCIAL_SAFE

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
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
def photo(client: httpx.Client) -> Iterator[dict[str, Any]]:
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
    assert {m["license"] for m in shipped} <= set(COMMERCIAL_SAFE)
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


def _result(client: httpx.Client, photo: dict[str, Any], model_id: str, **extra: Any) -> dict[str, Any]:
    started = client.post("/api/ai/runs", json={"asset_id": photo["id"], "model_id": model_id, **extra})
    assert started.status_code == 201, started.text
    job = wait(client, started.json()["job"]["id"])
    assert job["state"] == "succeeded", job
    return dict(client.get(f"/api/assets/{job['result']['asset_id']}").json())


def _pixels(client: httpx.Client, asset: dict[str, Any]) -> Any:
    import numpy as np

    image = pyvips.Image.new_from_buffer(client.get(asset["original_url"]).content, "")
    return np.asarray(image.numpy(), np.int32)


def test_erase_fills_the_painted_area_and_needs_a_mask(client: httpx.Client, photo: dict[str, Any]) -> None:
    install(client, "lama-erase")
    planned = client.post("/api/ai/plan", json={"asset_id": photo["id"], "model_id": "lama-erase"})
    assert planned.status_code == 200  # the plan shows before anything is painted
    assert (planned.json()["output_width"], planned.json()["output_height"]) == (160, 120)
    refused = client.post("/api/ai/runs", json={"asset_id": photo["id"], "model_id": "lama-erase"})
    assert refused.status_code == 422 and refused.json()["code"] == "erase.mask_required"
    # Paint over the bright square (x 50..110, y 30..90 of 160×120).
    mask = {"strokes": [{"points": [[0.4, 0.5], [0.6, 0.5]], "radius": 0.2}]}
    result = _result(client, photo, "lama-erase", mask=mask)
    assert (result["width"], result["height"]) == (160, 120)
    assert result["original_name"].endswith("retouched.png")
    before, after = _pixels(client, photo), _pixels(client, result)
    assert before[60, 80, 0] > 200  # the square was bright
    assert after[60, 80, 0] < 120  # and is filled in with the dark background
    assert abs(int(after[5, 5, 0]) - int(before[5, 5, 0])) <= 2  # far away nothing changed


def test_colorize_adds_colour_and_keeps_size(client: httpx.Client, photo: dict[str, Any]) -> None:
    install(client, "siggraph17-colorize")
    result = _result(client, photo, "siggraph17-colorize")
    assert (result["width"], result["height"]) == (160, 120)
    assert result["original_name"].endswith("colorized.png")


def test_deblur_runs_on_the_cpu_and_keeps_size(client: httpx.Client, photo: dict[str, Any]) -> None:
    install(client, "nafnet-deblur")
    plan = client.post("/api/ai/plan", json={"asset_id": photo["id"], "model_id": "nafnet-deblur"}).json()
    assert plan["device"] == "cpu"
    result = _result(client, photo, "nafnet-deblur")
    assert (result["width"], result["height"]) == (160, 120)
    assert result["derivation"]["device_name"] == "CPU"


# ------------------------------------------------------------------ your own ONNX models


def _onnx_upscaler(factor: int) -> bytes:
    """A tiny nearest-neighbour ×factor model, exported the way a user would bring one."""
    from onnx import TensorProto, helper

    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, ["n", 3, "h", "w"])
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, ["n", 3, "H", "W"])
    scales = helper.make_tensor("scales", TensorProto.FLOAT, [4], [1, 1, factor, factor])
    node = helper.make_node("Resize", ["input", "", "scales"], ["output"], mode="nearest")
    model = helper.make_model(
        helper.make_graph([node], "upscale", [x], [y], [scales]),
        opset_imports=[helper.make_opsetid("", 17)],
    )
    model.ir_version = 9
    return bytes(model.SerializeToString())


def _add_onnx(client: httpx.Client, content: bytes, filename: str, **params: str) -> httpx.Response:
    return client.post(
        "/api/models/onnx",
        params={"filename": filename, **params},
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )


def test_your_own_onnx_model_is_checked_added_run_and_removed(
    client: httpx.Client, photo: dict[str, Any]
) -> None:
    name = f"Test x2 {uuid.uuid4().hex[:6]}"
    added = _add_onnx(client, _onnx_upscaler(2), "nearest_x2.onnx", name=name)
    assert added.status_code == 202, added.text
    model_id = added.json()["model_id"]
    assert model_id.startswith("user-test-x2-")
    job = wait(client, added.json()["job"]["id"], 300)
    assert job["state"] == "succeeded", job
    assert job["result"]["scale"] == 2 and job["result"]["task"] == "upscale"
    try:
        model = next(m for m in client.get("/api/models").json() if m["id"] == model_id)
        assert (model["source"], model["status"], model["arch"]) == ("user", "installed", "onnx")
        assert model["scale"] == 2
        assert model["name"] == name and model["license"] == "Your own"
        assert model["probe"]["multiple"] == 1 and model["probe"]["output_range"] == 1

        plan = client.post("/api/ai/plan", json={"asset_id": photo["id"], "model_id": model_id}).json()
        assert plan["device"] == "cpu" and (plan["output_width"], plan["output_height"]) == (320, 240)
        result = _result(client, photo, model_id)
        assert (result["width"], result["height"]) == (320, 240)
        before, after = _pixels(client, photo), _pixels(client, result)
        assert abs(int(after[121, 161, 0]) - int(before[60, 80, 0])) <= 2  # nearest ×2

        # In a flow, the Upscale block sends this model to the CPU worker.
        def node(node_id: str, kind: str, x: int, **params: Any) -> dict[str, Any]:
            return {"id": node_id, "type": kind, "params": params, "position": {"x": x, "y": 0}}

        document = {
            "version": 1,
            "nodes": [
                node("in", "input", 0),
                node("up", "upscale", 200, model=model_id),
                node("out", "export", 400),
            ],
            "edges": [
                {"source": "in", "target": "up", "port": "out"},
                {"source": "up", "target": "out", "port": "out"},
            ],
        }
        flow = client.post("/api/flows", json={"name": f"Own model {name}", "document": document}).json()
        assert flow["problems"] == [], flow["problems"]
        try:
            started = client.post(
                f"/api/flows/{flow['id']}/runs",
                json={"source": {"kind": "assets", "asset_ids": [photo["id"]]}, "dry_run": True},
            )
            assert started.status_code == 201, started.text
            run_url = f"/api/flows/runs/{started.json()['id']}"
            deadline = time.monotonic() + 300
            while (detail := client.get(run_url).json())["run"]["state"] not in ("succeeded", "failed"):
                assert time.monotonic() < deadline, detail["run"]
                time.sleep(1)
            assert detail["run"]["state"] == "succeeded", detail
            assert detail["items"][0]["outputs"][0]["width"] == 320
        finally:
            client.delete(f"/api/flows/{flow['id']}")
    finally:
        assert client.delete(f"/api/models/{model_id}").status_code == 204
    assert model_id not in {m["id"] for m in client.get("/api/models").json()}


def test_onnx_files_that_cant_run_are_refused_with_a_fix(client: httpx.Client) -> None:
    wrong = _add_onnx(client, b"not a model", "notes.txt")
    assert wrong.status_code == 415 and wrong.json()["code"] == "onnx.wrong_type"

    broken = _add_onnx(client, b"\x08\x07 definitely not protobuf", "broken.onnx")
    job = wait(client, broken.json()["job"]["id"], 120)
    assert job["state"] == "failed" and job["error"]["code"] == "model.load_failed"
    assert job["error"]["fix"]
    assert broken.json()["model_id"] not in {m["id"] for m in client.get("/api/models").json()}
