#!/usr/bin/env python3
"""Generate vmangos terrain/collision data (maps/, vmaps/, optional mmaps/) for the custom map only.

The vmangos extractors walk every map in Map.dbc, so they get a minimal fake 1.12 client (build/<scene>/mini/Data):
dbc.MPQ carries a Map.dbc listing just the custom map, the full AreaTable.dbc (the .map files store each chunk's
exploreFlag, which must match area_template.explore_flag) and an empty GameObjectDisplayInfo.dbc; terrain.MPQ carries
our world files. Results land in patch/server/{maps,vmaps,mmaps}.

    patch/.venv/bin/python patch/pipeline/extract_server.py --scene tiangong [--mmaps]
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import OUR_MPQ, PATCH  # noqa: E402

import mpq  # noqa: E402
from dbc import DBC  # noqa: E402

VMANGOS = os.environ.get("VMANGOS", "/Users/mac/Downloads/git/wow1121cn/vmangos")
EXTRACTORS = os.environ.get("VMANGOS_EXTRACTORS", os.path.join(VMANGOS, "opt", "vmangos", "bin", "Extractors"))


def run(cmd, cwd):
    print("$", " ".join(cmd), f"(in {cwd})")
    p = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, errors="replace")
    print("\n".join(p.stdout.splitlines()[-25:]))
    if p.returncode != 0:
        raise SystemExit(f"{cmd[0]} failed with {p.returncode}")
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="tiangong")
    ap.add_argument("--mmaps", action="store_true")
    args = ap.parse_args()
    build_dir = os.path.join(PATCH, "build", args.scene)
    manifest = json.load(open(os.path.join(build_dir, "manifest.json")))
    map_id = manifest["config"]["map_id"]
    loose = os.path.join(build_dir, "files")

    def read(name):
        with open(os.path.join(loose, *name.split("\\")), "rb") as fh:
            return fh.read()

    mini = os.path.join(build_dir, "mini")
    if os.path.isdir(mini):
        shutil.rmtree(mini)
    data = os.path.join(mini, "Data")
    os.makedirs(data)

    full_map = DBC(read("DBFilesClient\\Map.dbc"))
    only = DBC(field_count=full_map.fields)
    only.strings = full_map.strings
    only.records = [r for r in full_map.records if r[0] == map_id]
    chain = mpq.Chain(mpq.client_chain(skip=(OUR_MPQ,)))
    god = DBC(chain.read("DBFilesClient\\GameObjectDisplayInfo.dbc"))
    chain.close()
    god.records = []
    dbcs = {
        "DBFilesClient\\Map.dbc": only.serialize(),
        "DBFilesClient\\AreaTable.dbc": read("DBFilesClient\\AreaTable.dbc"),
        "DBFilesClient\\GameObjectDisplayInfo.dbc": god.serialize(),
    }
    # MapExtractor reads DBCs from dbc.MPQ; VMapExtractor never opens dbc.MPQ, so terrain.MPQ carries them too.
    mpq.build(os.path.join(data, "dbc.MPQ"), dbcs)
    mpq.build(os.path.join(data, "terrain.MPQ"), {**{n: read(n) for n in manifest["world_files"]}, **dbcs})

    work = os.path.join(build_dir, "extract")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    run([os.path.join(EXTRACTORS, "MapExtractor"), "-i", mini, "-o", work, "-e", "1", "--silent"], work)
    # -s: the default (-l) keeps every triangle, so the server would collide with the detail (non-collidable) light
    # beams and cloud cards the client walks through; -s keeps only collision/render-non-detail faces.
    run([os.path.join(EXTRACTORS, "VMapExtractor"), "-s", "-d", data + "/", "--silent"], work)
    os.makedirs(os.path.join(work, "vmaps"), exist_ok=True)
    run([os.path.join(EXTRACTORS, "VMapAssembler"), "Buildings", "vmaps"], work)
    if args.mmaps:
        shutil.copy(os.path.join(EXTRACTORS, "config.json"), work)
        run([os.path.join(EXTRACTORS, "MoveMapGenerator"), str(map_id), "--silent",
             "--configInputPath", "config.json"], work)

    out = os.path.join(PATCH, "server")
    for sub in ("maps", "vmaps", "mmaps"):
        d = os.path.join(out, sub)
        if os.path.isdir(d):
            shutil.rmtree(d)
    maps = sorted(glob.glob(os.path.join(work, "maps", f"{map_id:03d}*.map")))
    os.makedirs(os.path.join(out, "maps"))
    for f in maps:
        shutil.copy(f, os.path.join(out, "maps"))
    os.makedirs(os.path.join(out, "vmaps"))
    models = {w["path"].split("\\")[-1].lower() + ".vmo" for w in manifest["wmos"]}
    vm = [f for f in glob.glob(os.path.join(work, "vmaps", "*"))
          if os.path.basename(f).startswith(f"{map_id:03d}") or os.path.basename(f).lower() in models]
    for f in vm:
        shutil.copy(f, os.path.join(out, "vmaps"))
    mm = []
    if args.mmaps:
        os.makedirs(os.path.join(out, "mmaps"))
        mm = glob.glob(os.path.join(work, "mmaps", f"{map_id:03d}*"))
        for f in mm:
            shutil.copy(f, os.path.join(out, "mmaps"))
    print(f"server data: {len(maps)} maps, {len(vm)} vmap files, {len(mm)} mmap files -> {out}")
    if not maps:
        raise SystemExit("no .map files produced")
    if not any(f.endswith(".vmtree") for f in vm):
        raise SystemExit("no .vmtree produced")
    with open(os.path.join(PATCH, "client", OUR_MPQ), "rb") as fh:
        digest = hashlib.md5(fh.read()).hexdigest()
    with open(os.path.join(build_dir, "extracted_from.txt"), "w") as fh:
        fh.write(digest + "\n")


if __name__ == "__main__":
    main()
