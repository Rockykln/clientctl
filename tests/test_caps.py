"""utils.caps — capability detection.

We never want to call real subprocesses or peek at the real DRM tree
during tests; everything is patched.
"""

import pytest

from utils import caps


@pytest.fixture(autouse=True)
def _reset_caps_cache():
    """Each test gets a fresh detection — no leak from previous runs."""
    caps._CAPS = None
    yield
    caps._CAPS = None


def test_detect_audio_pipewire(monkeypatch):
    monkeypatch.setattr(caps, "_has", lambda b: b == "wpctl")
    assert caps._detect_audio() == "pipewire"


def test_detect_audio_pulse(monkeypatch):
    monkeypatch.setattr(caps, "_has", lambda b: b == "pactl")
    assert caps._detect_audio() == "pulse"


def test_detect_audio_none(monkeypatch):
    monkeypatch.setattr(caps, "_has", lambda b: False)
    assert caps._detect_audio() == "none"


def test_detect_gpu_amd(monkeypatch, tmp_path):
    drm = tmp_path / "drm"
    card = drm / "card0" / "device"
    card.mkdir(parents=True)
    (card / "gpu_busy_percent").write_text("12\n")

    monkeypatch.setattr("pathlib.Path.glob", lambda self, pat: [card / "gpu_busy_percent"]
                        if "gpu_busy_percent" in pat else [])
    assert caps._detect_gpu() == "amd"


def test_detect_gpu_intel(monkeypatch, tmp_path):
    vendor = tmp_path / "vendor"
    vendor.write_text("0x8086\n")

    def fake_glob(self, pat):
        if "gpu_busy_percent" in pat:
            return []
        if "vendor" in pat:
            return [vendor]
        return []

    monkeypatch.setattr("pathlib.Path.glob", fake_glob)
    monkeypatch.setattr(caps, "_has", lambda b: b == "intel_gpu_top")
    assert caps._detect_gpu() == "intel"


def test_detect_gpu_nvidia(monkeypatch):
    monkeypatch.setattr("pathlib.Path.glob", lambda self, pat: [])
    monkeypatch.setattr(caps, "_has", lambda b: b == "nvidia-smi")
    assert caps._detect_gpu() == "nvidia"


def test_detect_gpu_none(monkeypatch):
    monkeypatch.setattr("pathlib.Path.glob", lambda self, pat: [])
    monkeypatch.setattr(caps, "_has", lambda b: False)
    assert caps._detect_gpu() == "none"


def test_detect_returns_complete_shape(monkeypatch):
    """Even on a system with no detectable backends, all keys are present."""
    monkeypatch.setattr(caps, "_has", lambda b: False)
    monkeypatch.setattr("pathlib.Path.glob",  lambda self, pat: [])
    monkeypatch.setattr(caps, "_busctl_property", lambda *a: None)
    monkeypatch.setattr("pathlib.Path.is_dir", lambda self: False)

    result = caps.detect(force=True)
    expected_keys = {
        "kde_plasma", "kde_brightness", "ddc", "audio", "battery",
        "power_profiles", "logind", "gpu", "dbus_monitor", "cachy",
        "session_type", "desktop",
    }
    assert expected_keys.issubset(result.keys())
    assert result["audio"] == "none"
    assert result["gpu"]   == "none"


def test_detect_caches_result(monkeypatch):
    calls = {"n": 0}

    def fake_has(b):
        calls["n"] += 1
        return False

    monkeypatch.setattr(caps, "_has", fake_has)
    monkeypatch.setattr("pathlib.Path.glob", lambda self, pat: [])
    monkeypatch.setattr(caps, "_busctl_property", lambda *a: None)
    monkeypatch.setattr("pathlib.Path.is_dir", lambda self: False)

    caps.detect()
    n_after_first  = calls["n"]
    caps.detect()
    n_after_second = calls["n"]
    assert n_after_second == n_after_first   # cached, no further calls


def test_detect_force_skips_cache(monkeypatch):
    monkeypatch.setattr(caps, "_has", lambda b: False)
    monkeypatch.setattr("pathlib.Path.glob", lambda self, pat: [])
    monkeypatch.setattr(caps, "_busctl_property", lambda *a: None)
    monkeypatch.setattr("pathlib.Path.is_dir", lambda self: False)

    caps.detect()
    second = caps.detect(force=True)
    assert second  # ran without raising


# ── User-disabled features (CLIENTCTL_DISABLE_FEATURES) ─────────────

def test_user_disabled_feature_overrides_positive_detection(monkeypatch):
    """Even if the system has the binary/backend, listing it in
    CLIENTCTL_DISABLE_FEATURES must hide it from the capability map."""
    import config
    # All probes report positive
    monkeypatch.setattr(caps, "_has",             lambda b: True)
    monkeypatch.setattr(caps, "_busctl_property", lambda *a: '"performance"')
    monkeypatch.setattr(caps, "_detect_audio",    lambda: "pipewire")
    monkeypatch.setattr(caps, "_detect_gpu",      lambda: "intel")
    monkeypatch.setattr(caps, "_detect_battery",  lambda: True)
    monkeypatch.setattr(caps, "_detect_kde_plasma",     lambda: True)
    monkeypatch.setattr(caps, "_detect_kde_brightness", lambda: True)
    monkeypatch.setattr(caps, "_detect_cachy",    lambda: False)
    monkeypatch.setattr(config, "DISABLED_FEATURES", {"audio", "gpu"})
    monkeypatch.setattr(caps, "_CAPS", None)

    result = caps.detect(force=True)
    # Disabled string-value features are coerced to "none"
    assert result["audio"] == "none"
    assert result["gpu"]   == "none"
    # Non-disabled features still surface
    assert result["battery"] is True


def test_brightness_alias_disables_both_backends(monkeypatch):
    """The 'brightness' alias is a UI-level concept resolved from
    kde_brightness OR ddc; hiding it must hide both."""
    import config
    monkeypatch.setattr(caps, "_has",             lambda b: True)
    monkeypatch.setattr(caps, "_busctl_property", lambda *a: None)
    monkeypatch.setattr(caps, "_detect_audio",    lambda: "pipewire")
    monkeypatch.setattr(caps, "_detect_gpu",      lambda: "intel")
    monkeypatch.setattr(caps, "_detect_battery",  lambda: False)
    monkeypatch.setattr(caps, "_detect_kde_plasma",     lambda: True)
    monkeypatch.setattr(caps, "_detect_kde_brightness", lambda: True)
    monkeypatch.setattr(caps, "_detect_cachy",    lambda: False)
    monkeypatch.setattr(config, "DISABLED_FEATURES", {"brightness"})
    monkeypatch.setattr(caps, "_CAPS", None)

    result = caps.detect(force=True)
    assert result["kde_brightness"] is False
    assert result["ddc"]            is False
