"""SSE broadcast hub + /api/events route."""

import json
import queue

import pytest

from core import realtime


@pytest.fixture(autouse=True)
def _reset_realtime():
    """Each test starts with no subscribers and an empty cache."""
    realtime._SUBSCRIBERS.clear()
    realtime._LAST.clear()
    yield
    realtime._SUBSCRIBERS.clear()
    realtime._LAST.clear()


def test_add_subscriber_returns_queue_and_registers():
    q = realtime.add_subscriber()
    assert isinstance(q, queue.Queue)
    assert realtime.subscriber_count() == 1


def test_remove_subscriber_unregisters():
    q = realtime.add_subscriber()
    realtime.remove_subscriber(q)
    assert realtime.subscriber_count() == 0


def test_remove_unknown_subscriber_is_noop():
    """Removing a queue that was never added must not raise — the SSE
    handler does this in its finally block on every connection close."""
    q: queue.Queue = queue.Queue()
    realtime.remove_subscriber(q)  # must not raise


def test_broadcast_pushes_to_all_subscribers():
    a = realtime.add_subscriber()
    b = realtime.add_subscriber()
    realtime.broadcast("sysinfo", {"cpu": 42})
    assert a.get_nowait()["data"]["cpu"] == 42
    assert b.get_nowait()["data"]["cpu"] == 42


def test_broadcast_caches_last_value_for_late_joiners():
    """A subscriber that connects AFTER a broadcast should still get the
    last known state immediately — not have to wait for the next tick."""
    realtime.broadcast("battery", {"percent": 80, "present": True})
    q = realtime.add_subscriber()
    event = q.get_nowait()
    assert event["name"] == "battery"
    assert event["data"]["percent"] == 80


def test_broadcast_full_queue_does_not_drop_other_subscribers():
    """A backed-up subscriber must not block delivery to fast ones."""
    fast = realtime.add_subscriber()
    slow = realtime.add_subscriber()
    # Drain the late-joiner snapshot so the queues start clean
    while True:
        try: slow.get_nowait()
        except queue.Empty: break
    # Saturate the slow queue via broadcast — fast also receives but we
    # immediately drain it so it stays under-full.
    for i in range(realtime._QUEUE_MAX + 5):
        realtime.broadcast("filler", {"i": i})
        try: fast.get_nowait()
        except queue.Empty: pass
    # New broadcast must still reach fast even though slow is full
    realtime.broadcast("sysinfo", {"cpu": 1})
    last = None
    while True:
        try: last = fast.get_nowait()
        except queue.Empty: break
    assert last is not None
    assert last["data"]["cpu"] == 1


def test_encode_sse_format():
    s = realtime.encode_sse("sysinfo", {"cpu": 12})
    assert s.startswith("event: sysinfo\n")
    assert "data: " in s
    # Two trailing newlines mark the end of an SSE message
    assert s.endswith("\n\n")


def test_encode_sse_round_trips_through_json():
    s = realtime.encode_sse("battery", {"percent": 75, "state": "charging"})
    data_line = next(l for l in s.splitlines() if l.startswith("data: "))
    payload = json.loads(data_line[len("data: "):])
    assert payload["percent"]  == 75
    assert payload["state"]    == "charging"


# ── Route-level tests ────────────────────────────────────────────────

def test_events_endpoint_requires_auth(client):
    res = client.get("/api/events")
    assert res.status_code == 401
    assert res.get_json()["ok"] is False


def test_events_endpoint_streams_with_correct_mimetype(authed_client):
    """The Content-Type must be text/event-stream — EventSource refuses
    the connection otherwise."""
    res = authed_client.get("/api/events", buffered=False)
    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"
    # Disable nginx/CF buffering — without these headers the events sit
    # in proxy buffers and the live-update feel disappears.
    assert res.headers.get("X-Accel-Buffering") == "no"
    assert res.headers.get("Cache-Control")     == "no-store"
    res.close()
