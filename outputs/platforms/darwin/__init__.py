"""macOS backends: Keychain, flock, LaunchAgent, networksetup + CoreWLAN."""
from __future__ import annotations
from platforms.base import Backends


def load(script):
    from platforms.darwin import browser, credentials, ipc, launcher, wlan
    return Backends(
        name='macos',
        credentials=credentials.CredentialStore(),
        lock=ipc.Lock(),
        stop=ipc.Stop(),
        autostart=launcher.Autostart(),
        wifi=wlan.Wifi(),
        spawn=launcher.start,
        browser=browser.browser_session,
    )


def running():
    from platforms.darwin import ipc
    return ipc.running()


def stop_running(timeout=None):
    from platforms.darwin import ipc
    return ipc.stop_running() if timeout is None else ipc.stop_running(timeout)
