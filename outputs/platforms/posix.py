"""Shared POSIX single-instance lock and stop signal.

macOS and Linux differ only in where the lock and pid files live, which
``platforms.paths`` already answers, so the two backends share one
implementation instead of two drifting copies.

The lock is an exclusive ``flock`` on a file; the kernel drops it when the
process dies, so a crash never leaves a stale lock behind. The pid file exists
only so the ``stop`` command can find the process to signal.
"""
from __future__ import annotations
import errno
import fcntl
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from platforms.paths import ensure, runtime_dir

STOP_TIMEOUT = 90


def lock_path():
    return ensure(runtime_dir(), private=True) / 'monitor.lock'


def pid_path():
    return ensure(runtime_dir(), private=True) / 'monitor.pid'


def read_pid():
    try:
        text = pid_path().read_text('ascii').strip()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def write_pid(pid):
    pid_path().write_text(str(pid), 'ascii')


def clear_pid():
    try:
        pid_path().unlink()
    except OSError:
        pass


def _signal(pid, signum):
    """Single seam for os.kill: signal 0 is a liveness probe, SIGTERM a request."""
    os.kill(pid, signum)


def alive(pid):
    if not pid or pid <= 0:
        return False
    try:
        _signal(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return False
    return True


def _cmdline(pid):
    if sys.platform.startswith('linux'):
        return Path('/proc/%d/cmdline' % pid).read_bytes()
    result = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=5)
    return result.stdout


def _tokens(raw):
    """/proc separates arguments with NUL; `ps` prints them space-separated."""
    parts = raw.split(b'\0') if b'\0' in raw else raw.split()
    return [part for part in parts if part]


def looks_like_monitor(pid):
    """True only when the process is positively this tool's monitor.

    The pid file survives a reboot, so the number in it can belong to anything
    by the time `stop` reads it. A substring test is not enough -- an editor
    with ``campus_auth`` in the filename would pass -- and treating an
    unreadable command line as a match turns a permission quirk into a
    SIGTERM sent to a stranger. Both cases now answer no: leaving a stale pid
    file behind is cheap, signalling the wrong process is not.
    """
    try:
        tokens = _tokens(_cmdline(pid))
    except Exception:
        return False
    if b'run' not in tokens:
        return False
    return any(part.rsplit(b'/', 1)[-1] in (b'campus_auth.py', b'campus_auth')
               for part in tokens)


class Lock:
    def __init__(self, path=None):
        self.path = Path(path) if path else lock_path()
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            return True
        ensure(self.path.parent, private=True)
        handle = open(str(self.path), 'a+')
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        try:
            write_pid(os.getpid())
        except Exception:
            # Without a pid file `stop` has no way to find this process. Failing
            # here is better than running in a state nobody can shut down, and
            # the lock must not be held by a process that is about to exit.
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            raise OSError('pid_file_unwritable') from None
        self.handle = handle
        return True

    def release(self):
        if self.handle is None:
            return
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
            clear_pid()

    def held(self):
        if self.handle is not None:
            return True
        handle = None
        try:
            handle = open(str(self.path), 'a+')
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        except Exception:
            return False
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
        finally:
            if handle is not None:
                handle.close()


class Stop:
    """Thread-safe stop flag that a signal handler can set from any thread."""

    def __init__(self):
        self.event = threading.Event()
        self._previous = {}

    def install_handlers(self):
        """SIGTERM is how `stop` asks for a graceful exit."""
        if self._previous:
            return
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                self._previous[signum] = signal.signal(signum, self._handle)
            except (ValueError, OSError):
                # Not the main thread, or the signal is unavailable.
                pass

    def _handle(self, signum, frame):
        self.event.set()

    def stopped(self):
        return self.event.is_set()

    def wait(self, seconds):
        if seconds > 0:
            self.event.wait(seconds)

    def request(self):
        self.event.set()

    def close(self):
        self.event.set()
        for signum, previous in self._previous.items():
            try:
                signal.signal(signum, previous)
            except (ValueError, OSError):
                pass
        self._previous.clear()


def running():
    pid = read_pid()
    return bool(pid and alive(pid) and looks_like_monitor(pid))


def stop_running(timeout=STOP_TIMEOUT):
    """Ask the monitor to exit; True when it is gone."""
    pid = read_pid()
    if not pid or not alive(pid) or not looks_like_monitor(pid):
        clear_pid()
        return True
    try:
        _signal(pid, signal.SIGTERM)
    except OSError:
        clear_pid()
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid):
            clear_pid()
            return True
        time.sleep(0.2)
    return False
