#!/bin/bash
# Install a built scene into the 1.12 client, the vmangos data dir and the world database.
#   patch/pipeline/install.sh [scene] [--restart]
# Env overrides:
#   WOW_CLIENT    1.12.1 client folder (gets Data/patch-5.MPQ)
#   MANGOSD_CONF  mangosd config; DataDir and WorldDatabase.Info are read from it
#   SERVER_CTL    start/stop script used by --restart (testserver.sh restart)
#   MYSQL_ARGS / WORLD_DB  override the connection parsed from MANGOSD_CONF
# Every file that would be overwritten is first saved to patch/backup/<scene>/ (see uninstall.sh).
set -euo pipefail
PATCH="$(cd "$(dirname "$0")/.." && pwd)"
SCENE="tiangong"
RESTART=0
for a in "$@"; do
    case "$a" in
        --restart) RESTART=1 ;;
        *) SCENE="$a" ;;
    esac
done
# shellcheck source=server_env.sh
. "$PATCH/pipeline/server_env.sh"
BACKUP="$PATCH/backup/$SCENE"
LIST="$BACKUP/installed.txt"
mkdir -p "$BACKUP/files"
touch "$LIST"

place() {   # place <src> <dst>
    local src="$1" dst="$2"
    if [ -e "$dst" ] && ! grep -qxF "$dst" "$LIST"; then
        local saved="$BACKUP/files${dst}"
        mkdir -p "$(dirname "$saved")"
        cp -p "$dst" "$saved"
        echo "  backed up $dst"
    fi
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    grep -qxF "$dst" "$LIST" || echo "$dst" >> "$LIST"
}

[ -f "$PATCH/client/patch-5.MPQ" ] || { echo "no client/patch-5.MPQ: run pipeline/build.py first" >&2; exit 1; }
[ -d "$PATCH/server/maps" ] || { echo "no server/maps: run pipeline/extract_server.py first" >&2; exit 1; }

echo "==> client ($WOW_CLIENT)"
place "$PATCH/client/patch-5.MPQ" "$WOW_CLIENT/Data/patch-5.MPQ"

echo "==> server data ($DATA_DIR)"
for sub in maps vmaps mmaps; do
    [ -d "$PATCH/server/$sub" ] || continue
    for f in "$PATCH/server/$sub"/*; do [ -e "$f" ] && place "$f" "$DATA_DIR/$sub/$(basename "$f")"; done
done

echo "==> world database ($WORLD_DB)"
# shellcheck disable=SC2086
mysql $MYSQL_ARGS --default-character-set=utf8mb4 "$WORLD_DB" < "$PATCH/db/${SCENE}_world.sql" 2>&1 \
    | grep -v "Using a password" || true

if [ "$RESTART" = 1 ]; then
    "$SERVER_CTL" restart
fi
echo "==> installed $SCENE (mangosd loads map_template at startup: $SERVER_CTL restart)"
