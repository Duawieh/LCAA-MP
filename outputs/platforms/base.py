"""Capability protocols every platform backend implements.

Nothing in this module touches a platform API, so it imports on any OS. Each
platform package exposes ``load(script)`` returning a :class:`Backends`, and
``running()`` / ``stop_running()`` for the cross-process commands.

Contract, identical for all three implementations:

* ``CredentialStore.read`` returns ``None`` when nothing is stored. It does not
  raise for "not found"; a genuine backend failure may still raise.
* ``CredentialStore.write`` never echoes the secret back to a caller, a log or
  an exception message.
* ``InstanceLock.acquire`` returns ``False`` when another instance already holds
  the lock, and never blocks. ``release`` tolerates being called twice.
* ``StopSignal.wait`` returns as soon as ``request`` is called, so the monitor
  loop can never be stuck for a whole interval.
* ``Autostart.install`` is idempotent and replaces a stale entry;
  ``remove`` tolerates a missing entry; ``installed`` reports the entry, not the
  running process.
* ``WifiBackend.ensure`` returns ``True`` when the caller should continue with
  the portal check. That includes "no campus candidate" and "backend unusable":
  Wi-Fi recovery is an optimisation, never a precondition.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol, Tuple

from campus_core import Candidate


class BrowserUnavailable(RuntimeError):
    """No browser on this machine can be driven by Playwright.

    Raised instead of letting an ImportError or a launch failure escape: on an
    old Windows or a headless server this is an expected condition, and the
    caller turns it into one ``BROWSER_UNAVAILABLE`` log line.
    """


class CredentialStore(Protocol):
    def read(self) -> Optional[Tuple[str, str]]: ...
    def write(self, user: str, secret: str) -> None: ...
    def delete(self) -> None: ...


class InstanceLock(Protocol):
    def acquire(self) -> bool: ...
    def release(self) -> None: ...
    def held(self) -> bool: ...


class StopSignal(Protocol):
    def install_handlers(self) -> None: ...
    def stopped(self) -> bool: ...
    def wait(self, seconds: float) -> None: ...
    def request(self) -> None: ...
    def close(self) -> None: ...


class Autostart(Protocol):
    def install(self, argv: List[str]) -> None: ...
    def remove(self) -> None: ...
    def installed(self) -> bool: ...


class WifiBackend(Protocol):
    def ensure(self, stopped: Callable[[], bool]) -> bool: ...
    def current(self) -> Optional[bytes]: ...
    def scan(self) -> List[Candidate]: ...
    def connect(self, candidate: Candidate) -> bool: ...


@dataclass
class Backends:
    """Everything the entry point needs, already bound to one platform."""

    name: str
    credentials: CredentialStore
    lock: InstanceLock
    stop: StopSignal
    autostart: Autostart
    wifi: WifiBackend
    # Detached launch of [script, 'run']; each platform picks its own
    # interpreter and detach flags.
    spawn: Callable[[List[str]], None]
    # Context manager yielding a Playwright browser, or None when the platform
    # has no usable browser. The HTTP path never depends on it.
    browser: Optional[Callable[..., object]] = None
