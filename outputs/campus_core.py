"""Platform-independent campus authentication core.

Uses only the standard library, so it is importable on Windows, macOS and Linux
and on Python 3.8. Platform services (credentials, browser, Wi-Fi,
single-instance IPC, autostart) are injected by the platform-specific entry
point. Never log browser exceptions or credentials.
"""
from __future__ import annotations
import concurrent.futures
from dataclasses import dataclass
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import ssl
import time
import urllib.parse
import urllib.request

import portal_http

log = logging.getLogger('campus')

PORTAL = 'http://10.10.0.166/'
INTERVAL = 15
CAMPUS = {b'iLZU', b'LZU'}
# Preferred order when the platform cannot measure signal strength.
PRIORITY = (b'iLZU', b'LZU')
# The browser is a fallback, so it only appears after HTTP has failed twice;
# a single rejection is usually a wrong password, not a broken protocol.
BROWSER_AFTER_FAILURES = 2
# An attempt that has not answered in five minutes is treated as lost. Every
# step has its own timeout, so this only fires when something is genuinely stuck.
ATTEMPT_TIMEOUT = 300
MAX_OUTSTANDING = 3
AUTH_MODES = ('auto', 'http', 'browser')
PROBES = (
    ('https://www.msftconnecttest.com/connecttest.txt', 200, b'Microsoft Connect Test'),
    ('https://connectivitycheck.platform.hicloud.com/generate_204', 204, b''),
    ('https://cp.cloudflare.com/generate_204', 204, b''),
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_CONTEXT = None


def ssl_context():
    """certifi's CA bundle, so an unpatched Windows 7 can still validate probes.

    Returns None when certifi is absent, which makes urllib use its default
    context. Cached because loading the bundle is not free.
    """
    global _CONTEXT
    if _CONTEXT is None:
        try:
            import certifi
            _CONTEXT = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _CONTEXT = False
    return _CONTEXT or None


def _opener():
    handlers = [urllib.request.ProxyHandler({}), NoRedirect()]
    context = ssl_context()
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def probe(spec):
    url, status, body = spec
    try:
        opener = _opener()
        request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'CampusAutoAuth/1.0'})
        with opener.open(request, timeout=4) as response:
            return response.status == status and response.read(512).strip() == body
    except Exception:
        return False


def internet_ok():
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PROBES)) as pool:
        return any(list(pool.map(probe, PROBES)))


class RetryPolicy:
    def __init__(self):
        self.misses = 0
        self.failures = 0
        self.next_attempt = 0.0

    def observe(self, online, now):
        self.misses = 0 if online else self.misses + 1
        if online:
            self.failures = 0
        return not online and self.misses >= 2 and now >= self.next_attempt

    def result(self, success, now):
        self.failures = 0 if success else self.failures + 1
        delay = 60 if success else min(900, 60 * 2 ** min(self.failures - 1, 4))
        self.next_attempt = now + delay
        return delay


@dataclass(frozen=True)
class Candidate:
    ssid: bytes
    profile: str
    signal: int
    connectable: bool = True


def choose(candidates, current):
    if current is not None and current not in CAMPUS:
        return None
    eligible = [n for n in candidates if n.ssid in CAMPUS and n.profile and n.connectable]
    return max(eligible, key=lambda n: (n.signal, n.ssid == current), default=None)


def pause(seconds, stopped):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if stopped():
            return False
        time.sleep(.2)
    return not stopped()


def configure_logging(folder=None):
    """Attach the rotating file handler once and return the log directory.

    Never raises: a read-only disk or a missing home directory should degrade to
    "no file log", not to a monitor that cannot start and gets restarted by the
    supervisor forever.
    """
    if folder is None:
        from platforms.paths import log_dir
        folder = log_dir()
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
            handler = RotatingFileHandler(folder / 'monitor.log', maxBytes=1024*1024,
                                          backupCount=5, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            log.setLevel(logging.INFO)
            log.addHandler(handler)
    except Exception:
        if not log.handlers:
            log.addHandler(logging.NullHandler())
        log.warning('LOG_UNAVAILABLE: running without a file handler')
    return folder


def _state_file():
    from platforms.paths import state_dir
    return state_dir() / 'status.json'


def record_state(**fields):
    """Atomic, best-effort heartbeat. Failure here must never stop the monitor."""
    try:
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(fields, sort_keys=True), 'utf-8')
        os.replace(str(temporary), str(path))
    except Exception:
        pass


def read_state():
    try:
        data = json.loads(_state_file().read_text('utf-8'))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_config(path=None, environ=None):
    """Read ``auth_mode`` and friends. Every field has a working default.

    Precedence is environment, then ``config.json`` next to the entry point,
    then the built-in values. A malformed file is ignored rather than fatal, so
    a typo can never stop the monitor from starting.
    """
    environ = os.environ if environ is None else environ
    config = {'auth_mode': 'auto', 'portal': PORTAL, 'interval': INTERVAL}
    source = Path(path) if path else Path(__file__).with_name('config.json')
    try:
        data = json.loads(source.read_text('utf-8'))
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        # A mode written as "HTTP" in the file has to mean the same thing as
        # CAMPUS_AUTH_MODE=HTTP, which is already lowercased below.
        mode = data.get('auth_mode')
        if isinstance(mode, str) and mode.strip():
            config['auth_mode'] = mode.strip().lower()
        portal = data.get('portal')
        if isinstance(portal, str) and portal.strip():
            config['portal'] = portal.strip()
        interval = data.get('interval')
        if isinstance(interval, int) and interval >= 5:
            config['interval'] = interval
    mode = environ.get('CAMPUS_AUTH_MODE', '').strip().lower()
    if mode:
        config['auth_mode'] = mode
    if config['auth_mode'] not in AUTH_MODES:
        log.warning('CONFIG_IGNORED: unknown auth_mode, using auto')
        config['auth_mode'] = 'auto'
    if not _valid_portal(config['portal']):
        log.warning('CONFIG_IGNORED: portal is not an http(s) URL, using the default')
        config['portal'] = PORTAL
    return config


def _valid_portal(value):
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.hostname)


class Authenticator:
    """One authentication attempt: HTTP first, browser only as a fallback.

    ``auth_mode`` decides the path. ``http`` never opens a browser, ``browser``
    skips HTTP entirely, ``auto`` tries HTTP and falls back when the portal
    demands a captcha or keeps rejecting an otherwise well-formed request.

    Repeated refusals are a wrong password, not a network problem. Left alone the
    monitor would retry every fifteen minutes forever, which is how an account
    gets locked out at two in the morning. After ``REJECTION_LIMIT`` refusals the
    authenticator starts skipping attempts, with the pause doubling up to an
    hour, so the account is left alone until a human fixes the password.
    """

    REJECTION_LIMIT = 3
    REJECTION_COOLDOWN = 600
    REJECTION_MAX = 3600

    def __init__(self, credentials, mode='auto', portal=None, browser_factory=None):
        self.credentials = credentials
        self.mode = mode
        self.portal = portal or PORTAL
        self.browser_factory = browser_factory
        self.http_failures = 0
        self.rejections = 0
        self.paused_until = 0.0

    def _paused(self, now):
        if now >= self.paused_until:
            return False
        log.info('AUTH_PAUSED: %ds left after repeated refusals',
                 int(self.paused_until - now))
        return True

    def _note_rejection(self, now):
        self.rejections += 1
        if self.rejections < self.REJECTION_LIMIT:
            return
        pause = min(self.REJECTION_MAX,
                    self.REJECTION_COOLDOWN * 2 ** (self.rejections - self.REJECTION_LIMIT))
        self.paused_until = now + pause
        log.warning('CREDENTIALS_REJECTED: %d refusals, pausing %ds; run setup',
                    self.rejections, pause)

    def __call__(self, stopped):
        now = time.monotonic()
        if self._paused(now):
            return False
        try:
            pair = self.credentials.read()
        except Exception:
            # A locked keychain or a Credential Manager that refuses the read
            # used to escape as a raw platform error, which the monitor only
            # saw as a generic AUTH_ERROR and `auth` printed as "Operation
            # failed". Name the cause instead; the message may quote a path.
            log.warning('CREDENTIALS_UNREADABLE: stored credential cannot be read; run setup')
            return False
        if not pair:
            log.warning('CREDENTIALS_MISSING: run setup')
            return False
        user, secret = pair
        if self.mode != 'browser':
            result = portal_http.login(user, secret, portal=self.portal, stopped=stopped)
            if result.success:
                self.http_failures = 0
                self.rejections = 0
                return True
            if result.reason == 'stopped':
                return False
            self.http_failures += 1
            if result.reason == 'rejected':
                self._note_rejection(now)
            if self.mode == 'http':
                return False
            if result.reason != 'captcha' and self.http_failures < BROWSER_AFTER_FAILURES:
                return False
        if self.browser_factory is None:
            log.warning('BROWSER_UNAVAILABLE: HTTP only, manual login required')
            return False
        # Imported here so the browser module can depend on this one instead of
        # the two forming a cycle at import time.
        import portal_browser
        from platforms.base import BrowserUnavailable
        try:
            return portal_browser.login_once(stopped, lambda: (user, secret), self.browser_factory)
        except BrowserUnavailable:
            log.warning('BROWSER_UNAVAILABLE: no usable browser on this system')
            return False


def recover_connection(stopped, ensure_wifi, login):
    if stopped():
        return False
    if internet_ok():
        return True
    if not ensure_wifi(stopped) or stopped():
        return False
    if internet_ok():
        return True
    return login(stopped)


def _collect(pending, policy, attempt_timeout):
    """Retire finished attempts, and give up on ones that stopped answering.

    A future cannot be cancelled once it is running, so a hung browser or a
    socket that ignores its timeout would otherwise block every later attempt
    while the process still looks healthy. Abandoning it costs one leaked
    thread and keeps the monitor alive; ``MAX_OUTSTANDING`` caps how many can
    pile up.
    """
    for item in list(pending):
        future, started_at = item
        if future.done():
            pending.remove(item)
            try:
                success = future.result()
            except Exception:
                # Browser error strings can contain fill values. Never emit them.
                success = False
                log.warning('AUTH_ERROR: authentication path failed; details suppressed')
            delay = policy.result(success, time.monotonic())
            log.info('RECOVERY_%s retry_after=%ss', 'VERIFIED' if success else 'FAILED', delay)
        elif time.monotonic() - started_at > attempt_timeout:
            pending.remove(item)
            delay = policy.result(False, time.monotonic())
            log.warning('AUTH_TIMEOUT: attempt exceeded %ss, abandoned; retry_after=%ss',
                        attempt_timeout, delay)


def monitor_loop(stopped, wait, ensure_wifi, login, request_stop, interval=INTERVAL,
                 heartbeat=None, attempt_timeout=ATTEMPT_TIMEOUT):
    """Polling loop. wait(seconds) and request_stop() are platform services.

    ``heartbeat`` receives a small dict every cycle so an operator can tell a
    working monitor from one that is merely alive.
    """
    policy = RetryPolicy()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    pending = []
    previous = None
    started = time.time()
    try:
        while not stopped():
            tick = time.monotonic()
            online = internet_ok()
            if online != previous:
                log.info('INTERNET_%s', 'ONLINE' if online else 'UNREACHABLE')
                previous = online
            _collect(pending, policy, attempt_timeout)
            ready = policy.observe(online, time.monotonic())
            if ready and len(pending) < MAX_OUTSTANDING and not stopped():
                log.info('RECOVERY_ATTEMPT')
                pending.append([executor.submit(recover_connection, stopped, ensure_wifi, login),
                                time.monotonic()])
            if heartbeat is not None:
                try:
                    heartbeat({'pid': os.getpid(), 'started': started,
                               'checked': time.time(), 'online': online,
                               'failures': policy.failures, 'attempts': len(pending)})
                except Exception:
                    pass  # an observability aid must never break the monitor
            remaining = max(0.1, interval - (time.monotonic() - tick))
            wait(remaining)
    except KeyboardInterrupt:
        request_stop()
    finally:
        # No request_stop() here: a loop that dies from an unexpected error has
        # to be restartable by the caller, and only a real stop should latch.
        executor.shutdown(wait=True)
