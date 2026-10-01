import json

from siqe.events.bus import MAX_PAYLOAD_BYTES, SUBSCRIBER_QUEUE_SIZE, EventHub, encode_event


def test_small_events_are_sent_whole() -> None:
    payload = json.loads(encode_event("job.updated", {"id": "1", "progress": 0.5, "message": "hi"}))
    assert payload == {"type": "job.updated", "data": {"id": "1", "progress": 0.5, "message": "hi"}}


def test_oversized_events_become_pointers() -> None:
    raw = encode_event("job.updated", {"id": "1", "state": "running", "result": {"blob": "x" * 20_000}})
    assert len(raw.encode()) <= MAX_PAYLOAD_BYTES
    data = json.loads(raw)["data"]
    assert data == {"id": "1", "state": "running", "truncated": True}


def test_slow_subscribers_drop_oldest_events_instead_of_growing() -> None:
    hub = EventHub("postgresql://unused")
    queue = hub.subscribe()
    for i in range(SUBSCRIBER_QUEUE_SIZE + 10):
        hub.dispatch({"type": "tick", "data": {"i": i}})
    assert queue.qsize() == SUBSCRIBER_QUEUE_SIZE
    assert queue.get_nowait()["data"]["i"] == 10
    hub.unsubscribe(queue)
    hub.dispatch({"type": "tick", "data": {}})
    assert queue.qsize() == SUBSCRIBER_QUEUE_SIZE - 1
