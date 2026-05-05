"""Session-auth helpers."""

from functools import wraps

from flask import jsonify, session


def is_authed() -> bool:
    return session.get("authed") is True


def require_auth(view):
    """Decorator: returns 401 JSON if no session, otherwise calls the view.

    The error shape matches every other JSON route in the app
    (``{"ok": False, "error": ...}``) so the frontend's generic error
    handler doesn't need a special case.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_authed():
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        return view(*args, **kwargs)
    return wrapper
