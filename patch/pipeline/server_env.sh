# Sourced by install.sh / uninstall.sh / the tests: where the client, the vmangos data and the world DB live.
WOW_CLIENT="${WOW_CLIENT:-/Users/mac/Downloads/git/wow1121cn}"
MANGOSD_CONF="${MANGOSD_CONF:-/Users/mac/Downloads/git/wow1121cn/.scratch/mangosd-m425.conf}"
SERVER_CTL="${SERVER_CTL:-/Users/mac/Downloads/git/wow1121cn/testserver.sh}"

_conf() { sed -n "s/^$1[[:space:]]*=[[:space:]]*\"\{0,1\}\([^\"]*\)\"\{0,1\}[[:space:]]*$/\1/p" "$MANGOSD_CONF" | head -1; }
DATA_DIR="${DATA_DIR:-$(_conf DataDir)}"
DATA_DIR="${DATA_DIR%/}"
IFS=';' read -r _h _p _u _pw _db <<< "$(_conf 'WorldDatabase\.Info')"
WORLD_DB="${WORLD_DB:-$_db}"
MYSQL_ARGS="${MYSQL_ARGS:--h$_h -P$_p -u$_u -p$_pw}"
[ -n "$DATA_DIR" ] && [ -n "$WORLD_DB" ] || { echo "cannot read DataDir/WorldDatabase.Info from $MANGOSD_CONF" >&2; exit 1; }
