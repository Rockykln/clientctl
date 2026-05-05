"""System: power profiles, DND, battery, sysinfo, shutdown, server-kill, capabilities."""

import logging
import os
import queue as _queue
import signal
import threading
import time

from flask import Blueprint, Response, jsonify, stream_with_context

import config
from core import notifications, realtime, system, themes as themes_module
from utils import caps, is_authed, require_auth

log = logging.getLogger("clientctl.routes.system")

bp = Blueprint("system", __name__)


# ── Version + capabilities ───────────────────────────────────────────

@bp.route("/api/version")
def version():
    """Plain version string — public, used by clients to detect updates."""
    return jsonify({
        "ok":       True,
        "version":  config.VERSION,
        "repo_url": config.REPO_URL,
    })


@bp.route("/api/capabilities")
@require_auth
def capabilities():
    """Frontend uses this to enable/disable features per system.
    Includes the version so the UI can render it without an extra fetch.

    Auth-gated because the response fingerprints the host (KDE version,
    GPU vendor, session type, installed binaries). On a public-facing
    tunnel an unauthenticated probe could otherwise enumerate the stack.
    The frontend only fetches this from `initApp()`, which runs post-auth,
    so locking it down does not break the UI.
    """
    return jsonify({
        "ok":       True,
        "version":  config.VERSION,
        "repo_url": config.REPO_URL,
        **caps.get(),
    })


# ── Themes ───────────────────────────────────────────────────────────

@bp.route("/api/themes")
def themes_list():
    """Available themes from themes.yml — frontend builds the picker from this.
    Public so the FOUC bootstrap can validate the cached choice."""
    return jsonify({"ok": True, **themes_module.get_state()})


@bp.route("/api/themes/reload", methods=["POST"])
@require_auth
def themes_reload():
    """Reload themes.yml without restarting the server."""
    state = themes_module.load()
    return jsonify({
        "ok":      True,
        "loaded":  list(state["themes"].keys()),
        "default": state["default"],
    })


# ── Power profiles ───────────────────────────────────────────────────

@bp.route("/api/power/state")
@require_auth
def power_state():
    return jsonify({
        "ok":       True,
        "profile":  system.power_profile(),
        "profiles": system.POWER_PROFILES,
    })


@bp.route("/api/power/cycle", methods=["POST"])
@require_auth
def power_cycle():
    try:
        return jsonify({"ok": True, "profile": system.power_cycle()})
    except Exception:
        log.exception("power cycle failed")
        return jsonify({"ok": False, "error": "Power profile change failed"}), 500


# ── Notifications / DND ──────────────────────────────────────────────

@bp.route("/api/notif/state")
@require_auth
def notif_state():
    return jsonify({"ok": True, "inhibited": system.dnd_active()})


@bp.route("/api/notif/toggle", methods=["POST"])
@require_auth
def notif_toggle():
    try:
        new_state = not system.dnd_active()
        system.dnd_set(new_state)
        return jsonify({"ok": True, "inhibited": new_state})
    except Exception:
        log.exception("DND toggle failed")
        return jsonify({"ok": False, "error": "DND toggle failed"}), 500


@bp.route("/api/notif/list")
@require_auth
def notif_list():
    return jsonify({"ok": True, "notifications": notifications.list_history()})


@bp.route("/api/notif/clear", methods=["POST"])
@require_auth
def notif_clear():
    notifications.clear_history()
    return jsonify({"ok": True})


# ── Battery + sysinfo ────────────────────────────────────────────────

@bp.route("/api/battery")
@require_auth
def battery():
    return jsonify({"ok": True, **system.battery_info()})


@bp.route("/api/sysinfo")
@require_auth
def sysinfo():
    try:
        return jsonify({"ok": True, **system.sysinfo()})
    except Exception:
        log.exception("sysinfo failed")
        return jsonify({"ok": False, "error": "Could not read sysinfo"}), 500


# ── Shutdown / server-kill ───────────────────────────────────────────

@bp.route("/api/shutdown", methods=["POST"])
@require_auth
def shutdown():
    """KDE Plasma dialog if available, otherwise direct logind poweroff."""
    try:
        if caps.get().get("kde_plasma"):
            system.shutdown_prompt()
        elif caps.get().get("logind"):
            system.shutdown_logind()
        else:
            return jsonify({"ok": False, "error": "no shutdown backend available"}), 501
        return jsonify({"ok": True})
    except Exception:
        log.exception("shutdown failed")
        return jsonify({"ok": False, "error": "Shutdown failed"}), 500


# ── Server-Sent Events ──────────────────────────────────────────────

@bp.route("/api/events")
def events():
    """Long-lived SSE stream — replaces sysinfo/battery/lock-state polling.

    Auth is checked once at connection time. On session expiry the client
    reconnects via EventSource's built-in retry; the new connection then
    fails the auth check and falls back to login.
    """
    if not is_authed():
        return jsonify({"ok": False, "error": "Authentication required"}), 401

    q = realtime.add_subscriber()

    @stream_with_context
    def gen():
        try:
            # Initial comment so the connection is flushed immediately —
            # EventSource considers itself "open" once any byte arrives.
            yield ": connected\n\n"
            while True:
                try:
                    event = q.get(timeout=20)
                except _queue.Empty:
                    # Heartbeat keeps proxies (Cloudflare 100s idle limit,
                    # nginx 60s default) from collapsing the connection.
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                yield realtime.encode_sse(event["name"], event["data"])
        finally:
            realtime.remove_subscriber(q)

    resp = Response(gen(), mimetype="text/event-stream")
    # Disable buffering across the stack — nginx/Cloudflare honour
    # `X-Accel-Buffering: no`, the rest is belt-and-braces.
    resp.headers["Cache-Control"]    = "no-store"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Connection"]        = "keep-alive"
    return resp


@bp.route("/api/server/kill", methods=["POST"])
@require_auth
def server_kill():
    """SIGTERM to parent (start.sh) — the trap there cleans up server + tunnel.

    Runs in a background thread so the HTTP response returns successfully
    before the process is taken down; otherwise the client would see a
    connection-reset and assume the kill failed.
    """
    def _shutdown():
        time.sleep(0.5)
        try:
            os.kill(os.getppid(), signal.SIGTERM)
        except Exception:
            pass
        # Hard exit if start.sh's trap didn't reach us within 2s. We bypass
        # atexit handlers on purpose — the parent is supposed to do cleanup.
        time.sleep(2)
        os._exit(0)
    threading.Thread(target=_shutdown, daemon=True).start()
    return jsonify({"ok": True})
