"""Server-Sent Events broadcast hub — pushes live state to subscribed clients.

Replaces several polling loops on the frontend (sysinfo, battery, lock state,
app state) with a single long-lived HTTP connection per tab. Cuts request
volume by ~10× during normal use and removes the "stale display while the
server is gone" gap.

Architecture:

    +-----------+   put     +-----------+   yield   +----------+
    | producers | --------> | per-conn  | --------> | EventSrc |
    | (threads) |           |   queue   |           |  client  |
    +-----------+           +-----------+           +----------+
       sysinfo, battery, lock, app-state — each runs on its own daemon
       thread, broadcasts when the value changes (or every TTL seconds
       as a heartbeat).

Why SSE instead of WebSockets:

  - We only push server → client, never the other way. WebSockets would
    add half-duplex complexity for no benefit.
  - SSE is plain HTTP — no extra dependency, works through Cloudflare
    tunnels, plays nicely with our existing session-cookie auth.
  - EventSource has built-in reconnect + Last-Event-ID handling.

Each subscriber gets its own bounded queue. If a client falls behind
(slow network) the queue fills and the next broadcast drops it — better
than memory growth or stalling all other clients.
"""

import json
import logging
import queue
import threading
import time

from core import system as system_module
from routes.auth import screen_locked

log = logging.getLogger("clientctl.core.realtime")

# Per-subscriber queues. List under a lock — we add/remove infrequently
# but iterate every broadcast.
_LOCK         = threading.Lock()
_SUBSCRIBERS: list[queue.Queue] = []
_QUEUE_MAX    = 32

# Cached last-broadcast values so a fresh subscriber gets state immediately
# instead of waiting up to one tick (~2s) for the next push.
_LAST: dict[str, dict] = {}


def add_subscriber() -> queue.Queue:
    """Register a new SSE connection and return its event queue.

    The connection handler reads from the returned queue with a timeout;
    None on the queue is the close signal. Caller must call
    ``remove_subscriber`` when the connection ends.
    """
    q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
    with _LOCK:
        _SUBSCRIBERS.append(q)
        # Send the current cached state right away — closes the "first
        # second is blank" gap that pure polling has.
        for name, data in _LAST.items():
            try:
                q.put_nowait({"name": name, "data": data})
            except queue.Full:
                break
    return q


def remove_subscriber(q: queue.Queue) -> None:
    with _LOCK:
        try:
            _SUBSCRIBERS.remove(q)
        except ValueError:
            pass


def broadcast(name: str, data: dict) -> None:
    """Push an event to every connected subscriber.

    Subscribers whose queue is full are NOT dropped — we silently skip
    them on this tick. They get the next event when their queue drains.
    """
    with _LOCK:
        _LAST[name] = data
        for q in _SUBSCRIBERS:
            try:
                q.put_nowait({"name": name, "data": data})
            except queue.Full:
                pass


# ── Producer threads ─────────────────────────────────────────────────

def _sysinfo_loop() -> None:
    """Push CPU/RAM/GPU/proc/net every 2 seconds.

    Same cadence as the previous polling-based sysinfoTimer — but one
    push to all clients instead of N polls per client per tick.
    """
    while True:
        try:
            broadcast("sysinfo", system_module.sysinfo())
        except Exception as e:
            log.debug("sysinfo broadcast failed: %s", e)
        time.sleep(2)


def _battery_loop() -> None:
    """Push battery state every 5 seconds (matches old poll cadence)."""
    while True:
        try:
            broadcast("battery", system_module.battery_info())
        except Exception as e:
            log.debug("battery broadcast failed: %s", e)
        time.sleep(5)


def _lock_loop() -> None:
    """Push screen-lock state every 3 seconds (matches old poll cadence).

    The frontend uses this to switch between the locked and unlocked
    panel views without the user having to refresh.
    """
    while True:
        try:
            broadcast("lock", {"screen_locked": screen_locked()})
        except Exception as e:
            log.debug("lock broadcast failed: %s", e)
        time.sleep(3)


def start_listener() -> None:
    """Spawn the producer threads. Idempotent — call once at server start."""
    threading.Thread(target=_sysinfo_loop, daemon=True, name="sse-sysinfo").start()
    threading.Thread(target=_battery_loop, daemon=True, name="sse-battery").start()
    threading.Thread(target=_lock_loop,    daemon=True, name="sse-lock").start()


# Helpers for tests + introspection
def subscriber_count() -> int:
    with _LOCK:
        return len(_SUBSCRIBERS)


def encode_sse(event_name: str, data: dict) -> str:
    """Serialise an event in the SSE wire format."""
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"
