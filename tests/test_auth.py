"""Auth flow integration tests via Flask test client."""

import pytest


# ── /api/status (unauthenticated) ────────────────────────────────────

def test_status_unauthed(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    body = res.get_json()
    assert body["authed"] is False
    assert "screen_locked" in body
    assert "passkey_count" in body


def test_ping_returns_204(client):
    res = client.get("/api/ping")
    assert res.status_code == 204
    assert res.data == b""


# ── /api/login ───────────────────────────────────────────────────────

def test_login_with_correct_code(client, known_login_code):
    res = client.post("/api/login", json={"code": known_login_code})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_login_strips_spaces(client, known_login_code):
    """Frontend formats the code as "123 456"; the server must accept that."""
    res = client.post("/api/login", json={"code": "123 456"})
    assert res.status_code == 200


def test_login_rejects_wrong_code(client, known_login_code):
    res = client.post("/api/login", json={"code": "000000"})
    assert res.status_code == 401
    body = res.get_json()
    assert body["ok"] is False
    assert "error" in body


def test_login_rejects_expired_code(client, monkeypatch):
    import config, time
    monkeypatch.setattr(config, "LOGIN_CODE", "999999")
    monkeypatch.setattr(config, "LOGIN_CODE_EXPIRES", time.time() - 1)
    res = client.post("/api/login", json={"code": "999999"})
    assert res.status_code == 401
    assert "expired" in res.get_json()["error"].lower()


def test_login_missing_payload(client):
    res = client.post("/api/login", json={})
    assert res.status_code == 401   # treated as wrong code


# ── Authed status / logout ──────────────────────────────────────────

def test_status_after_login(authed_client):
    res = authed_client.get("/api/status")
    assert res.get_json()["authed"] is True


def test_logout_clears_session(authed_client):
    res = authed_client.post("/api/logout")
    assert res.status_code == 200
    res2 = authed_client.get("/api/status")
    assert res2.get_json()["authed"] is False


# ── Auth-protected routes return 401 without session ───────────────

@pytest.mark.parametrize("method,path", [
    ("GET",  "/api/sysinfo"),
    ("GET",  "/api/battery"),
    ("GET",  "/api/volume"),
    ("GET",  "/api/displays"),
    ("GET",  "/api/audio/streams"),
    ("GET",  "/api/notif/state"),
    ("GET",  "/api/notif/list"),
    ("GET",  "/api/power/state"),
    ("GET",  "/api/passkey/list"),
    ("GET",  "/api/apps/list"),
    ("GET",  "/api/apps/status"),
    ("POST", "/api/lock"),
    ("POST", "/api/notif/toggle"),
    ("POST", "/api/power/cycle"),
])
def test_routes_require_auth(client, method, path):
    res = client.open(path, method=method, json={})
    assert res.status_code == 401, f"{method} {path} returned {res.status_code}"


# ── Capabilities is auth-gated (host fingerprinting protection) ────

def test_capabilities_returns_capability_keys_when_authed(authed_client):
    res = authed_client.get("/api/capabilities")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    # Must contain all standard capability keys
    for key in ("kde_plasma", "audio", "gpu", "battery"):
        assert key in body


# ── Passkey registration availability flag ──────────────────────────

def test_passkey_list_reports_registration_enabled(authed_client, monkeypatch):
    """When PASSKEY_REGISTRATION_PASSWORD is set, registration is enabled."""
    import config
    monkeypatch.setattr(config, "REG_PASSWORD", "x" * 36)
    res = authed_client.get("/api/passkey/list")
    assert res.status_code == 200
    body = res.get_json()
    assert body["registration_enabled"] is True
    assert "count" in body
    assert "max" in body


def test_passkey_list_reports_registration_disabled(authed_client, monkeypatch):
    """When PASSKEY_REGISTRATION_PASSWORD is empty, registration is disabled.

    The frontend uses this to disable the "Add passkey" button so users
    don't hit a 500 ("Server setup incomplete") after entering a password.
    """
    import config
    monkeypatch.setattr(config, "REG_PASSWORD", "")
    res = authed_client.get("/api/passkey/list")
    body = res.get_json()
    assert body["registration_enabled"] is False


def test_passkey_register_begin_blocked_without_setup_password(authed_client, monkeypatch):
    """The actual registration endpoint matches what the flag advertises."""
    import config
    monkeypatch.setattr(config, "REG_PASSWORD", "")
    res = authed_client.post("/api/passkey/register/begin",
                             json={"password": "anything", "name": "phone"})
    assert res.status_code == 500
    assert "incomplete" in res.get_json()["error"].lower()


# ── Passkey identification metadata (UA / MAC / usage counter) ──────

def test_ua_summary_recognises_common_browsers():
    from routes.auth import _ua_summary
    ipad_safari   = ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
                     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                     "Mobile/15E148 Safari/604.1")
    macos_chrome  = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/130.0 Safari/537.36")
    win_edge      = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/130.0 Safari/537.36 Edg/130.0")
    linux_ff      = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
                     "Gecko/20100101 Firefox/128.0")

    assert _ua_summary(ipad_safari)  == "iPad · Safari"
    assert _ua_summary(macos_chrome) == "macOS · Chrome"
    assert _ua_summary(win_edge)     == "Windows · Edge"
    assert _ua_summary(linux_ff)     == "Linux · Firefox"
    assert _ua_summary("")           == ""


def test_lookup_mac_returns_empty_for_loopback_and_unknown():
    """The function must short-circuit on loopback/unknown — these always
    come from the tunnel path where MAC lookup is meaningless."""
    from routes.auth import _lookup_mac
    assert _lookup_mac("")            == ""
    assert _lookup_mac("unknown")     == ""
    assert _lookup_mac("127.0.0.1")   == ""
    assert _lookup_mac("::1")         == ""


def test_lookup_mac_reads_from_arp_table(tmp_path, monkeypatch):
    """Real lookup path: parse /proc/net/arp and find the matching IP."""
    fake_arp = tmp_path / "arp"
    fake_arp.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.50.10    0x1         0x2         aa:bb:cc:dd:ee:ff     *        wlan0\n"
        "192.168.50.20    0x1         0x2         00:00:00:00:00:00     *        wlan0\n"
    )
    import builtins
    real_open = builtins.open

    def fake_open(path, *a, **kw):
        if str(path) == "/proc/net/arp":
            return real_open(fake_arp, *a, **kw)
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)
    from routes.auth import _lookup_mac
    assert _lookup_mac("192.168.50.10") == "aa:bb:cc:dd:ee:ff"
    # All-zero MAC is treated as "no entry" — UPower/incomplete ARP rows.
    assert _lookup_mac("192.168.50.20") == ""
    # Unknown IP → empty
    assert _lookup_mac("10.0.0.99")     == ""


def test_passkey_list_exposes_identification_fields(authed_client, tmp_state):
    """The list endpoint must surface mac/ip/ua/use_count/last_used so the
    UI can render production-safe device identification."""
    import json, time
    config_passkey = {
        "id":         "abc",
        "public_key": "key",
        "sign_count": 0,
        "name":       "iPad",
        "created":    int(time.time()),
        "ip":         "192.168.50.10",
        "mac":        "aa:bb:cc:dd:ee:ff",
        "ua_summary": "iPad · Safari",
        "use_count":  3,
        "last_used":  int(time.time()) - 100,
    }
    tmp_state.joinpath("passkeys.json").write_text(
        json.dumps({"passkeys": [config_passkey]})
    )
    res = authed_client.get("/api/passkey/list")
    body = res.get_json()
    assert body["count"] == 1
    p = body["passkeys"][0]
    # Every new identification field must be present in the payload —
    # the frontend joins them into the metadata line under the name.
    for field in ("mac", "ip", "ua", "use_count", "last_used"):
        assert field in p, f"missing {field}"
    assert p["mac"]       == "aa:bb:cc:dd:ee:ff"
    assert p["ua"]        == "iPad · Safari"
    assert p["use_count"] == 3
