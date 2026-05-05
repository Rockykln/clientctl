"""Tests for the intel_gpu_top streaming parser."""

import time

from core import intel_gpu


def test_engine_max_busy_picks_max():
    sample = {
        "engines": {
            "Render/3D":    {"busy": 12.5},
            "Blitter":      {"busy":  0.0},
            "Video":        {"busy": 47.3},
            "VideoEnhance": {"busy":  3.0},
        }
    }
    assert intel_gpu._engine_max_busy(sample) == 47.3


def test_engine_max_busy_no_engines():
    assert intel_gpu._engine_max_busy({}) is None
    assert intel_gpu._engine_max_busy({"engines": {}}) is None


def test_engine_max_busy_skips_invalid_entries():
    sample = {
        "engines": {
            "Bad1": "not-a-dict",
            "Bad2": {"busy": "nan-string"},
            "Good": {"busy": 5.5},
        }
    }
    # Bad entries are silently dropped, Good wins
    assert intel_gpu._engine_max_busy(sample) == 5.5


def test_busy_percent_returns_none_when_stale(monkeypatch):
    monkeypatch.setattr(intel_gpu, "_STATE",
                        {"busy": 50.0, "ts": time.time() - 10, "running": False})
    assert intel_gpu.busy_percent() is None


def test_busy_percent_fresh(monkeypatch):
    monkeypatch.setattr(intel_gpu, "_STATE",
                        {"busy": 42.7, "ts": time.time(), "running": True})
    assert intel_gpu.busy_percent() == 43


def test_busy_percent_no_data(monkeypatch):
    monkeypatch.setattr(intel_gpu, "_STATE",
                        {"busy": None, "ts": 0.0, "running": False})
    assert intel_gpu.busy_percent() is None


def test_start_listener_no_op_without_binary(monkeypatch):
    """If intel_gpu_top is not installed, start_listener returns silently."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: None)
    intel_gpu.start_listener()   # no exception, no thread spawned
