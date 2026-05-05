"""KWin scripting helpers.

KWin on Wayland does not give scripts a return channel — we work around
this with print() into journalctl + a marker. Write operations
(toggle/close) don't need a return value, so this trick is only required
for the query path.
"""

import json
import logging
import os
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger("clientctl.kwin")

_QDBUS     = "qdbus6"
_CACHE_TTL = 0.4

_STATE_CACHE = {"data": {}, "ts": 0.0}
_STATE_LOCK  = threading.Lock()


def run_script(js: str) -> None:
    """Load script via DBus, start it, unload asynchronously (no wait).

    The script file is written via tempfile.mkstemp (mode 0600, atomic
    name selection) — avoids the symlink-race / world-readable temp file
    pitfalls of writing to a hardcoded /tmp path.
    """
    fd, path = tempfile.mkstemp(prefix="clientctl-kwin-", suffix=".js", text=True)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(js)
    except Exception:
        os.close(fd)
        raise
    tmp = Path(path)
    plugin = f"clientctl-{secrets.token_hex(4)}"
    try:
        subprocess.run(
            [_QDBUS, "org.kde.KWin", "/Scripting",
             "org.kde.kwin.Scripting.loadScript", str(tmp), plugin],
            check=True, timeout=3,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [_QDBUS, "org.kde.KWin", "/Scripting",
             "org.kde.kwin.Scripting.start"],
            check=True, timeout=3,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    finally:
        def _cleanup():
            time.sleep(0.5)
            # Wrap the unload call: in environments without qdbus6 (CI,
            # tests) FileNotFoundError would otherwise bubble out of this
            # daemon thread as an unhandled exception.
            try:
                subprocess.run(
                    [_QDBUS, "org.kde.KWin", "/Scripting",
                     "org.kde.kwin.Scripting.unloadScript", plugin],
                    timeout=3,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
        threading.Thread(target=_cleanup, daemon=True).start()


def _matches_window(w: dict, cfg: dict) -> bool:
    target = cfg.get("desktop_id", "") or ""
    if target and w.get("df", "") == target:
        return True
    raw = cfg.get("wm_class", "")
    wm_list = [raw] if isinstance(raw, str) and raw else (list(raw) if raw else [])
    wm_lower = {x.lower() for x in wm_list}
    if w.get("rc", "") in wm_lower or w.get("rn", "") in wm_lower:
        return True
    cap_inc = (cfg.get("caption_includes", "") or "").lower()
    if cap_inc and cap_inc in (w.get("cap", "") or "").lower():
        return True
    return False


def query_states(apps: dict[str, dict]) -> dict:
    """Cached window states {app_id: {visible, active}}.

    Asks KWin for the window list, writes JSON to journalctl with a marker,
    reads it back.
    """
    with _STATE_LOCK:
        if time.time() - _STATE_CACHE["ts"] < _CACHE_TTL:
            return _STATE_CACHE["data"]

    marker = secrets.token_hex(8)
    js = f"""
const list = (typeof workspace.windowList === "function")
    ? workspace.windowList()
    : (workspace.clientList ? workspace.clientList() : []);
const out = [];
for (const w of list) {{
    if (!w) continue;
    out.push({{
        df: w.desktopFileName || "",
        rc: (w.resourceClass || "").toLowerCase(),
        rn: (w.resourceName  || "").toLowerCase(),
        cap: w.caption || "",
        pid: w.pid || w.processId || 0,
        min: !!w.minimized,
        active: !!(workspace.activeWindow && w.internalId === workspace.activeWindow.internalId),
    }});
}}
print("CCTL_S_{marker}:" + JSON.stringify(out));
"""
    try:
        run_script(js)
    except Exception as e:
        log.debug("KWin script failed: %s", e)
        return _STATE_CACHE["data"]

    marker_str = f"CCTL_S_{marker}:"
    payload = None
    # journalctl sometimes lags briefly behind print() — retry up to 4 times
    for _ in range(4):
        time.sleep(0.04)
        try:
            out = subprocess.check_output(
                ["journalctl", "--user", "-n", "20", "--no-pager", "-o", "cat",
                 "--since", "2 seconds ago"],
                stderr=subprocess.DEVNULL, timeout=1.5,
            ).decode()
        except Exception:
            continue
        for line in reversed(out.splitlines()):
            idx = line.find(marker_str)
            if idx != -1:
                payload = line[idx + len(marker_str):]
                break
        if payload:
            break
    if not payload:
        return _STATE_CACHE["data"]

    try:
        wins = json.loads(payload)
    except Exception:
        return _STATE_CACHE["data"]

    state = {}
    for app_id, cfg in apps.items():
        matches = [w for w in wins if _matches_window(w, cfg)]
        if matches:
            state[app_id] = {
                "visible": any(not w.get("min") for w in matches),
                "active":  any(w.get("active") for w in matches),
            }
    with _STATE_LOCK:
        _STATE_CACHE["data"] = state
        _STATE_CACHE["ts"]   = time.time()
    return state


def for_each(cfg: dict, js_action: str) -> None:
    """Find windows by multiple criteria in parallel and run JS on the `wins` list.

    Match criteria:
      desktop_id        — KWin desktopFileName
      wm_class          — resourceClass / resourceName (list, case-insensitive)
      pids              — KWin pid must be in pids
      caption_includes  — caption substring (additional match)
      caption_match     — caption substring (filter — MUST also match)
    """
    target  = cfg.get("desktop_id", "") or ""
    cap     = cfg.get("caption_match", "") or ""
    cap_inc = (cfg.get("caption_includes", "") or "").lower()
    pids    = cfg.get("pids", []) or []
    raw_wm  = cfg.get("wm_class", "")
    wm_list = [raw_wm] if isinstance(raw_wm, str) and raw_wm else (list(raw_wm) if raw_wm else [])
    wm_lower = [w.lower() for w in wm_list]

    js = f"""
const target  = {json.dumps(target)};
const wmList  = {json.dumps(wm_lower)};
const cap     = {json.dumps(cap)};
const capInc  = {json.dumps(cap_inc)};
const pids    = {json.dumps(pids)};
const list = (typeof workspace.windowList === "function")
    ? workspace.windowList()
    : (workspace.clientList ? workspace.clientList() : []);
const wins = list.filter(w => {{
    if (!w) return false;
    let m = false;
    if (target && w.desktopFileName === target) m = true;
    if (!m && wmList.length) {{
        const rc = (w.resourceClass || "").toLowerCase();
        const rn = (w.resourceName  || "").toLowerCase();
        if (wmList.indexOf(rc) !== -1 || wmList.indexOf(rn) !== -1) m = true;
    }}
    if (!m && pids.length) {{
        const wp = w.pid || w.processId || -1;
        if (pids.indexOf(wp) !== -1) m = true;
    }}
    if (!m && capInc) {{
        const c = (w.caption || "").toLowerCase();
        if (c.indexOf(capInc) !== -1) m = true;
    }}
    if (m && cap) {{
        m = !!(w.caption && w.caption.indexOf(cap) !== -1);
    }}
    return m;
}});
{js_action}
"""
    run_script(js)


_TOGGLE_JS = """
if (wins.length > 0) {
    const anyVisible = wins.some(w => !w.minimized);
    for (const w of wins) { w.minimized = anyVisible; }
    if (!anyVisible) {
        const top = wins[wins.length - 1];
        try { workspace.activeWindow = top; } catch (e) {}
    }
}
"""

_CLOSE_JS = """
for (const w of wins) {
    try { w.closeWindow(); } catch (e) {}
}
"""


def toggle(cfg: dict) -> None:
    for_each(cfg, _TOGGLE_JS)


def close(cfg: dict) -> None:
    for_each(cfg, _CLOSE_JS)
