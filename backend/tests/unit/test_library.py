"""Library building blocks: measurements, duplicates, rules, location removal and the import folder."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import pyvips
from PIL import Image
from sqlalchemy.dialects import postgresql

from siqe.imaging.io import inspect
from siqe.imaging.metadata import gps_from_fields, remove_location
from siqe.library import analysis, duplicates, imports
from siqe.library.embedder import choose_tags
from siqe.library.rules import DEFAULT_ALBUMS, Rule, RuleSet, compile_rules, parse

SAMPLES = Path(__file__).parents[3] / "samples"

pyvips.cache_set_max(0)  # files are rewritten in place below; don't serve stale decodes


def _preview(src: Path, out: Path, transform=None) -> Path:  # type: ignore[no-untyped-def]
    image = pyvips.Image.thumbnail(str(src), 1024)
    if transform is not None:
        image = transform(image)
    image.write_to_file(str(out))
    return out


# ------------------------------------------------------------------------ analysis


def test_hashes_survive_resizing_and_recompression(tmp_path: Path) -> None:
    base = analysis.analyse(_preview(SAMPLES / "lake-pier.jpg", tmp_path / "a.webp"))
    small = analysis.analyse(_preview(SAMPLES / "lake-pier.jpg", tmp_path / "b.jpg", lambda i: i.resize(0.4)))
    other = analysis.analyse(_preview(SAMPLES / "car.jpg", tmp_path / "c.webp"))
    assert analysis.hamming(base.phash, small.phash) <= 4
    assert analysis.hamming(base.dhash, small.dhash) <= 6
    assert analysis.hamming(base.phash, other.phash) >= 16
    assert -(2**63) <= base.phash < 2**63  # fits PostgreSQL BIGINT


def test_sharpness_drops_with_blur(tmp_path: Path) -> None:
    crisp = analysis.analyse(_preview(SAMPLES / "lake-pier.jpg", tmp_path / "a.webp"))
    blurred = analysis.analyse(
        _preview(SAMPLES / "lake-pier.jpg", tmp_path / "b.webp", lambda i: i.gaussblur(3))
    )
    assert 0 <= blurred.sharpness < 0.2 < crisp.sharpness <= 1


@pytest.mark.parametrize(
    ("rgb", "family"),
    [((220, 30, 30), "red"), ((30, 160, 40), "green"), ((30, 60, 220), "blue"), ((128, 128, 128), "neutral")],
)
def test_dominant_colour(rgb: tuple[int, int, int], family: str) -> None:
    pixels = np.full((16, 16, 3), rgb, np.uint8)
    assert analysis.dominant_colour(pixels)[0] == family


def test_clip_pixels_are_square_and_normalised(tmp_path: Path) -> None:
    px = analysis.clip_pixels(_preview(SAMPLES / "car.jpg", tmp_path / "a.webp"))
    assert px.shape == (224, 224, 3) and px.dtype == np.float32
    assert px.min() >= 0 and px.max() <= 1


def test_taken_at_and_gps_parsing() -> None:
    assert analysis.taken_at({"taken_at": "2024:06:01 18:22:05"}) == datetime(
        2024, 6, 1, 18, 22, 5, tzinfo=UTC
    )
    assert analysis.taken_at({"taken_at": "0000:00:00 00:00:00"}) is None
    assert analysis.taken_at({}) is None
    fields = {
        "GPSLatitude": "52/1 30/1 1234/100",
        "GPSLatitudeRef": "N",
        "GPSLongitude": "1/1 15/1 0/1",
        "GPSLongitudeRef": "W",
    }
    assert gps_from_fields(fields) == (52.503428, -1.25)
    assert gps_from_fields({**fields, "GPSLatitudeRef": "S"}) == (-52.503428, -1.25)
    assert gps_from_fields({"GPSLatitude": "0/1 0/1 0/1", "GPSLongitude": "0/1 0/1 0/1"}) is None
    assert gps_from_fields({}) is None


# ---------------------------------------------------------------------- location


def _with_gps(path: Path, fmt: str) -> None:
    image = Image.new("RGB", (64, 48), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0110] = "EOS R5"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (52.0, 30.0, 12.34), "W", (1.0, 15.0, 0.0)
    xmp = (
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/" exif:GPSLatitude="52,30.2N">'
        b"<exif:GPSLongitude>1,15W</exif:GPSLongitude></rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    image.save(path, format=fmt, exif=exif.tobytes(), xmp=xmp)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_remove_location_keeps_pixels_and_camera_data(tmp_path: Path, fmt: str) -> None:
    path = tmp_path / f"photo.{fmt.lower()}"
    _with_gps(path, fmt)
    before = inspect(path)
    assert before.has_gps and before.gps == (52.503428, -1.25)
    pixels = pyvips.Image.new_from_file(str(path)).numpy()
    size = path.stat().st_size

    assert remove_location(path) >= 1

    after = inspect(path)
    assert not after.has_gps and after.gps is None
    assert path.stat().st_size == size
    np.testing.assert_array_equal(pyvips.Image.new_from_file(str(path)).numpy(), pixels)
    image = pyvips.Image.new_from_file(str(path))
    assert image.get("exif-ifd0-Model").startswith("EOS R5")
    assert b"exif:GPS" not in path.read_bytes()


def test_remove_location_without_location_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "plain.jpg"
    Image.new("RGB", (8, 8)).save(path)
    data = path.read_bytes()
    assert remove_location(path) == 0
    assert path.read_bytes() == data


# --------------------------------------------------------------------- duplicates


def _cand(i: str, phash: int, dhash: int = 0, **kw: object) -> duplicates.Candidate:
    base: dict[str, object] = {
        "embedding": None,
        "width": 1000,
        "height": 800,
        "sharpness": 0.8,
        "size_bytes": 200_000,
        "format": "jpeg",
        "created": 0.0,
    }
    base.update(kw)
    return duplicates.Candidate(id=i, phash=phash, dhash=dhash, **base)  # type: ignore[arg-type]


def test_groups_join_close_hashes_transitively() -> None:
    items = [_cand("a", 0b0), _cand("b", 0b111), _cand("c", 0b111_1111_1111), _cand("d", -1)]
    assert sorted(sorted(g) for g in duplicates.groups(items)) == [[0, 1, 2]]


def test_groups_use_embeddings_for_edited_copies() -> None:
    v = np.zeros(512, np.float32)
    v[0] = 1
    w = v.copy()
    w[1] = 0.2
    w /= np.linalg.norm(w)
    cropped = (1 << 16) - 1  # 16 bits apart: too far for hashes alone
    unrelated = (1 << 32) - 1  # 32 bits apart, like two different photos
    items = [
        _cand("a", 0, embedding=v),
        _cand("b", cropped, dhash=cropped, embedding=w),
        _cand("c", unrelated << 30, dhash=unrelated, embedding=w),
    ]
    assert duplicates.groups(items) == [[0, 1]]


def test_kept_apart_images_are_not_regrouped() -> None:
    items = [_cand("a", 0, ok=True), _cand("b", 1, ok=True), _cand("c", 3)]
    assert duplicates.groups(items) == [[0, 1, 2]]  # c still joins both
    assert duplicates.groups(items[:2]) == []


def test_rank_prefers_resolution_then_sharpness_then_fidelity() -> None:
    small = _cand("small", 0, width=500, height=400)
    soft = _cand("soft", 0, sharpness=0.4)
    jpeg = _cand("jpeg", 0)
    png = _cand("png", 0, format="png", size_bytes=900_000)
    items = [small, soft, jpeg, png]
    order = [items[i].id for i in duplicates.rank(items)]
    assert order == ["png", "jpeg", "soft", "small"]
    assert duplicates.reason(png, small) == "Lower resolution"
    assert duplicates.reason(png, soft) == "Less sharp"
    assert duplicates.reason(png, jpeg) == "Compressed copy"


def test_pairs_handle_many_images_in_blocks() -> None:
    rng = np.random.default_rng(0)
    hashes = [int(x) for x in rng.integers(-(2**62), 2**62, 600)]
    items = [_cand(str(i), h, h) for i, h in enumerate(hashes)]
    items.append(_cand("copy", hashes[17], hashes[17]))
    assert duplicates.pairs(items, block=64) == [(17, 600)]


# ---------------------------------------------------------------------------- tags


def test_choose_tags_keeps_clear_winners_only() -> None:
    names = ["car", "lake", "dog"]
    tags = np.eye(3, 512, dtype=np.float32)
    image = np.array([[0.9, 0.88, 0.0] + [0.0] * 509], np.float32)
    image /= np.linalg.norm(image)
    assert choose_tags(image, tags, names) == [["car", "lake"]]
    flat = np.full((1, 512), 1 / np.sqrt(512), np.float32)  # equally close to everything
    assert choose_tags(flat, tags, names) == [[]]


# --------------------------------------------------------------------------- rules


def _sql(rules: RuleSet) -> str:
    return str(
        compile_rules(rules).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def test_rules_compile_to_sql() -> None:
    sql = _sql(
        parse(
            {
                "match": "any",
                "rules": [
                    {"field": "orientation", "op": "is", "value": "landscape"},
                    {"field": "tag", "op": "has", "value": "Lake"},
                    {"field": "name", "op": "contains", "value": "50%_off"},
                ],
            }
        )
    )
    assert " OR " in sql and "assets.width > assets.height" in sql
    assert "'lake' = ANY (assets.tags)" in sql
    assert "50\\%%\\_off" in sql  # LIKE wildcards in user text are escaped


@pytest.mark.parametrize(
    "rule",
    [
        {"field": "width", "op": "contains", "value": 3},
        {"field": "width", "op": "gte", "value": "wide"},
        {"field": "has_gps", "op": "is", "value": "yes"},
        {"field": "orientation", "op": "is", "value": "diagonal"},
        {"field": "taken", "op": "after", "value": "yesterday"},
        {"field": "nope", "op": "is", "value": 1},
    ],
)
def test_invalid_rules_are_refused(rule: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Rule.model_validate(rule)


def test_default_albums_are_valid() -> None:
    for _, rules in DEFAULT_ALBUMS:
        assert _sql(parse(rules))


# ----------------------------------------------------------------------- imports


def test_walk_finds_images_only(tmp_path: Path) -> None:
    (tmp_path / "trip").mkdir()
    (tmp_path / ".hidden").mkdir()
    for name in ("trip/a.JPG", "b.png", "notes.txt", ".c.jpg", ".hidden/d.jpg"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "link.jpg").symlink_to(tmp_path / "b.png")
    found = sorted(s.path for s in imports.walk(tmp_path))
    assert found == ["b.png", "trip/a.JPG"]


def test_decide_waits_for_files_to_settle() -> None:
    now = time.time()
    fresh = imports.Seen("a.jpg", 100, now - 2)
    settled = imports.Seen("a.jpg", 100, now - 60)
    assert imports.decide(fresh, None, now=now, settle=15) == "record"
    assert imports.decide(settled, None, now=now, settle=15) == "import"
    waiting = imports.Known(100, settled.mtime, "waiting")
    assert imports.decide(settled, waiting, now=now, settle=15) == "import"
    done = imports.Known(100, settled.mtime, "imported")
    assert imports.decide(settled, done, now=now, settle=15) == "skip"
    failed = imports.Known(100, settled.mtime, "failed")
    assert imports.decide(settled, failed, now=now, settle=15) == "skip"
    replaced = imports.Seen("a.jpg", 120, now - 60)
    assert imports.decide(replaced, done, now=now, settle=15) == "import"


def test_stage_hashes_and_refuses_escapes(tmp_path: Path) -> None:
    root = tmp_path / "in"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"hello")
    staged = imports.stage(root, "a.jpg", tmp_path / "tmp", 1024)
    assert staged.size_bytes == 5 and staged.path.read_bytes() == b"hello"
    assert staged.sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    with pytest.raises(OverflowError):
        imports.stage(root, "a.jpg", tmp_path / "tmp", 3)
    with pytest.raises(ValueError):
        imports.stage(root, "../in/../../etc/passwd", tmp_path / "tmp", 1024)
    assert len(os.listdir(tmp_path / "tmp")) == 1  # the failed copy was cleaned up
