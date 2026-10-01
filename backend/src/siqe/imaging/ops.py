"""Adjustment formulas, written twice: once for scalars and once for libvips images.

Working values are sRGB-encoded floats in 0..1. The browser preview
(``frontend/src/features/studio/gl/shader.ts`` and ``reference.ts``) implements exactly
these formulas. ``tests/fixtures/ops_parity.json`` is generated from ``apply_pixel`` and
checked against both the libvips path and the TypeScript reference, so if you change a
formula here, change it there and regenerate the fixture (``uv run python -m
siqe.imaging.parity``).

Pipeline order (pointwise stages, then spatial ones):
  A. temperature, tint, exposure in linear light
  B. whites and blacks as a levels stretch
  C. shadows and highlights as smooth tone bumps
  D. contrast around mid-grey
  E. vibrance, F. saturation, G. black & white, around Rec. 709 luma
  H. sharpen: adds source detail (luma minus blurred luma) scaled by amount
  I. vignette: radial gain with a smooth falloff
  then clamp to 0..1.
"""

import math
from typing import Any

import pyvips

LUMA = (0.2126, 0.7152, 0.0722)


# ----------------------------------------------------------------------------- scalars


def _srgb_to_linear(x: float) -> float:
    x = max(x, 0.0)
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(x: float) -> float:
    x = max(x, 0.0)
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055


def _luma(c: list[float]) -> float:
    return LUMA[0] * c[0] + LUMA[1] * c[1] + LUMA[2] * c[2]


def _clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def _smoothstep(e0: float, e1: float, x: float) -> float:
    t = _clamp01((x - e0) / (e1 - e0))
    return t * t * (3 - 2 * t)


def apply_pixel(rgb: tuple[float, float, float], ops: dict[str, dict[str, float]]) -> list[float]:
    """Reference implementation of the pointwise stages (A to G) plus the final clamp."""
    c = list(rgb)
    if {"temperature", "tint", "exposure"} & ops.keys():
        t = ops.get("temperature", {}).get("amount", 0) / 100
        n = ops.get("tint", {}).get("amount", 0) / 100
        ev = ops.get("exposure", {}).get("ev", 0)
        gains = (1 + 0.25 * t, 1 - 0.25 * n, 1 - 0.25 * t)
        k = 2.0**ev
        c = [_linear_to_srgb(_srgb_to_linear(v) * g * k) for v, g in zip(c, gains, strict=True)]
    if {"whites", "blacks"} & ops.keys():
        wp = 1 - 0.25 * ops.get("whites", {}).get("amount", 0) / 100
        bp = -0.15 * ops.get("blacks", {}).get("amount", 0) / 100
        c = [(v - bp) / (wp - bp) for v in c]
    if {"shadows", "highlights"} & ops.keys():
        s = ops.get("shadows", {}).get("amount", 0) / 100
        h = ops.get("highlights", {}).get("amount", 0) / 100
        out = []
        for v in c:
            cc = _clamp01(v)
            out.append(v + 0.35 * s * 6.75 * cc * (1 - cc) ** 2 + 0.35 * h * 6.75 * cc * cc * (1 - cc))
        c = out
    if "contrast" in ops:
        k = 1 + ops["contrast"]["amount"] / 100
        c = [(v - 0.5) * k + 0.5 for v in c]
    if "vibrance" in ops:
        v_amt = ops["vibrance"]["amount"] / 100
        lum = _luma(c)
        sat = _clamp01(max(c) - min(c))
        f = 1 + v_amt * (1 - sat)
        c = [lum + (v - lum) * f for v in c]
    if "saturation" in ops:
        f = 1 + ops["saturation"]["amount"] / 100
        lum = _luma(c)
        c = [lum + (v - lum) * f for v in c]
    if "black_white" in ops:
        lum = _luma(c)
        c = [lum, lum, lum]
    return [_clamp01(v) for v in c]


def vignette_gain(px: float, py: float, width: int, height: int, amount: float, midpoint: float) -> float:
    """Gain at pixel centre (px, py); amount in -100..100, midpoint in 0..0.95."""
    aspect = width / height
    dx = ((px + 0.5) / width - 0.5) * aspect
    dy = (py + 0.5) / height - 0.5
    d = math.hypot(dx, dy) / math.hypot(0.5 * aspect, 0.5)
    return 1 - (amount / 100) * _smoothstep(midpoint, 1.0, d)


# ------------------------------------------------------------------------------ libvips


def _v_srgb_to_linear(x: pyvips.Image) -> pyvips.Image:
    x = x.clamp(min=0.0, max=1e6)
    return (x <= 0.04045).ifthenelse(x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _v_linear_to_srgb(x: pyvips.Image) -> pyvips.Image:
    x = x.clamp(min=0.0, max=1e6)
    return (x <= 0.0031308).ifthenelse(x * 12.92, (x ** (1 / 2.4)) * 1.055 - 0.055)


def _v_luma(c: pyvips.Image) -> pyvips.Image:
    return c[0] * LUMA[0] + c[1] * LUMA[1] + c[2] * LUMA[2]


def _v_smoothstep(e0: float, e1: float, x: pyvips.Image) -> pyvips.Image:
    t = ((x - e0) / (e1 - e0)).clamp(min=0.0, max=1.0)
    return t * t * (t * -2 + 3)


def apply_adjustments(
    rgb: pyvips.Image,
    ops: dict[str, dict[str, float]],
    *,
    source_luma: pyvips.Image | None = None,
) -> pyvips.Image:
    """Apply every stage to a float sRGB image. ``source_luma`` feeds the sharpen stage."""
    c = rgb
    if {"temperature", "tint", "exposure"} & ops.keys():
        t = ops.get("temperature", {}).get("amount", 0) / 100
        n = ops.get("tint", {}).get("amount", 0) / 100
        k = 2.0 ** ops.get("exposure", {}).get("ev", 0)
        gains = [(1 + 0.25 * t) * k, (1 - 0.25 * n) * k, (1 - 0.25 * t) * k]
        c = _v_linear_to_srgb(_v_srgb_to_linear(c) * gains)
    if {"whites", "blacks"} & ops.keys():
        wp = 1 - 0.25 * ops.get("whites", {}).get("amount", 0) / 100
        bp = -0.15 * ops.get("blacks", {}).get("amount", 0) / 100
        c = (c - bp) / (wp - bp)
    if {"shadows", "highlights"} & ops.keys():
        s = ops.get("shadows", {}).get("amount", 0) / 100
        h = ops.get("highlights", {}).get("amount", 0) / 100
        cc = c.clamp(min=0.0, max=1.0)
        inv = cc * -1 + 1
        c = c + cc * inv * inv * (0.35 * s * 6.75) + cc * cc * inv * (0.35 * h * 6.75)
    if "contrast" in ops:
        k = 1 + ops["contrast"]["amount"] / 100
        c = (c - 0.5) * k + 0.5
    if "vibrance" in ops:
        v_amt = ops["vibrance"]["amount"] / 100
        lum = _v_luma(c)
        mx = c[0].maxpair(c[1]).maxpair(c[2])
        mn = c[0].minpair(c[1]).minpair(c[2])
        sat = (mx - mn).clamp(min=0.0, max=1.0)
        f = (sat * -1 + 1) * v_amt + 1
        c = (c - lum) * f + lum
    if "saturation" in ops:
        f = 1 + ops["saturation"]["amount"] / 100
        lum = _v_luma(c)
        c = (c - lum) * f + lum
    if "black_white" in ops:
        lum = _v_luma(c)
        c = lum.bandjoin([lum, lum])
    if "sharpen" in ops and source_luma is not None:
        p = ops["sharpen"]
        blurred = source_luma.gaussblur(p["radius"], precision="float")
        c = c + (source_luma - blurred) * (p["amount"] / 100)
    if "vignette" in ops:
        p = ops["vignette"]
        c = c * vignette_map(c.width, c.height, p["amount"], p["midpoint"])
    return c.clamp(min=0.0, max=1.0)


def vignette_map(width: int, height: int, amount: float, midpoint: float) -> pyvips.Image:
    aspect = width / height
    xy = pyvips.Image.xyz(width, height).cast("float")
    dx = ((xy[0] + 0.5) / width - 0.5) * aspect
    dy = (xy[1] + 0.5) / height - 0.5
    d = (dx * dx + dy * dy) ** 0.5 / math.hypot(0.5 * aspect, 0.5)
    return _v_smoothstep(midpoint, 1.0, d) * -(amount / 100) + 1


def luma(rgb: pyvips.Image) -> pyvips.Image:
    return _v_luma(rgb)


def describe(ops: dict[str, dict[str, Any]]) -> str:
    return ", ".join(sorted(ops)) or "no adjustments"
