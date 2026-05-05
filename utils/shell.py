"""subprocess wrapper with default timeout and stderr suppression."""

import subprocess


def run(cmd: list[str], timeout: float = 5.0) -> str:
    """Run *cmd*, return stdout as text.

    Raises ``subprocess.CalledProcessError`` on non-zero exit and
    ``subprocess.TimeoutExpired`` if *timeout* (seconds) elapses.
    stderr is silenced — callers that need it should use ``subprocess``
    directly.
    """
    return subprocess.check_output(
        cmd, timeout=timeout, stderr=subprocess.DEVNULL
    ).decode()
