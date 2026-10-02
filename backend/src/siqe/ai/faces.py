"""Face restoration around a detector and a 512 px face model, without torch.

For each detected face: fit a similarity transform from its five landmarks to the FFHQ
template, warp the face to 512 × 512, restore it, and blend it back through the inverse
transform with a feathered mask. Only the region around each face is ever read into memory,
so this works on very large images too.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pyvips

FACE = 512
# FFHQ landmark positions for a 512 px aligned face (eyes, nose, mouth corners).
TEMPLATE = np.array(
    [
        [192.98138, 239.94708],
        [318.90277, 240.1936],
        [256.63416, 314.01935],
        [201.26117, 371.41043],
        [313.08905, 371.15118],
    ],
    np.float64,
)
FEATHER = 48  # px, in face space


@dataclass(frozen=True)
class Face:
    score: float
    box: np.ndarray  # x1, y1, x2, y2
    landmarks: np.ndarray  # 5 × 2


Detect = Callable[[np.ndarray], list[Face]]  # H×W×3 uint8 RGB → faces in its pixels
Restore = Callable[[np.ndarray], np.ndarray]  # 512×512×3 float 0..1 → same


def similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """2×3 matrix of the rotation + uniform scale + translation mapping src points onto dst (Umeyama)."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = d.T @ s / len(src)
    u, sig, vt = np.linalg.svd(cov)
    sign = np.diag([1.0, np.sign(np.linalg.det(u @ vt))])
    rot = u @ sign @ vt
    scale = np.trace(np.diag(sig) @ sign) / s.var(0).sum()
    m = np.zeros((2, 3))
    m[:, :2] = scale * rot
    m[:, 2] = mu_d - scale * rot @ mu_s
    return m


def invert(m: np.ndarray) -> np.ndarray:
    full = np.vstack([m, [0, 0, 1]])
    return np.linalg.inv(full)[:2]


def sample(image: np.ndarray, xs: np.ndarray, ys: np.ndarray, fill: float = 0.0) -> np.ndarray:
    """Bilinear sample of H×W×C at float coordinates; outside the image gives ``fill``."""
    h, w = image.shape[:2]
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    fx = (xs - x0)[..., None]
    fy = (ys - y0)[..., None]
    out = np.zeros((*xs.shape, image.shape[2]), np.float32)
    for dy, wy in ((0, 1 - fy), (1, fy)):
        for dx, wx in ((0, 1 - fx), (1, fx)):
            xi, yi = x0 + dx, y0 + dy
            inside = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
            px = np.where(inside[..., None], image[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)], fill)
            out += px * wx * wy
    return out


def warp(image: np.ndarray, m: np.ndarray, size: tuple[int, int], fill: float = 0.0) -> np.ndarray:
    """Output pixel p takes image at inverse(m) · p, like cv2.warpAffine(image, m, size)."""
    w, h = size
    inv = invert(m)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    sx = inv[0, 0] * xs + inv[0, 1] * ys + inv[0, 2]
    sy = inv[1, 0] * xs + inv[1, 1] * ys + inv[1, 2]
    return sample(image, sx, sy, fill)


def feather_mask() -> np.ndarray:
    """1 in the middle of the aligned face, easing to 0 over FEATHER px at its edges."""
    d = np.minimum.outer(
        np.minimum(np.arange(FACE), np.arange(FACE)[::-1]), np.minimum(np.arange(FACE), np.arange(FACE)[::-1])
    )
    t = np.clip(d / FEATHER, 0, 1)
    return (t * t * (3 - 2 * t)).astype(np.float32)[..., None]


def restore_faces(
    image: pyvips.Image,
    detect: Detect,
    restore: Restore,
    *,
    detect_side: int = 1280,
    min_face: int = 16,
    on_face: Callable[[int, int], None] = lambda i, n: None,
) -> tuple[pyvips.Image, int]:
    """Restore every face in a float sRGB (0..1, 3-band) image. Returns the image and the face count."""
    scale = min(1.0, detect_side / max(image.width, image.height))
    small = image.resize(scale, kernel="linear") if scale < 1 else image
    small_u8 = (small.clamp(min=0.0, max=1.0) * 255).rint().cast("uchar").numpy()
    faces = [f for f in detect(np.asarray(small_u8)) if (f.box[2] - f.box[0]) / scale >= min_face]
    mask = feather_mask()
    out = image
    for index, face in enumerate(faces):
        on_face(index, len(faces))
        landmarks = face.landmarks / scale
        m = similarity(landmarks, TEMPLATE)
        # The face square, mapped back into the image, bounds the region we touch.
        corners = np.array([[0, 0, 1], [FACE, 0, 1], [0, FACE, 1], [FACE, FACE, 1]], np.float64).T
        pts = invert(m) @ corners
        x0 = max(0, int(np.floor(pts[0].min())) - 2)
        y0 = max(0, int(np.floor(pts[1].min())) - 2)
        x1 = min(image.width, int(np.ceil(pts[0].max())) + 2)
        y1 = min(image.height, int(np.ceil(pts[1].max())) + 2)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        region = np.asarray(out.crop(x0, y0, x1 - x0, y1 - y0).numpy(), np.float32).reshape(
            y1 - y0, x1 - x0, 3
        )
        local = m.copy()
        local[:, 2] += m[:, :2] @ np.array([x0, y0], np.float64)  # region coords → face coords
        aligned = warp(region, local, (FACE, FACE), fill=0.5)
        restored = np.clip(restore(aligned), 0, 1).astype(np.float32)
        back = warp(np.concatenate([restored, mask], 2), invert(local), (x1 - x0, y1 - y0))
        alpha = back[..., 3:4]
        blended = region * (1 - alpha) + back[..., :3] * alpha
        patch = pyvips.Image.new_from_memory(
            np.ascontiguousarray(blended, np.float32), x1 - x0, y1 - y0, 3, "float"
        )
        out = out.insert(patch, x0, y0)
    return out, len(faces)
