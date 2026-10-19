#!/usr/bin/env bash
# Prepare every downloaded archive in incoming/ that has no .glb yet, each to its triangle budget.
#   patch/scenes/tiangong/models/prep_all.sh [--force] [NAME ...]
set -uo pipefail
cd "$(dirname "$0")"
FORCE=""
[ "${1:-}" = "--force" ] && FORCE=1 && shift
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
PREP="../../../tools/prep_model.py"
# Budgets: rails and lanterns are instanced by the hundred, the main hall and the mountains are seen up close.
declare -A FACES=(
    [railing]=1200 [pine]=15000 [pine2]=20000 [corridor]=10000 [archbridge]=3000 [ropebridge]=7000 [lion]=8000
    [paifang]=50000 [censer]=8000 [lantern]=1500 [toro]=1800 [pavilion]=6500 [mountain]=60000
    [dragonpillar]=20000 [cntemple]=60000 [bpagoda]=40000 [temple]=120000 [langya]=120000 [jinshan]=120000
    [scroll]=80000 [cliffs]=100000 [golden]=200000 [dragon]=60000 [phoenix]=60000 [hall]=70000 [pagoda]=60000
    [citadel]=80000
)
if [ $# -gt 0 ]; then zips=(); for n in "$@"; do zips+=("incoming/$n.zip"); done; else zips=(incoming/*.zip); fi
for zip in "${zips[@]}"; do
    name="$(basename "$zip" .zip)"
    [ -f "$name.glb" ] && [ -z "$FORCE" ] && continue
    faces="${FACES[$name]:-60000}"
    if timeout 1800 "$BLENDER" -b --factory-startup -noaudio --python "$PREP" -- "$zip" "$name.glb" --faces "$faces" \
        --texture 1024 > "incoming/$name.log" 2>&1; then
        grep -E "^PREP" "incoming/$name.log"
    else
        echo "$name FAILED (incoming/$name.log)"
        tail -5 "incoming/$name.log"
    fi
done
