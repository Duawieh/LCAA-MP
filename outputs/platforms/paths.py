"""Directory rules shared by every backend.

Pure path arithmetic: no Windows API, no subprocess, no privilege check. Each
platform keeps user data where its own conventions expect it, so logs and
credentials survive a read-only source tree and never land next to the code.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

APP = 'CampusAutoAuth'
POSIX_APP = 'campus-autoauth'


def _env(name):
    value = os.environ.get(name)
    return Path(value) if value else None


def state_dir():
    """Durable per-user state: credentials fallback, pid file, launch scripts."""
    if sys.platform == 'win32':
        base = _env('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local'
        return base / APP
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP
    base = _env('XDG_STATE_HOME') or Path.home() / '.local' / 'state'
    return base / POSIX_APP


def log_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Logs' / APP
    return state_dir() / 'logs'


def runtime_dir():
    """Short-lived files: the single-instance lock and the monitor pid."""
    if sys.platform == 'win32' or sys.platform == 'darwin':
        return state_dir()
    base = _env('XDG_RUNTIME_DIR')
    if base:
        return base / POSIX_APP
    return Path('/tmp') / ('%s-%d' % (POSIX_APP, os.getuid()))


def credential_file():
    """0600 fallback used only when the OS keyring is unusable."""
    return state_dir() / 'credentials.json'


def ensure(folder, private=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if private:
        try:
            os.chmod(str(folder), 0o700)
        except OSError:
            pass
    return folder
