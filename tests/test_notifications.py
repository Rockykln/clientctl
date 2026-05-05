"""Tests for the in-memory notification history.

The dbus-monitor subprocess itself isn't testable without a real session
bus; we exercise the public API (list / clear / append) directly.
"""

from core import notifications


def setup_function(_):
    notifications._HISTORY.clear()


def test_list_history_starts_empty():
    assert notifications.list_history() == []


def test_clear_history_empties_the_deque():
    notifications._HISTORY.appendleft({"app": "x", "summary": "s", "body": "b", "ts": 0})
    assert len(notifications.list_history()) == 1
    notifications.clear_history()
    assert notifications.list_history() == []


def test_history_returns_a_copy():
    """list_history() must not return a live reference — callers shouldn't
    be able to mutate the deque accidentally through the returned list."""
    notifications._HISTORY.appendleft({"app": "a", "summary": "s", "body": "", "ts": 1})
    snapshot = notifications.list_history()
    snapshot.clear()
    assert len(notifications.list_history()) == 1, \
        "list_history() should return a snapshot copy, not the live deque"


def test_history_is_capped_at_30():
    """The deque is bounded so a runaway notification storm can't OOM us."""
    for i in range(50):
        notifications._HISTORY.appendleft({"app": f"a{i}", "summary": "", "body": "", "ts": i})
    assert len(notifications.list_history()) == 30


def test_history_preserves_insertion_order_newest_first():
    notifications._HISTORY.appendleft({"app": "first",  "summary": "", "body": "", "ts": 1})
    notifications._HISTORY.appendleft({"app": "second", "summary": "", "body": "", "ts": 2})
    items = notifications.list_history()
    assert items[0]["app"] == "second"
    assert items[1]["app"] == "first"
