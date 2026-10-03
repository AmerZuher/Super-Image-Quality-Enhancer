"""What a failed job shows: typed errors as they are, anything else as job.unexpected."""

from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from siqe.workflows.assets import UNEXPECTED, _failure


def _activity_error(cause: BaseException) -> ActivityError:
    error = ActivityError(
        "activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test",
        activity_type="prepare_asset",
        activity_id="1",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    error.__cause__ = cause
    return error


def test_typed_errors_keep_their_code_and_message() -> None:
    cause = ApplicationError("This image is damaged.", type="image.unreadable", non_retryable=True)
    assert _failure(_activity_error(cause)) == ("image.unreadable", "This image is damaged.")


def test_unexpected_errors_never_show_internals() -> None:
    cause = ApplicationError("Error: unable to call dzsave\n  VipsJpeg: premature end", type="Error")
    code, message = _failure(_activity_error(cause))
    assert code == UNEXPECTED
    assert "dzsave" not in message and "Vips" not in message


def test_timeouts_say_a_worker_stopped_responding() -> None:
    from temporalio.exceptions import TimeoutError as ActivityTimeout
    from temporalio.exceptions import TimeoutType

    code, message = _failure(
        _activity_error(ActivityTimeout("timeout", type=TimeoutType.HEARTBEAT, last_heartbeat_details=[]))
    )
    assert code == "job.timed_out" and "stopped responding" in message
