"""Linux background launch and autostart.

A ``systemd --user`` unit is preferred: it survives logout, restarts on failure
and needs no root. When the user manager is unreachable -- a container, a bare
TTY session, a distro without systemd -- an XDG autostart entry is written
instead, which is what a desktop session actually reads.

Both file formats carry their own escaping rules, and getting them wrong is
silent: the unit is accepted but starts the wrong command, or the desktop entry
is ignored. ``%`` is a field code in a desktop entry and a specifier in a unit,
``$`` is expanded by systemd, and a desktop ``Exec`` value is unescaped twice.
The renderers below encode each argument for the format it lands in.
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

from platforms.paths import ensure

UNIT_NAME = 'campus-autoauth.service'
DESKTOP_NAME = 'campus-autoauth.desktop'
UNIT_FOLDER = Path('.config') / 'systemd' / 'user'
AUTOSTART_FOLDER = Path('.config') / 'autostart'

# Characters that may be written without quotes. Everything else is quoted:
# both parsers accept a quoted argument, and a quoted argument is never split.
# Non-ASCII text is left alone so a Chinese path stays readable in the file.
SAFE = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_@%+=:,./-')


def _validate(values):
    """Refuse arguments that no amount of quoting can make safe.

    A newline ends the line in both formats, so an argument carrying one could
    inject a second directive; C0/C1 controls, the Unicode line separators and
    lone surrogates have no unambiguous representation either. Failing here
    means the caller never writes a half-usable autostart entry.
    """
    for value in values:
        for char in value:
            if (char < ' ' or '\x7f' <= char <= '\x9f' or char in '\u2028\u2029'
                    or '\ud800' <= char <= '\udfff'):
                raise ValueError('unsafe_autostart_argument')


def _plain(value):
    return bool(value) and all(char in SAFE or char >= '\x80' for char in value)


def _quote(value, extra=''):
    """Quote one argument; ``extra`` lists characters the parser also treats."""
    if _plain(value):
        return value
    out = ['"']
    for char in value:
        if char in '\\"' or char in extra:
            out.append('\\')
        out.append(char)
    out.append('"')
    return ''.join(out)


def _values(argv):
    values = [str(sys.executable)] + [str(part) for part in argv]
    _validate(values)
    return values


def _systemd_arg(value):
    # `%%` is a literal percent sign, `$$` a literal dollar: systemd expands
    # both before the command runs.
    return _quote(value).replace('%', '%%').replace('$', '$$')


def _desktop_arg(value):
    # The Exec value is unescaped twice: first as a desktop entry string, then
    # by the Exec parser. Escaping for both layers is what survives.
    inner = _quote(value, extra='`$')
    return inner.replace('\\', '\\\\').replace('%', '%%')


def command(argv):
    return ' '.join(_systemd_arg(part) for part in _values(argv))


def desktop_command(argv):
    return ' '.join(_desktop_arg(part) for part in _values(argv))


def unit_text(argv):
    """Pure function: the systemd unit body."""
    return '\n'.join([
        '[Unit]',
        'Description=LZU campus network auto authentication',
        'After=network-online.target',
        'Wants=network-online.target',
        '',
        '[Service]',
        'Type=simple',
        'ExecStart=' + command(argv),
        'Restart=on-failure',
        'RestartSec=30',
        '',
        '[Install]',
        'WantedBy=default.target',
        '',
    ])


def desktop_text(argv):
    """Pure function: the XDG autostart entry used when systemd is absent."""
    return '\n'.join([
        '[Desktop Entry]',
        'Type=Application',
        'Name=LZU campus network auto authentication',
        'Comment=Signs in to the eLearning portal when the campus network drops',
        'Exec=' + desktop_command(argv),
        'Terminal=false',
        'X-GNOME-Autostart-enabled=true',
        '',
    ])


def systemd_available():
    if not shutil.which('systemctl'):
        return False
    try:
        return subprocess.run(['systemctl', '--user', 'show-environment'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=10).returncode == 0
    except Exception:
        return False


def _systemctl(args):
    try:
        return subprocess.run(['systemctl', '--user'] + args, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=60).returncode
    except Exception:
        return 1


def start(argv):
    script = Path(argv[0]).resolve()
    subprocess.Popen(
        [sys.executable] + [str(part) for part in argv],
        cwd=str(script.parent),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class Autostart:
    def __init__(self, unit=None, desktop=None):
        home = Path.home()
        self.unit = Path(unit) if unit else home / UNIT_FOLDER / UNIT_NAME
        self.desktop = Path(desktop) if desktop else home / AUTOSTART_FOLDER / DESKTOP_NAME

    def _drop(self, path):
        try:
            path.unlink()
        except OSError:
            pass

    def install(self, argv):
        """Install the autostart entry, or raise ``OSError`` with a fixed code.

        A return code that is ignored turns a broken install into a silent one:
        the user is told the monitor starts at login and finds out months later
        that it never did. The previous configuration is left in place whenever
        the new one cannot be completed.
        """
        if systemd_available():
            body = unit_text(argv)
            existed = self.unit.exists()
            ensure(self.unit.parent)
            self.unit.write_text(body, encoding='utf-8')
            if _systemctl(['daemon-reload']) != 0:
                if not existed:
                    self._drop(self.unit)
                raise OSError('systemd_daemon_reload_failed')
            if _systemctl(['enable', '--now', self.unit.name]) != 0:
                if not existed:
                    self._drop(self.unit)
                raise OSError('systemd_enable_failed')
            # Only now is the unit live, so only now is the fallback redundant.
            self._drop(self.desktop)
            return
        if self.unit.exists():
            # A unit is installed but the user manager cannot be reached.
            # Writing an XDG entry would leave the old service loaded with no
            # file describing it, so refuse and let the caller report it.
            raise OSError('systemd_user_manager_unavailable')
        body = desktop_text(argv)
        ensure(self.desktop.parent)
        self.desktop.write_text(body, encoding='utf-8')

    def remove(self):
        """Remove what this tool installed; raise if a step could not be done."""
        if self.unit.exists():
            if _systemctl(['disable', '--now', self.unit.name]) != 0:
                raise OSError('systemd_disable_failed')
            self._drop(self.unit)
            if _systemctl(['daemon-reload']) != 0:
                raise OSError('systemd_daemon_reload_failed')
        self._drop(self.desktop)

    def installed(self):
        return self.unit.exists() or self.desktop.exists()
