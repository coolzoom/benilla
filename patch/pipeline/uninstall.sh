#!/bin/bash
# Remove an installed scene: delete installed files, restore backups, roll back the world database.
#   patch/pipeline/uninstall.sh [scene] [--restart]
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
[ -f "$LIST" ] || { echo "nothing installed for $SCENE"; exit 0; }

while IFS= read -r dst; do
    [ -n "$dst" ] || continue
    rm -f "$dst"
    if [ -e "$BACKUP/files${dst}" ]; then
        cp -p "$BACKUP/files${dst}" "$dst"
        echo "  restored $dst"
    fi
done < "$LIST"
# shellcheck disable=SC2086
mysql $MYSQL_ARGS "$WORLD_DB" < "$PATCH/db/${SCENE}_world_rollback.sql" 2>&1 | grep -v "Using a password" || true
rm -rf "$BACKUP"
if [ "$RESTART" = 1 ]; then
    "$SERVER_CTL" restart
fi
echo "==> uninstalled $SCENE (restart mangosd to drop the map: $SERVER_CTL restart)"
