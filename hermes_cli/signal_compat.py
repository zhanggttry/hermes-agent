"""
Cross-platform process signal helpers for Windows compatibility.

Provides Windows-safe alternatives to Unix-specific patterns:

- ``os.kill(pid, 0)`` for process existence checks → ``pid_exists(pid)``
- ``/proc/<pid>/stat`` for start times → ``get_process_start_time(pid)``
- ``/proc/<pid>/cmdline`` for command lines → ``read_process_cmdline(pid)``

On Windows, ``os.kill(pid, 0)`` raises ``OSError [WinError 87]`` and
``/proc/`` does not exist.  This module detects the platform and
delegates to the appropriate implementation.
"""

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# PID existence check (replaces os.kill(pid, 0))
# ---------------------------------------------------------------------------

def pid_exists(pid: int) -> bool:
    """Check whether a process with the given PID is alive.

    On POSIX, uses ``os.kill(pid, 0)`` (signal 0 = existence check).
    On Windows, ``os.kill(pid, 0)`` raises ``OSError [WinError 87]``,
    so we fall back to ``psutil`` when available, or the ``tasklist``
    command otherwise.
    """
    if not _IS_WINDOWS:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False
        return True

    # ---- Windows path ----
    # 1. Try psutil (most reliable, optional dependency)
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass

    # 2. Fallback: tasklist command (available on all Windows)
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return str(pid) in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # 3. Last resort: try os.kill and interpret the error code
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError as exc:
        if hasattr(exc, "winerror"):
            # WinError 5  = Access denied → process exists
            # WinError 87 = Invalid parameter → process doesn't exist
            return exc.winerror == 5
        if exc.errno == 22:  # EINVAL on some Windows Python builds
            return False
        return False
    # If os.kill succeeded, process existed (but we just sent SIGTERM!)
    return True


# ---------------------------------------------------------------------------
# Process start time (replaces /proc/<pid>/stat)
# ---------------------------------------------------------------------------

def get_process_start_time(pid: int) -> Optional[int]:
    """Return the process start time, or ``None`` on failure.

    On POSIX, reads field 22 from ``/proc/<pid>/stat`` (clock ticks).
    On Windows, uses ``psutil.Process.create_time()`` when available.
    """
    if _IS_WINDOWS:
        try:
            import psutil
            proc = psutil.Process(pid)
            # Use microseconds for granularity comparable to clock ticks
            return int(proc.create_time() * 1e6)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ImportError, OSError):
            return None

    stat_path = Path(f"/proc/{pid}/stat")
    try:
        return int(stat_path.read_text().split()[21])
    except (FileNotFoundError, IndexError, PermissionError, ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Process command line (replaces /proc/<pid>/cmdline)
# ---------------------------------------------------------------------------

def read_process_cmdline(pid: int) -> Optional[str]:
    """Return the process command line as a space-separated string.

    On POSIX, reads ``/proc/<pid>/cmdline``.
    On Windows, uses ``psutil.Process.cmdline()`` when available.
    """
    if _IS_WINDOWS:
        try:
            import psutil
            proc = psutil.Process(pid)
            return " ".join(proc.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied, ImportError, OSError):
            return None

    cmdline_path = Path(f"/proc/{pid}/cmdline")
    try:
        raw = cmdline_path.read_bytes()
    except (FileNotFoundError, PermissionError, OSError):
        return None

    if not raw:
        return None
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()


# ---------------------------------------------------------------------------
# Safe process termination helpers
# ---------------------------------------------------------------------------

def send_signal(pid: int, sig: int) -> None:
    """Send a signal to a process, with Windows compatibility.

    On Windows, ``signal.SIGKILL`` and ``signal.SIGUSR1`` do not exist.
    This function maps them to appropriate Windows equivalents:
    - ``SIGKILL`` → ``process.kill()`` via ``taskkill /T /F``
    - ``SIGUSR1`` → no-op (returns without error)
    - ``SIGTERM`` → ``process.terminate()`` via ``os.kill``
    """
    if _IS_WINDOWS:
        if sig == getattr(signal, "SIGKILL", -1):
            # Windows: force-kill via taskkill
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                os.kill(pid, signal.SIGTERM)
            return

        if sig == getattr(signal, "SIGUSR1", -1):
            # SIGUSR1 does not exist on Windows — silently skip
            return

        # SIGTERM and others — use os.kill directly
        os.kill(pid, sig)
        return

    # POSIX
    os.kill(pid, sig)


def send_kill_or_term(pid: int) -> None:
    """Send SIGKILL on POSIX, or force-terminate on Windows.

    Equivalent to ``os.kill(pid, signal.SIGKILL)`` on Unix, but uses
    ``taskkill /T /F`` on Windows where SIGKILL does not exist.
    """
    if _IS_WINDOWS:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            os.kill(pid, signal.SIGTERM)
            return
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout or "").strip() or f"taskkill failed for PID {pid}")
        return

    sig = getattr(signal, "SIGKILL", signal.SIGTERM)
    os.kill(pid, sig)
