"""Linux Wi-Fi control through NetworkManager.

``nmcli`` is asked only about connections the user already saved; nothing here
creates a profile, reads a PSK or asks for a password. On a machine without
NetworkManager (server, container) ``ensure`` reports "nothing to do" and the
monitor goes straight to portal authentication.
"""
from __future__ import annotations
import logging
import shutil
import subprocess

from campus_core import CAMPUS, Candidate, choose, pause

log = logging.getLogger('campus')


def available():
    return shutil.which('nmcli') is not None


def _run(args, timeout=30):
    try:
        result = subprocess.run(['nmcli'] + args, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout)
    except Exception:
        return 1, ''
    return result.returncode, result.stdout.decode('utf-8', 'replace')


def split_terse(line):
    """nmcli -t escapes ':' and '\\\\' with a backslash."""
    fields, buffer, escaped = [], [], False
    for char in line:
        if escaped:
            buffer.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            fields.append(''.join(buffer))
            buffer = []
        else:
            buffer.append(char)
    fields.append(''.join(buffer))
    return fields


def saved_profiles():
    """{ssid bytes: connection name} for saved wireless connections."""
    if not available():
        return {}
    code, text = _run(['-t', '-f', 'NAME,TYPE', 'connection', 'show'])
    if code != 0:
        return {}
    names = []
    for line in text.splitlines():
        fields = split_terse(line)
        if len(fields) >= 2 and fields[1].strip() == '802-11-wireless':
            names.append(fields[0])
    mapping = {}
    for name in names:
        code, text = _run(['-t', '-f', '802-11-wireless.ssid', 'connection', 'show', name])
        if code != 0:
            continue
        for line in text.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[0].strip() == '802-11-wireless.ssid' and fields[1]:
                mapping[fields[1].encode('utf-8')] = name
    return mapping


def _wifi_list(rescan):
    args = ['-t', '-f', 'IN-USE,SSID,SIGNAL', 'device', 'wifi', 'list']
    if not rescan:
        args += ['--rescan', 'no']
    code, text = _run(args)
    if code != 0 and not rescan:
        return _wifi_list(True)
    return code, text


def current():
    if not available():
        return None
    code, text = _wifi_list(False)
    if code != 0:
        return None
    for line in text.splitlines():
        fields = split_terse(line)
        if len(fields) >= 2 and fields[0].strip() == '*':
            name = fields[1]
            return name.encode('utf-8') if name else None
    return None


def scan():
    if not available():
        return []
    code, text = _wifi_list(True)
    if code != 0:
        return []
    saved = saved_profiles()
    found = {}
    for line in text.splitlines():
        fields = split_terse(line)
        if len(fields) < 3:
            continue
        name, strength = fields[1], fields[2]
        if not name:
            continue
        try:
            signal = int(strength)
        except ValueError:
            signal = 0
        key = name.encode('utf-8')
        previous = found.get(key)
        if previous is not None and previous.signal >= signal:
            continue
        found[key] = Candidate(key, saved.get(key, ''), signal, key in saved)
    return list(found.values())


def connect(candidate):
    if not available() or not candidate.profile:
        return False
    code, _ = _run(['connection', 'up', 'id', candidate.profile], timeout=90)
    return code == 0


def ensure(stopped):
    if not available():
        log.info('WIFI_UNAVAILABLE: NetworkManager not found, portal only')
        return not stopped()
    try:
        now = current()
        if now is not None and now not in CAMPUS:
            return True
        candidate = choose(scan(), now)
        if candidate is None:
            log.info('WIFI_NO_CAMPUS_CANDIDATE: continue portal check on existing connection')
            return True
        if stopped():
            return False
        log.info('WIFI_CONNECT ssid=%s signal=%s%%',
                 candidate.ssid.decode('utf-8', 'replace'), candidate.signal)
        if not connect(candidate):
            log.warning('WIFI_CONNECT_FAILED ssid=%s',
                        candidate.ssid.decode('utf-8', 'replace'))
            return not stopped()
        if not pause(3, stopped):
            return False
        for _ in range(17):
            if stopped():
                return False
            if current() == candidate.ssid:
                log.info('WIFI_CONNECTED ssid=%s', candidate.ssid.decode('utf-8', 'replace'))
                return pause(3, stopped)
            if not pause(1, stopped):
                return False
        log.warning('WIFI_CONNECT_TIMEOUT')
        return False
    except Exception:
        log.warning('WIFI_UNAVAILABLE: continue portal check on existing connection')
        return not stopped()


class Wifi:
    def ensure(self, stopped):
        return ensure(stopped)

    def current(self):
        return current()

    def scan(self):
        return scan()

    def connect(self, candidate):
        return connect(candidate)
