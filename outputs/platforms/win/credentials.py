"""Windows Credential Manager storage.

One generic credential per portal, owned by the current user. The target name is
stable so an upgrade keeps the saved password; pass a different ``target`` to
keep a second entry isolated from the real one.
"""
import pywintypes
import win32cred

TARGET = 'CampusAutoAuth/10.10.0.166/eLearning/v1'
ERROR_NOT_FOUND = 1168


class CredentialStore:
    def __init__(self, target=TARGET):
        self.target = target

    def read(self):
        try:
            entry = win32cred.CredRead(self.target, win32cred.CRED_TYPE_GENERIC)
        except pywintypes.error as exc:
            if exc.winerror == ERROR_NOT_FOUND:
                return None
            raise
        blob = entry['CredentialBlob']
        secret = blob.decode('utf-16-le') if isinstance(blob, bytes) else blob
        return entry['UserName'], secret

    def write(self, user, secret):
        win32cred.CredWrite({
            'Type': win32cred.CRED_TYPE_GENERIC,
            'TargetName': self.target,
            'UserName': user,
            'CredentialBlob': secret,
            'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }, 0)

    def delete(self):
        try:
            win32cred.CredDelete(self.target, win32cred.CRED_TYPE_GENERIC)
        except pywintypes.error as exc:
            if exc.winerror != ERROR_NOT_FOUND:
                raise
