"""Security regression tests.

Each test pins down a hardening step so accidental relaxations get caught
in CI before they ship.
"""

import os
import re
import time
from pathlib import Path

import pytest

import config
from utils.ratelimit import RateLimiter


# ── Rate limiter primitive ──────────────────────────────────────────

def test_ratelimiter_allows_below_threshold():
    rl = RateLimiter(max_attempts=3, window_seconds=60)
    for _ in range(3):
        ok, _ = rl.check("client-A")
        assert ok


def test_ratelimiter_blocks_when_exceeded():
    rl = RateLimiter(max_attempts=2, window_seconds=60)
    rl.check("client-A")
    rl.check("client-A")
    ok, retry = rl.check("client-A")
    assert ok is False
    assert retry > 0


def test_ratelimiter_isolates_keys():
    rl = RateLimiter(max_attempts=2, window_seconds=60)
    rl.check("client-A")
    rl.check("client-A")
    ok_a, _ = rl.check("client-A")
    ok_b, _ = rl.check("client-B")
    assert ok_a is False
    assert ok_b is True


def test_ratelimiter_reset_clears_bucket():
    rl = RateLimiter(max_attempts=2, window_seconds=60)
    rl.check("client-A")
    rl.check("client-A")
    rl.reset("client-A")
    ok, _ = rl.check("client-A")
    assert ok is True


def test_ratelimiter_window_expires(monkeypatch):
    rl = RateLimiter(max_attempts=2, window_seconds=1)
    rl.check("client-A")
    rl.check("client-A")
    blocked, _ = rl.check("client-A")
    assert blocked is False
    # Simulate time passing past the window
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 5)
    ok, _ = rl.check("client-A")
    assert ok is True


# ── /api/login rate-limiting ────────────────────────────────────────

def test_login_rate_limit_blocks_brute_force(client, known_login_code):
    from utils import ratelimit
    ratelimit.LOGIN_LIMITER.reset("127.0.0.1")
    # Exhaust the limit (5 by default)
    for _ in range(5):
        client.post("/api/login", json={"code": "000000"})
    res = client.post("/api/login", json={"code": "000000"})
    assert res.status_code == 429
    assert "Too many attempts" in res.get_json()["error"]


def test_login_success_resets_rate_limit(client, known_login_code):
    from utils import ratelimit
    ratelimit.LOGIN_LIMITER.reset("127.0.0.1")
    # 4 wrong, then 1 right — bucket should be cleared
    for _ in range(4):
        client.post("/api/login", json={"code": "000000"})
    res = client.post("/api/login", json={"code": known_login_code})
    assert res.status_code == 200


# ── Constant-time comparisons ───────────────────────────────────────

def test_login_uses_compare_digest(monkeypatch, client, known_login_code):
    """Login path goes through hmac.compare_digest, not == .
       We assert it indirectly by patching compare_digest and checking
       the route still rejects wrong codes (no fallback to ==)."""
    import hmac, routes.auth as auth_module
    calls = {"n": 0}
    real = hmac.compare_digest

    def spy(a, b):
        calls["n"] += 1
        return real(a, b)

    monkeypatch.setattr(auth_module.hmac, "compare_digest", spy)
    from utils import ratelimit
    ratelimit.LOGIN_LIMITER.reset("127.0.0.1")
    client.post("/api/login", json={"code": "000000"})
    assert calls["n"] >= 1, "login should call hmac.compare_digest"


# ── Session cookie hardening ────────────────────────────────────────

def test_session_cookie_is_httponly(client, known_login_code):
    from utils import ratelimit
    ratelimit.LOGIN_LIMITER.reset("127.0.0.1")
    res = client.post("/api/login", json={"code": known_login_code})
    set_cookie = res.headers.get("Set-Cookie", "")
    assert "HttpOnly" in set_cookie, f"Set-Cookie missing HttpOnly: {set_cookie}"


def test_session_cookie_samesite(client, known_login_code):
    from utils import ratelimit
    ratelimit.LOGIN_LIMITER.reset("127.0.0.1")
    res = client.post("/api/login", json={"code": known_login_code})
    set_cookie = res.headers.get("Set-Cookie", "")
    assert "SameSite=Lax" in set_cookie, f"Set-Cookie missing SameSite=Lax: {set_cookie}"


# ── Security headers ────────────────────────────────────────────────

@pytest.mark.parametrize("header,expected", [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options",        "DENY"),
    ("Referrer-Policy",        "same-origin"),
])
def test_security_headers_present(client, header, expected):
    res = client.get("/api/ping")
    assert res.headers.get(header) == expected


def test_csp_header_present(client):
    res = client.get("/api/ping")
    csp = res.headers.get("Content-Security-Policy", "")
    # Must restrict frame embedding, forbid cross-origin connect, and
    # specifically forbid inline scripts (no 'unsafe-inline' in script-src).
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'self'"     in csp
    assert "connect-src 'self'"     in csp
    assert "script-src 'self'"      in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0], \
        "script-src must NOT permit 'unsafe-inline' — move inline scripts to /static/*.js"


def test_permissions_policy_header(client):
    res = client.get("/api/ping")
    pp = res.headers.get("Permissions-Policy", "")
    # The panel never needs the camera/mic/geolocation — they should be
    # explicitly forbidden so a future XSS can't enable them either.
    for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert f"{feature}=()" in pp, f"Permissions-Policy must disable {feature}"


def test_server_header_does_not_leak_framework(client):
    """Werkzeug's default `Server: Werkzeug/X Python/Y` is info disclosure.
    We replace it with a neutral string."""
    res = client.get("/api/ping")
    server_hdr = res.headers.get("Server", "")
    assert "werkzeug" not in server_hdr.lower(), f"Server header leaks: {server_hdr}"
    assert "python"   not in server_hdr.lower(), f"Server header leaks: {server_hdr}"


def test_hsts_only_when_secure_cookie_is_on(client, monkeypatch):
    """Strict-Transport-Security would do nothing on plain HTTP — only emit
    it when the operator has signaled HTTPS via CLIENTCTL_COOKIE_SECURE."""
    import config
    # Cookie-Secure off → no HSTS
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    res = client.get("/api/ping")
    assert "Strict-Transport-Security" not in res.headers


def test_hsts_emitted_when_secure_cookie_is_on(monkeypatch):
    """Re-create the app with COOKIE_SECURE=True and check HSTS shows up."""
    import importlib, config
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    import server as srv
    importlib.reload(srv)
    app = srv.create_app()
    with app.test_client() as c:
        res = c.get("/api/ping")
    hsts = res.headers.get("Strict-Transport-Security", "")
    assert "max-age=" in hsts and "includeSubDomains" in hsts


# ── secret.key permissions ──────────────────────────────────────────

def test_secret_key_permissions_are_owner_only():
    """state/secret.key must be 0600 — anyone reading it can forge sessions."""
    if not config.SECRET_FILE.exists():
        pytest.skip("secret.key not generated yet")
    mode = config.SECRET_FILE.stat().st_mode & 0o777
    assert mode == 0o600, f"secret.key has mode {oct(mode)}, expected 0o600"


# ── Input validation ────────────────────────────────────────────────

def test_brightness_rejects_non_numeric_ddc_id(authed_client, monkeypatch):
    """ddc-<num> must be digits only — no path traversal or arg injection."""
    from core import displays
    calls = {"ran": False}
    monkeypatch.setattr(displays, "run", lambda *a, **kw: calls.update(ran=True) or "")
    res = authed_client.post("/api/brightness/ddc-..%2Fetc%2Fpasswd",
                             json={"brightness": 50})
    # Whatever status the router/validator settles on (404 unknown route
    # after path-normalization, 405 from method routing, or 500 from the
    # validator's ValueError), ddcutil MUST NOT have been invoked.
    assert res.status_code in (404, 405, 500)
    assert calls["ran"] is False

    # Direct test against the validator: a non-numeric ddc id raises.
    from core import displays
    with pytest.raises(ValueError):
        displays.set_brightness("ddc-../etc/passwd", 50)


def test_cachy_icon_name_rejects_path_traversal(monkeypatch, tmp_path):
    """Even if state/tray_icon contains '../etc/passwd' the resolver must
    fall back to the safe default rather than building a path that
    escapes ICON_DIR."""
    from core import cachy
    fake_state = tmp_path / "tray_icon"
    fake_state.write_text("../../etc/passwd\n")
    monkeypatch.setattr(cachy, "STATE_FILE", fake_state)
    name = cachy.icon_name()
    assert name == cachy.FALLBACK


def test_cachy_icon_name_accepts_safe_names(monkeypatch, tmp_path):
    from core import cachy
    fake_state = tmp_path / "tray_icon"
    fake_state.write_text("cachy-update-yellow\n")
    monkeypatch.setattr(cachy, "STATE_FILE", fake_state)
    assert cachy.icon_name() == "cachy-update-yellow"


# ── Passkey credential enumeration ──────────────────────────────────

def test_passkey_auth_finish_returns_generic_error(client, monkeypatch):
    """Unknown / invalid credentials all return the same message — an
    attacker probing the endpoint can't distinguish 'credential exists
    but failed' from 'credential not registered'."""
    from utils import ratelimit
    ratelimit.PASSKEY_AUTH_LIMITER.reset("127.0.0.1")

    res = client.post("/api/passkey/auth/finish",
                      json={"_token": "bogus", "id": "anything"})
    body = res.get_json()
    assert res.status_code == 401
    error = body.get("error", "")
    # Specifically must NOT leak phrases like "Unknown passkey"
    assert "unknown" not in error.lower()
    assert "credential" not in error.lower()


# ── X-Forwarded-For multi-hop spoofing ──────────────────────────────

def test_xff_multi_hop_is_rejected_for_rate_limit_key(client, known_login_code):
    """Comma-separated XFF chains are ignored — attacker can't bypass the
    per-IP rate limit by forging multiple hops."""
    from utils import ratelimit
    ratelimit.LOGIN_LIMITER.reset("127.0.0.1")
    ratelimit.LOGIN_LIMITER.reset("1.2.3.4")
    # Multi-hop XFF is ignored; the bucket is keyed on remote_addr (127.0.0.1)
    for _ in range(5):
        client.post("/api/login",
                    json={"code": "000000"},
                    headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    # Bucket for the fallback key (127.0.0.1) should now be exhausted
    res = client.post("/api/login", json={"code": "000000"})
    assert res.status_code == 429
