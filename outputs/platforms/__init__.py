"""Platform-specific backends.

Each subpackage is imported only on its own OS, so a missing pywin32 on Linux or
a missing keyring on Windows never breaks the import graph. ``load`` is the only
entry point the command line needs.
"""
from __future__ import annotations
import importlib
import sys

_MODULES = {}


def _module():
    if sys.platform == 'win32':
        name = 'platforms.win'
    elif sys.platform == 'darwin':
        name = 'platforms.darwin'
    elif sys.platform.startswith('linux'):
        name = 'platforms.linux'
    else:
        raise RuntimeError('unsupported_platform: %s' % sys.platform)
    if name not in _MODULES:
        _MODULES[name] = importlib.import_module(name)
    return _MODULES[name]


def load(script):
    """Return the Backends bundle for this OS. ``script`` is the entry file."""
    return _module().load(script)


def running():
    return _module().running()


def stop_running(timeout=None):
    module = _module()
    if timeout is None:
        return module.stop_running()
    return module.stop_running(timeout)
