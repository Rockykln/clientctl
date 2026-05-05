"""Fast /proc scanner for PID and state detection.

Replaces the pgrep cascade: a single /proc walk builds an index of
(comm, cmdline, ppid, state); all apps are matched locally. Cache 0.8s
turns 11 apps × 3 pgrep calls into one /proc walk.
"""

import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("clientctl.procs")

_PROC = Path("/proc")
_TTL  = 0.8

_CACHE: dict = {"data": [], "ts": 0.0}
_LOCK  = threading.Lock()


class ProcEntry:
    __slots__ = ("pid", "ppid", "comm", "cmdline", "state")

    def __init__(self, pid: int, ppid: int, comm: str, cmdline: list[str], state: str):
        self.pid     = pid
        self.ppid    = ppid
        self.comm    = comm
        self.cmdline = cmdline
        self.state   = state


def _read_one(pid_str: str) -> ProcEntry | None:
    if not pid_str.isdigit():
        return None
    pid = int(pid_str)
    base = _PROC / pid_str
    try:
        stat_txt = (base / "stat").read_text()
    except Exception:
        return None
    # Format: "<pid> (<comm with spaces>) <state> <ppid> ..."
    r = stat_txt.rfind(")")
    if r == -1:
        return None
    rest = stat_txt[r + 2:].split()
    if len(rest) < 2:
        return None
    state = rest[0]
    try:
        ppid = int(rest[1])
    except ValueError:
        ppid = 0

    try:
        comm = (base / "comm").read_text(errors="ignore").strip()
    except Exception:
        comm = ""
    try:
        cmd_raw = (base / "cmdline").read_bytes()
        cmdline = [a.decode("utf-8", errors="ignore") for a in cmd_raw.split(b"\0") if a]
    except Exception:
        cmdline = []

    return ProcEntry(pid, ppid, comm, cmdline, state)


def _scan() -> list[ProcEntry]:
    out = []
    try:
        for entry in _PROC.iterdir():
            p = _read_one(entry.name)
            if p is not None:
                out.append(p)
    except Exception as e:
        log.warning("/proc scan failed: %s", e)
    return out


def snapshot() -> list[ProcEntry]:
    """Cached snapshot of all processes (TTL 0.8s)."""
    with _LOCK:
        if time.time() - _CACHE["ts"] < _TTL and _CACHE["data"]:
            return _CACHE["data"]
        _CACHE["data"] = _scan()
        _CACHE["ts"]   = time.time()
        return _CACHE["data"]


def invalidate() -> None:
    """Drop cache — call after launch/kill so the next status check is fresh."""
    with _LOCK:
        _CACHE["ts"] = 0.0


def find_app_pids(cfg: dict) -> list[int]:
    """Find PIDs matching the app config via binary, cmdline path and cmdline_match.

    PWAs (cfg["pwa_id"]) return nothing here — they are detected through
    KWin window matching (see routes/apps.py).
    """
    if cfg.get("pwa_id"):
        return []

    binary = cfg.get("binary")
    if not binary:
        return []

    binary_trunc = binary[:15].lower()  # Linux comm is truncated to 15 chars
    cm = cfg.get("cmdline_match")

    pids: set[int] = set()
    for p in snapshot():
        # 1) comm match (case-insensitive, respects 15-char truncation)
        if p.comm and p.comm.lower() == binary_trunc:
            pids.add(p.pid)
            continue
        # 2) cmdline[0] ends with binary (or cmdline[0] == binary)
        if p.cmdline:
            exe = p.cmdline[0]
            if exe == binary or exe.endswith("/" + binary):
                pids.add(p.pid)
                continue
        # 3) cmdline_match: substring appears in any arg (Electron apps)
        if cm and any(cm in a for a in p.cmdline):
            pids.add(p.pid)
    return list(pids)


def is_paused(pids: list[int]) -> bool:
    """True if any of the given PIDs is SIGSTOP'd (state T/t)."""
    if not pids:
        return False
    by_pid = {p.pid: p for p in snapshot()}
    for pid in pids:
        p = by_pid.get(pid)
        if p and p.state in ("T", "t"):
            return True
    return False


def descendants(pids: list[int]) -> list[int]:
    """All PIDs including recursive descendants (for pausing/killing whole trees)."""
    if not pids:
        return []
    children: dict[int, list[int]] = {}
    for p in snapshot():
        if p.ppid:
            children.setdefault(p.ppid, []).append(p.pid)

    seen = set()
    stack = list(pids)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children.get(cur, []))
    return list(seen)


def find_konsole_with_arg(arg_substr: str) -> list[int]:
    """Special case: konsole PIDs whose cmdline contains `arg_substr`."""
    out = []
    for p in snapshot():
        if not p.cmdline:
            continue
        if "konsole" not in p.cmdline[0].lower():
            continue
        if any(arg_substr in a for a in p.cmdline):
            out.append(p.pid)
    return out
