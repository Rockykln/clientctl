"""clientctl — Flask entry point.

Minimal entry:
  - load config (config.py)
  - probe capabilities (utils.caps)
  - start notification + intel-gpu listeners (core.notifications / core.intel_gpu)
  - register blueprints (routes.*)
  - print banner + run server

All backend logic lives in core/, all HTTP handlers in routes/.
"""

import sys
# Suppress .pyc creation regardless of how we're invoked. Setting this
# before any other import means no __pycache__ shows up in the project tree.
sys.dont_write_bytecode = True

import atexit
import logging
import mimetypes
import os
import shutil
import signal
import socket
from pathlib import Path

# Register the PWA manifest MIME so /manifest.webmanifest is served as
# `application/manifest+json` — browsers reject manifests with the wrong
# Content-Type. Werkzeug doesn't ship this in its default table.
mimetypes.add_type("application/manifest+json", ".webmanifest")

from flask import Flask, send_from_directory

import config
from core import intel_gpu, notifications, realtime, themes as themes_module
from routes.apps     import bp as apps_bp
from routes.audio    import bp as audio_bp
from routes.auth     import bp as auth_bp
from routes.cachy    import bp as cachy_bp
from routes.displays import bp as displays_bp
from routes.system   import bp as system_bp
from utils import caps, run

log = logging.getLogger("clientctl.server")


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.secret_key                 = config.SECRET_KEY
    app.permanent_session_lifetime = config.SESSION_TTL_SECONDS

    # Load themes from themes.yml (creates from themes.example.yml on first run)
    themes_module.load()

    # Session cookie hardening
    #   HttpOnly  — JS can't read the cookie (XSS mitigation)
    #   SameSite  — browser refuses to send the cookie on cross-site requests (CSRF)
    #   Secure    — opt-in via env when behind HTTPS; refuses cookie over plain HTTP
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.COOKIE_SECURE,
    )

    # Defense-in-depth security headers on every response
    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options",        "DENY")
        resp.headers.setdefault("Referrer-Policy",        "same-origin")
        # Lock down browser features the panel doesn't use. Especially:
        # cameras / microphones / location have no business firing here.
        resp.headers.setdefault(
            "Permissions-Policy",
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()",
        )
        # CSP: scripts come exclusively from /self (no inline) — possible
        # because the theme bootstrap was moved out to /theme-bootstrap.js.
        # Inline styles are still allowed (theme-picker swatches set CSS
        # custom props inline). Tightening that would require nonces.
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "worker-src 'self'; "
            "manifest-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        # HSTS only when we know we're served over HTTPS — sending it on
        # plain HTTP is harmless but useless; gate on the same flag that
        # marks cookies Secure.
        if config.COOKIE_SECURE:
            resp.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        # Don't advertise the framework + version. Werkzeug sets
        # `Server: Werkzeug/X.Y.Z Python/A.B.C` by default — info disclosure.
        resp.headers["Server"] = "clientctl"
        return resp

    # ── Error pages ───────────────────────────────────────────
    # JSON for /api/* paths (caller is most likely fetch/XHR), styled
    # HTML for everything else. Both share the same /static/error.html
    # template so they pick up the active theme automatically.
    _ERROR_META = {
        401: ("Sign-in required",
              "Your session expired or you're not signed in. Open the panel and authenticate again."),
        403: ("Forbidden",
              "Your session doesn't grant access to this action."),
        404: ("Not found",
              "We couldn't find the page or resource you asked for."),
        405: ("Method not allowed",
              "The endpoint exists but doesn't accept this HTTP verb."),
        429: ("Too many requests",
              "You've hit the rate limit. Wait a minute and try again."),
        500: ("Something broke",
              "An unexpected error happened on the server. The console log has details."),
        502: ("Tunnel down",
              "The Cloudflare tunnel can't reach the server right now."),
        503: ("Service unavailable",
              "The server is temporarily not accepting requests."),
    }

    def _render_error(code: int):
        from flask import request, jsonify, Response
        title, msg = _ERROR_META.get(code, ("Error", "Something went wrong."))

        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": title, "code": code}), code

        try:
            tpl = (config.STATIC / "error.html").read_text()
        except Exception:
            return Response(f"{code} {title}", status=code, mimetype="text/plain")
        body = (tpl
                .replace("{{STATUS}}",  str(code))
                .replace("{{TITLE}}",   title)
                .replace("{{MESSAGE}}", msg)
                .replace("<body class=\"error-page\">",
                         f'<body class="error-page" data-status="{code}">'))
        return Response(body, status=code, mimetype="text/html; charset=utf-8")

    # Register the same handler for every code — Flask wires by status.
    for _code in (401, 403, 404, 405, 429, 500, 502, 503):
        app.register_error_handler(_code, lambda e, c=_code: _render_error(c))

    # Static files (always no-store so Safari picks up new JS/CSS)
    @app.route("/")
    def index():
        resp = send_from_directory(config.STATIC, "index.html")
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp

    # Theme-CSS gets generated from themes.yml at server start (and on
    # /api/themes/reload). Served at /themes.css so the existing
    # `<link>` setup just needs one extra entry in index.html.
    @app.route("/themes.css")
    def themes_css():
        from flask import Response
        css = themes_module.get_css()
        resp = Response(css, mimetype="text/css")
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp

    @app.route("/<path:p>")
    def static_files(p):
        resp = send_from_directory(config.STATIC, p)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp

    for bp in (auth_bp, apps_bp, audio_bp, displays_bp, system_bp, cachy_bp):
        app.register_blueprint(bp)

    return app


def _local_ips() -> list[str]:
    ips = []
    try:
        out = run(["ip", "-4", "addr"])
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and not line.startswith("inet 127."):
                ips.append(line.split()[1].split("/")[0])
    except Exception:
        try:
            ips.append(socket.gethostbyname(socket.gethostname()))
        except Exception:
            pass
    return ips


def banner(app_caps: dict) -> None:
    code = config.LOGIN_CODE
    formatted = f"{code[:3]} {code[3:]}"
    print()
    print("=" * 60)
    print(f"  clientctl v{config.VERSION} — login code")
    print("=" * 60)
    print()
    print(f"  Mode   {config.MODE}    (bind {config.BIND_HOST}:{config.PORT})")
    print(f"  Code   {formatted}")
    print(f"  TTL    {config.CODE_TTL_SECONDS // 60} minutes")
    print()
    if config.MODE == "dev":
        print(f"  Open   http://127.0.0.1:{config.PORT}   (localhost only)")
    elif config.MODE == "tunnel":
        print(f"  Open   via your Cloudflare tunnel hostname (HTTPS)")
        print(f"         server itself bound to 127.0.0.1:{config.PORT}")
    else:
        for ip in _local_ips():
            print(f"  Open   http://{ip}:{config.PORT}")
    print()
    print(f"  Renew  kill -USR1 {os.getpid()}   (regenerates the code)")
    print()
    available = [k for k, v in app_caps.items() if v not in (False, "none", "")]
    if available:
        print(f"  Caps   {', '.join(available)}")
    if not config.LAUNCHABLE_APPS:
        print("  ! apps.yml is empty or missing — grid will be empty")
    print()
    print("=" * 60)
    print()


_CLEANUP_DIRS = ("__pycache__", ".pytest_cache")


def _cleanup_artifacts() -> None:
    """Remove transient build/test artifacts on exit.

    Only triggers when run as a script (not from pytest). Belt-and-braces
    on top of `sys.dont_write_bytecode = True` — Python may have written
    bytecode before that line ran, or pytest left some behind earlier.
    """
    root = Path(__file__).resolve().parent
    skip_parts = (".venv", "venv", ".git")
    for d in root.rglob("*"):
        if not d.is_dir() or d.name not in _CLEANUP_DIRS:
            continue
        if any(part in skip_parts for part in d.parts):
            continue
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


def _signal_exit(signum, _frame):
    """Make SIGTERM / SIGINT trigger atexit handlers (default would skip them)."""
    sys.exit(0)


def _signal_regen_code(_signum, _frame):
    """SIGUSR1 → regenerate the login code on demand.

    Use case: the original 6-digit code expired (10 min TTL) and you want
    to log in again without restarting the server. Send:
        kill -USR1 <pid_of_python>
    The new code is printed to the server's stdout (visible in start.sh's
    terminal or the systemd journal).
    """
    code = config.regenerate_login_code()
    formatted = f"{code[:3]} {code[3:]}"
    print()
    print("=" * 60)
    print(f"  ↻ Login code regenerated   {formatted}")
    print(f"    Valid for {config.CODE_TTL_SECONDS // 60} minutes")
    print("=" * 60)
    print(flush=True)


if __name__ == "__main__":
    atexit.register(_cleanup_artifacts)
    signal.signal(signal.SIGTERM, _signal_exit)
    signal.signal(signal.SIGINT,  _signal_exit)
    signal.signal(signal.SIGUSR1, _signal_regen_code)

    app_caps = caps.detect()
    if app_caps.get("dbus_monitor"):
        notifications.start_listener()
    if app_caps.get("gpu") == "intel":
        intel_gpu.start_listener()
    # SSE producer threads — push live state to /api/events subscribers.
    realtime.start_listener()

    app = create_app()
    banner(app_caps)

    # threaded=True → slow KWin/journalctl calls don't block other requests
    # Bind host comes from config.MODE:
    #   dev     → 127.0.0.1
    #   lan     → 0.0.0.0    (default; auth + rate-limit + cookies cover the exposure)
    #   tunnel  → 127.0.0.1   (cloudflared takes care of the public side)
    # nosec B104  — explicitly chosen via MODE, never an accident
    app.run(host=config.BIND_HOST, port=config.PORT, debug=False, threaded=True)  # nosec B104
