"""Notification history via dbus-monitor subprocess.

Listens for org.freedesktop.Notifications.Notify and parses the multi-line
output. In-memory deque of the last 30 — cleared on server restart.
"""

import collections
import logging
import re
import subprocess
import threading
import time

log = logging.getLogger("clientctl.notifications")

_HISTORY: collections.deque = collections.deque(maxlen=30)
_LOCK = threading.Lock()

_STR_RE = re.compile(r'^string "((?:[^"\\]|\\.)*)"$')


def _unescape(s: str) -> str:
    try:
        return s.encode("latin-1", "ignore").decode("unicode_escape", errors="replace")
    except Exception:
        return s


def _listener_loop():
    """Daemon thread. On error wait 2s and restart."""
    while True:
        try:
            proc = subprocess.Popen(
                ["dbus-monitor", "--session",
                 "interface='org.freedesktop.Notifications',member='Notify'"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
            log.info("dbus-monitor started pid=%d", proc.pid)
            in_notify = False
            strings: list[str] = []
            assert proc.stdout is not None
            for line in proc.stdout:
                stripped = line.strip()
                if "member=Notify" in stripped:
                    in_notify = True
                    strings = []
                    continue
                if not in_notify:
                    continue
                m = _STR_RE.match(stripped)
                if m:
                    strings.append(_unescape(m.group(1)))
                    if len(strings) >= 4:
                        with _LOCK:
                            _HISTORY.appendleft({
                                "app":     strings[0] or "—",
                                "summary": strings[2],
                                "body":    strings[3],
                                "ts":      int(time.time()),
                            })
                        in_notify = False
                        strings = []
            err = proc.stderr.read() if proc.stderr else ""
            log.warning("dbus-monitor exit rc=%s err=%r", proc.returncode, err[:200])
        except Exception as e:
            log.error("notif-listener error: %s", e)
        time.sleep(2)


def start_listener() -> None:
    threading.Thread(target=_listener_loop, daemon=True, name="notif-listener").start()


def list_history() -> list[dict]:
    with _LOCK:
        return list(_HISTORY)


def clear_history() -> None:
    with _LOCK:
        _HISTORY.clear()
