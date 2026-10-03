import json
from pathlib import Path

import pytest
import pyvips

from siqe.core.errors import AppError
from siqe.imaging import ops
from siqe.imaging.edits import EditDocument, Geometry, catalog, parse_document
from siqe.imaging.export import ExportOptions, check_dimensions, encode
from siqe.imaging.io import inspect, open_image
from siqe.imaging.parity import render as render_fixture
from siqe.imaging.pipeline import apply_geometry, output_size, render, render_working, resize_to
from siqe.imaging.working import from_working, to_working

FIXTURE = Path(__file__).parents[1] / "fixtures" / "ops_parity.json"


def save(image: pyvips.Image, path: Path) -> Path:
    image.write_to_file(str(path))
    return path


def gradient(width: int = 64, height: int = 48) -> pyvips.Image:
    xy = pyvips.Image.xyz(width, height)
    r = xy[0] * (255 / (width - 1))
    g = xy[1] * (255 / (height - 1))
    b = (r + g) / 2
    return r.bandjoin([g, b]).cast("uchar").copy(interpretation="srgb")


# --------------------------------------------------------------------------- admission


def test_inspect_reads_header(tmp_path: Path) -> None:
    info = inspect(save(gradient(), tmp_path / "a.png"))
    assert (info.format, info.width, info.height, info.bit_depth, info.has_alpha) == ("png", 64, 48, 8, False)


def test_too_large_is_refused_before_decoding(tmp_path: Path) -> None:
    path = save(gradient(400, 300), tmp_path / "big.jpg")
    with pytest.raises(AppError) as err:
        inspect(path, max_megapixels=0)
    assert err.value.code == "image.too_large"
    assert err.value.status == 413


def test_garbage_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "fake.jpg"
    path.write_bytes(b"not an image at all")
    with pytest.raises(AppError) as err:
        inspect(path)
    assert err.value.code == "image.unreadable"


def test_truncated_file_fails_cleanly(tmp_path: Path) -> None:
    path = save(gradient(256, 256), tmp_path / "t.jpg")
    path.write_bytes(path.read_bytes()[:400])
    with pytest.raises((AppError, pyvips.Error)):
        render(path, EditDocument()).rgb.avg()


# ----------------------------------------------------------------------- edit document


def test_noop_ops_are_dropped_and_order_is_canonical() -> None:
    doc = parse_document(
        {
            "ops": [
                {"id": "contrast", "params": {"amount": 20}},
                {"id": "exposure", "params": {"ev": 0.5}},
                {"id": "saturation", "params": {"amount": 0}},
                {"id": "black_white"},
            ]
        }
    )
    assert [e.id for e in doc.ops] == ["exposure", "contrast", "black_white"]


@pytest.mark.parametrize(
    "raw",
    [
        {"ops": [{"id": "melt"}]},
        {"ops": [{"id": "exposure", "params": {"ev": 9}}]},
        {"ops": [{"id": "exposure", "params": {"stops": 1}}]},
        {"ops": [{"id": "contrast", "params": {"amount": 5}}, {"id": "contrast", "params": {"amount": 6}}]},
        {"geometry": {"crop": {"x": 0.6, "y": 0, "w": 0.6, "h": 1}}},
        {"geometry": {"rotate": 45}},
    ],
)
def test_invalid_documents_are_rejected(raw: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(AppError) as err:
        parse_document(raw)
    assert err.value.code == "edit.invalid"


def test_catalog_lists_every_op_with_ranges() -> None:
    entries = {c["id"]: c for c in catalog()}
    assert entries["exposure"]["params"][0]["min"] == -4
    assert entries["black_white"]["params"] == []


# ---------------------------------------------------------------- formulas and parity


def test_fixture_is_up_to_date() -> None:
    assert FIXTURE.read_text() == render_fixture(), "run: uv run python -m siqe.imaging.parity"


def test_libvips_path_matches_reference_formulas() -> None:
    data = json.loads(FIXTURE.read_text())
    for case in data["cases"]:
        pixel = pyvips.Image.black(1, 1, bands=3).cast("float") + case["rgb"]
        out = ops.apply_adjustments(pixel, case["ops"])
        got = [out[i].avg() for i in range(3)]
        assert got == pytest.approx(case["expected"], abs=data["tolerance"]), case


def test_exposure_one_stop_doubles_linear_light() -> None:
    c = ops.apply_pixel((0.5, 0.5, 0.5), {"exposure": {"ev": 1}})
    assert ops._srgb_to_linear(c[0]) == pytest.approx(2 * ops._srgb_to_linear(0.5), abs=1e-6)


def test_negative_vignette_leaves_centre_and_darkens_corners() -> None:
    gain = ops.vignette_map(101, 101, -80, 0.3)
    assert gain.getpoint(50, 50)[0] == pytest.approx(1.0)
    assert gain.getpoint(0, 0)[0] == pytest.approx(ops.vignette_gain(0, 0, 101, 101, -80, 0.3), abs=1e-5)
    assert gain.getpoint(0, 0)[0] < 0.3
    assert ops.vignette_map(101, 101, 50, 0.3).getpoint(0, 0)[0] > 1.4


def test_sharpen_increases_local_contrast(tmp_path: Path) -> None:
    edge = (pyvips.Image.xyz(40, 40)[0] > 19).ifthenelse(200, 60).cast("uchar")
    path = save(edge.bandjoin([edge, edge]).copy(interpretation="srgb"), tmp_path / "edge.png")
    plain = render(path, EditDocument()).rgb
    sharp = render(
        path, parse_document({"ops": [{"id": "sharpen", "params": {"amount": 150, "radius": 1.5}}]})
    ).rgb
    assert sharp.getpoint(19, 20)[0] < plain.getpoint(19, 20)[0]
    assert sharp.getpoint(20, 20)[0] > plain.getpoint(20, 20)[0]


# -------------------------------------------------------------------------- geometry


@pytest.mark.parametrize(
    ("geometry", "size"),
    [
        (Geometry(), (64, 48)),
        (Geometry(rotate=90), (48, 64)),
        (Geometry(rotate=270, crop={"x": 0, "y": 0, "w": 0.5, "h": 0.25}), (24, 16)),
        (Geometry(crop={"x": 0.25, "y": 0.5, "w": 0.5, "h": 0.5}), (32, 24)),
    ],
)
def test_geometry_sizes(geometry: Geometry, size: tuple[int, int]) -> None:
    out = apply_geometry(gradient(), geometry)
    assert (out.width, out.height) == size
    assert output_size(64, 48, geometry) == size


def test_rotate_then_flip_maps_corners() -> None:
    src = gradient()
    out = apply_geometry(src, Geometry(rotate=90, flip_h=True))
    # Rotating clockwise puts the source's top-left at the top-right; flipping moves it back left.
    assert out.getpoint(0, 0) == src.getpoint(0, 0)


def test_exif_orientation_is_applied(tmp_path: Path) -> None:
    img = gradient().copy()
    img.set_type(pyvips.GValue.gint_type, "orientation", 6)
    path = save(img, tmp_path / "o.jpg")
    work = to_working(open_image(path))
    assert (work.width, work.height) == (48, 64)


# -------------------------------------------------------------------- bit depth, alpha


def test_sixteen_bit_survives_round_trip(tmp_path: Path) -> None:
    img = (gradient().cast("ushort") * 257).cast("ushort").copy(interpretation="rgb16")
    work = to_working(open_image(save(img, tmp_path / "16.png")))
    assert work.depth == 16
    out = from_working(work, depth=16)
    assert out.format == "ushort"
    assert out.getpoint(63, 47) == img.getpoint(63, 47)


def test_alpha_is_kept_apart_and_reattached(tmp_path: Path) -> None:
    rgba = gradient().bandjoin(128)
    work = to_working(open_image(save(rgba.copy(interpretation="srgb"), tmp_path / "a.png")))
    assert work.alpha is not None
    out = from_working(render_working(work, parse_document({"ops": [{"id": "black_white"}]})))
    assert out.bands == 4
    assert out.getpoint(10, 10)[3] == 128


def test_alpha_is_flattened_onto_white_without_transparency(tmp_path: Path) -> None:
    clear = (gradient() * 0).bandjoin(0).copy(interpretation="srgb")
    work = to_working(open_image(save(clear, tmp_path / "clear.png")))
    out = from_working(work, keep_alpha=False)
    assert out.bands == 3
    assert out.getpoint(5, 5) == [255, 255, 255]


# ----------------------------------------------------------------------------- export


def test_webp_dimension_limit() -> None:
    with pytest.raises(AppError) as err:
        check_dimensions(20_000, 100, ExportOptions(format="webp"))
    assert err.value.code == "format.dimension_limit"
    check_dimensions(20_000, 100, ExportOptions(format="png"))


def test_target_size_needs_lossy_format() -> None:
    with pytest.raises(ValueError):
        ExportOptions(format="png", target_kb=100)


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp", "avif", "tiff"])
def test_encode_every_format(tmp_path: Path, fmt: str) -> None:
    work = render(save(gradient(), tmp_path / "src.png"), EditDocument())
    options = ExportOptions(format=fmt)  # type: ignore[arg-type]
    seen: list[float] = []
    result = encode(work, options, tmp_path / f"out.{fmt}", tmp_path / "tmp", progress=seen.append)
    assert result.path.exists() and result.size_bytes > 0
    assert (result.width, result.height) == (64, 48)
    assert pyvips.Image.new_from_file(str(result.path)).width == 64
    assert seen[-1] == pytest.approx(1.0)
    assert not list((tmp_path / "tmp").iterdir())


def test_target_size_is_met(tmp_path: Path) -> None:
    noise = pyvips.Image.gaussnoise(800, 600, sigma=60).cast("uchar")
    src = save(noise.bandjoin([noise, noise]).copy(interpretation="srgb"), tmp_path / "noise.png")
    result = encode(
        render(src, EditDocument()), ExportOptions(format="jpeg", target_kb=60), tmp_path / "o.jpg", tmp_path
    )
    assert result.size_bytes <= 60 * 1024
    assert result.quality is not None and 10 <= result.quality < 95


def test_target_size_on_a_big_image_measures_a_copy_and_still_fits(tmp_path: Path) -> None:
    """Over SEARCH_PROXY_MP the search runs on a smaller copy; the real file must still fit."""
    xyz = pyvips.Image.xyz(2600, 1800)
    soft = pyvips.Image.perlin(2600, 1800, cell_size=64, uchar=True)
    img = soft.bandjoin([(xyz[0] / 10.2).cast("uchar"), (xyz[1] / 7.1).cast("uchar")])
    src = save(img.copy(interpretation="srgb"), tmp_path / "big.png")
    result = encode(
        render(src, EditDocument()), ExportOptions(format="jpeg", target_kb=400), tmp_path / "o.jpg", tmp_path
    )
    assert result.size_bytes <= 400 * 1024
    assert result.quality is not None and result.quality >= 30
    assert not list(tmp_path.glob("*.proxy.v"))


def test_unreachable_target_is_reported(tmp_path: Path) -> None:
    noise = pyvips.Image.gaussnoise(1200, 900, sigma=80).cast("uchar")
    src = save(noise.bandjoin([noise, noise]).copy(interpretation="srgb"), tmp_path / "noise.png")
    with pytest.raises(AppError) as err:
        encode(
            render(src, EditDocument()),
            ExportOptions(format="jpeg", target_kb=10),
            tmp_path / "o.jpg",
            tmp_path,
        )
    assert err.value.code == "export.target_unreachable"


def test_resize_keeps_aspect(tmp_path: Path) -> None:
    work = resize_to(render(save(gradient(), tmp_path / "s.png"), EditDocument()), 32)
    assert (work.width, work.height) == (32, 24)


def test_cancelling_during_encode_stops_libvips(tmp_path: Path) -> None:
    noise = pyvips.Image.gaussnoise(1500, 1500, sigma=40).cast("uchar")
    src = save(noise.bandjoin([noise, noise]).copy(interpretation="srgb"), tmp_path / "n.png")

    def cancelled(_fraction: float) -> None:
        raise InterruptedError("cancelled")

    with pytest.raises(pyvips.Error):
        encode(
            render(src, EditDocument()),
            ExportOptions(format="png"),
            tmp_path / "o.png",
            tmp_path / "t",
            progress=cancelled,
        )
    assert not (tmp_path / "o.png").exists()


def test_validation_messages_are_plain() -> None:
    with pytest.raises(AppError) as err:
        parse_document({"ops": [{"id": "exposure", "params": {"ev": 12}}]})
    assert err.value.detail == "The edit settings aren't valid: Exposure stops must be between -4 and 4."


def test_disk_reserve_is_a_share_capped_at_20_gb() -> None:
    from siqe.system.resources import disk_reserve

    assert disk_reserve(100 * 10**9, 0.05) == 5 * 10**9
    assert disk_reserve(2 * 10**12, 0.05) == 20 * 10**9
