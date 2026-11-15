"""macOS background launch and per-user autostart through a LaunchAgent.

``launchctl bootstrap`` is the modern call; older systems only understand
``load -w``. Both are attempted so the same code works on 10.13 and 14.
"""
from __future__ import annotations
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from platforms.paths import ensure, log_dir

LABEL = 'com.lcaa.monitor'
AGENT_FOLDER = Path('Library') / 'LaunchAgents'


def plist_bytes(argv, label=LABEL):
    """Pure function: the LaunchAgent body, with no call into launchd."""
    payload = {
        'Label': label,
        'ProgramArguments': [str(part) for part in argv],
        'RunAtLoad': True,
        # Restart after a crash, but not after `stop`: that path exits 0, which
        # launchd reads as a successful exit.
        'KeepAlive': {'SuccessfulExit': False},
        'ProcessType': 'Background',
        'StandardOutPath': str(log_dir() / 'launchd.out'),
        'StandardErrorPath': str(log_dir() / 'launchd.err'),
    }
    return plistlib.dumps(payload)


def command(argv):
    return [sys.executable] + [str(part) for part in argv]


def start(argv):
    script = Path(argv[0]).resolve()
    subprocess.Popen(
        command(argv),
        cwd=str(script.parent),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _launchctl(args):
    try:
        return subprocess.run(['launchctl'] + args, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode
    except Exception:
        return 1


class Autostart:
    def __init__(self, label=LABEL, path=None):
        self.label = label
        # Resolved at construction, not at import: HOME can change between the
        # installer and the daemon, and a cached path would follow the wrong one.
        self.path = Path(path) if path else Path.home() / AGENT_FOLDER / (label + '.plist')

    def install(self, argv):
        """Install the agent, or raise ``OSError`` with a fixed code.

        ``launchctl`` reports failures through the exit status only. Ignoring it
        means telling the user the monitor starts at login when launchd never
        accepted the plist, and they find out when the network drops.
        """
        body = plist_bytes(command(argv), self.label)
        ensure(self.path.parent)
        ensure(log_dir())
        self.path.write_bytes(body)
        domain = 'gui/%d' % os.getuid()
        # `bootstrap` is the modern call; 10.13 and older only know `load -w`.
        _launchctl(['bootout', '%s/%s' % (domain, self.label)])
        if _launchctl(['bootstrap', domain, str(self.path)]) == 0:
            return
        if _launchctl(['load', '-w', str(self.path)]) == 0:
            return
        raise OSError('launchd_install_failed')

    def remove(self):
        """Remove the agent; raise if launchd would not let go of it."""
        if not self.path.exists():
            # Nothing of ours is installed. Skip launchctl entirely rather than
            # probing a label that was never registered.
            return
        domain = 'gui/%d' % os.getuid()
        if _launchctl(['bootout', '%s/%s' % (domain, self.label)]) != 0:
            if _launchctl(['unload', '-w', str(self.path)]) != 0:
                raise OSError('launchd_remove_failed')
        try:
            self.path.unlink()
        except OSError:
            pass

    def installed(self):
        return self.path.exists()
