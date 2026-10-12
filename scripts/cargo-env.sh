# Source from a repo script. Pins Cargo's output to this checkout's target/.
#
# Cursor's sandbox exports CARGO_TARGET_DIR into a fresh directory under
# $TMPDIR/cursor-sandbox-cache. Cargo prefers that variable over .cargo/config.toml,
# so each agent build wrote a new full dependency graph (about 10 GB) and left the
# previous one in place. Several of those runs are what filled the disk.
_benilla_env_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CARGO_TARGET_DIR="$_benilla_env_root/target"
unset _benilla_env_root

# Incremental caches are named <crate>-<fingerprint>. A changed fingerprint (extra
# RUSTFLAGS, a different target directory) starts a new directory and never deletes
# the old one; each holds a dep-graph of several hundred MB. Keep the newest
# directory for each crate and drop the rest. Safe to call when target/ is absent.
benilla_prune_incremental() {
    local inc d base key keep
    [ -d "${CARGO_TARGET_DIR:-}" ] || return 0
    shopt -s nullglob
    for inc in "$CARGO_TARGET_DIR"/*/incremental "$CARGO_TARGET_DIR"/*/*/incremental; do
        [ -d "$inc" ] || continue
        keep=""
        while IFS= read -r d; do
            [ -n "$d" ] || continue
            [ -d "$d" ] || continue
            base="${d%/}"
            base="${base##*/}"
            key="${base%-*}"
            [ -n "$key" ] || continue
            case " $keep " in
            *" $key "*) rm -rf "$d" ;;
            *) keep="$keep $key" ;;
            esac
        done < <(ls -1dt "$inc"/*/ 2>/dev/null)
    done
    shopt -u nullglob
}
