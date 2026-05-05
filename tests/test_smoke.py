"""Smoke tests — verifies the project imports and wires up correctly.

These run on any machine, no KDE/Plasma required.
"""

import importlib


def test_all_modules_importable():
    modules = [
        "config",
        "utils", "utils.shell", "utils.encoding", "utils.auth", "utils.caps",
        "core", "core.procs", "core.kwin", "core.notifications",
        "core.intel_gpu", "core.audio", "core.displays", "core.system",
        "core.cachy",
        "routes", "routes.auth", "routes.apps", "routes.audio",
        "routes.displays", "routes.system", "routes.cachy",
        "server",
    ]
    for name in modules:
        importlib.import_module(name)


def test_create_app_registers_all_blueprints():
    from server import create_app
    app = create_app()
    bp_names = set(app.blueprints.keys())
    assert {"auth", "apps", "audio", "displays", "system", "cachy"} <= bp_names


def test_url_map_has_expected_routes():
    from server import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules()}
    expected = {
        "/api/status", "/api/ping", "/api/login", "/api/logout",
        "/api/lock", "/api/unlock",
        "/api/passkey/list", "/api/passkey/delete",
        "/api/passkey/register/begin", "/api/passkey/register/finish",
        "/api/passkey/auth/begin", "/api/passkey/auth/finish",
        "/api/sysinfo", "/api/battery", "/api/capabilities", "/api/version",
        "/api/notif/state", "/api/notif/toggle", "/api/notif/list", "/api/notif/clear",
        "/api/power/state", "/api/power/cycle",
        "/api/shutdown", "/api/server/kill",
        "/api/volume", "/api/audio/streams",
        "/api/displays",
        "/api/apps/list", "/api/apps/status",
        "/api/cachy/state", "/api/cachy/icon", "/api/cachy/run",
    }
    missing = expected - rules
    assert not missing, f"missing routes: {missing}"


def test_serves_index_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"clientctl" in res.data


def test_serves_static_assets(client):
    for path in ("/style.css", "/app.js", "/favicon.svg"):
        res = client.get(path)
        assert res.status_code == 200, f"{path} returned {res.status_code}"


def test_static_no_store_header(client):
    res = client.get("/")
    assert "no-store" in res.headers.get("Cache-Control", "")


# ── Version consistency ─────────────────────────────────────────────

import re
from pathlib import Path

import config


def test_version_format_is_semver():
    """Must follow MAJOR.MINOR.PATCH (with optional pre-release)."""
    assert re.match(r"^\d+\.\d+\.\d+(-[\w.]+)?$", config.VERSION), \
        f"Bad version format: {config.VERSION!r}"


def test_version_matches_pyproject():
    """config.VERSION must match the version in pyproject.toml."""
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m, "version line not found in pyproject.toml"
    assert m.group(1) == config.VERSION, \
        f"Version mismatch: config.VERSION={config.VERSION!r} vs pyproject={m.group(1)!r}"


def test_version_endpoint(client):
    res = client.get("/api/version")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["version"] == config.VERSION


def test_version_in_capabilities(authed_client):
    res = authed_client.get("/api/capabilities")
    body = res.get_json()
    assert body.get("version") == config.VERSION


def test_repo_url_in_version_and_capabilities(client, authed_client, monkeypatch):
    """The bottom-right repo link is fed from config.REPO_URL via these endpoints."""
    monkeypatch.setattr(config, "REPO_URL", "https://github.com/example/clientctl")
    # /api/version is public (operational/CI use), /api/capabilities is auth-gated.
    body = client.get("/api/version").get_json()
    assert body["repo_url"] == "https://github.com/example/clientctl"
    body = authed_client.get("/api/capabilities").get_json()
    assert body["repo_url"] == "https://github.com/example/clientctl"


def test_capabilities_requires_auth(client):
    """Capabilities exposes host fingerprint (GPU/distro/installed tools).
    Must not leak to unauthenticated callers — defense against tunnel probes."""
    res = client.get("/api/capabilities")
    assert res.status_code == 401
    body = res.get_json()
    assert body["ok"] is False
    assert "kde_plasma" not in body
    assert "gpu" not in body


def test_repo_url_matches_config(client):
    """The repo_url field must always reflect config.REPO_URL — empty in
    forks (so no placeholder link is shown) or the maintainer's URL once
    they fill it in alongside a release."""
    body = client.get("/api/version").get_json()
    assert "repo_url" in body
    assert body["repo_url"] == config.REPO_URL
