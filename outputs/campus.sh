#!/bin/sh
# POSIX launcher: prefer the project virtualenv, fall back to the system python3.
set -e
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for candidate in "$here/../.venv/bin/python" "$here/../.venv/bin/python3" python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" "$here/campus_auth.py" "$@"
    fi
done
echo "python3 not found; install Python 3.8 or later" >&2
exit 1
