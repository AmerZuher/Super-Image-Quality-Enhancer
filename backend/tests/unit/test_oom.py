import pytest

from siqe.ai.oom import InsufficientMemoryError, is_oom_error, run_with_halving


class OutOfMemoryError(RuntimeError):
    """Same class name as torch.OutOfMemoryError, without needing torch installed."""


def fake_gpu(capacity: int, calls: list[int]):  # type: ignore[no-untyped-def]
    def work(size: int) -> str:
        calls.append(size)
        if size > capacity:
            raise OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")
        return f"ok@{size}"

    return work


def test_fits_first_time() -> None:
    calls: list[int] = []
    assert run_with_halving(fake_gpu(1024, calls), 512, minimum=128) == ("ok@512", 512)
    assert calls == [512]


def test_retries_once_then_halves_until_it_fits() -> None:
    calls: list[int] = []
    fallbacks: list[tuple[int, int]] = []
    result = run_with_halving(
        fake_gpu(300, calls), 1024, minimum=128, on_fallback=lambda a, b: fallbacks.append((a, b))
    )
    assert result == ("ok@256", 256)
    assert calls == [1024, 1024, 512, 512, 256]
    assert fallbacks == [(1024, 512), (512, 256)]


def test_gives_up_below_minimum_with_typed_error() -> None:
    with pytest.raises(InsufficientMemoryError) as info:
        run_with_halving(fake_gpu(10, []), 512, minimum=256)
    assert info.value.code == "gpu.insufficient_memory"


def test_other_errors_are_not_swallowed() -> None:
    def broken(size: int) -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        run_with_halving(broken, 512, minimum=128)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("CUDA out of memory. Tried to allocate 20.00 MiB", True),
        ("[ONNXRuntimeError] : 6 : RUNTIME_EXCEPTION : Failed to allocate memory", True),
        ("CUDNN_STATUS_ALLOC_FAILED", True),
        ("shape mismatch", False),
    ],
)
def test_is_oom_error(message: str, expected: bool) -> None:
    assert is_oom_error(RuntimeError(message)) is expected
