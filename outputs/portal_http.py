"""Headless campus portal authentication over plain HTTP.

Standard library only. No browser, no display, no desktop keyring: this module
runs on a CLI-only Linux server as well as on Windows and macOS.

The portal is served over plain HTTP by design. This module cannot add transport
security the school does not provide; credentials are protected only by the
portal's own XEncode obfuscation. Never log the password, info or chksum.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import platform
import random
import re
import socket
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger('campus')

PORTAL = 'http://10.10.0.166'
AC_ID = '2'
N = '200'
TYPE = '1'
ENC_VER = 'srun_bx1'
DEFAULT_DOMAIN = '@study'
USER_AGENT = 'Mozilla/5.0 (CampusAutoAuth/1.0)'
TIMEOUT = 4

ALPHABET = 'LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA'
MASK = 0xFFFFFFFF
DELTA = 0x9E3779B9


class PortalError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect means the portal is not where we think it is: fail instead."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class LoginResult:
    success: bool
    reason: str


def _pack(data, with_length):
    words = [int.from_bytes(data[i:i + 4].ljust(4, b'\0'), 'little')
             for i in range(0, len(data), 4)]
    if with_length:
        words.append(len(data))
    return words


def _unpack(words):
    return b''.join(word.to_bytes(4, 'little') for word in words)


def xencode(data, key):
    """SRun's XXTEA variant: little-endian 32-bit words, length appended."""
    if not data:
        return b''
    words = _pack(data, True)
    keys = _pack(key, False)
    if len(keys) < 4:
        keys += [0] * (4 - len(keys))
    n = len(words) - 1
    z = words[n]
    total = 0
    for _ in range(6 + 52 // (n + 1)):
        total = (total + DELTA) & MASK
        e = (total >> 2) & 3
        for p in range(n):
            y = words[p + 1]
            m = (((z >> 5) ^ (y << 2))
                 + (((y >> 3) ^ (z << 4)) ^ (total ^ y))
                 + (keys[(p & 3) ^ e] ^ z))
            words[p] = (words[p] + m) & MASK
            z = words[p]
        y = words[0]
        m = (((z >> 5) ^ (y << 2))
             + (((y >> 3) ^ (z << 4)) ^ (total ^ y))
             + (keys[(n & 3) ^ e] ^ z))
        words[n] = (words[n] + m) & MASK
        z = words[n]
    return _unpack(words)


def srun_base64(data):
    """Standard Base64 layout with SRun's shuffled alphabet."""
    out = []
    for i in range(0, len(data), 3):
        chunk = data[i:i + 3]
        value = int.from_bytes(chunk.ljust(3, b'\0'), 'big')
        b1, b2, b3 = (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF
        out.append(ALPHABET[b1 >> 2])
        out.append(ALPHABET[((b1 & 0x03) << 4) | (b2 >> 4)])
        out.append(ALPHABET[((b2 & 0x0F) << 2) | (b3 >> 6)] if len(chunk) > 1 else '=')
        out.append(ALPHABET[b3 & 0x3F] if len(chunk) > 2 else '=')
    return ''.join(out)


def normalize_user(user, domain=DEFAULT_DOMAIN):
    user = user.strip()
    return user if '@' in user else user + domain


def _now_ms():
    return int(time.time() * 1000)


def _callback():
    return 'jQuery{}_{}'.format(random.randint(10 ** 18, 10 ** 19 - 1), _now_ms())


def _safe_code(value):
    return re.sub(r'[^a-z0-9_]', '', str(value).lower())[:40] or 'unknown'


def parse_jsonp(text):
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = re.match(r'^[^(]*\((.*)\)\s*;?\s*$', text, re.S)
    if not match:
        raise PortalError('unexpected_response')
    return json.loads(match.group(1))


def _get(url, params=None, timeout=TIMEOUT):
    # urlencode turns '+' in the Base64 payload into %2B. Without that the
    # portal decodes it as a space and every login fails.
    query = urllib.parse.urlencode(params or {})
    target = url + '?' + query if query else url
    request = urllib.request.Request(target, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
    # No proxy and no redirects: the credential must reach 10.10.0.166 or
    # nowhere, so an environment proxy or a 302 cannot take it elsewhere.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        return response.read().decode('utf-8', 'replace')


def _base(portal):
    """Portal root without a trailing slash; config files often add one."""
    return (portal or PORTAL).rstrip('/')


def get_local_ip(portal=PORTAL, timeout=TIMEOUT):
    portal = _base(portal)
    try:
        html = _get(portal + '/', timeout=timeout)
        match = (re.search(r'id="user_ip"\s+value="([^"]+)"', html)
                 or re.search(r'value="([^"]+)"\s+id="user_ip"', html))
        if match:
            return match.group(1)
    except Exception:
        pass
    host = urllib.parse.urlparse(portal).hostname
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


def get_challenge(portal, user, ip, timeout=TIMEOUT):
    data = parse_jsonp(_get(_base(portal) + '/cgi-bin/get_challenge', {
        'callback': _callback(), 'username': user, 'ip': ip, '_': _now_ms(),
    }, timeout))
    if not isinstance(data, dict):
        # A captive portal or a proxy in the way answers `null` or `[]`.
        raise PortalError('challenge_missing')
    token = data.get('challenge') or data.get('token')
    if not token:
        raise PortalError('challenge_missing')
    return str(token)


def build_login_params(user, password, ip, token, ac_id=AC_ID, n=N, type_=TYPE):
    info_json = json.dumps({
        'username': user, 'password': password, 'ip': ip,
        'acid': ac_id, 'enc_ver': ENC_VER,
    }, separators=(',', ':'))
    info = '{SRBX1}' + srun_base64(xencode(info_json.encode('utf-8'), token.encode('utf-8')))
    hmd5 = hmac.new(token.encode('utf-8'), password.encode('utf-8'), hashlib.md5).hexdigest()
    chksum = hashlib.sha1(''.join(
        token + part for part in (user, hmd5, ac_id, ip, n, type_, info)
    ).encode('utf-8')).hexdigest()
    system = platform.system() or 'Unknown'
    return {
        'callback': _callback(), 'action': 'login', 'username': user,
        'password': '{MD5}' + hmd5, 'ac_id': ac_id, 'ip': ip,
        'chksum': chksum, 'info': info, 'n': n, 'type': type_,
        'os': system, 'name': system, 'double_stack': '0', '_': _now_ms(),
    }


def login(user, password, portal=PORTAL, timeout=TIMEOUT, stopped=None):
    if stopped is not None and stopped():
        return LoginResult(False, 'stopped')
    portal = _base(portal)
    user = normalize_user(user)
    try:
        ip = get_local_ip(portal, timeout)
        token = get_challenge(portal, user, ip, timeout)
        params = build_login_params(user, password, ip, token)
        data = parse_jsonp(_get(portal + '/cgi-bin/srun_portal', params, timeout))
    except Exception:
        log.warning('HTTP_LOGIN_ERROR: portal request failed')
        return LoginResult(False, 'error')
    if not isinstance(data, dict):
        # Valid JSON, wrong shape: a captive portal or a proxy answered instead.
        log.warning('HTTP_LOGIN_ERROR: unexpected response shape')
        return LoginResult(False, 'error')
    error = str(data.get('error', ''))
    if error == 'ok':
        log.info('HTTP_LOGIN_OK')
        return LoginResult(True, 'ok')
    if 'captcha' in json.dumps(data, ensure_ascii=False).lower():
        log.warning('CAPTCHA_REQUIRED: manual portal login required')
        return LoginResult(False, 'captcha')
    log.warning('HTTP_LOGIN_REJECTED: %s', _safe_code(error))
    return LoginResult(False, 'rejected')


def online_info(portal=PORTAL, timeout=TIMEOUT):
    """Return the portal's account record, or None when offline."""
    try:
        data = parse_jsonp(_get(_base(portal) + '/cgi-bin/rad_user_info', {
            'callback': _callback(), '_': _now_ms(),
        }, timeout))
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get('error') == 'ok' else None
