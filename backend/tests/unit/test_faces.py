import numpy as np
import pyvips

from siqe.ai.faces import FACE, TEMPLATE, Face, invert, restore_faces, similarity, warp


def test_similarity_recovers_rotation_scale_and_shift() -> None:
    angle, scale, shift = 0.3, 1.7, np.array([40.0, -12.0])
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    src = TEMPLATE / 3
    dst = scale * src @ rot.T + shift
    m = similarity(src, dst)
    np.testing.assert_allclose(m[:, :2], scale * rot, atol=1e-9)
    np.testing.assert_allclose(m[:, 2], shift, atol=1e-9)
    np.testing.assert_allclose(invert(invert(m)), m, atol=1e-9)


def test_warp_moves_pixels_like_warp_affine() -> None:
    image = np.zeros((10, 10, 1), np.float32)
    image[2, 3] = 1
    shifted = warp(image, np.array([[1.0, 0, 4], [0, 1.0, 1]]), (10, 10))
    assert shifted[3, 7, 0] == 1


def gradient(w: int = 400, h: int = 300) -> pyvips.Image:
    xy = pyvips.Image.xyz(w, h).cast("float")
    return (xy[0] / w).bandjoin([xy[1] / h, (xy[0] + xy[1]) / (w + h)])


def face_at(cx: float, cy: float, size: float) -> Face:
    pts = (TEMPLATE - FACE / 2) * (size / FACE) + [cx, cy]
    return Face(0.99, np.array([cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2]), pts)


def test_identity_restorer_leaves_the_image_unchanged() -> None:
    image = gradient()
    out, count = restore_faces(image, lambda rgb: [face_at(200, 150, 120)], lambda f: f)
    assert count == 1
    diff = (out - image).abs().max()
    assert diff < 0.01


def test_restored_face_is_blended_only_around_the_face() -> None:
    image = gradient()
    red = lambda f: np.broadcast_to(np.array([1.0, 0, 0], np.float32), f.shape).copy()  # noqa: E731
    out, _ = restore_faces(image, lambda rgb: [face_at(200, 150, 120)], red)
    assert out.getpoint(200, 150) == [1.0, 0.0, 0.0]
    assert out.getpoint(10, 10) == image.getpoint(10, 10)
    assert out.getpoint(390, 290) == image.getpoint(390, 290)


def test_detection_runs_on_a_downscaled_copy_and_maps_back() -> None:
    image = gradient(4000, 3000)
    seen: list[tuple[int, ...]] = []

    def detect(rgb: np.ndarray) -> list[Face]:
        seen.append(rgb.shape)
        return [face_at(640, 480, 60)]  # in the 1280 px copy

    out, count = restore_faces(image, detect, lambda f: np.zeros_like(f), detect_side=1280)
    assert seen == [(960, 1280, 3)]
    assert count == 1
    assert out.getpoint(2000, 1500) == [0.0, 0.0, 0.0]


def test_tiny_faces_are_skipped() -> None:
    _, count = restore_faces(gradient(), lambda rgb: [face_at(50, 50, 8)], lambda f: f)
    assert count == 0
