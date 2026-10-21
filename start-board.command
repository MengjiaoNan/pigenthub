#!/bin/zsh
# Finder starts .command files outside the project directory.
cd -- "${0:A:h}" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PYTHONUTF8=1

action="${1:-start}"
python_bin=""
for candidate in "$PWD/.venv/bin/python" "${BOARD_PYTHON:-}" \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 \
    "$HOME/miniconda3/bin/python" /opt/miniconda3/bin/python \
    "$HOME/anaconda3/bin/python" /opt/anaconda3/bin/python python3 python; do
    [[ -n "$candidate" ]] || continue
    if "$candidate" -I -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        python_bin="$candidate"
        break
    fi
done

if [[ -z "$python_bin" ]]; then
    print 'Install Python 3.10 or newer, then double-click this launcher again.'
    print 'Download: https://www.python.org/downloads/macos/'
    [[ -t 0 ]] && read -r '?Press Enter to close this window...'
    exit 1
fi

"$python_bin" "$PWD/launcher.py" "$action" "${@:2}"
result=$?
if (( result != 0 )) && [[ -t 0 ]]; then
    read -r '?Press Enter to close this window...'
fi
exit "$result"
