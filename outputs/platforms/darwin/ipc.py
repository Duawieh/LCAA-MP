"""macOS single-instance lock and stop signal (flock + pid file)."""
from platforms.posix import STOP_TIMEOUT, Lock, Stop, alive, read_pid, running, stop_running  # noqa: F401
