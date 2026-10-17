#!/bin/bash
# Build, extract, install, restart the server and run every test.
#   patch/pipeline/all.sh [scene] [--mmaps] [--no-client-test]
set -euo pipefail
PATCH="$(cd "$(dirname "$0")/.." && pwd)"
SCENE="tiangong"
MMAPS=()
CLIENT_TEST=1
for a in "$@"; do
    case "$a" in
        --mmaps) MMAPS=(--mmaps) ;;
        --no-client-test) CLIENT_TEST=0 ;;
        *) SCENE="$a" ;;
    esac
done
PY="$PATCH/.venv/bin/python"
"$PY" "$PATCH/pipeline/build.py" --scene "$SCENE"
"$PY" "$PATCH/pipeline/extract_server.py" --scene "$SCENE" "${MMAPS[@]+"${MMAPS[@]}"}"
"$PATCH/pipeline/install.sh" "$SCENE" --restart
"$PY" -m pytest -q "$PATCH/tests"
[ "$CLIENT_TEST" = 1 ] && "$PATCH/tests/client/run_client_test.sh" "$SCENE"
echo "==> $SCENE: all green"
