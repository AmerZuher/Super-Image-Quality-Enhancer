"""Generates the shared fixture that keeps server and browser edit formulas identical.

Run ``uv run python -m siqe.imaging.parity`` after changing a formula in ``ops.py``; it
rewrites both copies of the fixture. The backend and frontend tests compare against it.
"""

import json
import random
from pathlib import Path
from typing import Any

from siqe.imaging.edits import OPS
from siqe.imaging.ops import apply_pixel

ROOT = Path(__file__).resolve().parents[4]
TARGETS = (
    ROOT / "backend" / "tests" / "fixtures" / "ops_parity.json",
    ROOT / "frontend" / "src" / "features" / "studio" / "ops_parity.json",
)
POINTWISE = [op for op in OPS if op.id not in ("sharpen", "vignette")]


def cases(count: int = 160, seed: int = 7) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for index in range(count):
        rgb = (round(rng.random(), 4), round(rng.random(), 4), round(rng.random(), 4))
        # Each case uses one op alone for the first rounds, then random combinations.
        chosen = (
            [POINTWISE[index % len(POINTWISE)]] if index < len(POINTWISE) * 3 else rng.sample(POINTWISE, 3)
        )
        ops: dict[str, dict[str, float]] = {}
        for spec in chosen:
            ops[spec.id] = {p.name: round(rng.uniform(p.min, p.max), 2) for p in spec.params}
        out.append({"rgb": rgb, "ops": ops, "expected": [round(v, 6) for v in apply_pixel(rgb, ops)]})
    return out


def render() -> str:
    return json.dumps({"tolerance": 1e-4, "cases": cases()}, indent=1) + "\n"


def main() -> None:
    text = render()
    for target in TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        print(f"wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
