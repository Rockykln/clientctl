"""Audio backend: master volume via wpctl, per-app streams via pactl.

Requires PipeWire (or PulseAudio with pactl). If neither wpctl nor pactl
is available the functions return empty/trivial defaults and the audio
feature is hidden via capabilities.
"""

import logging
import re
import subprocess

from utils import run

log = logging.getLogger("clientctl.core.audio")

_VOL_RE = re.compile(r"Volume:\s*([\d.]+)(\s*\[MUTED\])?")


# ── Master volume (wpctl) ────────────────────────────────────────────

def master_state() -> dict:
    try:
        raw = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]).strip()
    except Exception as e:
        log.debug("wpctl get-volume failed: %s", e)
        return {"volume": 0, "muted": False, "available": False}
    m = _VOL_RE.search(raw)
    if not m:
        return {"volume": 0, "muted": False, "available": False}
    vol = int(round(float(m.group(1)) * 100))
    return {
        "volume":    min(vol, 100),
        "muted":     bool(m.group(2)),
        "available": True,
    }


def master_set(volume: int | None = None, mute=None) -> None:
    if volume is not None:
        v = max(0, min(100, int(volume)))
        run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{v / 100:.2f}"])
    if mute is not None:
        arg = "toggle" if mute == "toggle" else ("1" if mute else "0")
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", arg])


# ── Per-app streams (pactl) ──────────────────────────────────────────

def list_streams() -> list[dict]:
    """Active sink-inputs with app names + volume/mute."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sink-inputs"], text=True,
            stderr=subprocess.DEVNULL, timeout=3,
        )
    except Exception:
        return []
    streams: list[dict] = []
    cur: dict = {}
    for raw in out.splitlines():
        line = raw.rstrip()
        if line.startswith("Sink Input #"):
            if cur.get("id") is not None:
                streams.append(cur)
            cur = {"id": int(line.split("#", 1)[1].strip())}
        elif "Volume:" in line and ("front-left" in line or "mono" in line):
            m = re.search(r"(\d+)%", line)
            if m:
                cur["volume"] = min(int(m.group(1)), 100)
        elif line.lstrip().startswith("Mute:"):
            cur["muted"] = "yes" in line.lower()
        elif "application.name" in line:
            m = re.search(r'application\.name\s*=\s*"(.*?)"', line)
            if m: cur["name"] = m.group(1)
        elif "media.name" in line and "name" not in cur:
            m = re.search(r'media\.name\s*=\s*"(.*?)"', line)
            if m: cur["name"] = m.group(1)
        elif "application.icon_name" in line:
            m = re.search(r'application\.icon_name\s*=\s*"(.*?)"', line)
            if m: cur["icon"] = m.group(1)
    if cur.get("id") is not None:
        streams.append(cur)
    return [
        {
            "id":     s["id"],
            "name":   s.get("name") or "Unknown",
            "volume": s.get("volume", 100),
            "muted":  s.get("muted", False),
        }
        for s in streams if "volume" in s
    ]


def stream_set(sid: int, volume: int | None = None, mute=None) -> None:
    if volume is not None:
        v = max(0, min(100, int(volume)))
        subprocess.run(
            ["pactl", "set-sink-input-volume", str(sid), f"{v}%"],
            check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    if mute is not None:
        arg = "toggle" if mute == "toggle" else ("1" if mute else "0")
        subprocess.run(
            ["pactl", "set-sink-input-mute", str(sid), arg],
            check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
