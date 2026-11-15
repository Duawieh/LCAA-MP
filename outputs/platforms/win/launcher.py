"""Windows background launch (pythonw) and per-user logon autostart.

The autostart entry lives in ``HKCU`` so it needs no administrator rights and
affects only the current user. Moving the project invalidates the stored path,
which is why the entry is rewritten on every install.
"""
import os
import subprocess
import sys
from pathlib import Path
import winreg

RUN_NAME = 'CampusAutoAuth-eLearning'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def pythonw():
    """pythonw.exe keeps the console closed; fall back when it is absent."""
    executable = Path(sys.executable)
    windowless = executable.with_name('pythonw.exe')
    return windowless if windowless.exists() else executable


def command(argv):
    return subprocess.list2cmdline([str(pythonw())] + [str(part) for part in argv])


def _spawn(argv):
    script = Path(argv[0]).resolve()
    subprocess.Popen(
        [str(pythonw())] + [str(part) for part in argv],
        cwd=str(script.parent),
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={key: value for key, value in os.environ.items() if key not in ('DEBUG', 'PWDEBUG')},
    )


def start(argv):
    _spawn(argv)


class Autostart:
    def __init__(self, name=RUN_NAME):
        self.name = name

    def install(self, argv):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, self.name, 0, winreg.REG_SZ, command(argv))

    def remove(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, self.name)
        except FileNotFoundError:
            pass

    def installed(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, self.name)
        except FileNotFoundError:
            return False
        return True
