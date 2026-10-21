#!/bin/sh
# Linux entry point; also usable from a POSIX terminal on macOS.
cd -- "$(dirname -- "$0")" || exit 1
export PYTHONUTF8=1
for candidate in "$PWD/.venv/bin/python" "${BOARD_PYTHON:-}" python3 python \
    "$HOME/miniconda3/bin/python" "$HOME/anaconda3/bin/python"; do
    [ -n "$candidate" ] || continue
    if "$candidate" -I -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        exec "$candidate" "$PWD/launcher.py" "$@"
    fi
done
printf '%s\n' 'Python 3.10+ is required: https://www.python.org/downloads/'
exit 1
