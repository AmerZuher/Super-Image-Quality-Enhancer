import pytest

from siqe.ai.governor import Calibration, choose_settings, clamp_tile, cpu_settings, fit_calibration

GIB = 1024**3


def test_fit_recovers_a_line() -> None:
    cal = fit_calibration([(100, 1_000 + 100 * 50), (400, 1_000 + 400 * 50)])
    assert cal.base_bytes == pytest.approx(1_000)
    assert cal.bytes_per_px == pytest.approx(50)
    assert Calibration.from_dict(cal.to_dict()) == cal
    assert Calibration.from_dict({"nope": 1}) is None


def test_picks_largest_tile_then_batch_that_fits() -> None:
    # 200 MB of weights, 2 KB per input pixel: a 512 tile (+2×16 context = 544²) needs ~0.8 GB.
    cal = Calibration(base_bytes=200e6, bytes_per_px=2048)
    big = choose_settings(cal, 22 * GIB, width=8000, height=6000, context=16, multiple=8)
    assert big.tile == 1024 and big.batch >= 4
    small = choose_settings(cal, 1 * GIB, width=8000, height=6000, context=16, multiple=8)
    assert small.tile == 512 and small.batch == 1


def test_batch_never_exceeds_the_number_of_tiles() -> None:
    cal = Calibration(base_bytes=0, bytes_per_px=1)
    s = choose_settings(cal, 100 * GIB, width=300, height=200, context=8, multiple=1)
    assert s.tile == 300 and s.batch == 1


def test_nothing_fits_starts_small_for_the_ladder() -> None:
    s = choose_settings(Calibration(5 * GIB, 4096), 2 * GIB, width=4000, height=3000, context=16, multiple=1)
    assert (s.tile, s.batch) == (128, 1)


def test_uncalibrated_and_cpu_defaults() -> None:
    assert choose_settings(None, 0, width=4000, height=3000, context=8, multiple=1).tile == 512
    assert cpu_settings(width=200, height=100, context=8, multiple=8).tile == 200
    assert clamp_tile(512, 30, 20) == 64
