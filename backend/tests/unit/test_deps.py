"""The request's database session commits before the response is sent."""

from typing import get_args

from siqe.api.deps import SessionDep


def test_sessions_commit_before_the_response() -> None:
    # FastAPI's default ("request") ends yield dependencies after the response is sent, so a client
    # could read before the write is committed (a tag added, then missing on the next GET).
    depends = get_args(SessionDep)[1]
    assert depends.scope == "function"
