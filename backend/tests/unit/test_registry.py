import hashlib
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from safetensors.numpy import load_file

from siqe.ai import registry
from siqe.ai.manifest import COMMERCIAL_SAFE, MODELS, ModelFile, ModelSpec
from siqe.core.errors import AppError
from tests.unit.ai_helpers import write_fake_v10


def test_catalog_is_commercial_safe_and_pinned() -> None:
    ids = [m.id for m in MODELS]
    assert len(ids) == len(set(ids))
    for m in MODELS:
        assert m.license in COMMERCIAL_SAFE, m.id
        assert m.files, m.id
        for f in m.files:
            assert re.fullmatch(r"[0-9a-f]{64}", f.sha256), f.name
            assert f.url.startswith("https://") and f.size > 0
            assert "huggingface.co" not in f.url
    classic = registry.get_spec("siqe-classic")
    assert classic.weights.stored_name.endswith(".safetensors")
    with pytest.raises(AppError) as err:
        registry.get_spec("nope")
    assert err.value.code == "model.not_found"


class BrokenStream(httpx.SyncByteStream):
    """Sends part of the body, then the connection drops."""

    def __init__(self, body: bytes, cut: int) -> None:
        self.body = body
        self.cut = cut

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield self.body[: self.cut]
        raise httpx.ReadError("connection reset")


def server(payload: bytes, *, honour_range: bool = True, fail_after: int | None = None):  # type: ignore[no-untyped-def]
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        body = payload
        status = 200
        rng = request.headers.get("range")
        if rng and honour_range:
            start = int(rng.split("=")[1].rstrip("-"))
            body = payload[start:]
            status = 206
        if fail_after is not None:
            return httpx.Response(status, stream=BrokenStream(body, fail_after))
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def file_for(payload: bytes, name: str = "w.pth") -> ModelFile:
    return ModelFile(name, f"https://example.test/{name}", hashlib.sha256(payload).hexdigest(), len(payload))


PAYLOAD = bytes(range(256)) * 9000  # ~2.3 MB, several chunks


def test_downloads_and_verifies(tmp_path: Path) -> None:
    client, _ = server(PAYLOAD)
    seen: list[int] = []
    path = registry.download_file(
        client, file_for(PAYLOAD), tmp_path / "m/w.pth", tmp_path / "tmp", on_bytes=seen.append
    )
    assert path.read_bytes() == PAYLOAD
    assert seen[-1] == len(PAYLOAD)
    assert not list((tmp_path / "tmp").iterdir())


def test_interrupted_download_resumes_with_range(tmp_path: Path) -> None:
    f = file_for(PAYLOAD)
    broken, _ = server(PAYLOAD, fail_after=1_000_000)
    with pytest.raises(AppError) as err:
        registry.download_file(broken, f, tmp_path / "w.pth", tmp_path / "tmp")
    assert err.value.code == "model.download_failed"
    partial = next((tmp_path / "tmp").iterdir())
    assert partial.stat().st_size == 1_000_000
    client, calls = server(PAYLOAD)
    registry.download_file(client, f, tmp_path / "w.pth", tmp_path / "tmp")
    assert calls[0]["range"] == "bytes=1000000-"
    assert (tmp_path / "w.pth").read_bytes() == PAYLOAD


def test_server_ignoring_range_starts_over(tmp_path: Path) -> None:
    f = file_for(PAYLOAD)
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / f"model-{f.sha256[:16]}.partial").write_bytes(PAYLOAD[:500])
    client, _ = server(PAYLOAD, honour_range=False)
    registry.download_file(client, f, tmp_path / "w.pth", tmp_path / "tmp")
    assert (tmp_path / "w.pth").read_bytes() == PAYLOAD


def test_corrupted_download_is_deleted(tmp_path: Path) -> None:
    client, _ = server(PAYLOAD[:-1] + b"\x00")
    with pytest.raises(AppError) as err:
        registry.download_file(client, file_for(PAYLOAD), tmp_path / "w.pth", tmp_path / "tmp")
    assert err.value.code == "model.checksum_mismatch"
    assert not (tmp_path / "w.pth").exists()
    assert not list((tmp_path / "tmp").iterdir())


def test_verified_file_is_not_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "w.pth").write_bytes(PAYLOAD)
    client, calls = server(PAYLOAD)
    registry.download_file(client, file_for(PAYLOAD), tmp_path / "w.pth", tmp_path / "tmp")
    assert calls == []


def test_http_errors_are_typed(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(AppError) as err:
        registry.download_file(client, file_for(PAYLOAD), tmp_path / "w.pth", tmp_path / "tmp")
    assert "404" in err.value.detail


def test_install_converts_siqe_classic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(registry, "models_root", lambda: tmp_path / "models")
    write_fake_v10(tmp_path / "v10.h5")
    payload = (tmp_path / "v10.h5").read_bytes()
    spec = ModelSpec(
        id="siqe-classic",
        name="SIQE Classic",
        task="upscale",
        arch="siqe_classic",
        scale=3,
        summary="",
        license="MIT",
        license_url="",
        homepage="",
        files=(
            ModelFile(
                "v10.h5",
                "https://example.test/v10.h5",
                hashlib.sha256(payload).hexdigest(),
                len(payload),
                convert_to="v10.safetensors",
            ),
        ),
    )
    client, _ = server(payload)
    progress: list[tuple[int, int]] = []
    path = registry.install_files(spec, client, on_progress=lambda d, t: progress.append((d, t)))
    assert path == tmp_path / "models/siqe-classic/v10.safetensors"
    assert load_file(str(path))["entry.weight"].shape == (64, 1, 5, 5)
    assert not (tmp_path / "models/siqe-classic/v10.h5").exists()
    assert progress[-1] == (len(payload), len(payload))
    assert registry.files_present(spec)
