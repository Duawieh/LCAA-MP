"""Windows backends: pywin32, wlanapi, Credential Manager, HKCU Run, Edge."""
from __future__ import annotations
from platforms.base import Backends


def load(script):
    from platforms.win import browser, credentials, ipc, launcher, wlan
    return Backends(
        name='windows',
        credentials=credentials.CredentialStore(),
        lock=ipc.Mutex(),
        stop=ipc.StopEvent(),
        autostart=launcher.Autostart(),
        wifi=wlan.WinWifi(),
        spawn=launcher.start,
        browser=browser.browser_session,
    )


def running():
    from platforms.win import ipc
    return ipc.running()


def stop_running(timeout=None):
    from platforms.win import ipc
    return ipc.stop_running() if timeout is None else ipc.stop_running(timeout)
