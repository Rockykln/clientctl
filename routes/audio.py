"""Audio: master volume + per-app streams."""

import logging

from flask import Blueprint, jsonify, request

from core import audio
from utils import require_auth

log = logging.getLogger("clientctl.routes.audio")

bp = Blueprint("audio", __name__)


# Generic error response: log the full exception server-side, return a
# bounded user-facing message. Avoids leaking subprocess stderr / Python
# tracebacks to whoever can hit the route. Used by every except handler
# in this blueprint.
def _err(msg: str, status: int = 500):
    log.exception(msg)
    return jsonify({"ok": False, "error": msg}), status


@bp.route("/api/volume", methods=["GET"])
@require_auth
def volume_get():
    try:
        return jsonify({"ok": True, **audio.master_state()})
    except Exception:
        return _err("Could not read master volume")


@bp.route("/api/volume", methods=["POST"])
@require_auth
def volume_set():
    body = request.json or {}
    try:
        audio.master_set(volume=body.get("volume"), mute=body.get("mute"))
        return jsonify({"ok": True, **audio.master_state()})
    except Exception:
        return _err("Could not change master volume")


@bp.route("/api/audio/streams")
@require_auth
def streams_list():
    try:
        return jsonify({"ok": True, "streams": audio.list_streams()})
    except Exception:
        return _err("Could not list audio streams")


@bp.route("/api/audio/stream/<int:sid>", methods=["POST"])
@require_auth
def stream_set(sid: int):
    body = request.json or {}
    try:
        audio.stream_set(sid, volume=body.get("volume"), mute=body.get("mute"))
        return jsonify({"ok": True})
    except Exception:
        return _err("Could not change stream volume")
