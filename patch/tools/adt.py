"""1.12 WDT/ADT writer (v18; MCNK with MCVT/MCNR/MCLY/MCRF/MCAL/MCLQ/MCSE, MODF placements, no MH2O).

Layouts follow stock 1.12.1 Azeroth_32_48.adt (patch/ref), benilla-adt, and the vmangos map extractor's reader
contrib/extractor/loadlib/adt.h.
"""
import math
import struct

import numpy as np

from wmo import chunk

TILE = 1600.0 / 3.0          # 533.333 yards
CHUNK = TILE / 16.0          # 33.333 yards
UNIT = CHUNK / 8.0           # 4.1666 yards
CENTER = 32.0 * TILE         # 17066.666

MCLY_USE_ALPHA = 0x100


def tile_of(world_x, world_y):
    """(file_x, file_y) of the ADT containing a world position; files are named Map_<file_x>_<file_y>.adt."""
    return int((CENTER - world_y) // TILE), int((CENTER - world_x) // TILE)


def world_to_placement(x, y, z):
    return (CENTER - y, z, CENTER - x)


def modf_entry(name_index, unique_id, world_pos, local_min, local_max, yaw_deg=0.0):
    """MODF entry. rotation.y = 180 + yaw makes WMO local axes equal world axes when yaw is 0
    (CMap::CreateMapObjDef applies RotateAroundZ(rot.y + pi))."""
    yaw = math.radians(yaw_deg)
    c, s = math.cos(yaw), math.sin(yaw)
    corners = []
    for lx in (local_min[0], local_max[0]):
        for ly in (local_min[1], local_max[1]):
            for lz in (local_min[2], local_max[2]):
                wx = world_pos[0] + lx * c - ly * s
                wy = world_pos[1] + lx * s + ly * c
                corners.append((wx, wy, world_pos[2] + lz))
    pl = [world_to_placement(*p) for p in corners]
    lo = [min(p[i] for p in pl) for i in range(3)]
    hi = [max(p[i] for p in pl) for i in range(3)]
    pos = world_to_placement(*world_pos)
    return struct.pack("<II3f3f3f3fHHHH", name_index, unique_id, *pos, 0.0, 180.0 + yaw_deg, 0.0, *lo, *hi, 0, 0, 0,
                       0)


def build_wdt(tiles):
    main = bytearray(64 * 64 * 8)
    for fx, fy in tiles:
        struct.pack_into("<II", main, (fy * 64 + fx) * 8, 1, 0)
    return (chunk("MVER", struct.pack("<I", 18)) + chunk("MPHD", b"\0" * 32) + chunk("MAIN", bytes(main)) +
            chunk("MWMO", b""))


def _alpha4(values):
    """64x64 floats in [0,1] -> 2048-byte 4-bit alpha map (low nibble first)."""
    q = np.clip(np.rint(values * 15.0), 0, 15).astype(np.uint8)
    return (q[:, 0::2] | (q[:, 1::2] << 4)).tobytes()


def build_adt(fx, fy, height_fn, textures, alpha_fns, area_id, wmo_names=(), modf=()):
    """height_fn(world_x, world_y)->z (numpy-vectorised); alpha_fns: per layer >0, fn(world_x, world_y)->[0,1]."""
    mtex = b"".join(t.encode() + b"\0" for t in textures)
    mwmo = bytearray()
    mwid = []
    for n in wmo_names:
        mwid.append(len(mwmo))
        mwmo += n.encode() + b"\0"
    modf_data = b"".join(modf)
    n_wmo = len(modf)

    mcnks = []
    for iy in range(16):
        for ix in range(16):
            top_x = CENTER - (fy * 16 + iy) * CHUNK
            top_y = CENTER - (fx * 16 + ix) * CHUNK
            xs, ys = [], []
            for row in range(17):
                if row % 2 == 0:
                    r = row // 2
                    for col in range(9):
                        xs.append(top_x - r * UNIT)
                        ys.append(top_y - col * UNIT)
                else:
                    r = row // 2
                    for col in range(8):
                        xs.append(top_x - r * UNIT - UNIT / 2)
                        ys.append(top_y - col * UNIT - UNIT / 2)
            xs = np.array(xs)
            ys = np.array(ys)
            hz = np.asarray(height_fn(xs, ys), dtype=np.float64)
            base = float(hz.min())
            mcvt = struct.pack("<145f", *(hz - base))

            e = 0.5
            dzdx = (height_fn(xs + e, ys) - height_fn(xs - e, ys)) / (2 * e)
            dzdy = (height_fn(xs, ys + e) - height_fn(xs, ys - e)) / (2 * e)
            n = np.stack([-dzdx, -dzdy, np.ones_like(xs)], axis=1)
            n /= np.linalg.norm(n, axis=1, keepdims=True)
            mcnr = np.clip(np.rint(n * 127), -127, 127).astype(np.int8).tobytes() + b"\0" * 13

            layers = b""
            mcal = b""
            ax = top_x - (np.arange(64) + 0.5) * (CHUNK / 64)
            ay = top_y - (np.arange(64) + 0.5) * (CHUNK / 64)
            gx, gy = np.meshgrid(ax, ay, indexing="ij")
            layers += struct.pack("<IIII", 0, 0, 0, 0)
            for li, fn in enumerate(alpha_fns[:3]):
                layers += struct.pack("<IIII", li + 1, MCLY_USE_ALPHA, len(mcal), 0)
                mcal += _alpha4(np.asarray(fn(gx, gy), dtype=np.float64))
            n_layers = 1 + len(alpha_fns[:3])
            mcrf = struct.pack(f"<{n_wmo}I", *range(n_wmo))

            sub = b""
            ofs = {}
            hdr_size = 8 + 128
            # Stock 1.12 order; MCLQ is a bare header (its declared size is always 0, the MCNK's sizeLiquid 8
            # covers it) and MCSE an empty emitter list, as on dry stock chunks.
            for tag, data in (("MCVT", mcvt), ("MCNR", mcnr), ("MCLY", layers), ("MCRF", mcrf), ("MCAL", mcal),
                              ("MCLQ", b""), ("MCSE", b"")):
                ofs[tag] = hdr_size + len(sub)
                if tag == "MCNR":
                    sub += struct.pack("<4sI", b"RNCM", 435) + data
                else:
                    sub += chunk(tag, data)
            header = struct.pack("<IIIIIIIIIIIIIIIHH16sIIIIII3fIII",
                                 0, ix, iy, n_layers, 0,
                                 ofs["MCVT"], ofs["MCNR"], ofs["MCLY"], ofs["MCRF"], ofs["MCAL"], len(mcal) + 8,
                                 0, 0, area_id, n_wmo, 0, 0, b"\0" * 16, 0, 0,
                                 ofs["MCSE"], 0, ofs["MCLQ"], 8,
                                 top_x, top_y, base, 0, 0, 0)
            assert len(header) == 128, len(header)
            mcnks.append(chunk("MCNK", header + sub))

    mver = chunk("MVER", struct.pack("<I", 18))
    body_chunks = [("MCIN", None), ("MTEX", mtex), ("MMDX", b""), ("MMID", b""), ("MWMO", bytes(mwmo)),
                   ("MWID", struct.pack(f"<{len(mwid)}I", *mwid)), ("MDDF", b""), ("MODF", modf_data)]
    mhdr_size = 8 + 64
    rel = {}
    cur = mhdr_size
    for tag, data in body_chunks:
        rel[tag] = cur
        cur += 8 + (4096 if tag == "MCIN" else len(data))
    mcnk_start = len(mver) + cur
    mcin = bytearray()
    off = mcnk_start
    for m in mcnks:
        mcin += struct.pack("<IIII", off, len(m), 0, 0)
        off += len(m)
    mhdr = struct.pack("<16I", 0, rel["MCIN"] - 8, rel["MTEX"] - 8, rel["MMDX"] - 8, rel["MMID"] - 8,
                       rel["MWMO"] - 8, rel["MWID"] - 8, rel["MDDF"] - 8, rel["MODF"] - 8, 0, 0, 0, 0, 0, 0, 0)
    out = mver + chunk("MHDR", mhdr)
    for tag, data in body_chunks:
        out += chunk(tag, bytes(mcin) if tag == "MCIN" else data)
    out += b"".join(mcnks)
    return out
