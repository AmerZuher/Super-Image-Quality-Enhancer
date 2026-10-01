"""End-to-end checks against a running stack (`make up`, then `make test-integration`).

Set SIQE_TEST_BASE_URL to point somewhere other than http://localhost:8080.
"""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE = os.environ.get("SIQE_TEST_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE, timeout=30) as c:
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


def test_system_reports_both_workers(client: httpx.Client) -> None:
    deadline = time.monotonic() + 60
    while True:
        workers = client.get("/api/system").json()["workers"]
        kinds = {w["kind"] for w in workers if w["online"]}
        if {"cpu", "gpu"} <= kinds:
            return
        if time.monotonic() > deadline:
            pytest.fail(f"online workers: {kinds}")
        time.sleep(2)


def test_self_test_runs_to_completion(client: httpx.Client) -> None:
    job = client.post("/api/jobs/self-test").raise_for_status().json()
    assert job["state"] == "queued"
    deadline = time.monotonic() + 300
    while True:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            break
        if time.monotonic() > deadline:
            pytest.fail(f"self-test stuck in {job['state']}: {job['message']}")
        time.sleep(1)
    assert job["state"] == "succeeded", job
    assert job["progress"] == 1.0
    assert job["result"]["cpu"]["imaging"]["libvips"]
    assert job["result"]["gpu"]["benchmarks"]


def test_unknown_job_is_problem_json(client: httpx.Client) -> None:
    response = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "job.not_found"


def test_update_status_shape(client: httpx.Client) -> None:
    body = client.get("/api/updates").json()
    assert body["current_version"]
    assert body["releases_url"].endswith("/releases")
