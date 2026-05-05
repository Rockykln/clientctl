"""Auth: code login, passkey registration & authentication.

Server-side challenge store keyed by token (instead of Flask session) so
the begin/finish flow does not depend on cookies between the two calls.

Hardening:
  - Rate-limit /api/login + /api/passkey/* per remote IP (brute-force gate)
  - hmac.compare_digest for code + setup-password (timing-attack mitigation)
  - Generic error messages on passkey auth (no credential enumeration)
"""

import hmac
import json
import logging
import os
import secrets
import subprocess
import threading
import time
from urllib.parse import quote

from flask import Blueprint, jsonify, request, session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

import config
from utils import b64url_decode, b64url_encode, is_authed, require_auth
from utils.ratelimit import LOGIN_LIMITER, PASSKEY_AUTH_LIMITER, PASSKEY_REG_LIMITER

log = logging.getLogger("clientctl.auth")


def _client_ip() -> str:
    """Best-effort remote IP for rate-limit keys. Honours X-Forwarded-For
    only when it's a single hop, since the server should sit behind at most
    one proxy (Cloudflare tunnel) — multi-hop spoofing is rejected."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd and "," not in fwd:
        return fwd.strip()
    return request.remote_addr or "unknown"


def _safe_log(s) -> str:
    """URL-quote user-controllable data before sending it to log.*

    Prevents log injection via crafted X-Forwarded-For headers (or any
    request-derived string carrying CR/LF). `urllib.parse.quote` is on
    CodeQL's recognised-sanitizer list — using it here documents the
    intent at the type level instead of relying on a regex CodeQL can't
    follow through a helper.
    """
    return quote(str(s), safe=":.@/-")[:200]


def _lookup_mac(ip: str) -> str:
    """Read /proc/net/arp to find the MAC for the given IP.

    Only useful for clients on the same L2 segment (LAN). Through the
    Cloudflare tunnel the remote IP collapses to 127.0.0.1, so this returns
    "" for loopback or any address not in the ARP cache."""
    if not ip or ip in ("unknown", "127.0.0.1", "::1"):
        return ""
    try:
        with open("/proc/net/arp") as f:
            next(f)  # skip header
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip:
                    mac = parts[3]
                    return "" if mac == "00:00:00:00:00:00" else mac
    except Exception:
        pass
    return ""


def _ua_summary(ua: str) -> str:
    """Compact UA string → 'iPad · Safari', 'macOS · Firefox', etc.
    Used as a fallback identifier when no MAC is available (tunnel access)."""
    if not ua:
        return ""
    ua_l = ua.lower()
    if   "iphone"   in ua_l: device = "iPhone"
    elif "ipad"     in ua_l: device = "iPad"
    elif "android"  in ua_l: device = "Android"
    elif "mac os x" in ua_l: device = "macOS"
    elif "windows"  in ua_l: device = "Windows"
    elif "linux"    in ua_l: device = "Linux"
    else:                    device = "Device"
    if   "firefox/"      in ua_l: browser = "Firefox"
    elif "edg/"          in ua_l: browser = "Edge"
    elif "chrome/"       in ua_l and "edg/" not in ua_l: browser = "Chrome"
    elif "safari/"       in ua_l: browser = "Safari"
    else:                          browser = "Browser"
    return f"{device} · {browser}"


bp = Blueprint("auth", __name__)


# ── Passkey storage ──────────────────────────────────────────────────

def load_passkeys() -> list[dict]:
    try:
        with config.PASSKEYS_FILE.open("r") as f:
            data = json.load(f)
        return data.get("passkeys", []) if isinstance(data, dict) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        log.warning("passkeys.json corrupt: %s", e)
        return []


def save_passkeys(items: list[dict]) -> None:
    config.PASSKEYS_FILE.write_text(json.dumps({"passkeys": items}, indent=2))
    try:
        os.chmod(config.PASSKEYS_FILE, 0o600)
    except Exception:
        pass


# ── Challenge store ──────────────────────────────────────────────────
# Server-side dict, token returned via response — robust against cookie
# issues between begin and finish.

_CHALLENGES: dict[str, dict] = {}
_CHALLENGE_LOCK = threading.Lock()
_CHALLENGE_TTL  = 300


def _challenge_store(challenge_bytes: bytes, kind: str, extra: dict | None = None) -> str:
    token   = b64url_encode(secrets.token_bytes(16))
    expires = time.time() + _CHALLENGE_TTL
    with _CHALLENGE_LOCK:
        now = time.time()
        # Drop expired entries
        for t in list(_CHALLENGES.keys()):
            if _CHALLENGES[t]["expires"] < now:
                del _CHALLENGES[t]
        _CHALLENGES[token] = {
            "challenge": b64url_encode(challenge_bytes),
            "kind":      kind,
            "extra":     extra or {},
            "expires":   expires,
        }
    return token


def _challenge_take(token: str, kind: str) -> dict | None:
    with _CHALLENGE_LOCK:
        entry = _CHALLENGES.pop(token, None)
    if not entry or entry["kind"] != kind or entry["expires"] < time.time():
        return None
    return entry


# ── Lock / unlock helpers ────────────────────────────────────────────

_LOCK_CACHE = {"value": False, "ts": 0.0}
_LOCK_CACHE_TTL = 0.8


def screen_locked() -> bool:
    """Read lock state via org.freedesktop.ScreenSaver.GetActive (cached 0.8s)."""
    now = time.time()
    if now - _LOCK_CACHE["ts"] < _LOCK_CACHE_TTL:
        return _LOCK_CACHE["value"]
    try:
        out = subprocess.check_output(
            ["busctl", "--user", "call",
             "org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
             "org.freedesktop.ScreenSaver", "GetActive"],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        val = out.endswith("true")
    except Exception:
        val = False
    _LOCK_CACHE["value"] = val
    _LOCK_CACHE["ts"]    = now
    return val


def do_unlock_session() -> None:
    try:
        subprocess.run(
            ["loginctl", "unlock-session"],
            check=True, timeout=5,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ── Routes ───────────────────────────────────────────────────────────

@bp.route("/api/status")
def status():
    return jsonify({
        "authed":        is_authed(),
        "screen_locked": screen_locked(),
        "passkey_count": len(load_passkeys()),
    })


@bp.route("/api/ping")
def ping():
    return ("", 204)


@bp.route("/api/login", methods=["POST"])
def login():
    ip = _client_ip()
    allowed, retry_in = LOGIN_LIMITER.check(ip)
    if not allowed:
        log.warning("login: rate-limited %s (retry in %ds)", _safe_log(ip), int(retry_in))
        return jsonify({
            "ok":    False,
            "error": f"Too many attempts. Try again in {int(retry_in)} seconds.",
        }), 429

    body = request.json or {}
    code = body.get("code", "").replace(" ", "")
    remember = bool(body.get("remember", False))

    if time.time() > config.LOGIN_CODE_EXPIRES:
        return jsonify({
            "ok":    False,
            "error": "Code expired — send SIGUSR1 to the server (or restart) "
                     "to regenerate.",
        }), 401
    # hmac.compare_digest avoids leaking how many leading digits matched
    # via response timing (mostly theoretical for 6-digit numerics, but free).
    if not hmac.compare_digest(code, config.LOGIN_CODE):
        return jsonify({"ok": False, "error": "Invalid code"}), 401

    LOGIN_LIMITER.reset(ip)        # successful login clears the bucket
    session.permanent = True
    session["authed"] = True
    # Dynamic per-session lifetime: 7d default, 14d if "remember me" is set.
    # Flask reads app.permanent_session_lifetime per-request, so this works
    # without mutating app config globally.
    from flask import current_app
    from datetime import timedelta
    secs = (config.SESSION_TTL_REMEMBER_SECONDS if remember
            else config.SESSION_TTL_SECONDS)
    current_app.permanent_session_lifetime = timedelta(seconds=secs)
    return jsonify({"ok": True, "remember": remember})


@bp.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.route("/api/lock", methods=["POST"])
@require_auth
def lock():
    try:
        # Fire-and-forget — does not wait for loginctl
        subprocess.Popen(
            ["loginctl", "lock-session"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return jsonify({"ok": True})
    except Exception:
        log.exception("lock-session failed")
        return jsonify({"ok": False, "error": "Lock failed"}), 500


@bp.route("/api/unlock", methods=["POST"])
@require_auth
def unlock():
    do_unlock_session()
    return jsonify({"ok": True})


# ── Passkeys ─────────────────────────────────────────────────────────

@bp.route("/api/passkey/list")
@require_auth
def passkey_list():
    items = load_passkeys()
    return jsonify({
        "ok":    True,
        "count": len(items),
        "max":   config.MAX_PASSKEYS,
        # True only when PASSKEY_REGISTRATION_PASSWORD is configured —
        # the frontend uses this to disable the "Add passkey" button so
        # users don't hit a 500 error after entering a setup password.
        "registration_enabled": bool(config.REG_PASSWORD),
        "passkeys": [
            {
                "id":        p["id"],
                "name":      p.get("name", ""),
                "created":   p.get("created", 0),
                "mac":       p.get("mac", ""),
                "ip":        p.get("ip", ""),
                "ua":        p.get("ua_summary", ""),
                "use_count": p.get("use_count", 0),
                "last_used": p.get("last_used", 0),
            }
            for p in items
        ],
    })


@bp.route("/api/passkey/delete", methods=["POST"])
@require_auth
def passkey_delete():
    cred_id = (request.json or {}).get("id", "")
    if not cred_id:
        return jsonify({"ok": False, "error": "id required"}), 400
    items = [p for p in load_passkeys() if p["id"] != cred_id]
    save_passkeys(items)
    return jsonify({"ok": True, "count": len(items)})


@bp.route("/api/passkey/register/begin", methods=["POST"])
@require_auth
def passkey_register_begin():
    ip = _client_ip()
    allowed, retry_in = PASSKEY_REG_LIMITER.check(ip)
    if not allowed:
        log.warning("passkey-register: rate-limited %s (retry in %ds)", _safe_log(ip), int(retry_in))
        return jsonify({
            "ok":    False,
            "error": f"Too many attempts. Try again in {int(retry_in)} seconds.",
        }), 429

    body = request.json or {}
    if not config.REG_PASSWORD:
        return jsonify({"ok": False, "error": "Server setup incomplete"}), 500
    # Constant-time compare — the setup password is high-value and worth
    # protecting from timing-based char-by-char enumeration.
    if not hmac.compare_digest(body.get("password", ""), config.REG_PASSWORD):
        return jsonify({"ok": False, "error": "Wrong setup password"}), 401
    PASSKEY_REG_LIMITER.reset(ip)

    items = load_passkeys()
    if len(items) >= config.MAX_PASSKEYS:
        return jsonify({"ok": False, "error": f"Max {config.MAX_PASSKEYS} passkeys"}), 400

    name = (body.get("name") or "Device").strip()[:50]

    exclude = [
        PublicKeyCredentialDescriptor(id=b64url_decode(p["id"]))
        for p in items
    ]
    options = generate_registration_options(
        rp_id=config.RP_ID,
        rp_name=config.RP_NAME,
        user_id=config.USER_ID_BYTES,
        user_name=config.USER_NAME,
        user_display_name=config.USER_NAME,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
        exclude_credentials=exclude,
    )
    token = _challenge_store(options.challenge, "register", {"name": name})
    options_dict = json.loads(options_to_json(options))
    options_dict["_token"] = token
    return jsonify(options_dict)


@bp.route("/api/passkey/register/finish", methods=["POST"])
@require_auth
def passkey_register_finish():
    body  = request.json or {}
    token = body.pop("_token", "")
    entry = _challenge_take(token, "register")
    if not entry:
        return jsonify({"ok": False, "error": "No registration flow active"}), 400

    try:
        verification = verify_registration_response(
            credential=body,
            expected_challenge=b64url_decode(entry["challenge"]),
            expected_origin=config.ORIGIN,
            expected_rp_id=config.RP_ID,
        )
    except Exception:
        log.exception("passkey-register: verification failed")
        return jsonify({"ok": False, "error": "Verification failed"}), 400

    items = load_passkeys()
    if len(items) >= config.MAX_PASSKEYS:
        return jsonify({"ok": False, "error": "Max reached"}), 400

    name = entry["extra"].get("name", "Device")
    ip   = _client_ip()
    items.append({
        "id":         b64url_encode(verification.credential_id),
        "public_key": b64url_encode(verification.credential_public_key),
        "sign_count": verification.sign_count,
        "name":       name,
        "created":    int(time.time()),
        # Identification metadata so the user can tell devices apart in
        # the passkey list. MAC is best-effort (LAN clients only — empty
        # via tunnel); UA summary is the realistic fallback identifier.
        "ip":         ip,
        "mac":        _lookup_mac(ip),
        "ua_summary": _ua_summary(request.headers.get("User-Agent", "")),
    })
    save_passkeys(items)
    return jsonify({"ok": True, "name": name, "count": len(items)})


@bp.route("/api/passkey/auth/begin", methods=["POST"])
def passkey_auth_begin():
    """No auth required — this IS the auth flow."""
    items = load_passkeys()
    if not items:
        return jsonify({"ok": False, "error": "No passkeys registered"}), 400

    allow = [
        PublicKeyCredentialDescriptor(id=b64url_decode(p["id"]))
        for p in items
    ]
    options = generate_authentication_options(
        rp_id=config.RP_ID,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    token = _challenge_store(options.challenge, "auth")
    options_dict = json.loads(options_to_json(options))
    options_dict["_token"] = token
    return jsonify(options_dict)


@bp.route("/api/passkey/auth/finish", methods=["POST"])
def passkey_auth_finish():
    """Verifies passkey login and also unlocks the PC.

    Generic error messages on every failure path so attackers can't tell
    "credential exists but verification failed" from "credential unknown" —
    both leaks would help them enumerate registered passkeys.
    """
    ip = _client_ip()
    allowed, retry_in = PASSKEY_AUTH_LIMITER.check(ip)
    if not allowed:
        log.warning("passkey-auth: rate-limited %s (retry in %ds)", _safe_log(ip), int(retry_in))
        return jsonify({
            "ok":    False,
            "error": f"Too many attempts. Try again in {int(retry_in)} seconds.",
        }), 429

    body  = request.json or {}
    token = body.pop("_token", "")
    entry = _challenge_take(token, "auth")
    if not entry:
        return jsonify({"ok": False, "error": "Authentication failed"}), 401

    cred_id_b64 = body.get("id", "")
    items = load_passkeys()
    # hmac.compare_digest in the lookup so the runtime doesn't depend on
    # which credential matched (or whether one matched at all).
    matching = next(
        (p for p in items if hmac.compare_digest(p["id"], cred_id_b64)),
        None,
    )
    if not matching:
        log.info("passkey-auth: unknown credential id from %s", _safe_log(ip))
        return jsonify({"ok": False, "error": "Authentication failed"}), 401

    try:
        verification = verify_authentication_response(
            credential=body,
            expected_challenge=b64url_decode(entry["challenge"]),
            expected_origin=config.ORIGIN,
            expected_rp_id=config.RP_ID,
            credential_public_key=b64url_decode(matching["public_key"]),
            credential_current_sign_count=matching["sign_count"],
        )
    except Exception as e:
        log.info("passkey-auth: verification failed from %s: %s", _safe_log(ip), _safe_log(e))
        return jsonify({"ok": False, "error": "Authentication failed"}), 401

    matching["sign_count"] = verification.new_sign_count
    # Independent server-side usage counter — Apple/Windows Hello always
    # report sign_count=0 (anti-fingerprinting per WebAuthn spec), so we
    # track this ourselves for the UI.
    matching["use_count"] = matching.get("use_count", 0) + 1
    matching["last_used"] = int(time.time())
    save_passkeys(items)

    PASSKEY_AUTH_LIMITER.reset(ip)
    session.permanent = True
    session["authed"] = True
    do_unlock_session()
    return jsonify({"ok": True, "name": matching.get("name", "")})
