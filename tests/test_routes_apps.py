"""Tests for /api/apps/* routes — KWin and procs are mocked."""

from unittest.mock import patch

import pytest


@pytest.fixture
def fake_apps(monkeypatch):
    """Pin LAUNCHABLE_APPS + GRID to a known set (independent of apps.yml)."""
    import config
    apps = {
        "files": {
            "name":       "Files",
            "binary":     "dolphin",
            "desktop_id": "org.kde.dolphin",
            "icon":       "/usr/share/icons/dolphin.svg",
        },
        "browser": {
            "name":       "Browser",
            "binary":     "firefox",
            "desktop_id": "firefox",
            "icon":       "/usr/share/icons/firefox.svg",
        },
        "pwa": {
            "name":       "Some PWA",
            "pwa_id":     "abc123",
            "desktop_id": "chrome-abc123-Default",
        },
    }
    grid = ["files", "browser", "pwa", "cachy"]
    monkeypatch.setattr(config, "LAUNCHABLE_APPS", apps)
    monkeypatch.setattr(config, "GRID",            grid)
    return apps, grid


def test_apps_list_returns_grid(authed_client, fake_apps):
    res = authed_client.get("/api/apps/list")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    cell_ids = [c["id"] for c in body["cells"]]
    # cachy entry is preserved as the special slot
    assert cell_ids == ["files", "browser", "pwa", "cachy"]
    types = {c["id"]: c["type"] for c in body["cells"]}
    assert types["cachy"] == "cachy"
    assert types["files"] == "app"


def test_apps_list_skips_unknown_grid_entries(authed_client, monkeypatch):
    import config
    monkeypatch.setattr(config, "LAUNCHABLE_APPS", {"files": {"name": "F"}})
    monkeypatch.setattr(config, "GRID",            ["files", "ghost"])
    res = authed_client.get("/api/apps/list")
    cells = res.get_json()["cells"]
    assert [c["id"] for c in cells] == ["files"]


def test_apps_list_requires_auth(client):
    res = client.get("/api/apps/list")
    assert res.status_code == 401


def test_apps_status_batch(authed_client, fake_apps):
    """KWin + procs are mocked — we only verify the response shape."""
    from core import kwin, procs
    with patch.object(kwin, "query_states", return_value={"files": {"visible": True, "active": True}}), \
         patch.object(procs, "find_app_pids", return_value=[]), \
         patch.object(procs, "snapshot",      return_value=[]):
        res = authed_client.get("/api/apps/status")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    for app_id in fake_apps[0]:
        assert app_id in body["apps"]
        st = body["apps"][app_id]
        assert set(st.keys()) == {"running", "paused", "visible", "active"}


def test_app_status_unknown_id(authed_client, fake_apps):
    res = authed_client.get("/api/app/does-not-exist/status")
    assert res.status_code == 404


def test_app_pause_pwa_returns_error(authed_client, fake_apps):
    res = authed_client.post("/api/app/pwa/pause")
    assert res.status_code == 400
    assert "PWA" in res.get_json()["error"]


def test_app_kill_pwa_only_closes_window(authed_client, fake_apps):
    from core import kwin
    with patch.object(kwin, "close") as close_mock:
        res = authed_client.post("/api/app/pwa/kill")
    assert res.status_code == 200
    body = res.get_json()
    assert body["closed"] is True
    assert body["killed"] == 0
    close_mock.assert_called_once()


def test_app_pause_when_not_running(authed_client, fake_apps):
    from core import procs
    with patch.object(procs, "find_app_pids", return_value=[]), \
         patch.object(procs, "snapshot",      return_value=[]):
        res = authed_client.post("/api/app/files/pause")
    assert res.status_code == 400
    assert "not running" in res.get_json()["error"].lower()


def test_app_icon_404_when_missing(authed_client, fake_apps, tmp_path):
    """Icon path doesn't exist on this system — must return 404, not crash."""
    res = authed_client.get("/api/app/files/icon")
    assert res.status_code == 404


def test_app_icon_unknown_app(authed_client, fake_apps):
    res = authed_client.get("/api/app/nonexistent/icon")
    assert res.status_code == 404


def test_app_close_unknown(authed_client, fake_apps):
    res = authed_client.post("/api/app/nonexistent/close")
    assert res.status_code == 404
