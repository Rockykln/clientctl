"""Intel GPU usage via `intel_gpu_top -J`.

Intel iGPUs do not expose `gpu_busy_percent` in sysfs; the clean way is
`intel_gpu_top` from intel-gpu-tools. That binary needs CAP_PERFMON,
granted once with sudo:

    sudo setcap cap_perfmon+ep /usr/bin/intel_gpu_top

We start intel_gpu_top as a daemon subprocess with `-J` (JSON stream) and
`-s 1000` (sample every 1s). For each sample we read the `engines` map
and take the max `busy` value as the overall GPU utilization.
"""

import json
import logging
import shutil
import subprocess
import threading
import time

log = logging.getLogger("clientctl.core.intel_gpu")

_LOCK = threading.Lock()
_STATE: dict = {"busy": None, "ts": 0.0, "running": False}


def _engine_max_busy(sample: dict) -> float | None:
    engines = sample.get("engines") or {}
    if not engines:
        return None
    busy_values = []
    for eng in engines.values():
        if isinstance(eng, dict) and "busy" in eng:
            try:
                busy_values.append(float(eng["busy"]))
            except (ValueError, TypeError):
                continue
    return max(busy_values) if busy_values else None


def _listener_loop():
    """Daemon thread: start intel_gpu_top -J -s 1000 and parse the stream."""
    decoder = json.JSONDecoder()
    while True:
        try:
            proc = subprocess.Popen(
                ["intel_gpu_top", "-J", "-s", "1000"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
            log.info("intel_gpu_top started pid=%d", proc.pid)
            with _LOCK:
                _STATE["running"] = True

            buf = ""
            assert proc.stdout is not None
            for chunk in iter(lambda: proc.stdout.read(4096), ""):
                buf += chunk
                # Strip the leading separators of the JSON-array form
                while True:
                    stripped = buf.lstrip(" \t\n\r,[")
                    if not stripped:
                        buf = stripped
                        break
                    try:
                        obj, idx = decoder.raw_decode(stripped)
                    except json.JSONDecodeError:
                        # Wait for more data
                        buf = stripped
                        break
                    buf = stripped[idx:]
                    busy = _engine_max_busy(obj) if isinstance(obj, dict) else None
                    if busy is not None:
                        with _LOCK:
                            _STATE["busy"] = busy
                            _STATE["ts"]   = time.time()

            err = proc.stderr.read() if proc.stderr else ""
            log.warning("intel_gpu_top exit rc=%s err=%r", proc.returncode, err[:200])
        except FileNotFoundError:
            log.warning("intel_gpu_top not installed")
            return  # do not restart loop
        except PermissionError as e:
            log.warning("intel_gpu_top missing capability: %s — run `sudo setcap cap_perfmon+ep /usr/bin/intel_gpu_top`", e)
            return
        except Exception as e:
            log.error("intel-gpu listener error: %s", e)
        finally:
            with _LOCK:
                _STATE["running"] = False
        time.sleep(2)


def start_listener() -> None:
    if not shutil.which("intel_gpu_top"):
        return
    threading.Thread(target=_listener_loop, daemon=True, name="intel-gpu").start()


def busy_percent() -> int | None:
    """Latest sample value. None if daemon not running or sample older than 5s."""
    with _LOCK:
        ts   = _STATE["ts"]
        busy = _STATE["busy"]
    if busy is None or time.time() - ts > 5.0:
        return None
    return int(round(busy))
