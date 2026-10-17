"""Offline checks of everything the pipeline produced: MPQ contents, 1.12 DBC rows, WMO/ADT structure against stock
1.12 files, collision under the spawn point, vmangos map/vmap files, the generated SQL and the installed DB rows."""
import glob
import hashlib
import os
import struct

import numpy as np
import pytest

import adt as adtlib
import blp
import wowfmt
from conftest import db_connect, server_env
from dbc import DBC, u2f

WMO_GROUP_ORDER = ["MOPY", "MOVI", "MOVT", "MONR", "MOTV", "MOBA"]
BSP_LEAF_LIMIT = 300
DBC_NAMES = ("Map", "AreaTable", "LoadingScreens", "Light", "LightParams", "LightIntBand", "LightFloatBand")
ZHCN = 4
MAX_AREA_BIT = 64 * 32       # PLAYER_EXPLORED_ZONES_1..64 in 1.12
BLP_DXT1 = (2, 0, 0)         # encoding, alphaDepth, alphaEncoding
BLP_PAL_A8 = (1, 8, 8)


def wdt_path(cfg):
    return f"World\\Maps\\{cfg['directory']}\\{cfg['directory']}.wdt"


def adt_paths(cfg):
    return [f"World\\Maps\\{cfg['directory']}\\{cfg['directory']}_{x}_{y}.adt" for x, y in cfg["tiles"]]


def wmo_files(manifest):
    for w in manifest["wmos"]:
        base = w["path"][:-4]
        yield w, [w["path"]] + [f"{base}_{i:03d}.wmo" for i in range(w["groups"])]


def _md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


# ---------------------------------------------------------------- MPQ contents

def test_mpq_has_map_files(cfg, manifest, lower_mpq):
    need = [wdt_path(cfg)] + adt_paths(cfg)
    for _, files in wmo_files(manifest):
        need += files
    missing = [n for n in need if n.lower() not in lower_mpq]
    assert not missing, missing


def test_mpq_has_dbcs(lower_mpq):
    for d in DBC_NAMES:
        assert f"dbfilesclient\\{d.lower()}.dbc" in lower_mpq, d


def test_mpq_name_sorts_above_stock_patches():
    """1.12 loads Data/patch-?.MPQ (one character, highest first) ahead of patch.MPQ and the base archives."""
    names = {n.lower() for n in os.listdir(os.path.join(server_env()["client"], "Data"))} - {"patch-5.mpq"}
    others = [n for n in names if len(n) == len("patch-5.mpq") and n.startswith("patch-") and n.endswith(".mpq")]
    assert all(n < "patch-5.mpq" for n in others), f"{others} would outrank patch-5.MPQ"


def test_every_referenced_texture_is_packed(cfg, manifest, lower_mpq):
    refs = set()
    for w, _ in wmo_files(manifest):
        refs |= set(wowfmt.WMORoot(lower_mpq[w["path"].lower()]).textures.values())
    for p in adt_paths(cfg):
        refs |= set(wowfmt.ADT(lower_mpq[p.lower()]).textures)
    refs.add(cfg["loading_screen"])
    missing = sorted(r for r in refs if r.lower() not in lower_mpq)
    assert not missing, missing


def test_blp_textures_use_stock_encodings(client_mpq):
    """DXT1 for opaque textures, palettized + 8-bit alpha for translucent ones: both are stock 1.12 encodings."""
    blps = [n for n in client_mpq if n.lower().endswith(".blp")]
    assert blps
    for n in blps:
        data = client_mpq[n]
        assert data[:4] == b"BLP2" and struct.unpack_from("<I", data, 4)[0] == 1, n
        enc = struct.unpack_from("<BBB", data, 8)
        assert enc in (BLP_DXT1, BLP_PAL_A8), f"{n}: {enc}"
        img = blp.decode(data)
        w, h = img.size
        assert w & (w - 1) == 0 and h & (h - 1) == 0, (n, img.size)


def test_loading_screen_is_stock_shape(cfg, lower_mpq):
    data = lower_mpq[cfg["loading_screen"].lower()]
    assert struct.unpack_from("<BBB", data, 8) == BLP_DXT1
    assert struct.unpack_from("<II", data, 12) == (512, 512)


# ---------------------------------------------------------------- DBC rows

@pytest.fixture(scope="session")
def dbcs(lower_mpq):
    return {k: DBC(lower_mpq[f"dbfilesclient\\{k.lower()}.dbc"]) for k in DBC_NAMES}


@pytest.fixture(scope="session")
def base_dbcs(patch_dir):
    d = os.path.join(patch_dir, "build", "base_dbc")
    return {k: DBC.load(os.path.join(d, k + ".dbc")) for k in DBC_NAMES}


def test_dbc_layouts_are_stock(dbcs, base_dbcs):
    for k in DBC_NAMES:
        assert dbcs[k].fields == base_dbcs[k].fields, k
        assert len(dbcs[k].records) > len(base_dbcs[k].records), f"{k}: no row added"


def test_stock_rows_survive(dbcs, base_dbcs):
    for k in DBC_NAMES:
        ours = {r[0]: r for r in dbcs[k].records}
        for r in base_dbcs[k].records:
            assert r[0] in ours, f"{k} row {r[0]} lost"


def test_map_row(cfg, dbcs):
    d = dbcs["Map"]
    assert d.fields == 42
    r = d.find(cfg["map_id"])
    assert r is not None
    assert d.string(r[1]) == cfg["directory"]
    assert d.string(r[4 + ZHCN]) == cfg["name"]
    assert r[2] == 0, "open world, not an instance"
    assert r[19] == cfg["area_id"]
    assert r[38] == cfg["loading_screen_id"]
    assert u2f(r[41]) == 1.0


def test_area_row(cfg, dbcs):
    d = dbcs["AreaTable"]
    r = d.find(cfg["area_id"])
    assert r and r[1] == cfg["map_id"] and r[2] == 0 and r[3] == cfg["area_bit"]
    assert d.string(r[11 + ZHCN]) == cfg["name"]
    assert cfg["area_bit"] < MAX_AREA_BIT
    bits = [x[3] for x in d.records if x[0] != cfg["area_id"]]
    assert cfg["area_bit"] not in bits, "area bit collides with a stock area"


def test_loading_screen_row(cfg, dbcs):
    d = dbcs["LoadingScreens"]
    r = d.find(cfg["loading_screen_id"])
    assert r and d.string(r[2]).lower() == cfg["loading_screen"].lower()


def test_light_rows(cfg, dbcs):
    lt = dbcs["Light"].find(cfg["light_id"])
    assert lt and lt[1] == cfg["map_id"]
    assert (u2f(lt[2]), u2f(lt[3]), u2f(lt[4]), u2f(lt[6])) == (0.0, 0.0, 0.0, 0.0), "map-wide light"
    pid = cfg["light_params_id"]
    assert lt[7:11] == [pid] * 4 and dbcs["LightParams"].find(lt[11]), "clear/storm slots ours, death slot stock"
    assert dbcs["LightParams"].find(pid)
    for band in range(18):
        r = dbcs["LightIntBand"].find((pid - 1) * 18 + band + 1)
        assert r and 1 <= r[1] <= 16, band
    for band in range(6):
        assert dbcs["LightFloatBand"].find((pid - 1) * 6 + band + 1), band
    others = [r for r in dbcs["Light"].records if r[1] == cfg["map_id"] and r[0] != cfg["light_id"]]
    assert not others


# ---------------------------------------------------------------- WDT / ADT

def test_wdt_matches_reference(cfg, lower_mpq, patch_dir):
    ref = wowfmt.WDT(open(os.path.join(patch_dir, "ref", "Azeroth.wdt"), "rb").read())
    w = wowfmt.WDT(lower_mpq[wdt_path(cfg).lower()])
    assert w.order == ref.order
    assert sorted(w.tiles) == sorted(tuple(t) for t in cfg["tiles"])


def test_adt_structure_matches_reference(cfg, manifest, lower_mpq, patch_dir):
    ref = wowfmt.ADT(open(os.path.join(patch_dir, "ref", "Azeroth_32_48.adt"), "rb").read())
    ref_head = [t for t in ref.order if t != "MCNK"]
    ref_sub = ref.chunks[0]["sub"]
    n_wmo = len(manifest["wmos"])
    for p in adt_paths(cfg):
        a = wowfmt.ADT(lower_mpq[p.lower()])
        assert [t for t in a.order if t != "MCNK"] == ref_head, p
        assert a.order.count("MCNK") == 256
        assert len(a.modf) == n_wmo and len(a.wmo_names) == n_wmo
        assert sorted(a.mwid) == sorted(a.wmo_names)
        for i, c in enumerate(a.chunks):
            assert (c["ix"], c["iy"]) == (i % 16, i // 16)
            assert c["area"] == cfg["area_id"]
            assert c["sub"] == ref_sub
            assert c["flags"] & ~0xFF == 0, "1.12 MCNK flags have no WotLK bits"
            assert c["size_liquid"] == 8, "dry chunk: bare MCLQ header as in stock"
            assert 1 <= c["layers"] <= 4


def test_adt_chunk_positions(cfg, lower_mpq):
    for (fx, fy), p in zip(cfg["tiles"], adt_paths(cfg)):
        a = wowfmt.ADT(lower_mpq[p.lower()])
        c0 = a.chunks[0]
        assert abs(c0["pos"][0] - (adtlib.CENTER - fy * adtlib.TILE)) < 1e-3
        assert abs(c0["pos"][1] - (adtlib.CENTER - fx * adtlib.TILE)) < 1e-3


def test_modf_bounds_contain_world_spawn(manifest, cfg, lower_mpq):
    a = wowfmt.ADT(lower_mpq[adt_paths(cfg)[0].lower()])
    sx, sy, sz, _ = manifest["spawn"]
    px, pz = adtlib.CENTER - sy, adtlib.CENTER - sx
    inside = [m for m in a.modf if m[8] <= px <= m[11] and m[9] <= sz <= m[12] and m[10] <= pz <= m[13]]
    assert inside, "no WMO placement extent covers the spawn point"


# ---------------------------------------------------------------- WMO

def test_wmo_root_matches_reference(manifest, lower_mpq, patch_dir):
    ref = wowfmt.WMORoot(open(os.path.join(patch_dir, "ref", "bridge.wmo"), "rb").read())
    for w, _ in wmo_files(manifest):
        r = wowfmt.WMORoot(lower_mpq[w["path"].lower()])
        assert r.order == ref.order, w["path"]
        assert r.n_groups == len(r.group_info) == w["groups"]
        assert r.n_mat == len(r.materials)
        for m in r.materials:
            assert m[3] in r.textures, "MOMT texture offset not at a MOTX string start"


def test_wmo_group_matches_reference(manifest, lower_mpq, patch_dir):
    ref = wowfmt.WMOGroup(open(os.path.join(patch_dir, "ref", "bridge_000.wmo"), "rb").read())
    assert ref.order[:6] == WMO_GROUP_ORDER
    for w, files in wmo_files(manifest):
        for name in files[1:]:
            assert wowfmt.WMOGroup(lower_mpq[name.lower()]).order[:6] == WMO_GROUP_ORDER, name


def test_wmo_groups_are_consistent(manifest, lower_mpq):
    for w, files in wmo_files(manifest):
        root = wowfmt.WMORoot(lower_mpq[files[0].lower()])
        for gi, name in enumerate(files[1:]):
            g = wowfmt.WMOGroup(lower_mpq[name.lower()])
            nv, nf = len(g.verts), len(g.mopy)
            assert len(g.indices) == nf and len(g.normals) == nv and len(g.uvs) == nv
            assert g.indices.max() < nv
            assert np.isfinite(g.verts).all()
            mats = g.mopy[:, 1]
            assert ((mats < root.n_mat) | (mats == 0xFF)).all()
            covered = 0
            for b in g.batches:
                start, count, vmin, vmax, mat = b[6], b[7], b[8], b[9], b[11]
                assert start % 3 == 0 and count % 3 == 0 and mat < root.n_mat
                tri = g.indices[start // 3:(start + count) // 3]
                assert tri.min() >= vmin and tri.max() <= vmax
                covered += count // 3
            assert covered == nf
            gb = np.array(root.group_info[gi][1:7])
            assert (g.verts.min(0) >= gb[:3] - 0.01).all() and (g.verts.max(0) <= gb[3:] + 0.01).all()


def test_wmo_bsp_is_valid(manifest, lower_mpq):
    for w, files in wmo_files(manifest):
        for name in files[1:]:
            g = wowfmt.WMOGroup(lower_mpq[name.lower()])
            assert g.flags & 0x1 and g.bsp, name
            nf = len(g.mopy)
            seen = set()
            for flags, neg, pos, n_faces, start, _ in g.bsp:
                if flags & 4:
                    assert n_faces <= BSP_LEAF_LIMIT
                    assert start + n_faces <= len(g.bsp_refs)
                    seen |= set(g.bsp_refs[start:start + n_faces].tolist())
                else:
                    for ch in (neg, pos):
                        assert ch == -1 or 0 <= ch < len(g.bsp)
            assert all(f < nf for f in seen)
            collidable = set(np.nonzero((g.mopy[:, 0] & 0x04) == 0)[0].tolist())
            assert collidable <= seen, f"{name}: {len(collidable - seen)} collidable faces missing from BSP"


# ---------------------------------------------------------------- walkability

@pytest.fixture(scope="session")
def collision(manifest, lower_mpq):
    tris = []
    for w, files in wmo_files(manifest):
        for name in files[1:]:
            tris.append(wowfmt.collision_mesh(wowfmt.WMOGroup(lower_mpq[name.lower()])))
    return np.concatenate(tris)


def test_spawn_stands_on_floor(cfg, collision):
    x, y, z, _ = cfg["spawn_local"]
    floor = wowfmt.ray_down(collision, x, y, z + 2)
    assert floor is not None, "nothing under spawn: player would fall"
    assert 0 <= z - floor < 2.5, f"spawn z {z} vs floor {floor}"
    assert wowfmt.ray_down(collision, x, y, z + 3.0) == floor, "spawn is inside geometry"


def test_walk_path_is_continuous(cfg, manifest, collision):
    """The scene's walk path (spawn to the main hall) must have a floor everywhere and only climbable steps."""
    x, y, z, _ = cfg["spawn_local"]
    steps = wowfmt.walk(collision, manifest["walk_path"], wowfmt.ray_down(collision, x, y, z + 2))
    assert len(steps) > 10
    ox, oy = cfg["origin"]
    for px, py, pz in manifest["probes"]:
        assert any(abs(px - ox - sx) < 1e-3 and abs(py - oy - sy) < 1e-3 and abs(pz - sz) < 1e-3
                   for sx, sy, sz in steps), (px, py, pz)


# ---------------------------------------------------------------- vmangos data

def test_server_maps(cfg, patch_dir):
    files = sorted(glob.glob(os.path.join(patch_dir, "server", "maps", f"{cfg['map_id']:03d}*.map")))
    assert len(files) == len(cfg["tiles"])
    want = {f"{cfg['map_id']:03d}{y:02d}{x:02d}.map" for x, y in cfg["tiles"]}
    assert {os.path.basename(f) for f in files} == want
    for f in files:
        assert open(f, "rb").read(8) == b"MAPSz1.4", f


def test_server_vmaps(cfg, manifest, patch_dir, lower_mpq):
    vm = os.path.join(patch_dir, "server", "vmaps")
    assert open(os.path.join(vm, f"{cfg['map_id']:03d}.vmtree"), "rb").read(8) == b"VMAP_7.0"
    assert len(glob.glob(os.path.join(vm, f"{cfg['map_id']:03d}_*.vmtile"))) == len(cfg["tiles"])
    names = {os.path.basename(p).lower() for p in glob.glob(os.path.join(vm, "*.wmo.vmo"))}
    for w, files in wmo_files(manifest):
        solid = any(len(wowfmt.collision_mesh(wowfmt.WMOGroup(lower_mpq[f.lower()]))) for f in files[1:])
        if solid:
            assert w["path"].split("\\")[-1].lower() + ".vmo" in names, w["path"]


def test_server_files_match_build(patch_dir, manifest):
    """Server maps/vmaps must be re-extracted whenever the MPQ changes."""
    stamp = os.path.join(patch_dir, "build", manifest["scene"], "extracted_from.txt")
    assert os.path.exists(stamp), "run pipeline/extract_server.py"
    assert open(stamp).read().strip() == _md5(os.path.join(patch_dir, "client", "patch-5.MPQ")), \
        "server data is stale: run pipeline/extract_server.py"


def test_sql_patch(cfg, manifest, patch_dir):
    sql = open(os.path.join(patch_dir, "db", f"{manifest['scene']}_world.sql"), encoding="utf8").read()
    assert f"DELETE FROM `map_template` WHERE `entry` = {cfg['map_id']};" in sql
    assert f"VALUES ({cfg['map_id']}, 0, 0, 0, 0, 0, 0, -1, 0, 0, '{cfg['name']}', '');" in sql
    assert f"VALUES ({cfg['area_id']}, {cfg['map_id']}, 0, {cfg['area_bit']}, 64," in sql
    assert f"DELETE FROM `game_tele` WHERE `id` = {cfg['tele_id']}" in sql
    assert f"{cfg['map_id']}, '{cfg['tele_name']}');" in sql


# ---------------------------------------------------------------- installed

def test_installed_files_match(patch_dir, cfg):
    env = server_env()
    assert _md5(os.path.join(env["client"], "Data", "patch-5.MPQ")) == _md5(os.path.join(patch_dir, "client",
                                                                                         "patch-5.MPQ"))
    for sub in ("maps", "vmaps"):
        for f in glob.glob(os.path.join(patch_dir, "server", sub, "*")):
            dst = os.path.join(env["data_dir"], sub, os.path.basename(f))
            assert os.path.exists(dst) and _md5(dst) == _md5(f), dst


def test_db_installed(cfg):
    db = db_connect(server_env()["world_db"])
    with db.cursor() as cur:
        cur.execute("SELECT map, name FROM game_tele WHERE id=%s", (cfg["tele_id"],))
        assert cur.fetchone() == (cfg["map_id"], cfg["tele_name"])
        cur.execute("SELECT map_type, ghost_entrance_map, map_name FROM map_template WHERE entry=%s", (cfg["map_id"],))
        assert cur.fetchone() == (0, -1, cfg["name"])
        cur.execute("SELECT map_id, zone_id, explore_flag, name FROM area_template WHERE entry=%s", (cfg["area_id"],))
        assert cur.fetchone() == (cfg["map_id"], 0, cfg["area_bit"], cfg["name"])
        cur.execute("SELECT entry FROM area_template WHERE explore_flag=%s AND entry<>%s",
                    (cfg["area_bit"], cfg["area_id"]))
        assert cur.fetchone() is None, "explore_flag collides with a server area"
