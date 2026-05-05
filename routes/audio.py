"""Audio: master volume + per-app streams."""

import logging

from flask import Blueprint, jsonify, request

from core import audio
from utils import require_auth

log = logging.getLogger("clientctl.routes.audio")

bp = Blueprint("audio", __name__)


@bp.route("/api/volume", methods=["GET"])
@require_auth
def volume_get():
    try:
        return jsonify({"ok": True, **audio.master_state()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/volume", methods=["POST"])
@require_auth
def volume_set():
    body = request.json or {}
    try:
        audio.master_set(volume=body.get("volume"), mute=body.get("mute"))
        return jsonify({"ok": True, **audio.master_state()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/audio/streams")
@require_auth
def streams_list():
    try:
        return jsonify({"ok": True, "streams": audio.list_streams()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/audio/stream/<int:sid>", methods=["POST"])
@require_auth
def stream_set(sid: int):
    body = request.json or {}
    try:
        audio.stream_set(sid, volume=body.get("volume"), mute=body.get("mute"))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
