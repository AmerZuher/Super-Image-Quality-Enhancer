"""Face counts in the Library: counting on a preview, and the ``faces`` rule."""

from pathlib import Path

import numpy as np
import pytest
import pyvips
from sqlalchemy.dialects import postgresql

from siqe.library import faces
from siqe.library.rules import Rule, RuleSet, compile_rule, matches


def _preview(tmp_path: Path, width: int = 2000, height: int = 1000) -> Path:
    path = tmp_path / "preview.webp"
    (pyvips.Image.black(width, height, bands=3) + 120).cast("uchar").webpsave(str(path))
    return path


def _face(x: float, y: float, size: float) -> tuple[float, np.ndarray, np.ndarray]:
    return 0.99, np.array([x, y, x + size, y + size]), np.zeros((5, 2))


def test_counts_faces_and_ignores_tiny_ones(tmp_path: Path) -> None:
    seen: list[tuple[int, ...]] = []

    def detect(rgb: np.ndarray) -> list[tuple[float, np.ndarray, np.ndarray]]:
        seen.append(rgb.shape)
        return [_face(10, 10, 80), _face(200, 10, 25), _face(400, 10, 12)]

    assert faces.count(detect, _preview(tmp_path)) == 2  # the 12 px face is crowd
    assert seen == [(640, 1280, 3)]  # detected on a copy no larger than 1280 px


def test_halves_the_detection_size_after_running_out_of_memory(tmp_path: Path) -> None:
    sides: list[int] = []

    def detect(rgb: np.ndarray) -> list[tuple[float, np.ndarray, np.ndarray]]:
        sides.append(max(rgb.shape[:2]))
        if len(sides) <= 2:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        # At 640 px, a 12 px face is 24 px at full detection size, so it counts.
        return [_face(10, 10, 12)]

    assert faces.count(detect, _preview(tmp_path)) == 1
    assert sides == [1280, 1280, 640]


def test_small_previews_are_used_as_they_are(tmp_path: Path) -> None:
    def detect(rgb: np.ndarray) -> list[tuple[float, np.ndarray, np.ndarray]]:
        assert rgb.shape == (300, 400, 3)
        return [_face(0, 0, 19), _face(50, 50, 20)]

    assert faces.count(detect, _preview(tmp_path, 400, 300)) == 1


@pytest.mark.parametrize(
    ("op", "value", "count", "expected"),
    [
        ("gte", 1, 2, True),
        ("gte", 1, 0, False),
        ("lte", 0, 0, True),
        ("lte", 0, -1, False),  # couldn't be checked
        ("gte", 0, None, False),  # not counted yet
        ("lte", 5, None, False),
    ],
)
def test_faces_rule_in_python(op: str, value: int, count: int | None, expected: bool) -> None:
    rules = RuleSet(rules=[Rule(field="faces", op=op, value=value)])  # type: ignore[arg-type]
    assert matches(rules, {"width": 10, "height": 10, "faces": count}) is expected


def test_faces_rule_in_sql_leaves_out_uncounted_images() -> None:
    sql = str(
        compile_rule(Rule(field="faces", op="lte", value=0)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "assets.faces >= 0" in sql and "assets.faces <= 0" in sql
    with pytest.raises(ValueError):
        Rule(field="faces", op="is", value=1)
