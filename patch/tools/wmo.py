"""v17 WMO writer (1.12 shares the format): exterior groups with batches, BSP collision tree, no portals/doodads.

Chunk order and struct sizes match stock 1.12.1 ElwynnLionBridge.wmo (patch/ref/bridge*.wmo), benilla-wmo and the
vmangos vmap extractor (contrib/vmap_extractor/vmapextract/wmo.cpp).
"""
import struct

import numpy as np

# MOMT flags
F_UNLIT = 0x01
F_UNFOGGED = 0x02
F_TWOSIDED = 0x04
F_EXTLIGHT = 0x08
F_SIDN = 0x10
F_CLAMP_S = 0x40
F_CLAMP_T = 0x80

# blend modes (EGxBlend)
BLEND_OPAQUE = 0
BLEND_ALPHAKEY = 1
BLEND_ALPHA = 2
BLEND_ADD = 3

# MOPY flags
POLY_DETAIL = 0x04       # not collidable (server vmap extractor and client both skip it)
POLY_COLLIDE = 0x08
POLY_RENDER = 0x20

GROUP_BSP = 0x1
GROUP_EXTERIOR = 0x8
GROUP_EXT_UNK = 0x8000   # set on every exterior group in Blizzard data

MAX_LEAF_FACES = 96


def chunk(tag, data):
    return struct.pack("<4sI", tag[::-1].encode(), len(data)) + data


class Material:
    def __init__(self, texture, flags=0, blend=BLEND_OPAQUE, shader=0, emissive=0xFF000000, diffuse=0xFF7F7F7F,
                 texture2=""):
        self.texture = texture
        self.texture2 = texture2
        self.flags = flags
        self.blend = blend
        self.shader = shader
        self.emissive = emissive
        self.diffuse = diffuse


class Mesh:
    """Triangle soup with per-vertex attributes; faces carry material index and MOPY flags."""

    def __init__(self):
        self.pos = []
        self.nrm = []
        self.uv = []
        self.faces = []  # (a, b, c, material, polyflags)

    def add_vertex(self, p, n, uv):
        self.pos.append(p)
        self.nrm.append(n)
        self.uv.append(uv)
        return len(self.pos) - 1

    def add_tri(self, a, b, c, mat, flags=POLY_RENDER):
        self.faces.append((a, b, c, mat, flags))

    def extend(self, other):
        base = len(self.pos)
        self.pos += other.pos
        self.nrm += other.nrm
        self.uv += other.uv
        self.faces += [(a + base, b + base, c + base, m, f) for a, b, c, m, f in other.faces]


def _bsp(verts, tris, face_ids, box_min, box_max, nodes, refs, depth=0):
    idx = len(nodes)
    nodes.append(None)
    if len(face_ids) <= MAX_LEAF_FACES or depth >= 24:
        nodes[idx] = (4, 0xFFFF, 0xFFFF, len(face_ids), len(refs), 0.0)
        refs.extend(face_ids)
        return idx
    ext = box_max - box_min
    axis = int(np.argmax(ext))
    tri_min = verts[tris[face_ids]].min(axis=1)[:, axis]
    tri_max = verts[tris[face_ids]].max(axis=1)[:, axis]
    split = float(np.median((tri_min + tri_max) * 0.5))
    if not (box_min[axis] < split < box_max[axis]):
        split = float((box_min[axis] + box_max[axis]) * 0.5)
    neg = [f for f, lo in zip(face_ids, tri_min) if lo <= split]
    pos = [f for f, hi in zip(face_ids, tri_max) if hi >= split]
    if len(neg) == len(face_ids) and len(pos) == len(face_ids):
        nodes[idx] = (4, 0xFFFF, 0xFFFF, len(face_ids), len(refs), 0.0)
        refs.extend(face_ids)
        return idx
    neg_max = box_max.copy()
    neg_max[axis] = split
    pos_min = box_min.copy()
    pos_min[axis] = split
    n_child = _bsp(verts, tris, neg, box_min, neg_max, nodes, refs, depth + 1) if neg else 0xFFFF
    p_child = _bsp(verts, tris, pos, pos_min, box_max, nodes, refs, depth + 1) if pos else 0xFFFF
    nodes[idx] = (axis, n_child, p_child, 0, 0, split)
    return idx


class Group:
    def __init__(self, name, mesh):
        self.name = name
        self.mesh = mesh

    def build(self, group_name_ofs):
        m = self.mesh
        order = sorted(range(len(m.faces)), key=lambda i: m.faces[i][3])
        # Re-emit vertices per batch so every batch owns a contiguous vertex range.
        pos, nrm, uv, idx, polys, batches = [], [], [], [], [], []
        cur_mat, remap, b_start, v_start = None, {}, 0, 0
        for fi in order:
            a, b, c, mat, flags = m.faces[fi]
            if mat != cur_mat:
                if cur_mat is not None:
                    batches.append((b_start, len(idx) - b_start, v_start, len(pos) - 1, cur_mat))
                cur_mat, remap, b_start, v_start = mat, {}, len(idx), len(pos)
            for v in (a, b, c):
                if v not in remap:
                    remap[v] = len(pos)
                    pos.append(m.pos[v])
                    nrm.append(m.nrm[v])
                    uv.append(m.uv[v])
                idx.append(remap[v])
            polys.append((flags, mat))
        if cur_mat is not None:
            batches.append((b_start, len(idx) - b_start, v_start, len(pos) - 1, cur_mat))
        assert len(pos) < 65536, f"group {self.name} has {len(pos)} vertices; split it"

        verts = np.array(pos, dtype=np.float32).reshape(-1, 3)
        tris = np.array(idx, dtype=np.int64).reshape(-1, 3)
        bmin, bmax = verts.min(axis=0), verts.max(axis=0)
        self.bmin, self.bmax = bmin, bmax

        collidable = [i for i, (fl, _) in enumerate(polys) if not (fl & POLY_DETAIL)]
        nodes, refs = [], []
        if collidable:
            _bsp(verts, tris, collidable, bmin.astype(np.float64) - 0.01, bmax.astype(np.float64) + 0.01, nodes,
                 refs)
        else:
            nodes = [(4, 0xFFFF, 0xFFFF, 0, 0, 0.0)]

        mopy = b"".join(struct.pack("<BB", fl, mt) for fl, mt in polys)
        movi = struct.pack(f"<{len(idx)}H", *idx)
        movt = verts.tobytes()
        monr = np.array(nrm, dtype=np.float32).tobytes()
        motv = np.array(uv, dtype=np.float32).tobytes()
        moba = b""
        for start, count, vmin, vmax, mat in batches:
            bv = verts[vmin:vmax + 1]
            lo = np.floor(bv.min(axis=0)).clip(-32768, 32767).astype(int)
            hi = np.ceil(bv.max(axis=0)).clip(-32768, 32767).astype(int)
            moba += struct.pack("<3h3hIHHHBB", *lo, *hi, start, count, vmin, vmax, 0, mat)
        mobn = b"".join(struct.pack("<HHHHIf", *n) for n in nodes)
        mobr = struct.pack(f"<{len(refs)}H", *refs)

        self.flags = GROUP_BSP | GROUP_EXTERIOR | GROUP_EXT_UNK
        body = (chunk("MOPY", mopy) + chunk("MOVI", movi) + chunk("MOVT", movt) + chunk("MONR", monr) +
                chunk("MOTV", motv) + chunk("MOBA", moba) + chunk("MOBN", mobn) + chunk("MOBR", mobr))
        header = struct.pack("<3I6f6H4BIIII", group_name_ofs, 0, self.flags, *bmin, *bmax, 0, 0, 0, 0,
                             len(batches), 0, 0, 0, 0, 0, 0, 0, 0, 0)
        assert len(header) == 0x44
        return chunk("MVER", struct.pack("<I", 17)) + chunk("MOGP", header + body)


def split_groups(name, mesh, max_verts=60000):
    """Split a mesh into Groups that each stay under the 16-bit index limit."""
    groups, cur, remap = [], Mesh(), {}
    for a, b, c, mat, fl in mesh.faces:
        if len(cur.pos) + 3 > max_verts:
            groups.append(Group(f"{name}_{len(groups)}", cur))
            cur, remap = Mesh(), {}
        ids = []
        for v in (a, b, c):
            if v not in remap:
                remap[v] = cur.add_vertex(mesh.pos[v], mesh.nrm[v], mesh.uv[v])
            ids.append(remap[v])
        cur.add_tri(*ids, mat, fl)
    if cur.faces:
        groups.append(Group(f"{name}_{len(groups)}", cur))
    return groups


def build(materials, groups, wmo_id=0, ambient=0xFF202020):
    """Returns {suffix: bytes}: '' for the root file and '_000'.. for groups."""
    motx = bytearray()
    tex_ofs = {}

    def tex(name):
        if name not in tex_ofs:
            tex_ofs[name] = len(motx)
            raw = name.encode() + b"\0"
            raw += b"\0" * ((4 - len(raw) % 4) % 4)
            motx.extend(raw)
        return tex_ofs[name]

    momt = b""
    for m in materials:
        t1 = tex(m.texture)
        t2 = tex(m.texture2) if m.texture2 else 0
        momt += struct.pack("<IIIIIIIIIIII4I", m.flags, m.shader, m.blend, t1, m.emissive, 0, t2, m.diffuse, 0, 0,
                            0, 0, 0, 0, 0, 0)

    mogn = bytearray(b"\0\0")
    files = {}
    infos = []
    gmin = np.array([1e9] * 3)
    gmax = np.array([-1e9] * 3)
    for i, g in enumerate(groups):
        ofs = len(mogn)
        mogn += g.name.encode() + b"\0"
        files[f"_{i:03d}"] = g.build(ofs)
        infos.append((g.flags & ~GROUP_BSP, g.bmin, g.bmax, ofs))
        gmin = np.minimum(gmin, g.bmin)
        gmax = np.maximum(gmax, g.bmax)
    mogn += b"\0" * ((4 - len(mogn) % 4) % 4)
    mogi = b"".join(struct.pack("<I6fi", fl, *lo, *hi, ofs) for fl, lo, hi, ofs in infos)
    self_bbox = (*gmin, *gmax)

    mohd = struct.pack("<7III6fHH", len(materials), len(groups), 0, 0, 0, 0, 1, ambient, wmo_id, *self_bbox, 0, 0)
    mods = struct.pack("<20sIII", b"Set_$DefaultGlobal", 0, 0, 0)
    mfog = struct.pack("<I3fff", 0, 0, 0, 0, 0, 0) + struct.pack("<ffI", 444.4445, 0.25, 0xFF000000) + \
        struct.pack("<ffI", 222.2222, -0.5, 0xFF000000)
    root = (chunk("MVER", struct.pack("<I", 17)) + chunk("MOHD", mohd) + chunk("MOTX", bytes(motx)) +
            chunk("MOMT", momt) + chunk("MOGN", bytes(mogn)) + chunk("MOGI", mogi) + chunk("MOSB", b"\0" * 4) +
            chunk("MOPV", b"") + chunk("MOPT", b"") + chunk("MOPR", b"") + chunk("MOVV", b"") + chunk("MOVB", b"") +
            chunk("MOLT", b"") + chunk("MODS", mods) + chunk("MODN", b"") + chunk("MODD", b"") +
            chunk("MFOG", mfog))
    files[""] = root
    return files, (gmin, gmax)
