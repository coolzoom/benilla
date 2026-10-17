"""Readers for the formats the writers produce (WDT/ADT/WMO), used by tests and for debugging.

    python -m tools.wowfmt <file.wmo|file.adt|file.wdt>   (run from patch/)
"""
import struct
import sys

import numpy as np


def chunks(data, start=0, end=None):
    """Yield (tag, offset_of_data, size) for a flat run of reversed-FourCC chunks."""
    end = len(data) if end is None else end
    p = start
    while p + 8 <= end:
        tag = data[p:p + 4][::-1].decode("latin1")
        size = struct.unpack_from("<I", data, p + 4)[0]
        if tag == "MCNR" and size == 435:
            size = 448
        yield tag, p + 8, size
        p += 8 + size
    assert p == end, f"chunk run overruns: ended at {p}, expected {end}"


def chunk_map(data, start=0, end=None):
    out = {}
    for tag, ofs, size in chunks(data, start, end):
        out.setdefault(tag, (ofs, size))
    return out


def strings(blob):
    """Offset -> string for a NUL-separated string block."""
    out, p = {}, 0
    while p < len(blob):
        q = blob.find(b"\0", p)
        if q < 0:
            break
        if q > p:
            out[p] = blob[p:q].decode("utf8", "replace")
        p = q + 1
    return out


class WMORoot:
    def __init__(self, data):
        self.order = [t for t, _, _ in chunks(data)]
        c = chunk_map(data)
        o, _ = c["MOHD"]
        (self.n_mat, self.n_groups, self.n_portals, self.n_lights, self.n_models, self.n_doodads, self.n_sets,
         self.ambient, self.wmo_id) = struct.unpack_from("<9I", data, o)
        self.bbox = struct.unpack_from("<6f", data, o + 36)
        o, n = c["MOTX"]
        self.textures = strings(data[o:o + n])
        o, n = c["MOMT"]
        self.materials = [struct.unpack_from("<IIIIIIIIIIII4I", data, o + i * 64) for i in range(n // 64)]
        o, n = c["MOGI"]
        self.group_info = [struct.unpack_from("<I6fi", data, o + i * 32) for i in range(n // 32)]


class WMOGroup:
    def __init__(self, data):
        top = [t for t, _, _ in chunks(data)]
        assert top == ["MVER", "MOGP"], top
        o, n = chunk_map(data)["MOGP"]
        hdr = struct.unpack_from("<3I6f6H4BIIII", data, o)
        self.flags = hdr[2]
        self.bbox = hdr[3:9]
        self.n_batches = hdr[11]
        self.order = [t for t, _, _ in chunks(data, o + 0x44, o + n)]
        c = chunk_map(data, o + 0x44, o + n)

        def arr(tag, dt, width=1):
            co, cn = c[tag]
            a = np.frombuffer(data, dtype=dt, count=cn // np.dtype(dt).itemsize, offset=co)
            return a.reshape(-1, width) if width > 1 else a

        self.mopy = arr("MOPY", np.uint8, 2)
        self.indices = arr("MOVI", "<u2", 3)
        self.verts = arr("MOVT", "<f4", 3)
        self.normals = arr("MONR", "<f4", 3)
        self.uvs = arr("MOTV", "<f4", 2)
        co, cn = c["MOBA"]
        self.batches = [struct.unpack_from("<3h3hIHHHBB", data, co + i * 24) for i in range(cn // 24)]
        self.bsp = []
        self.bsp_refs = np.zeros(0, np.uint16)
        if "MOBN" in c:
            co, cn = c["MOBN"]
            self.bsp = [struct.unpack_from("<HhhHIf", data, co + i * 16) for i in range(cn // 16)]
            self.bsp_refs = arr("MOBR", "<u2")


class ADT:
    def __init__(self, data):
        self.order = [t for t, _, _ in chunks(data)]
        c = chunk_map(data)
        mh = c["MHDR"][0]
        self.mhdr = struct.unpack_from("<16I", data, mh)
        o, n = c["MCIN"]
        self.mcin = [struct.unpack_from("<IIII", data, o + i * 16) for i in range(256)]
        o, n = c["MTEX"]
        self.textures = list(strings(data[o:o + n]).values())
        o, n = c["MWMO"]
        self.wmo_names = strings(data[o:o + n])
        o, n = c["MWID"]
        self.mwid = list(struct.unpack_from(f"<{n // 4}I", data, o))
        o, n = c["MODF"]
        self.modf = [struct.unpack_from("<II3f3f3f3fHHHH", data, o + i * 64) for i in range(n // 64)]
        self.chunks = []
        for off, size, _, _ in self.mcin:
            assert data[off:off + 4] == b"KNCM", f"MCIN points at {data[off:off + 4]!r}"
            hdr = struct.unpack_from("<IIIIIIIIIIIIIIIHH16sIIIIII3fIII", data, off + 8)
            sub = {}
            for name, idx in (("MCVT", 5), ("MCNR", 6), ("MCLY", 7), ("MCRF", 8), ("MCAL", 9), ("MCSE", 20),
                              ("MCLQ", 22)):
                if hdr[idx]:
                    sub[name] = data[off + hdr[idx]:off + hdr[idx] + 4][::-1].decode("latin1")
            heights = np.frombuffer(data, "<f4", 145, off + hdr[5] + 8)
            self.chunks.append({"flags": hdr[0], "ix": hdr[1], "iy": hdr[2], "layers": hdr[3], "area": hdr[13],
                                "n_wmo": hdr[14], "pos": hdr[24:27], "sub": sub, "size": size,
                                "size_liquid": hdr[23], "heights": heights + hdr[26],
                                "zmin": float(heights.min() + hdr[26]), "zmax": float(heights.max() + hdr[26])})


class WDT:
    def __init__(self, data):
        self.order = [t for t, _, _ in chunks(data)]
        o, _ = chunk_map(data)["MAIN"]
        self.tiles = [(i % 64, i // 64) for i in range(4096) if struct.unpack_from("<I", data, o + i * 8)[0] & 1]


def collision_mesh(group):
    """Triangles (N,3,3) of a group that the client/server collide with."""
    keep = (group.mopy[:, 0] & 0x04) == 0
    return group.verts[group.indices[keep]]


def ray_down(tris, x, y, z_from=1e5):
    """Highest triangle z under (x, y) below z_from, or None."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    v0, v1 = b[:, :2] - a[:, :2], c[:, :2] - a[:, :2]
    p = np.array([x, y]) - a[:, :2]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    ok = np.abs(den) > 1e-9
    den = np.where(ok, den, 1)
    u = (p[:, 0] * v1[:, 1] - v1[:, 0] * p[:, 1]) / den
    v = (v0[:, 0] * p[:, 1] - p[:, 0] * v0[:, 1]) / den
    hit = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
    zs = a[:, 2] + u * (b[:, 2] - a[:, 2]) + v * (c[:, 2] - a[:, 2])
    zs = zs[hit & (zs <= z_from)]
    return float(zs.max()) if len(zs) else None


def walk(tris, path, start_z, step=2.0, max_rise=2.1):
    """Follow a polyline [(x, y), ...] on the collision floor starting at start_z.
    Returns [(x, y, floor_z)] per step; raises ValueError on a hole or a step higher than max_rise."""
    out = []
    prev = start_z
    for (x0, y0), (x1, y1) in zip(path[:-1], path[1:]):
        n = max(1, int(np.hypot(x1 - x0, y1 - y0) / step))
        for i in range(n + (1 if (x1, y1) == tuple(path[-1]) else 0)):
            x, y = x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n
            f = ray_down(tris, x, y, prev + max_rise + 2)
            if f is None:
                raise ValueError(f"hole at ({x:.1f}, {y:.1f})")
            if f - prev > max_rise:
                raise ValueError(f"step too high at ({x:.1f}, {y:.1f}): {prev:.1f} -> {f:.1f}")
            out.append((float(x), float(y), f))
            prev = f
    return out


def main(path):
    data = open(path, "rb").read()
    low = path.lower()
    if low.endswith(".wdt"):
        w = WDT(data)
        print(w.order, "tiles:", w.tiles)
    elif low.endswith(".adt"):
        a = ADT(data)
        print(a.order)
        print("textures:", a.textures, "wmos:", list(a.wmo_names.values()), "modf:", len(a.modf))
        print("z range:", min(c["zmin"] for c in a.chunks), max(c["zmax"] for c in a.chunks))
    elif low.endswith(".wmo"):
        try:
            g = WMOGroup(data)
            print(g.order, "flags %#x" % g.flags, "faces", len(g.mopy), "verts", len(g.verts), "bsp", len(g.bsp))
        except AssertionError:
            r = WMORoot(data)
            print(r.order)
            print("groups", r.n_groups, "materials", r.n_mat, "bbox", r.bbox)
            print("textures:", list(r.textures.values()))


if __name__ == "__main__":
    main(sys.argv[1])
