"""Windows named kernel objects: one mutex for single instance, one event to stop.

Both are per-user: the object name carries the caller's SID, so two logged-in
users each get their own monitor instead of fighting over one global object.
The kernel releases both when the last handle closes, so a crashed monitor never
leaves a lock behind.
"""
import time
import pywintypes
import win32api
import win32con
import win32event
import win32security

LOCK_SUFFIX = 'monitor'
STOP_SUFFIX = 'stop'
STOP_TIMEOUT = 90
ERROR_ALREADY_EXISTS = 183
ERROR_FILE_NOT_FOUND = 2


def object_name(suffix):
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.ConvertSidToStringSid(
            win32security.GetTokenInformation(token, win32security.TokenUser)[0])
    finally:
        token.Close()
    return 'Global\\CampusAutoAuth-' + sid + '-' + suffix


class Mutex:
    def __init__(self, suffix=LOCK_SUFFIX):
        self.suffix = suffix
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            return True
        # GetLastError is only meaningful for this call, so clear it first;
        # CreateMutex does not reset it on its own.
        win32api.SetLastError(0)
        handle = win32event.CreateMutex(None, False, object_name(self.suffix))
        if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
            handle.Close()
            return False
        self.handle = handle
        return True

    def release(self):
        if self.handle is None:
            return
        self.handle.Close()
        self.handle = None

    def held(self):
        if self.handle is not None:
            return True
        try:
            handle = win32event.OpenMutex(win32con.SYNCHRONIZE, False, object_name(self.suffix))
        except pywintypes.error as exc:
            if exc.winerror == ERROR_FILE_NOT_FOUND:
                return False
            raise
        handle.Close()
        return True


class StopEvent:
    def __init__(self, suffix=STOP_SUFFIX):
        self.suffix = suffix
        self.handle = win32event.CreateEvent(None, True, False, object_name(suffix))
        win32event.ResetEvent(self.handle)

    def install_handlers(self):
        """Named events replace signal handling; nothing to install."""

    def stopped(self):
        if self.handle is None:
            return True
        return win32event.WaitForSingleObject(self.handle, 0) == win32event.WAIT_OBJECT_0

    def wait(self, seconds):
        if self.handle is None:
            return
        win32event.WaitForSingleObject(self.handle, max(0, int(seconds * 1000)))

    def request(self):
        if self.handle is not None:
            win32event.SetEvent(self.handle)

    def close(self):
        if self.handle is not None:
            self.handle.Close()
            self.handle = None


def running():
    return Mutex().held()


def stop_running(timeout=STOP_TIMEOUT):
    """Set the stop event of the running monitor and wait for it to exit."""
    if not running():
        return True
    try:
        event = win32event.OpenEvent(win32event.EVENT_MODIFY_STATE, False, object_name(STOP_SUFFIX))
    except pywintypes.error as exc:
        if exc.winerror == ERROR_FILE_NOT_FOUND:
            return False
        raise
    try:
        win32event.SetEvent(event)
    finally:
        event.Close()
    for _ in range(int(timeout)):
        if not running():
            return True
        time.sleep(1)
    return False
