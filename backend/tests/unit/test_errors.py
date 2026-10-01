from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from siqe.core.errors import PROBLEM_JSON, AppError, NotFoundError, register_error_handlers


class Body(BaseModel):
    scale: int


def make_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/too-large")
    async def too_large() -> None:
        raise AppError(
            "image.too_large",
            "The image is 400 MP; the limit is 250 MP.",
            status=413,
            fix="Downscale it first or raise SIQE_MAX_INPUT_MEGAPIXELS.",
            limit_megapixels=250,
        )

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError("job.not_found", "No such job.")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.post("/validate")
    async def validate(body: Body) -> Body:
        return body

    return TestClient(app, raise_server_exceptions=False)


def test_app_error_is_problem_json_with_fix_and_extras() -> None:
    response = make_client().get("/too-large")
    assert response.status_code == 413
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["code"] == "image.too_large"
    assert body["type"] == "urn:siqe:error:image.too_large"
    assert body["fix"].startswith("Downscale")
    assert body["limit_megapixels"] == 250
    assert body["instance"] == "/too-large"


def test_subclass_carries_its_status() -> None:
    response = make_client().get("/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "job.not_found"


def test_unexpected_errors_do_not_leak_details() -> None:
    response = make_client().get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal.error"
    assert "secret" not in response.text


def test_validation_errors_are_listed() -> None:
    response = make_client().post("/validate", json={"scale": "big"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "request.invalid"
    assert body["errors"][0]["loc"][-1] == "scale"
