"""Cachy-Update cell: state, icon, run."""

import logging
import os
import subprocess

from flask import Blueprint, abort, jsonify, send_file

from core import cachy, kwin
from utils import require_auth

log = logging.getLogger("clientctl.routes.cachy")

bp = Blueprint("cachy", __name__)


@bp.route("/api/cachy/state")
@require_auth
def state():
    return jsonify({"ok": True, **cachy.state()})


@bp.route("/api/cachy/icon")
def icon():
    # Manual auth check (not @require_auth): served to an <img> tag; a
    # JSON-401 would render as a broken image. See routes/apps.py:app_icon.
    from utils import is_authed
    if not is_authed():
        abort(401)
    path = cachy.icon_path()
    if not path:
        abort(404)
    resp = send_file(path, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/cachy/run", methods=["POST"])
@require_auth
def run_cachy():
    try:
        pids = cachy.konsole_pids()
        if pids:
            cfg = {**cachy.KONSOLE_CFG, "pids": pids}
            kwin.toggle(cfg)
            return jsonify({"ok": True, "action": "toggled"})
        subprocess.Popen(
            ["konsole", "--title", "Cachy-Update", "-e", "arch-update"],
            start_new_session=True,
            env={**os.environ},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({"ok": True, "action": "launched"})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "konsole not found"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
