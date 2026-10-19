"""天宫云阙 (Celestial Palace above the Sea of Clouds) - scene definition consumed by pipeline/build.py.

One 8x8-tile map laid out like a hand scroll along local +x (heavenimage/ references), about 3.6 km from end to end:

  崖畔苍松   the spawn: a marble terrace on a cliff with pines, a round gate framing the low sun
  白玉天桥   a kilometre of white-jade bridge over the cloud sea to a colossal stone ring gate between waterfalls
  浮岛群     a rising causeway through floating mountains crowned with pavilions, pagodas and temples
  红柱长廊   a covered red-pillared gallery along a cliff
  天路       a sweeping ramp climbing 220 yards to
  金阙广场   a vast golden plaza with dragon pillars, lions and censers, the main hall at its end, dragon and phoenix above

Structure the player walks on (decks, piers, ramps, plaza slabs, the ring gate) is built here and dressed in Poly Haven
photo textures (textures/); everything else is downloaded models (models/, see models/CREDITS.md) instanced by PLACE.
"""
import math
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import geom  # noqa: E402
import gltf  # noqa: E402
import texgen  # noqa: E402
import wmo  # noqa: E402
from wmo import Material, Mesh, POLY_DETAIL, POLY_RENDER  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(HERE, "models")
PHOTO_DIR = os.path.join(HERE, "textures")

# The sky sun is drawn at infinity regardless of farclip, but the client fixes its azimuth at 45 degrees toward world
# +x+y and only moves its elevation with the time of day (DayNight::SetPlanets). Everything below is authored along +x
# and rotated by YAW so the sun hangs SUN_OFFSET degrees left of the axis, SUN_ELEVATION degrees above the horizon.
SUN_ELEVATION = 17.0
SUN_OFFSET = 15.0
YAW = math.radians(45.0 - SUN_OFFSET)
_el, _az = math.radians(SUN_ELEVATION), math.radians(SUN_OFFSET)
SUN_DIR = np.array([math.cos(_el) * math.cos(_az), math.cos(_el) * math.sin(_az), math.sin(_el)])


def rot(x, y, yaw=YAW):
    c, s = math.cos(yaw), math.sin(yaw)
    return (x * c - y * s, x * s + y * c)


# Heights of the walkable route (local coords, yards).
SPAWN_Z = 160.0
ISLES_Z = 200.0
PLAZA_Z = 420.0
DECK_W = 26.0
SPAWN = (-1690.0, 0.0)

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
    # Tiles 29..36 on both axes: world -2666.7..1600 around the origin below, their centre.
    "tiles": [(x, y) for x in range(29, 37) for y in range(29, 37)],
    "wmo_dir": "World\\wmo\\HeavenPalace",
    "tex_dir": "World\\HeavenPalace\\Textures",
    "origin": (-533.333, -533.333),
    "spawn_local": (*rot(*SPAWN), SPAWN_Z + 0.5, YAW),
}
OX, OY = CONFIG["origin"]


def T(name):
    return f"{CONFIG['tex_dir']}\\{name}.blp"


# ---------------------------------------------------------------- the route (local x, y, deck z)

def _route(points, step=10.0):
    """Catmull-Rom through (x, y, z) points, resampled every `step` yards of plan length."""
    dense = geom.spline(points, 400)
    seg = np.linalg.norm(np.diff(dense[:, :2], axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], max(2, int(s[-1] / step) + 1))
    return np.stack([np.interp(t, s, dense[:, k]) for k in range(3)], axis=1)


SPAWN_TERRACE = (-1770.0, -1590.0, -80.0, 80.0)          # x0, x1, y0, y1 at SPAWN_Z
BRIDGE = _route([(-1590, 0, SPAWN_Z), (-1060, 0, SPAWN_Z + 12), (-520, 0, SPAWN_Z)])
RING_X = -480.0
RING_LANDING = (-520.0, -400.0, -40.0, 40.0)
CAUSEWAY = _route([(-400, 0, SPAWN_Z), (-150, 25, 175), (150, -20, 190), (430, 10, ISLES_Z), (560, 0, ISLES_Z)])
GALLERY = _route([(560, 0, ISLES_Z), (1000, 0, ISLES_Z)])
SKY_ROAD = _route([(1000, 0, ISLES_Z), (1120, 70, 260), (1260, -50, 350), (1400, 0, PLAZA_Z), (1440, 0, PLAZA_Z)])
PLAZA = (1440.0, 1800.0, -250.0, 250.0)
HALL_BASE = (1650.0, 1790.0, -120.0, 120.0)              # the main hall's stepped base, 18 yards over the plaza

# Local-space polyline a player must be able to walk (checked offline and against server collision).
WALK_PATH = [rot(x, y) for x, y in [SPAWN, (-1600, 0)]
             + [tuple(p[:2]) for r in (BRIDGE, CAUSEWAY, GALLERY, SKY_ROAD) for p in r]
             + [(1600, 0)]]


# ---------------------------------------------------------------- textures and procedural materials

PHOTOS = {
    "tg_marble": ("marble_01.jpg", 1024),
    "tg_deck": ("white_sandstone_blocks_02.jpg", 1024),
    "tg_paving": ("marble_tiles.jpg", 1024),
    "tg_pattern": ("patterned_paving.jpg", 1024),
    "tg_rockwall": ("rock_wall_08.jpg", 1024),
    "tg_cliff": ("marble_cliff_03.jpg", 1024),
    "tg_sandstone": ("white_sandstone_blocks_02.jpg", 1024),
}

MATS = [
    Material(T("tg_marble"), wmo.F_TWOSIDED),                                   # 0 white marble
    Material(T("tg_deck"), wmo.F_TWOSIDED),                                     # 1 deck tiles
    Material(T("tg_paving"), wmo.F_TWOSIDED),                                   # 2 plaza paving
    Material(T("tg_pattern"), wmo.F_TWOSIDED),                                  # 3 axis paving
    Material(T("tg_rockwall"), wmo.F_TWOSIDED),                                 # 4 rock
    Material(T("tg_gold"), wmo.F_TWOSIDED, emissive=0xFF201000),                # 5 gold
    # Exterior WMO batches are always fogged with the fog colour (CMapObj::UnifiedRender ignores F_UNFOGGED there),
    # so translucent alpha blending is what fades correctly.
    Material(T("tg_fall"), wmo.F_TWOSIDED, wmo.BLEND_ALPHA),                    # 6 waterfall
    Material(T("tg_sandstone"), wmo.F_TWOSIDED),                                # 7 sandstone blocks
    Material(T("tg_cliff"), wmo.F_TWOSIDED),                                    # 8 cliff rock
]
MARBLE, DECK, PAVING, PATTERN, ROCK, GOLD, FALL, SANDSTONE, CLIFF = range(len(MATS))
DECOR = POLY_DETAIL | POLY_RENDER


def _photo(name, size):
    img = Image.open(os.path.join(PHOTO_DIR, name)).convert("RGB")
    return img.resize((size, size), Image.Resampling.LANCZOS)


def textures():
    """{archive path: (PIL image, has_alpha)}."""
    out = {T(k): (_photo(f, s), False) for k, (f, s) in PHOTOS.items()}
    out |= {
        T("tg_gold"): (texgen.gold(256, 3), False),
        T("tg_fall"): (texgen.waterfall(256, 11), True),
        T("tg_cloud"): (texgen.cloud(512, 7), False),
        T("tg_cloud_b"): (texgen.cloud(512, 17), False),
        T("tg_cloud_g"): (texgen.cloud(512, 57), False),
    }
    for name in _used_assets():
        out |= _asset(name)[2]
    return out


# ---------------------------------------------------------------- terrain (far below the cloud sea)

def terrain_height(x, y):
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    return (6.0 * np.sin(x / 41.0) * np.cos(y / 37.0) + 4.0 * np.sin((x + y) / 23.0) +
            2.5 * np.cos((x - 2 * y) / 13.0))


def terrain_layers():
    """Base texture plus (texture, alpha_fn) layers."""
    def bright(x, y):
        return np.clip(0.5 + 0.5 * np.sin(x / 57.0 + np.cos(y / 61.0) * 2.0), 0, 1)

    def soft(x, y):
        return np.clip(0.5 + 0.5 * np.cos(x / 83.0 - np.sin(y / 71.0) * 1.7), 0, 1) * 0.6
    # Terrain layers are opaque (DXT1): a layer's alpha comes from MCAL, and texture alpha only feeds the _s specular.
    return [T("tg_cloud"), T("tg_cloud_b"), T("tg_cloud_g")], [bright, soft]


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
    "float": {0: 90000.0, 1: 0.6, 2: 1.0, 3: 0.25, 4: 0.95, 5: 1.0},
}


# ---------------------------------------------------------------- downloaded models

# file: prepared .glb in models/. drop / crop: leave out named materials / keep faces centred in a box given as
# fractions of the bounds (both cut away the display ground). key: translucent materials alpha-tested. paint: material
# name -> recolouring function. solid: collides (walkable). linear: the long horizontal side is turned onto +x (rails,
# corridors, bridges). turn: extra yaw (degrees) that faces the model's front toward -x, the way the player comes.
ASSETS = {
    "railing": {"file": "railing.glb", "solid": True, "linear": True, "reshape": "_level_railing"},
    "pine": {"file": "pine.glb", "solid": False,
             "drop": ("color_969696_texture_19_green_stained_wood_pine_PBR_texture-seamless",
                      "color_969696_texture_5_rock_moss_texture-seamless")},
    "corridor": {"file": "corridor.glb", "solid": False, "linear": True},
    "archbridge": {"file": "archbridge.glb", "solid": False, "linear": True},
    "ropebridge": {"file": "ropebridge.glb", "solid": False, "linear": True},
    "lion": {"file": "lion.glb", "solid": True, "turn": -90.0},
    "paifang": {"file": "paifang.glb", "solid": True, "linear": True, "turn": 90.0,
                "crop": ((0.0, 0.0, 0.002), (1.0, 1.0, 1.0)), "photo": ("tg_marble", 6.0)},
    "censer": {"file": "censer.glb", "solid": True},
    "lantern": {"file": "lantern.glb", "solid": False},
    "toro": {"file": "toro.glb", "solid": True},
    "pavilion": {"file": "pavilion.glb", "solid": True, "turn": -90.0},
    "mountain": {"file": "mountain.glb", "solid": False, "drop": ("cloud",)},
    "dragonpillar": {"file": "dragonpillar.glb", "solid": True},
    "cntemple": {"file": "cntemple.glb", "solid": True, "turn": -90.0},
    "bpagoda": {"file": "bpagoda.glb", "solid": False, "drop": ("Ground",), "crop": ((0.0, 0.0, 0.02), (1.0, 1.0, 1.0))},
    "temple": {"file": "temple.glb", "solid": False, "turn": -90.0, "paint": {"Scene_-_Root": "_brighten"}},
    "langya": {"file": "langya.glb", "solid": False},
    "jinshan": {"file": "jinshan.glb", "solid": False},
    "golden": {"file": "golden.glb", "solid": True, "turn": -90.0},
    "hall": {"file": "hall.glb", "solid": True, "turn": 180.0, "crop": ((0.25, 0.17, 0.08), (0.83, 0.83, 1.0))},
    "pagoda": {"file": "pagoda.glb", "solid": False, "drop": ("BaotaHLLDZ_1001",)},
    "dragon": {"file": "dragon.glb", "solid": False, "paint": {"MI_b09_00_drg_hair": "_paint_dragon"}},
    "phoenix": {"file": "phoenix.glb", "solid": False, "drop": ("15_-_Default", "Material_13"), "key": True},
    "citadel": {"file": "citadel.glb", "solid": False},
}


def _paint_dragon(img):
    """The dragon's only map is an iridescent glow mask over a near-black red: crimson scales, the green belly plates
    turned gold, the mask's dark lines kept as the scales' shading."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    lum = a.mean(axis=2, keepdims=True)
    belly = np.clip((a[..., 1:2] - np.maximum(a[..., 0:1], a[..., 2:3])) * 2.5, 0.0, 1.0)
    crimson, gold = np.array([0.72, 0.07, 0.05]), np.array([0.98, 0.74, 0.28])
    col = (crimson + (gold - crimson) * belly) * (0.45 + 0.55 * lum)
    return Image.fromarray((col.clip(0, 1) * 255).astype(np.uint8), "RGB").convert("RGBA")


def _level_railing(model):
    """The balustrade scan runs down a stair at 1:2: sheared level, its steps and the end posts cut off, it is one
    section of panel with a post in the middle that repeats end to end."""
    p = model.pos - model.pos.min(axis=0)
    p[:, 2] += 0.5 * p[:, 0]
    model.pos = p
    lo, hi = p.min(axis=0), p.max(axis=0)
    frac = lambda v, k: (v - lo[k]) / (hi[k] - lo[k])
    keep = ((frac(0.25, 0), 0.0, frac(1.12, 2)), (frac(1.62, 0), 1.0, 1.0))
    return gltf.select(model, box=keep)


def _brighten(img):
    """Atlases authored for a strong key light read as near-black under the zone's softer one."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    out = (np.power(a, 0.7) * 1.25).clip(0, 1) * 255
    return Image.fromarray(out.astype(np.uint8), "RGB").convert("RGBA")


PAINT = {"_paint_dragon": _paint_dragon, "_brighten": _brighten}
RESHAPE = {"_level_railing": _level_railing}
_assets = {}


def _yaw_matrix(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _asset(name):
    """(model normalised to its footprint centre at the origin and lowest point at z 0, [Material], textures)."""
    if name in _assets:
        return _assets[name]
    spec = ASSETS[name]
    model = gltf.select(gltf.load(os.path.join(MODELS_DIR, spec["file"])), spec.get("drop", ()), spec.get("crop"))
    if "reshape" in spec:
        model = RESHAPE[spec["reshape"]](model)
    turn = spec.get("turn", 0.0)
    ext = model.pos.max(axis=0) - model.pos.min(axis=0)
    if spec.get("linear") and ext[1] > ext[0]:
        turn += 90.0
    r = _yaw_matrix(turn)
    model.pos, model.nrm = model.pos @ r.T, model.nrm @ r.T
    lo, hi = model.pos.min(axis=0), model.pos.max(axis=0)
    model.pos = model.pos - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    blends = {"OPAQUE": wmo.BLEND_OPAQUE, "MASK": wmo.BLEND_ALPHAKEY,
              "BLEND": wmo.BLEND_ALPHAKEY if spec.get("key") else wmo.BLEND_ALPHA}
    if "photo" in spec:
        # Untextured models: one of the scene photos, projected along each vertex's dominant normal axis.
        photo, repeats = spec["photo"]
        p, a = model.pos * (repeats / max(float(np.ptp(model.pos, axis=0).max()), 1e-9)), np.abs(model.nrm)
        model.uv = np.where((a[:, 2] >= a[:, :2].max(axis=1))[:, None], p[:, [0, 1]],
                            np.where((a[:, 0] >= a[:, 1])[:, None], p[:, [1, 2]], p[:, [0, 2]]))
        mats = [Material(T(photo), wmo.F_TWOSIDED, wmo.BLEND_OPAQUE)] * len(model.names)
        _assets[name] = (model, mats, {})
        return _assets[name]
    mats, texs = [], {}
    for i, (img, blend, mname) in enumerate(zip(model.images, model.blends, model.names)):
        if mname in spec.get("paint", {}):
            img = PAINT[spec["paint"][mname]](img)
        path = T(f"tgm_{name}_{i}")
        texs[path] = (img, blend != "OPAQUE")
        mats.append(Material(path, wmo.F_TWOSIDED, blends.get(blend, wmo.BLEND_OPAQUE)))
    _assets[name] = (model, mats, texs)
    return _assets[name]


def _available(name):
    return os.path.isfile(os.path.join(MODELS_DIR, ASSETS[name]["file"]))


# ---------------------------------------------------------------- placements

# (asset, (x, y, z), yaw degrees, size yards, axis of `size`: 'x' / 'y' / 'z' / 'max', anchor, height); z is where the
# model's lowest point goes, or its highest with anchor 'top'; a height scales z on its own (stretched rail sections).
PLACE = []
RAIL_HEIGHT = 3.2


def place(asset, x, y, z, yaw=0.0, size=10.0, axis="max", anchor="base", height=None):
    PLACE.append((asset, (x, y, z), yaw, size, axis, anchor, height))


def rails(route, width=DECK_W, seg=9.0, sides=(1, -1), inset=1.2):
    """Balustrade segments along both edges of a deck route, each `seg` yards long."""
    pts = np.asarray(route)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1))])
    n = max(1, int(round(s[-1] / seg)))
    t = np.linspace(0.0, s[-1], n + 1)
    p = np.stack([np.interp(t, s, pts[:, k]) for k in range(3)], axis=1)
    for a, b in zip(p[:-1], p[1:]):
        d = b[:2] - a[:2]
        length = float(np.linalg.norm(d))
        d /= max(length, 1e-6)
        left = np.array([-d[1], d[0]])
        yaw = math.degrees(math.atan2(d[1], d[0]))
        mid = (a + b) / 2
        for side in sides:
            q = mid[:2] + left * side * (width / 2 - inset)
            place("railing", q[0], q[1], float(min(a[2], b[2])), yaw, length + 0.3, "x", height=RAIL_HEIGHT)


def rect_rails(x0, x1, y0, y1, z, gaps=(), seg=9.0):
    """Balustrade round a rectangle; `gaps` are (side, centre, width) openings, side one of 'x0', 'x1', 'y0', 'y1'."""
    edges = {"x0": ((x0, y1), (x0, y0)), "x1": ((x1, y0), (x1, y1)), "y0": ((x0, y0), (x1, y0)),
             "y1": ((x1, y1), (x0, y1))}
    for side, (a, b) in edges.items():
        a, b = np.array(a, float), np.array(b, float)
        cuts = sorted((c, w) for s, c, w in gaps if s == side)
        horizontal = side in ("y0", "y1")
        lo, hi = (min(a[0], b[0]), max(a[0], b[0])) if horizontal else (min(a[1], b[1]), max(a[1], b[1]))
        spans, start = [], lo
        for c, w in cuts:
            spans.append((start, c - w / 2))
            start = c + w / 2
        spans.append((start, hi))
        for u0, u1 in spans:
            if u1 - u0 < seg * 0.5:
                continue
            if horizontal:
                route = [(u0, a[1], z), (u1, a[1], z)]
            else:
                route = [(a[0], u0, z), (a[0], u1, z)]
            rails(route, width=0.0, seg=seg, sides=(1,), inset=0.0)


def _layout():
    PLACE.clear()
    # 崖畔苍松: the spawn cliff, pines leaning over the edge, a small pavilion.
    x0, x1, y0, y1 = SPAWN_TERRACE
    place("mountain", (x0 + x1) / 2 - 10, 0, 14, 20, 320, "max")
    place("pine", -1620, 66, SPAWN_Z, 200, 46, "z")
    place("pine", -1745, -64, SPAWN_Z, 30, 38, "z")
    place("pavilion", -1735, 40, SPAWN_Z, 0, 34, "x")
    for y in (-30, 30):
        place("toro", -1600, y, SPAWN_Z, 0, 9, "z")
    rect_rails(x0, x1, y0, y1, SPAWN_Z, gaps=[("x1", 0.0, DECK_W)])
    # 白玉天桥 and its ring gate between two waterfall mountains.
    rails(BRIDGE)
    for side in (-1, 1):
        place("mountain", RING_X + 40, side * 230, 60, 90 * side, 340, "max")
        place("lion", RING_X - 70, side * 20, SPAWN_Z, 0, 9, "z")
    # 浮岛群: floating mountains along the causeway, crowned with pavilions, pagodas and temples.
    rails(CAUSEWAY)
    isles = [("langya", -170, 300, 150, 260), ("jinshan", 120, -330, 140, 300), ("mountain", -260, -330, 120, 220),
             ("mountain", 300, 340, 135, 240), ("mountain", 40, 560, 170, 200), ("mountain", 420, -560, 160, 230)]
    for asset, x, y, z, size in isles:
        place(asset, x, y, z, (x * 7) % 360, size, "max")
    place("pagoda", -260, -330, 120 + 150, 0, 120, "z")
    place("bpagoda", 300, 340, 135 + 160, 0, 110, "z")
    place("ropebridge", -230, -165, 175, 90, 140, "x")
    place("archbridge", 200, 175, 185, 90, 120, "x")
    for x, y in ((-60, 420), (220, -470), (-330, 180), (380, 200)):
        place("pine", x, y, 230, (x * 3) % 360, 40, "z")
    # 红柱长廊: the covered gallery, a cliff on its right.
    gx = np.arange(GALLERY[0][0] + 20, GALLERY[-1][0], 40.0)
    for x in gx:
        place("corridor", float(x), 0, ISLES_Z, 0, 40.5, "x")
    place("mountain", 780, -330, 60, 160, 380, "max")
    place("temple", 790, -250, ISLES_Z + 60, 0, 150, "x")
    # 天路.
    rails(SKY_ROAD)
    # 金阙广场: gateway, lions, censers, lanterns, dragon pillars, side halls, the main hall; dragon and phoenix above.
    px0, px1, py0, py1 = PLAZA
    place("mountain", (px0 + px1) / 2, 0, PLAZA_Z - 285, 0, 660, "max")
    rect_rails(px0, px1, py0, py1, PLAZA_Z, gaps=[("x0", 0.0, DECK_W + 4)])
    place("paifang", px0 + 30, 0, PLAZA_Z, 0, 70, "x")
    for side in (-1, 1):
        place("lion", px0 + 55, side * 26, PLAZA_Z, 0, 12, "z")
        for x in (1520.0, 1580.0):
            place("censer", x, side * 40, PLAZA_Z, 0, 10, "z")
        for x in (1500.0, 1560.0, 1620.0):
            place("dragonpillar", x, side * 80, PLAZA_Z, 0, 46, "z")
        for x in np.arange(px0 + 40, px1 - 20, 45.0):
            place("toro", float(x), side * (py1 - 18), PLAZA_Z, 0, 9, "z")
        place("cntemple", 1600, side * 185, PLAZA_Z, 90 * side, 110, "max")
    hx0, hx1, hy0, hy1 = HALL_BASE
    place("golden", (hx0 + hx1) / 2 + 10, 0, PLAZA_Z + 18, 0, 230, "y")
    place("dragon", 1600, 150, PLAZA_Z + 150, 0, 330, "max")
    place("phoenix", 1620, -150, PLAZA_Z + 160, 0, 200, "max")
    # Backdrop beyond the plaza: the floating citadel.
    place("citadel", 2050, -520, 300, 0, 420, "x")


def _used_assets():
    _layout()
    return sorted({a for a, *_ in PLACE if _available(a)})


# ---------------------------------------------------------------- procedural structure

def ribbon(m, route, width, thick, top=DECK, side=MARBLE, flags=POLY_RENDER, tile=12.0):
    """A deck slab following `route` (x, y, z of its top), `width` wide and `thick` deep."""
    pts = np.asarray(route, dtype=np.float64)
    d = np.gradient(pts[:, :2], axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    left = np.stack([-d[:, 1], d[:, 0]], axis=1)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    L = np.column_stack([pts[:, :2] + left * width / 2, pts[:, 2]])
    R = np.column_stack([pts[:, :2] - left * width / 2, pts[:, 2]])
    down = np.array([0.0, 0.0, thick])
    u = width / tile
    for i in range(len(pts) - 1):
        v0, v1 = s[i] / tile, s[i + 1] / tile
        geom.quad(m, R[i], R[i + 1], L[i + 1], L[i], top, uv=((0, v0), (0, v1), (u, v1), (u, v0)), flags=flags)
        h = thick / tile
        for a, b in ((L[i], L[i + 1]), (R[i + 1], R[i])):
            geom.quad(m, a - down, b - down, b, a, side, uv=((v0, h), (v1, h), (v1, 0), (v0, 0)), flags=flags)
        geom.quad(m, L[i] - down, L[i + 1] - down, R[i + 1] - down, R[i] - down, side,
                  uv=((0, v0), (0, v1), (u, v1), (u, v0)), flags=flags)


def piers(m, route, every=160.0, radius=7.0, bottom=-60.0, thick=4.0):
    pts = np.asarray(route)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1))])
    for t in np.arange(every / 2, s[-1], every):
        x, y, z = (float(np.interp(t, s, pts[:, k])) for k in range(3))
        grade = abs(float(np.interp(t + 5, s, pts[:, 2]) - np.interp(t - 5, s, pts[:, 2]))) / 10
        z -= grade * (radius + 3) * 1.42
        geom.cylinder(m, (x, y), radius, bottom, z - thick, MARBLE, seg=20, cap=False, uv_rep=(3, 18))
        geom.box(m, (x - radius - 3, y - radius - 3, z - thick - 6), (x + radius + 3, y + radius + 3, z - thick),
                 MARBLE, uv_scale=0.08)
        geom.cylinder(m, (x, y), radius + 1.2, z - thick - 9, z - thick - 6, GOLD, seg=20)


def slab(m, x0, x1, y0, y1, z, thick, top=PAVING, side=MARBLE, tile=16.0, flags=POLY_RENDER):
    geom.box(m, (x0, y0, z - thick), (x1, y1, z - 0.02), side, uv_scale=1.0 / tile, flags=flags)
    geom.quad(m, (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), top,
              uv=((0, 0), ((x1 - x0) / tile, 0), ((x1 - x0) / tile, (y1 - y0) / tile), (0, (y1 - y0) / tile)),
              flags=flags)


def stepped_base(m, x0, x1, y0, y1, z, height, tiers=3, step=8.0):
    """须弥座: marble tiers with gold trims rising `height` over z; returns the top."""
    th = height / tiers
    for i in range(tiers):
        k = (tiers - 1 - i) * step
        slab(m, x0 - k, x1 + k, y0 - k, y1 + k, z + th * (i + 1), th, top=MARBLE if i < tiers - 1 else PAVING)
        top = z + th * (i + 1)
        geom.box(m, (x0 - k - 0.8, y0 - k - 0.8, top - 1.3), (x1 + k + 0.8, y1 + k + 0.8, top - 0.3), GOLD, uv_scale=0.2)
    return z + height


def stair(m, x0, x1, y0, y1, z0, z1, steps):
    run = (x1 - x0) / steps
    for i in range(steps):
        za = z0 + (z1 - z0) * (i + 1) / steps
        geom.box(m, (x0 + i * run, y0, z0 - 1), (x0 + (i + 1) * run + 0.02, y1, za), MARBLE, uv_scale=0.1)


def waterfall(m, x, y, z_top, z_bot, width, facing):
    f = np.array(facing, dtype=np.float64)
    f /= np.linalg.norm(f)
    side = np.array([-f[1], f[0]])
    for off in (0.0, 2.0, 4.5):
        bx, by = x + f[0] * off, y + f[1] * off
        w = width * (1 + off * 0.08)
        p0 = (bx - side[0] * w / 2, by - side[1] * w / 2, z_bot)
        p1 = (bx + side[0] * w / 2, by + side[1] * w / 2, z_bot)
        p2 = (bx + side[0] * w / 2, by + side[1] * w / 2, z_top)
        p3 = (bx - side[0] * w / 2, by - side[1] * w / 2, z_top)
        geom.quad(m, p0, p1, p2, p3, FALL, uv=((0, (z_top - z_bot) / 40), (1, (z_top - z_bot) / 40), (1, 0), (0, 0)),
                  flags=DECOR)


def ring_gate(m, x, z_floor, R, r):
    """A colossal stone ring standing across the route, open at the foot so the deck runs through."""
    c = (x, 0.0, z_floor + R - r * 0.6)
    gap = math.asin(min(0.95, (DECK_W / 2 + 4) / R))
    a0, a1 = -math.pi / 2 + gap, 3 * math.pi / 2 - gap
    geom.torus_arc(m, c, (0, 1), R, r, a0, a1, MARBLE, seg=128, rseg=18, uv_rep=(36, 3))
    for dx in (-r * 0.55, r * 0.55):
        geom.torus_arc(m, (x + dx, 0.0, c[2]), (0, 1), R - r + 1.0, 2.0, a0, a1, GOLD, seg=128, rseg=8)
        geom.torus_arc(m, (x + dx, 0.0, c[2]), (0, 1), R + r - 1.0, 2.2, a0, a1, GOLD, seg=128, rseg=8)
    for s in (-1, 1):
        ey = R * math.cos(a0) * s
        geom.box(m, (x - r * 1.4, ey - r * 1.1 * s, z_floor - 40), (x + r * 1.4, ey + r * 1.1 * s, z_floor + 14),
                 MARBLE, uv_scale=0.05)


def build_route():
    m = Mesh()
    x0, x1, y0, y1 = SPAWN_TERRACE
    stepped_base(m, x0, x1, y0, y1, SPAWN_Z - 24, 24, tiers=3, step=6)
    # moon window at the terrace edge, framing the sun ahead
    ring_gate(m, x1 - 10, SPAWN_Z, 36, 4.0)
    ribbon(m, BRIDGE, DECK_W, 5.0)
    piers(m, BRIDGE)
    lx0, lx1, ly0, ly1 = RING_LANDING
    slab(m, lx0, lx1, ly0, ly1, SPAWN_Z, 8.0, top=PATTERN)
    ring_gate(m, RING_X, SPAWN_Z, 115, 15.0)
    for side in (-1, 1):
        waterfall(m, RING_X + 60, side * 190, 380, 40, 70, (-0.3, -side * 1.0))
        waterfall(m, RING_X + 20, side * 330, 330, 40, 50, (-0.8, -side * 0.6))
    ribbon(m, CAUSEWAY, DECK_W, 5.0)
    piers(m, CAUSEWAY, every=180)
    ribbon(m, GALLERY, DECK_W + 6, 6.0, top=PATTERN)
    piers(m, GALLERY, every=120)
    ribbon(m, SKY_ROAD, DECK_W + 4, 6.0)
    piers(m, SKY_ROAD, every=110, bottom=-80)
    px0, px1, py0, py1 = PLAZA
    slab(m, px0, px1, py0, py1, PLAZA_Z, 30.0, top=PAVING)
    slab(m, px0, HALL_BASE[0], -18, 18, PLAZA_Z + 0.05, 0.05, top=PATTERN)
    hx0, hx1, hy0, hy1 = HALL_BASE
    stepped_base(m, hx0, hx1, hy0, hy1, PLAZA_Z, 18, tiers=3, step=8)
    stair(m, hx0 - 46, hx0 - 16, -24, 24, PLAZA_Z, PLAZA_Z + 18, 16)
    for side in (-1, 1):
        waterfall(m, px1 - 40, side * (py1 + 2), PLAZA_Z - 2, 60, 80, (0, side))
        waterfall(m, px0 + 120, side * (py1 + 2), PLAZA_Z - 2, 60, 60, (0, side))
    # waterfalls off the floating isles
    for x, y, z in ((-170, 300, 160), (120, -330, 150), (300, 340, 150), (-260, -330, 130)):
        waterfall(m, x + 40, y - math.copysign(60, y), z, 20, 30, (0.3, -math.copysign(1, y)))
    return m


# ---------------------------------------------------------------- WMO pieces

def _instances(name):
    """One mesh holding every placement of an asset, and its materials."""
    model, mats, _ = _asset(name)
    flags = POLY_RENDER if ASSETS[name]["solid"] else DECOR
    ext = model.pos.max(axis=0) - model.pos.min(axis=0)
    mesh = Mesh()
    faces = [(int(a), int(b), int(c), int(f)) for (a, b, c), f in zip(model.tris, model.face_mat)]
    for asset, (x, y, z), yaw, size, axis, anchor, height in PLACE:
        if asset != name:
            continue
        span = ext.max() if axis == "max" else ext["xyz".index(axis)]
        s = size / max(span, 1e-9)
        scale = np.array([s, s, height / max(ext[2], 1e-9) if height else s])
        r = _yaw_matrix(yaw)
        p = (model.pos * scale) @ r.T
        p[:, 2] += z - (p[:, 2].max() if anchor == "top" else 0.0)
        p[:, 0] += x
        p[:, 1] += y
        n = model.nrm @ r.T
        base = len(mesh.pos)
        mesh.pos += [tuple(map(float, v)) for v in p]
        mesh.nrm += [tuple(map(float, v)) for v in n]
        mesh.uv += [tuple(map(float, v)) for v in model.uv]
        mesh.faces += [(a + base, b + base, c + base, f, flags) for a, b, c, f in faces]
    return mesh, mats


def wmos():
    """[(archive path, wmo files dict, bbox, world position, mesh)] - every piece is authored in local coords."""
    out = []
    c, s = math.cos(YAW), math.sin(YAW)
    r = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    pieces = [("tg_route", build_route(), MATS)]
    for name in _used_assets():
        mesh, mats = _instances(name)
        pieces.append((f"tg_{name}", mesh, mats))
    for name, mesh, mats in pieces:
        mesh.pos = [tuple(map(float, p)) for p in np.asarray(mesh.pos, dtype=np.float64) @ r.T]
        mesh.nrm = [tuple(map(float, n)) for n in np.asarray(mesh.nrm, dtype=np.float64) @ r.T]
        groups = wmo.split_groups(name, mesh)
        files, bbox = wmo.build(mats, groups, wmo_id=0, ambient=0xFF3A3020)
        out.append((f"{CONFIG['wmo_dir']}\\{name}.wmo", files, bbox, (OX, OY, 0.0), mesh))
    return out


def spawn_world():
    lx, ly, z, o = CONFIG["spawn_local"]
    return (OX + lx, OY + ly, z, o)
