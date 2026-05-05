"""Display brightness (KDE PowerManagement + ddcutil)."""

import logging

from flask import Blueprint, jsonify, request

from core import displays
from utils import require_auth

log = logging.getLogger("clientctl.routes.displays")

bp = Blueprint("displays", __name__)


@bp.route("/api/displays")
@require_auth
def list_displays():
    try:
        return jsonify({"ok": True, "displays": displays.detect()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/brightness/<display_id>", methods=["POST"])
@require_auth
def set_brightness(display_id: str):
    pct = (request.json or {}).get("brightness", 100)
    try:
        displays.set_brightness(display_id, pct)
        return jsonify({"ok": True, "brightness": int(pct)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
