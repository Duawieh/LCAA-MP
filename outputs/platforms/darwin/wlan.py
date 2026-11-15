"""macOS Wi-Fi control.

``networksetup`` handles the association; scanning uses CoreWLAN because the
``airport`` tool was removed in macOS 14.4. Reading the current SSID needs
Location permission on macOS 14+; when it is denied the call simply reports
"not connected" and the monitor falls back to portal authentication, which is
the part that actually matters.
"""
from __future__ import annotations
import logging
import re
import subprocess

from campus_core import CAMPUS, PRIORITY, Candidate, choose, pause

log = logging.getLogger('campus')


def _run(args, timeout=20):
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout)
    except Exception:
        return 1, ''
    return result.returncode, result.stdout.decode('utf-8', 'replace')


def interface():
    """Find the Wi-Fi device instead of assuming en0."""
    code, text = _run(['networksetup', '-listallhardwareports'])
    if code != 0:
        return None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith('hardware port:') and 'wi-fi' in line.lower():
            for follow in lines[index + 1:index + 3]:
                if follow.strip().lower().startswith('device:'):
                    return follow.split(':', 1)[1].strip()
    return None


def current():
    device = interface()
    if not device:
        return None
    code, text = _run(['networksetup', '-getairportnetwork', device])
    if code != 0:
        return None
    match = re.search(r'Current Wi-Fi Network:\s*(.+)', text)
    if not match:
        return None
    name = match.group(1).strip()
    return name.encode('utf-8') if name else None


def scan():
    """CoreWLAN scan; empty list when PyObjC is not installed."""
    try:
        import CoreWLAN
    except Exception:
        return []
    try:
        client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
        wifi = client.interface()
        if wifi is None:
            return []
        networks, _ = wifi.scanForNetworksWithName_error_(None, None)
    except Exception:
        return []
    found = {}
    for network in networks or []:
        name = network.ssid()
        if not name:
            continue
        # CoreWLAN reports dBm; normalise to the 0-100 scale the policy expects.
        strength = max(0, min(100, int(network.rssi() or -100) + 100))
        key = name.encode('utf-8')
        previous = found.get(key)
        if previous is not None and previous.signal >= strength:
            continue
        found[key] = Candidate(key, name, strength, True)
    return list(found.values())


def blind_candidates():
    """No CoreWLAN: try the campus SSIDs in priority order."""
    return [Candidate(ssid, ssid.decode('ascii'), len(PRIORITY) - index, True)
            for index, ssid in enumerate(PRIORITY)]


def connect(candidate):
    device = interface()
    if not device:
        return False
    # No password argument: the network must already be saved in System
    # Settings, which is exactly the constraint the project promises to keep.
    code, _ = _run(['networksetup', '-setairportnetwork', device, candidate.ssid.decode('utf-8')],
                   timeout=60)
    return code == 0


def ensure(stopped):
    try:
        if not interface():
            log.info('WIFI_UNAVAILABLE: no Wi-Fi interface')
            return not stopped()
        now = current()
        if now is not None and now not in CAMPUS:
            return True
        candidates = scan() or blind_candidates()
        candidate = choose(candidates, now)
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
