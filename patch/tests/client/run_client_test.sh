#!/bin/bash
# Real-client test: benilla logs in the dedicated GM test character, runs `.tele <name>` and `.gps`, reads the
# zone name from its own Lua, takes in-world screenshots, exits; client_check.py gives the verdict.
#   patch/tests/client/run_client_test.sh [scene]
# Env: TEST_USER / TEST_PASS / TEST_CHAR (provisioned by tests/test_e2e.py; never a player's account),
#      WOW_HOST (127.0.0.1:3735), BENILLA_BIN (target/play/benilla), CLIENT_SECS (run length, 120).
# Timeline: the first world load (Northshire) settles by ~35 s, then `.gm on`, `.tele` at 47 s, `.gps` at 59/71 s;
# the camera poses and the screenshot burst fill the last 30 s.
set -euo pipefail
PATCH="$(cd "$(dirname "$0")/../.." && pwd)"
REPO="$(cd "$PATCH/.." && pwd)"
SCENE="${1:-tiangong}"
PY="$PATCH/.venv/bin/python"
MANIFEST="$PATCH/build/$SCENE/manifest.json"
[ -f "$MANIFEST" ] || { echo "scene $SCENE not built" >&2; exit 1; }
TELE="$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['config']['tele_name'])" "$MANIFEST")"
USER_="${TEST_USER:-TIANGONG}"
PASS_="${TEST_PASS:-tiangong}"
CHAR_="${TEST_CHAR:-Yunque}"
BIN="${BENILLA_BIN:-$REPO/target/play/benilla}"
SECS="${CLIENT_SECS:-120}"
if [ ! -x "$BIN" ]; then
    (cd "$REPO" && ./dev.sh 2)
fi

# Make sure the account and character exist, and park the character off the custom map (Northshire) so the
# client's `.tele` is a real cross-map transfer through the loading screen. The bot logs out before benilla starts.
"$PY" -c "
import sys; sys.path[:0] = ['$PATCH/tests', '$PATCH/tests/e2e']
import wowbot, conftest
wowbot.provision(conftest.db_connect('${REALMD_DB:-m425realmd}'), '$USER_', '$PASS_')
w = wowbot.connect('$USER_', '$PASS_', '$CHAR_')
w.command('.go xyz -8949.95 -132.49 83.53 0', settle=4)
print('parked on map', w.mapid)
w.close()
"

OUT="$PATCH/logs/client-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT/home"
LOG="$OUT/client.log"
echo "==> benilla ($BIN) -> $OUT"
(
    cd "$REPO"
    env BENILLA_HOME="$OUT/home" WOW_HOST="${WOW_HOST:-127.0.0.1:3735}" \
        WOW_USER="$USER_" WOW_PASS="$PASS_" WOW_CHAR="$CHAR_" WOW_ALLOW_ACCOUNT=1 \
        WOW_UNATTENDED=1 WOW_NOSOUND=1 \
        WOW_PROBE_CHAT=".gm on;.tele $TELE;.gps;.gps" WOW_PROBE_CHAT_AT=35 WOW_PROBE_CHAT_EVERY=12 \
        WOW_PROBE_LUA='ProbeLog("TGZONE=" .. tostring(GetRealZoneText()) .. ";")' WOW_PROBE_LUA_AT=12 \
        WOW_PROBE_LUA_AGAIN=12 \
        WOW_PROBE_CAM="30,8,14@$((SECS - 32));210,8,14@$((SECS - 19))" \
        WOW_LIVE_SHOT="$OUT/shot.png" WOW_LIVE_SHOT_AT=$((SECS - 30)) WOW_LIVE_SHOT_COUNT=4 WOW_LIVE_SHOT_EVERY=6 \
        WOW_PROBE_EXIT_AT="$SECS" \
        "$BIN" > "$LOG" 2>&1 || echo "benilla exited with $?"
)
SHOTS=("$OUT"/shot*.png)
"$PY" "$PATCH/tests/client/client_check.py" "$LOG" "$MANIFEST" "${SHOTS[@]}"
