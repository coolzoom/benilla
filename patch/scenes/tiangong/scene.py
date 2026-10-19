"""天宫云阙 (Celestial Palace above the Sea of Clouds) - scene definition consumed by pipeline/build.py.

Layout follows the prompt in heavenplan: centred single-point perspective along +X. From the spawn terrace the
player looks through a giant circular stone gate, down a long white-jade stair-bridge, to a golden palace on a
tiered platform; floating islands with pagodas flank it, a static dragon coils overhead, a phoenix spreads its
wings beside the hall, and a colossal translucent deity silhouette rises behind everything, lit by light shafts.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import geom  # noqa: E402
import texgen  # noqa: E402
import wmo  # noqa: E402
from wmo import Material, Mesh, POLY_DETAIL, POLY_RENDER  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# The sky sun is drawn at infinity regardless of farclip, but the client fixes its azimuth at 45 degrees toward world
# +x+y and only moves its elevation with the time of day (DayNight::SetPlanets). Everything below is authored along +x
# and rotated by YAW so the sun hangs SUN_OFFSET degrees left of the axis, SUN_ELEVATION degrees above the horizon.
SUN_ELEVATION = 17.0
SUN_OFFSET = 15.0
YAW = math.radians(45.0 - SUN_OFFSET)
_el, _az = math.radians(SUN_ELEVATION), math.radians(SUN_OFFSET)
SUN_DIR = np.array([math.cos(_el) * math.cos(_az), math.cos(_el) * math.sin(_az), math.sin(_el)])
# 1.12's Map.dbc has no timeOfDayOverride: the real sun follows server time. The golden hour lives in the light bands
# (held constant all day) and in the authored beams, which point along SUN_DIR.


def rot(x, y, yaw=YAW):
    c, s = math.cos(yaw), math.sin(yaw)
    return (x * c - y * s, x * s + y * c)


CONFIG = {
    "map_id": 800,
    "directory": "HeavenPalace",
    "name": "天宫云阙",
    "description": "云海之上的天宫",
    "area_id": 4988,
    "area_bit": 2000,          # AreaTable exploreFlag == vmangos area_template.explore_flag; stock max 1814
    "area_level": 60,
    "tele_id": 8800,
    "tele_name": "tiangong",
    "light_id": 500,
    "light_params_id": 600,
    "loading_screen_id": 255,
    "loading_screen": "Interface\\Glues\\LoadingScreens\\LoadScreenTianGong.blp",
    "tiles": [(x, y) for x in range(31, 34) for y in range(31, 34)],
    "wmo_dir": "World\\wmo\\HeavenPalace",
    "tex_dir": "World\\HeavenPalace\\Textures",
    "origin": (-266.667, -266.667),
    "spawn_local": (*rot(-392.0, 0.0), 120.5, YAW),
}

TERRACE_Z = 120.0
PALACE_Z = 200.0
EYE = np.array([-392.0, 0.0, TERRACE_Z + 3.0])   # authoring-space viewpoint the sky cards are turned toward
# Local-space polyline a player must be able to walk (checked offline and against server collision).
WALK_PATH = [rot(x, y) for x, y in [(-392.0, 0.0), (-318.0, 0.0), (52.0, 0.0), (90.0, 0.0), (120.0, 0.0)]]
OX, OY = CONFIG["origin"]


def T(name):
    return f"{CONFIG['tex_dir']}\\{name}.blp"


def textures():
    """{archive path: (PIL image, has_alpha)}."""
    return {
        T("tg_jade"): (texgen.jade(512, 1), False),
        T("tg_paving"): (texgen.jade_paving(512, 2), False),
        T("tg_gold"): (texgen.gold(256, 3), False),
        T("tg_tile"): (texgen.glazed_tile(256, 4), False),
        T("tg_lacquer"): (texgen.red_lacquer(256, 5), False),
        T("tg_stone"): (texgen.stone(512, 6), False),
        T("tg_cloud"): (texgen.cloud(512, 7), False),
        T("tg_cloud_b"): (texgen.cloud(512, 17), False),
        T("tg_cloud_g"): (texgen.cloud(512, 57), False),
        T("tg_cloud_a"): (texgen.cloud_puff(512, 27), True),
        T("tg_cloud_c"): (texgen.cloud_puff(512, 47), True),
        T("tg_cloud_rim"): (texgen.cloud_rim(512, 37), True),
        T("tg_beam"): (texgen.beam(256), True),
        T("tg_scale"): (texgen.dragon_scale(256, 8), False),
        T("tg_feather"): (texgen.feather(256, 9), False),
        T("tg_deity"): (texgen.deity(512, 10), True),
        T("tg_fall"): (texgen.waterfall(256, 11), True),
        T("tg_leaf"): (texgen.foliage(256, 12), False),
        T("tg_rock"): (texgen.rock(256, 13), False),
    }


# ---------------------------------------------------------------- terrain

def terrain_height(x, y):
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    return (6.0 * np.sin(x / 41.0) * np.cos(y / 37.0) + 4.0 * np.sin((x + y) / 23.0) +
            2.5 * np.cos((x - 2 * y) / 13.0))


def terrain_layers():
    """Base texture plus (texture, alpha_fn) layers."""
    def bright(x, y):
        return np.clip(0.5 + 0.5 * np.sin(x / 57.0 + np.cos(y / 61.0) * 2.0), 0, 1)

    def gold_light(x, y):
        lx, ly = rot(x - OX, y - OY, -YAW)
        d = np.abs(ly) / 260.0
        return np.clip(0.8 - d, 0, 1) * np.clip((lx + 450) / 600.0, 0, 1)
    # Terrain layers are opaque (DXT1): a layer's alpha comes from MCAL, and texture alpha only feeds the _s specular.
    return [T("tg_cloud"), T("tg_cloud_b"), T("tg_cloud_g")], [bright, gold_light]


# ---------------------------------------------------------------- lighting (hex RGB, band index -> colour)

LIGHT = {
    "int": {
        0: 0xFFB868,   # sun diffuse: golden-hour amber
        1: 0x587CA8,   # ambient: cool cyan-blue fill (warm/cool contrast)
        # sky dome is drawn additively over the sun disc (DayNight::DNSky::Render), so it must stay below white
        2: 0x24548A,   # sky top
        3: 0x3F7CB4,   # sky middle
        4: 0x7FA6C4,   # middle to horizon
        5: 0xC8A070,   # above horizon: golden hour
        6: 0xE8A058,   # horizon
        7: 0xA9C4D4,   # fog: cyan-blue haze (aerial perspective)
        8: 0x4D4D4D,
        9: 0xFFD890,   # sun disc and glare
        10: 0xFFD8A8,  # sky clouds, sun side
        11: 0xE8B080,  # sky clouds, slope
        12: 0x8FA6C8,  # sky clouds, base
        13: 0x7A5A40,
        14: 0x3A6E86,  # ocean shallow
        15: 0x1E4660,  # ocean deep
        16: 0x4F8296,  # river shallow
        17: 0x2F5A70,  # river deep
    },
    # 0 fog end in inches (x36; clamped to farclip), 1 fog start as a fraction of it, 3 sky cloud density
    "float": {0: 45000.0, 1: 0.6, 2: 1.0, 3: 0.25, 4: 0.95, 5: 1.0},
}


# ---------------------------------------------------------------- materials

MATS = [
    Material(T("tg_jade"), wmo.F_TWOSIDED),                                     # 0 jade
    Material(T("tg_paving"), wmo.F_TWOSIDED),                                   # 1 paving
    Material(T("tg_gold"), wmo.F_TWOSIDED, emissive=0xFF201000),                # 2 gold
    Material(T("tg_tile"), wmo.F_TWOSIDED, emissive=0xFF181000),                # 3 glazed tile
    Material(T("tg_lacquer"), wmo.F_TWOSIDED),                                  # 4 red lacquer
    Material(T("tg_stone"), wmo.F_TWOSIDED),                                    # 5 stone
    Material(T("tg_scale"), wmo.F_TWOSIDED, emissive=0xFF102018),               # 6 dragon
    Material(T("tg_feather"), wmo.F_TWOSIDED, emissive=0xFF301008),             # 7 phoenix
    # Exterior WMO batches are always fogged with the fog colour (CMapObj::UnifiedRender ignores F_UNFOGGED there), so
    # additive glow would turn into opaque fog-coloured sheets; translucent alpha blending fades correctly instead.
    Material(T("tg_deity"), wmo.F_TWOSIDED | wmo.F_UNLIT, wmo.BLEND_ALPHA),     # 8 deity glow
    Material(T("tg_beam"), wmo.F_TWOSIDED | wmo.F_UNLIT, wmo.BLEND_ALPHA),      # 9 light shaft
    Material(T("tg_cloud_a"), wmo.F_TWOSIDED | wmo.F_UNLIT, wmo.BLEND_ALPHA),   # 10 cloud sheet
    Material(T("tg_fall"), wmo.F_TWOSIDED, wmo.BLEND_ALPHA),                    # 11 waterfall
    Material(T("tg_leaf"), wmo.F_TWOSIDED),                                     # 12 foliage
    Material(T("tg_rock"), wmo.F_TWOSIDED),                                     # 13 rock
    Material(T("tg_cloud_c"), wmo.F_TWOSIDED | wmo.F_UNLIT, wmo.BLEND_ALPHA),   # 14 cloud sheet, second variant
    Material(T("tg_cloud_rim"), wmo.F_TWOSIDED | wmo.F_UNLIT, wmo.BLEND_ALPHA),  # 15 backlit cloud
]
(JADE, PAVING, GOLD, TILE, LACQUER, STONE, SCALE, FEATHER, DEITY, BEAM, CLOUD, FALL, LEAF, ROCK, CLOUD2,
 RIM) = range(len(MATS))
DECOR = POLY_DETAIL | POLY_RENDER


# ---------------------------------------------------------------- builders (local coords, origin at CONFIG origin)

def railing(m, x0, x1, y, z0, z1, posts=6.0):
    """Jade balustrade along x at lateral offset y; z rises linearly from z0 to z1."""
    n = max(2, int(abs(x1 - x0) / posts))
    for i in range(n + 1):
        t = i / n
        x = x0 + (x1 - x0) * t
        z = z0 + (z1 - z0) * t
        geom.box(m, (x - 0.5, y - 0.5, z), (x + 0.5, y + 0.5, z + 3.2), JADE)
        geom.box(m, (x - 0.65, y - 0.65, z + 3.2), (x + 0.65, y + 0.65, z + 3.8), GOLD)
    steps = n
    for i in range(steps):
        xa = x0 + (x1 - x0) * i / steps
        xb = x0 + (x1 - x0) * (i + 1) / steps
        za = z0 + (z1 - z0) * i / steps
        zb = z0 + (z1 - z0) * (i + 1) / steps
        geom.quad(m, (xa, y - 0.3, za + 2.6), (xb, y - 0.3, zb + 2.6), (xb, y - 0.3, zb + 3.0),
                  (xa, y - 0.3, za + 3.0), JADE)
        geom.quad(m, (xa, y + 0.3, za + 2.6), (xb, y + 0.3, zb + 2.6), (xb, y + 0.3, zb + 3.0),
                  (xa, y + 0.3, za + 3.0), JADE)
        geom.quad(m, (xa, y - 0.25, za + 0.2), (xb, y - 0.25, zb + 0.2), (xb, y - 0.25, zb + 2.6),
                  (xa, y - 0.25, za + 2.6), JADE, uv=((0, 0), (0.5, 0), (0.5, 0.4), (0, 0.4)))


def sumeru_base(m, cx, cy, w, d, z_top, tiers=3, tier_h=8.0, step_in=8.0):
    """Stacked jade platform tiers (须弥座) with gold trims; returns top z."""
    z = z_top - tiers * tier_h
    for i in range(tiers):
        ww = w - 2 * step_in * (tiers - 1 - i) * 0 + 2 * step_in * (tiers - 1 - i)
        dd = d + 2 * step_in * (tiers - 1 - i)
        geom.box(m, (cx - ww / 2, cy - dd / 2, z), (cx + ww / 2, cy + dd / 2, z + tier_h), JADE, uv_scale=0.05)
        geom.box(m, (cx - ww / 2 - 0.6, cy - dd / 2 - 0.6, z + tier_h - 0.8),
                 (cx + ww / 2 + 0.6, cy + dd / 2 + 0.6, z + tier_h), GOLD, uv_scale=0.2)
        z += tier_h
    geom.quad(m, (cx - w / 2, cy - d / 2, z + 0.02), (cx + w / 2, cy - d / 2, z + 0.02),
              (cx + w / 2, cy + d / 2, z + 0.02), (cx - w / 2, cy + d / 2, z + 0.02), PAVING,
              uv=((0, 0), (w / 16, 0), (w / 16, d / 16), (0, d / 16)))
    return z


def hall(m, cx, cy, w, d, z, col_h, n_cols_w=9, n_cols_d=5, eaves=2):
    """Palace hall: red columns, lacquer walls, gold brackets, double-eaved glazed hip roof."""
    for i in range(n_cols_w):
        for j in range(n_cols_d):
            if 0 < i < n_cols_w - 1 and 0 < j < n_cols_d - 1:
                continue
            x = cx - w / 2 + w * i / (n_cols_w - 1)
            y = cy - d / 2 + d * j / (n_cols_d - 1)
            geom.cylinder(m, (x, y), 1.8, z, z + col_h, LACQUER, seg=12, cap=False, uv_rep=(1, 3))
            geom.box(m, (x - 2.6, y - 2.6, z), (x + 2.6, y + 2.6, z + 1.2), JADE)
    inset = 6.0
    geom.box(m, (cx - w / 2 + inset, cy - d / 2 + inset, z), (cx + w / 2 - inset, cy + d / 2 - inset, z + col_h),
             LACQUER, uv_scale=0.04)
    for k in range(5):
        dx = (k - 2) * w / 6
        geom.box(m, (cx + dx - 5, cy - d / 2 + inset - 0.5, z), (cx + dx + 5, cy - d / 2 + inset + 0.2, z + col_h * 0.8),
                 GOLD, uv_scale=0.3)
    zt = z + col_h
    geom.box(m, (cx - w / 2 - 3, cy - d / 2 - 3, zt), (cx + w / 2 + 3, cy + d / 2 + 3, zt + 3.5), GOLD, uv_scale=0.1)
    roof_z = zt + 3.5
    for e in range(eaves):
        scale = 1.0 - 0.28 * e
        rh = col_h * (0.55 if e == eaves - 1 else 0.3)
        geom.hip_roof(m, (cx, cy), w * scale, d * scale, roof_z, rh, 9.0 * scale, TILE, curl=0.4, seg=10)
        if e < eaves - 1:
            roof_z += rh * 0.75
            iw, idd = w * (1 - 0.28 * (e + 1)), d * (1 - 0.28 * (e + 1))
            geom.box(m, (cx - iw / 2, cy - idd / 2, roof_z - rh * 0.6), (cx + iw / 2, cy + idd / 2, roof_z),
                     LACQUER, uv_scale=0.05)
            geom.box(m, (cx - iw / 2 - 1, cy - idd / 2 - 1, roof_z - 1.5), (cx + iw / 2 + 1, cy + idd / 2 + 1, roof_z),
                     GOLD, uv_scale=0.2)
    top = roof_z + col_h * 0.55
    ridge = max(w * scale / 2 + 9 * scale - (d * scale / 2 + 9 * scale), w * scale * 0.15)
    geom.box(m, (cx - ridge - 2, cy - 1.2, top - 1), (cx + ridge + 2, cy + 1.2, top + 2.5), GOLD, uv_scale=0.2)
    for s in (-1, 1):
        geom.cylinder(m, (cx + s * (ridge + 2), cy), 2.0, top, top + 8, GOLD, seg=10)
    return top


def pagoda(m, cx, cy, z, base_w, tiers, tier_h):
    w = base_w
    for i in range(tiers):
        geom.box(m, (cx - w / 2, cy - w / 2, z), (cx + w / 2, cy + w / 2, z + tier_h), LACQUER, uv_scale=0.08)
        geom.box(m, (cx - w / 2 - 1, cy - w / 2 - 1, z + tier_h - 1.2), (cx + w / 2 + 1, cy + w / 2 + 1, z + tier_h),
                 GOLD, uv_scale=0.2)
        geom.hip_roof(m, (cx, cy), w, w, z + tier_h, tier_h * 0.45, w * 0.28, TILE, curl=0.55, seg=6)
        z += tier_h * 1.25
        w *= 0.84
    geom.cylinder(m, (cx, cy), 0.8, z - tier_h * 0.3, z + tier_h * 1.2, GOLD, seg=8)
    for k in range(3):
        geom.cylinder(m, (cx, cy), 2.4 - k * 0.5, z + k * 3, z + k * 3 + 1.2, GOLD, seg=10)
    return z


def island(m, cx, cy, z_top, radius, depth, seed):
    rng = np.random.default_rng(seed)
    ph = rng.random(6) * 6.28

    def rad(a, v):
        wob = 1 + 0.12 * math.sin(3 * a + ph[0]) + 0.07 * math.sin(7 * a + ph[1]) + 0.04 * math.sin(13 * a + ph[2])
        return radius * wob * (1 - v) ** 0.8 + 3.0

    def f(u, v):
        a = u * 2 * math.pi
        r = rad(a, v)
        return (cx + r * math.cos(a), cy + r * math.sin(a), z_top - 2 - depth * v ** 1.2)
    geom.grid_surface(m, f, 36, 10, ROCK, uv_fn=lambda u, v: (u * 12, v * 4), closed_u=True)

    def top(u, v):
        a = u * 2 * math.pi
        r = rad(a, 0) * (1 - v)
        return (cx + r * math.cos(a), cy + r * math.sin(a), z_top - 2 + 2 * (1 - v) ** 0.3 * 0 + 2 * v)
    geom.grid_surface(m, top, 36, 4, LEAF, uv_fn=lambda u, v: (u * 8, v * 3), closed_u=True)


def waterfall(m, x, y, z_top, z_bot, width, facing):
    f = np.array(facing, dtype=np.float64)
    f /= np.linalg.norm(f)
    side = np.array([-f[1], f[0]])
    for k, off in enumerate((0.0, 1.5)):
        bx, by = x + f[0] * off, y + f[1] * off
        p0 = (bx - side[0] * width / 2, by - side[1] * width / 2, z_bot)
        p1 = (bx + side[0] * width / 2, by + side[1] * width / 2, z_bot)
        p2 = (bx + side[0] * width / 2, by + side[1] * width / 2, z_top)
        p3 = (bx - side[0] * width / 2, by - side[1] * width / 2, z_top)
        geom.quad(m, p0, p1, p2, p3, FALL, uv=((0, (z_top - z_bot) / 40), (1, (z_top - z_bot) / 40), (1, 0),
                                               (0, 0)), flags=DECOR)


# ---------------------------------------------------------------- WMO pieces

def build_gate():
    m = Mesh()
    # spawn terrace
    sumeru_base(m, -385, 0, 80, 90, TERRACE_Z, tiers=3, tier_h=6)
    railing(m, -425, -345, -45, TERRACE_Z, TERRACE_Z)
    railing(m, -425, -345, 45, TERRACE_Z, TERRACE_Z)
    railing(m, -425, -425, -45, TERRACE_Z, TERRACE_Z)
    for s in (-1, 1):
        geom.box(m, (-430, s * 46 - 1, TERRACE_Z), (-424, s * 46 + 1, TERRACE_Z + 4), JADE)
    # giant moon gate: stone ring with gold inner/outer rims, standing in the YZ plane facing +X
    R, r = 72.0, 9.0
    c = (-335.0, 0.0, TERRACE_Z + R - 6)
    a0, a1 = -math.pi / 2 + 0.36, 3 * math.pi / 2 - 0.36   # open at the bottom so the walkway passes through
    geom.torus_arc(m, c, (0, 1), R, r, a0, a1, STONE, seg=96, rseg=14, uv_rep=(24, 2))
    geom.torus_arc(m, (c[0] - 4, c[1], c[2]), (0, 1), R - r + 0.8, 1.6, a0, a1, GOLD, seg=96, rseg=8)
    geom.torus_arc(m, (c[0] + 4, c[1], c[2]), (0, 1), R - r + 0.8, 1.6, a0, a1, GOLD, seg=96, rseg=8)
    geom.torus_arc(m, (c[0] - 3, c[1], c[2]), (0, 1), R + r - 0.5, 1.8, a0, a1, GOLD, seg=96, rseg=8)
    for s in (-1, 1):
        ex = R * math.cos(a0) * s
        geom.box(m, (c[0] - 12, ex - 10 * s, TERRACE_Z - 6), (c[0] + 12, ex + 10 * s, TERRACE_Z + 8), JADE,
                 uv_scale=0.08)
    # pedestals and guardian pillars
    for s in (-1, 1):
        geom.box(m, (-350, s * 62 - 14, TERRACE_Z - 18), (-320, s * 62 + 14, TERRACE_Z + 10), JADE, uv_scale=0.06)
        geom.cylinder(m, (-335, s * 96), 4.0, TERRACE_Z - 18, TERRACE_Z + 90, JADE, seg=16, uv_rep=(2, 8))
        geom.cylinder(m, (-335, s * 96), 5.5, TERRACE_Z + 88, TERRACE_Z + 94, GOLD, seg=16)
        geom.box(m, (-341, s * 96 - 6, TERRACE_Z - 22), (-329, s * 96 + 6, TERRACE_Z - 16), JADE)
    # walkway through the gate
    geom.box(m, (-348, -14, TERRACE_Z - 6), (-318, 14, TERRACE_Z), JADE, uv_scale=0.08)
    geom.quad(m, (-348, -14, TERRACE_Z + 0.02), (-318, -14, TERRACE_Z + 0.02), (-318, 14, TERRACE_Z + 0.02),
              (-348, 14, TERRACE_Z + 0.02), PAVING, uv=((0, 0), (2, 0), (2, 2), (0, 2)))
    return m


def build_bridge():
    m = Mesh()
    x0, x1 = -318.0, 52.0
    width = 26.0
    steps = 160
    rise = PALACE_Z - TERRACE_Z
    run = (x1 - x0) / steps
    for i in range(steps):
        xa = x0 + i * run
        za = TERRACE_Z + rise * (i + 1) / steps
        geom.box(m, (xa, -width / 2, za - 2.2), (xa + run + 0.02, width / 2, za), JADE, uv_scale=0.08)
    # underside beam with gold trim, and arch supports down into the clouds
    geom.quad(m, (x0, -width / 2, TERRACE_Z - 6), (x1, -width / 2, PALACE_Z - 6), (x1, width / 2, PALACE_Z - 6),
              (x0, width / 2, TERRACE_Z - 6), STONE, uv=((0, 0), (20, 0), (20, 2), (0, 2)))
    for s in (-1, 1):
        y = s * width / 2
        geom.quad(m, (x0, y, TERRACE_Z - 6), (x1, y, PALACE_Z - 6), (x1, y, PALACE_Z), (x0, y, TERRACE_Z),
                  STONE, uv=((0, 0), (20, 0), (20, 0.4), (0, 0.4)))
        geom.quad(m, (x0, y + s * 0.3, TERRACE_Z - 1.2), (x1, y + s * 0.3, PALACE_Z - 1.2),
                  (x1, y + s * 0.3, PALACE_Z - 0.2), (x0, y + s * 0.3, TERRACE_Z - 0.2), GOLD,
                  uv=((0, 0), (40, 0), (40, 0.2), (0, 0.2)))
        railing(m, x0, x1, s * (width / 2 - 0.8), TERRACE_Z, PALACE_Z)
    for k in range(1, 4):
        xc = x0 + (x1 - x0) * k / 4
        zc = TERRACE_Z + rise * k / 4
        geom.torus_arc(m, (xc, 0, zc - 60), (1, 0), 40, 5, math.pi * 0.15, math.pi * 0.85, STONE, seg=24, rseg=8,
                       uv_rep=(6, 1))
        geom.cylinder(m, (xc - 36, 0), 6, zc - 120, zc - 50, STONE, seg=12, cap=False, uv_rep=(2, 6))
        geom.cylinder(m, (xc + 36, 0), 6, zc - 120, zc - 50, STONE, seg=12, cap=False, uv_rep=(2, 6))
    return m


def build_palace():
    m = Mesh()
    top = sumeru_base(m, 175, 0, 230, 290, PALACE_Z, tiers=3, tier_h=10, step_in=10)
    # front landing joins the bridge
    geom.box(m, (52, -18, PALACE_Z - 10), (64, 18, PALACE_Z), JADE, uv_scale=0.08)
    # grand central stair into the hall, flanked by dragon-carved ramp (御路)
    for i in range(12):
        geom.box(m, (95 + i * 2.5, -22, PALACE_Z + i * 0.9), (95 + (i + 1) * 2.5, 22, PALACE_Z + (i + 1) * 0.9),
                 JADE, uv_scale=0.1)
    geom.quad(m, (95, -5, PALACE_Z + 0.4), (125, -5, PALACE_Z + 11.2), (125, 5, PALACE_Z + 11.2),
              (95, 5, PALACE_Z + 0.4), GOLD, uv=((0, 0), (3, 0), (3, 1), (0, 1)))
    hall_z = PALACE_Z + 10.8
    geom.box(m, (122, -100, PALACE_Z), (262, 100, hall_z), JADE, uv_scale=0.05)
    hall(m, 192, 0, 120, 180, hall_z, 58, n_cols_w=7, n_cols_d=11, eaves=2)
    # side pavilions
    for s in (-1, 1):
        geom.box(m, (90, s * 122 - 20, PALACE_Z), (130, s * 122 + 20, PALACE_Z + 4), JADE, uv_scale=0.08)
        hall(m, 110, s * 122, 30, 30, PALACE_Z + 4, 16, n_cols_w=4, n_cols_d=4, eaves=2)
    # railing around the platform edge
    for s in (-1, 1):
        railing(m, 62, 288, s * 143, PALACE_Z, PALACE_Z)
    railing(m, 288, 288, -143, PALACE_Z, PALACE_Z)
    # bronze-gold ritual cauldrons and lamp pillars along the axis
    for x in (70, 85):
        for s in (-1, 1):
            geom.cylinder(m, (x, s * 26), 1.5, PALACE_Z, PALACE_Z + 14, GOLD, seg=10)
            geom.box(m, (x - 2.5, s * 26 - 2.5, PALACE_Z + 14), (x + 2.5, s * 26 + 2.5, PALACE_Z + 18), GOLD)
    return m


def build_islands():
    m = Mesh()
    for s in (-1, 1):
        cx, cy, zt = -40.0, s * 250.0, 175.0
        island(m, cx, cy, zt, 70, 150, 3 + s)
        sumeru_base(m, cx, cy, 70, 70, zt + 6, tiers=2, tier_h=4, step_in=5)
        pagoda(m, cx, cy, zt + 6, 34, 7, 18)
        waterfall(m, cx + 30, cy - s * 55, zt - 4, 20, 22, (0.4, -s * 1.0))
        waterfall(m, cx - 45, cy - s * 40, zt - 4, 40, 14, (-0.6, -s * 0.8))
        # small floating rocks
        for k in range(4):
            ang = k * 1.7 + s
            island(m, cx + 120 * math.cos(ang), cy + 90 * math.sin(ang), zt - 30 - 25 * k, 10 + 3 * k, 30 + 6 * k,
                   11 + k + s)
    # tall rear tower on its own island
    island(m, 400, 0, 230, 90, 200, 21)
    sumeru_base(m, 400, 0, 90, 90, 240, tiers=2, tier_h=5, step_in=6)
    pagoda(m, 400, 0, 240, 48, 9, 26)
    for s in (-1, 1):
        waterfall(m, 400 + 50, s * 70, 225, 30, 30, (0.5, s * 1.0))
    return m


def build_dragon():
    m = Mesh()
    pts = []
    for k in range(12):
        a = k / 11 * 2.6 * math.pi + 0.6
        r = 150 - 25 * k / 11
        pts.append((-60 + r * math.cos(a) * 0.9, r * math.sin(a), 250 + 140 * k / 11 + 18 * math.sin(a * 2)))
    path = geom.spline(pts, 220)

    def radius(t):
        return 2.0 + 8.5 * math.sin(math.pi * min(1.0, t * 1.05)) ** 0.6 if t < 0.97 else 9.0
    geom.sweep(m, path, radius, SCALE, rseg=14, flags=DECOR, uv_rep=(60, 2))
    # dorsal fins
    for i in range(6, len(path) - 6, 6):
        p = path[i]
        t = path[i + 1] - path[i - 1]
        t /= np.linalg.norm(t)
        up = np.cross(t, np.cross(np.array([0, 0, 1.0]), t))
        up /= max(np.linalg.norm(up), 1e-6)
        r = radius(i / len(path))
        a = p + up * r * 0.8
        geom.quad(m, a - t * 3, a + t * 3, a + t * 1 + up * r * 0.9, a - t * 2 + up * r * 0.7, GOLD, flags=DECOR)
    # head: elongated snout, horns and whiskers at the end of the path
    head = path[-1]
    fwd = path[-1] - path[-6]
    fwd /= np.linalg.norm(fwd)
    snout = [head + fwd * k * 4 for k in range(8)]
    geom.sweep(m, snout, lambda t: 9.0 * (1 - 0.6 * t), SCALE, rseg=14, flags=DECOR, uv_rep=(3, 2))
    side = np.cross(fwd, np.array([0, 0, 1.0]))
    side /= max(np.linalg.norm(side), 1e-6)
    for s in (-1, 1):
        horn = [head + side * s * 5 + np.array([0, 0, 6]) - fwd * k * 4 + np.array([0, 0, k * 3]) for k in range(7)]
        geom.sweep(m, horn, lambda t: 1.8 * (1 - t) + 0.3, GOLD, rseg=8, flags=DECOR, uv_rep=(2, 1))
        whisk = [head + fwd * 28 + side * s * (4 + k * 5) - np.array([0, 0, k * 2.5 - 2 * math.sin(k)]) for k in
                 range(9)]
        geom.sweep(m, whisk, lambda t: 0.8 * (1 - t) + 0.2, GOLD, rseg=6, flags=DECOR, uv_rep=(2, 1))
        eye = head + fwd * 14 + side * s * 6.5 + np.array([0, 0, 4])
        geom.cylinder(m, (eye[0], eye[1]), 1.6, eye[2] - 1.2, eye[2] + 1.2, GOLD, seg=8)
    # claws
    for t in (0.35, 0.6):
        i = int(t * (len(path) - 1))
        p = path[i] - np.array([0, 0, radius(t)])
        for k in range(3):
            geom.sweep(m, [p, p + np.array([3 * k - 3, 2, -10]), p + np.array([3 * k - 3, 6, -16])],
                       lambda u: 1.6 * (1 - u) + 0.3, GOLD, rseg=6, flags=DECOR, uv_rep=(1, 1))
    return m


def build_phoenix():
    m = Mesh()
    c = np.array([300.0, -210.0, 360.0])
    body = [c + np.array([-30 + k * 7, 0, 10 * math.sin(k / 3)]) for k in range(10)]
    geom.sweep(m, body, lambda t: 3 + 7 * math.sin(math.pi * t), FEATHER, rseg=12, flags=DECOR, uv_rep=(3, 2))
    neck = [body[-1] + np.array([k * 4, 0, k * 4 + 2 * k * k * 0.1]) for k in range(7)]
    geom.sweep(m, neck, lambda t: 3.5 - 1.5 * t, FEATHER, rseg=10, flags=DECOR, uv_rep=(2, 1))
    head = neck[-1]
    geom.sweep(m, [head, head + np.array([6, 0, -1]), head + np.array([11, 0, -3])], lambda t: 3 * (1 - t) + 0.3, GOLD,
               rseg=8, flags=DECOR)
    for k in range(3):
        crest = [head + np.array([-k * 2, 0, 2]) + np.array([-j * 3, 0, j * 3.5]) for j in range(5)]
        geom.sweep(m, crest, lambda t: 1.0 * (1 - t) + 0.2, GOLD, rseg=6, flags=DECOR)
    # spread wings: feathered fan silhouettes extruded thin, in planes tilted upward
    wing = [(0, 0), (30, 8), (70, 22), (115, 48), (150, 85), (140, 70), (150, 62), (128, 50), (138, 38), (110, 30),
            (118, 18), (90, 12), (95, 2), (65, 0), (60, -8), (30, -8)]
    for s in (-1, 1):
        u_axis = np.array([0.15, s * 1.0, 0.25])
        u_axis /= np.linalg.norm(u_axis)
        v_axis = np.array([0.9, 0.0, 0.42])
        v_axis /= np.linalg.norm(v_axis)
        pts = [(p[0], p[1] * 0.9) for p in wing]
        geom.extrude_polygon(m, pts, c + np.array([-6, s * 4, 6]), u_axis, v_axis, 2.0, FEATHER, flags=DECOR,
                             side_mat=GOLD)
    # long flowing tail plumes
    for k in range(5):
        a = (k - 2) * 0.22
        tail = geom.spline([body[0], body[0] + np.array([-40, 60 * a, -10]), body[0] + np.array([-90, 120 * a, -35]),
                            body[0] + np.array([-150, 170 * a, -80 + 10 * k])], 40)
        geom.sweep(m, tail, lambda t: 3.0 * (1 - t) ** 0.5 + 0.6, FEATHER, rseg=8, flags=DECOR, uv_rep=(8, 1),
                   squash=0.35)
    return m


def build_deity():
    """Colossal standing deity silhouette with halo, far behind the palace, facing the spawn."""
    m = Mesh()
    x = 640.0
    sil = [(0, 0), (60, 0), (85, 120), (95, 260), (110, 330), (150, 360), (165, 420), (120, 450), (90, 470), (70, 500),
           (60, 540), (30, 560), (0, 565)]
    full = [(-p[0], p[1]) for p in reversed(sil[1:])] + sil[:-1] + [(0, 565)]
    pts = []
    for p in full:
        if not pts or pts[-1] != p:
            pts.append(p)
    pts = pts[:-1] if pts[0] == pts[-1] else pts
    geom.extrude_polygon(m, pts, (x, 0, -20), (0, 1, 0), (0, 0, 1), 3.0, DEITY, flags=DECOR)
    geom.torus_arc(m, (x + 10, 0, 520), (0, 1), 85, 3.5, 0, 2 * math.pi, DEITY, seg=72, rseg=6, flags=DECOR)
    geom.torus_arc(m, (x + 12, 0, 520), (0, 1), 120, 2.0, 0, 2 * math.pi, DEITY, seg=72, rseg=6, flags=DECOR)
    for k in range(24):
        a = k / 24 * 2 * math.pi
        p0 = np.array([x + 14, 90 * math.cos(a), 520 + 90 * math.sin(a)])
        p1 = np.array([x + 14, 150 * math.cos(a), 520 + 150 * math.sin(a)])
        side = np.array([0, -math.sin(a), math.cos(a)]) * 3
        geom.quad(m, p0 - side, p1 - side * 2, p1 + side * 2, p0 + side, DEITY, flags=DECOR)
    return m


# Where sunlight shafts land (roof ridges and slopes of the halls, plaza, pagodas, bridge, the sea of clouds) and the
# shaft width there. Every shaft runs parallel to SUN_DIR, so in perspective they all fan out from the sky sun.
RAY_TARGETS = [
    ((192, 0, 317), 34), ((165, -45, 298), 26), ((215, 50, 300), 30), ((150, 70, 286), 22), ((235, -75, 284), 24),
    ((110, 122, 248), 20), ((110, -122, 248), 20), ((95, -40, 211), 30), ((250, 30, 211), 26), ((60, 0, 200), 22),
    ((-40, 250, 300), 26), ((-40, -250, 300), 26), ((400, 0, 470), 36), ((-60, 0, 176), 28), ((-190, 6, 148), 24),
    ((-330, 0, 190), 30), ((-150, 170, 80), 46), ((10, -210, 85), 40), ((300, 220, 110), 50), ((-260, -150, 75), 44),
]
RAY_LENGTH = 700.0


def _frame(axis):
    a = axis / np.linalg.norm(axis)
    e1 = np.cross(a, [0.0, 0.0, 1.0])
    e1 /= np.linalg.norm(e1)
    return a, e1, np.cross(a, e1)


def build_beams():
    """Tyndall-effect light shafts: three additive cards per shaft, 60 degrees apart around the shaft axis, so the
    beam keeps its volume from any viewpoint (never more than one card edge-on)."""
    m = Mesh()
    for (tx, ty, tz), w in RAY_TARGETS:
        end = np.array([tx, ty, tz], dtype=np.float64)
        start = end + SUN_DIR * RAY_LENGTH
        a, e1, e2 = _frame(end - start)
        for ang in (0.0, math.pi / 3, 2 * math.pi / 3):
            side = (math.cos(ang) * e1 + math.sin(ang) * e2) * w / 2
            geom.quad(m, start - side * 0.7, start + side * 0.7, end + side * 1.3, end - side * 1.3, BEAM,
                      flags=DECOR)
    return m


PIECES = [
    ("tg_gate", build_gate),
    ("tg_bridge", build_bridge),
    ("tg_palace", build_palace),
    ("tg_islands", build_islands),
    ("tg_dragon", build_dragon),
    ("tg_phoenix", build_phoenix),
    ("tg_deity", build_deity),
    ("tg_beams", build_beams),
]


def wmos():
    """[(archive path, wmo files dict, bbox, world position)] - every piece is authored in local coords."""
    out = []
    c, s = math.cos(YAW), math.sin(YAW)
    r = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    for i, (name, fn) in enumerate(PIECES):
        mesh = fn()
        mesh.pos = [tuple(map(float, p)) for p in np.asarray(mesh.pos, dtype=np.float64) @ r.T]
        mesh.nrm = [tuple(map(float, n)) for n in np.asarray(mesh.nrm, dtype=np.float64) @ r.T]
        groups = wmo.split_groups(name, mesh)
        files, bbox = wmo.build(MATS, groups, wmo_id=0, ambient=0xFF3A3020)
        out.append((f"{CONFIG['wmo_dir']}\\{name}.wmo", files, bbox, (OX, OY, 0.0), mesh))
    return out


def spawn_world():
    lx, ly, z, o = CONFIG["spawn_local"]
    return (OX + lx, OY + ly, z, o)
