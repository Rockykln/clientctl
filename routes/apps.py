"""App control: launch, toggle, close, pause, kill, icon, status."""

import logging
import os
import signal as _signal
import subprocess
from pathlib import Path

from flask import Blueprint, abort, jsonify, send_file

import config
from core import kwin, procs
from utils import require_auth

log = logging.getLogger("clientctl.apps")

bp = Blueprint("apps", __name__)

# Virtual PID for PWAs — window-based detection without a real process
_PWA_VIRTUAL_PID = -1

_SIGNAL_MAP = {
    "STOP": _signal.SIGSTOP,
    "CONT": _signal.SIGCONT,
    "KILL": _signal.SIGKILL,
    "TERM": _signal.SIGTERM,
}


def _app_pids(cfg: dict, app_id: str | None = None) -> list[int]:
    """PIDs for the app. PWAs return [-1] when a matching KWin window is open."""
    if cfg.get("pwa_id"):
        if app_id is None:
            return []
        states = kwin.query_states(config.LAUNCHABLE_APPS)
        return [_PWA_VIRTUAL_PID] if app_id in states else []
    return procs.find_app_pids(cfg)


def _real_pids_with_descendants(cfg: dict) -> list[int]:
    """PIDs + all child processes (for pausing/killing whole process trees)."""
    direct = [p for p in _app_pids(cfg) if p > 0]
    return procs.descendants(direct) if direct else []


def _send_signal(cfg: dict, sig: str) -> int:
    pids = _real_pids_with_descendants(cfg)
    n = 0
    for pid in pids:
        try:
            os.kill(pid, _SIGNAL_MAP[sig])
            n += 1
        except (ProcessLookupError, PermissionError):
            pass
        except Exception as e:
            log.debug("kill -%s %d failed: %s", sig, pid, e)
    return n


def _launch(cfg: dict) -> None:
    """Prefer gio launch (clean DBus activation), fall back to cmd."""
    desktop = cfg.get("desktop_file")
    if desktop and Path(desktop).is_file():
        cmd = ["gio", "launch", desktop]
    else:
        cmd = cfg["cmd"]
    subprocess.Popen(
        cmd,
        start_new_session=True,
        env={**os.environ},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ── Routes ───────────────────────────────────────────────────────────

@bp.route("/api/apps/list")
@require_auth
def apps_list():
    """Returns cell order + display names — frontend renders the grid from this."""
    cells = []
    for entry in config.GRID:
        if entry == "cachy":
            cells.append({"id": "cachy", "type": "cachy", "name": "Cachy Update"})
        elif entry in config.LAUNCHABLE_APPS:
            cfg = config.LAUNCHABLE_APPS[entry]
            cells.append({
                "id":   entry,
                "type": "app",
                "name": cfg.get("name", entry),
            })
    return jsonify({"ok": True, "cells": cells})


@bp.route("/api/app/<app_id>/icon")
def app_icon(app_id: str):
    # Manual auth check instead of @require_auth: this endpoint is hit by
    # <img> tags, where a JSON-401 body would just render as a broken image.
    # abort(401) lets the browser handle the failure cleanly.
    from utils import is_authed
    if not is_authed():
        abort(401)
    cfg = config.LAUNCHABLE_APPS.get(app_id)
    if not cfg:
        abort(404)
    icon_path = cfg.get("icon", "")
    path = Path(icon_path) if icon_path else None
    if not path or not path.is_file():
        abort(404)
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    resp = send_file(path, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.route("/api/app/<app_id>/toggle", methods=["POST"])
@require_auth
def app_toggle(app_id: str):
    cfg = config.LAUNCHABLE_APPS.get(app_id)
    if not cfg:
        return jsonify({"ok": False, "error": "unknown app"}), 404
    try:
        running = bool(_app_pids(cfg, app_id))
        if running:
            real_pids = _real_pids_with_descendants(cfg)
            tmp_cfg = {**cfg, "pids": real_pids} if real_pids else cfg
            kwin.toggle(tmp_cfg)
            return jsonify({"ok": True, "action": "toggled", "name": cfg["name"]})
        _launch(cfg)
        procs.invalidate()
        return jsonify({"ok": True, "action": "launched", "name": cfg["name"]})
    except FileNotFoundError:
        log.exception("toggle: launcher binary not found")
        return jsonify({"ok": False, "error": "Launcher not found"}), 500
    except Exception:
        log.exception("toggle failed")
        return jsonify({"ok": False, "error": "Toggle failed"}), 500


@bp.route("/api/app/<app_id>/status")
@require_auth
def app_status(app_id: str):
    cfg = config.LAUNCHABLE_APPS.get(app_id)
    if not cfg:
        return jsonify({"ok": False, "error": "unknown app"}), 404
    pids = _app_pids(cfg, app_id)
    running = bool(pids)
    win_state = kwin.query_states(config.LAUNCHABLE_APPS).get(app_id, {}) if running else {}
    real_pids = [p for p in pids if p > 0]
    return jsonify({
        "ok":      True,
        "running": running,
        "paused":  procs.is_paused(real_pids),
        "visible": win_state.get("visible", running),
        "active":  win_state.get("active", False),
        "pids":    pids,
        "name":    cfg["name"],
    })


@bp.route("/api/apps/status")
@require_auth
def apps_status():
    """Batch status for all apps. One KWin query, one /proc scan."""
    win_states = kwin.query_states(config.LAUNCHABLE_APPS)
    procs.snapshot()  # warm cache
    out = {}
    for app_id, cfg in config.LAUNCHABLE_APPS.items():
        pids = _app_pids(cfg, app_id)
        running = bool(pids)
        ws = win_states.get(app_id, {}) if running else {}
        real_pids = [p for p in pids if p > 0]
        out[app_id] = {
            "running": running,
            "paused":  procs.is_paused(real_pids),
            "visible": ws.get("visible", running),
            "active":  ws.get("active", False),
        }
    return jsonify({"ok": True, "apps": out})


@bp.route("/api/app/<app_id>/close", methods=["POST"])
@require_auth
def app_close(app_id: str):
    cfg = config.LAUNCHABLE_APPS.get(app_id)
    if not cfg:
        return jsonify({"ok": False, "error": "unknown app"}), 404
    try:
        pids = _real_pids_with_descendants(cfg)
        tmp_cfg = {**cfg, "pids": pids} if pids else cfg
        kwin.close(tmp_cfg)
        return jsonify({"ok": True, "name": cfg["name"]})
    except Exception:
        log.exception("close failed")
        return jsonify({"ok": False, "error": "Close failed"}), 500


@bp.route("/api/app/<app_id>/pause", methods=["POST"])
@require_auth
def app_pause(app_id: str):
    """Toggle SIGSTOP / SIGCONT."""
    cfg = config.LAUNCHABLE_APPS.get(app_id)
    if not cfg:
        return jsonify({"ok": False, "error": "unknown app"}), 404
    if cfg.get("pwa_id"):
        return jsonify({"ok": False,
                        "error": "Pause not possible for PWAs (would freeze the browser)"}), 400
    try:
        pids = [p for p in _app_pids(cfg, app_id) if p > 0]
        if not pids:
            return jsonify({"ok": False, "error": "App is not running"}), 400
        if procs.is_paused(pids):
            _send_signal(cfg, "CONT")
            return jsonify({"ok": True, "action": "resumed", "name": cfg["name"]})
        _send_signal(cfg, "STOP")
        return jsonify({"ok": True, "action": "paused", "name": cfg["name"]})
    except Exception:
        log.exception("pause failed")
        return jsonify({"ok": False, "error": "Pause failed"}), 500


@bp.route("/api/app/<app_id>/kill", methods=["POST"])
@require_auth
def app_kill(app_id: str):
    cfg = config.LAUNCHABLE_APPS.get(app_id)
    if not cfg:
        return jsonify({"ok": False, "error": "unknown app"}), 404
    # PWAs: only close the window — killing would take down the Chromium parent
    if cfg.get("pwa_id"):
        try:
            kwin.close(cfg)
            return jsonify({"ok": True, "killed": 0, "closed": True, "name": cfg["name"]})
        except Exception:
            log.exception("kill (PWA close) failed")
            return jsonify({"ok": False, "error": "Close failed"}), 500
    try:
        n = _send_signal(cfg, "KILL")
        procs.invalidate()
        return jsonify({"ok": True, "killed": n, "name": cfg["name"]})
    except Exception:
        log.exception("kill failed")
        return jsonify({"ok": False, "error": "Kill failed"}), 500
