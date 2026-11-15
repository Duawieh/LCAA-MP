"""Keyring-backed credential storage shared by macOS and Linux.

One item per portal, stored as JSON so the account name and the secret survive a
round trip. When the OS keyring is missing or unusable -- a headless Linux box
with no SecretService, a locked Keychain -- the store degrades to a 0600 file and
says so once in the log instead of failing silently or asking for the password
again on every run.
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path

from platforms.paths import credential_file, ensure

log = logging.getLogger('campus')

SERVICE = 'CampusAutoAuth/10.10.0.166/eLearning/v1'
ACCOUNT = 'eLearning'


def _keyring():
    try:
        import keyring
    except Exception:
        return None
    return keyring


class KeyringCredentialStore:
    def __init__(self, service=SERVICE, path=None):
        self.service = service
        self.path = Path(path) if path else credential_file()
        self._noted = False

    # -- OS keyring ----------------------------------------------------
    def _keyring_read(self):
        keyring = _keyring()
        if keyring is None:
            return None
        try:
            raw = keyring.get_password(self.service, ACCOUNT)
        except Exception:
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return str(data['user']), str(data['secret'])
        except Exception:
            return None

    def _keyring_write(self, payload):
        keyring = _keyring()
        if keyring is None:
            return False
        try:
            keyring.set_password(self.service, ACCOUNT, payload)
            return True
        except Exception:
            return False

    def _keyring_delete(self):
        keyring = _keyring()
        if keyring is None:
            return
        try:
            keyring.delete_password(self.service, ACCOUNT)
        except Exception:
            pass

    # -- 0600 file fallback -------------------------------------------
    def _note_fallback(self):
        if self._noted:
            return
        self._noted = True
        log.warning('CREDENTIALS_FILE_FALLBACK: OS keyring unavailable, using %s', self.path)

    def _file_read(self):
        try:
            data = json.loads(self.path.read_text('utf-8'))
        except (OSError, ValueError):
            return None
        try:
            return str(data['user']), str(data['secret'])
        except (KeyError, TypeError):
            return None

    def _file_write(self, payload):
        ensure(self.path.parent, private=True)
        # os.open applies the mode at creation time, so the secret is never
        # world-readable even for an instant.
        handle = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(payload)

    def _file_clear(self):
        try:
            self.path.unlink()
        except OSError:
            pass

    # -- protocol ------------------------------------------------------
    def read(self):
        pair = self._keyring_read()
        if pair:
            return pair
        return self._file_read()

    def write(self, user, secret):
        payload = json.dumps({'user': user, 'secret': secret})
        if self._keyring_write(payload):
            self._file_clear()
            return
        self._note_fallback()
        self._file_write(payload)

    def delete(self):
        self._keyring_delete()
        self._file_clear()
