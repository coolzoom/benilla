"""Binary glTF (.glb) to wmo.Mesh: triangles, normals, first UV set and base-colour textures, nothing else.

Meshes are placed by their node transforms and converted from glTF's +Y-up to WoW's +Z-up. Each glTF material becomes
one texture (its base-colour image tinted by its base-colour factor, or a flat swatch of the factor); fit() scales and
moves the result so its footprint sits centred on a point.
"""
import io
import json
import math
import struct

import numpy as np
from PIL import Image

_COMPONENTS = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
# glTF (x, y, z) with +Y up and +Z toward the viewer -> WoW (x, y, z) with +Z up; a proper rotation (det +1).
_TO_WOW = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
MAX_TEXTURE = 1024


class Model:
    """Triangle soup in WoW axes with per-face glTF material index, plus each material's texture image."""

    def __init__(self, pos, nrm, uv, tris, face_mat, images, blends, names):
        self.pos, self.nrm, self.uv, self.tris, self.face_mat = pos, nrm, uv, tris, face_mat
        self.images, self.blends, self.names = images, blends, names


def _read_glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    magic, version, _ = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2, f"{path}: not a glTF 2 binary"
    ofs, doc, binary = 12, None, b""
    while ofs < len(data):
        size, kind = struct.unpack_from("<I4s", data, ofs)
        body = data[ofs + 8:ofs + 8 + size]
        if kind == b"JSON":
            doc = json.loads(body)
        elif kind == b"BIN\0":
            binary = body
        ofs += 8 + size
    return doc, binary


def _view(doc, binary, index):
    v = doc["bufferViews"][index]
    assert v.get("buffer", 0) == 0 and "uri" not in doc["buffers"][0], "only self-contained .glb files are read"
    start = v.get("byteOffset", 0)
    return binary[start:start + v["byteLength"]], v.get("byteStride")


def _accessor(doc, binary, index):
    a = doc["accessors"][index]
    dtype = np.dtype(_COMPONENTS[a["componentType"]])
    width = _WIDTH[a["type"]]
    count = a["count"]
    if "bufferView" not in a:
        return np.zeros((count, width), dtype=np.float32)
    raw, stride = _view(doc, binary, a["bufferView"])
    start = a.get("byteOffset", 0)
    item = dtype.itemsize * width
    if stride and stride != item:
        rows = np.frombuffer(raw, dtype=np.uint8, count=stride * (count - 1) + item, offset=start)
        rows = np.lib.stride_tricks.as_strided(rows, shape=(count, item), strides=(stride, 1))
        out = np.ascontiguousarray(rows).view(dtype).reshape(count, width)
    else:
        out = np.frombuffer(raw, dtype=dtype, count=count * width, offset=start).reshape(count, width)
    if a.get("normalized") and dtype.kind in "iu":
        out = out.astype(np.float32) / np.iinfo(dtype).max
    return out


def _matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    t = np.eye(4)
    t[:3, 3] = node.get("translation", (0, 0, 0))
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    r = np.eye(4)
    r[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    s = np.diag([*node.get("scale", (1, 1, 1)), 1.0])
    return t @ r @ s


def _pow2_size(n):
    return min(MAX_TEXTURE, 1 << max(3, math.ceil(math.log2(max(n, 1)) - 0.25)))


def _material_image(doc, binary, mat):
    pbr = mat.get("pbrMetallicRoughness", {})
    factor = np.array(pbr.get("baseColorFactor", (1, 1, 1, 1)), dtype=np.float32)
    tex = pbr.get("baseColorTexture")
    if tex is None and "emissiveTexture" in mat:
        # Some exports (Sketchfab's "shadeless" models) carry all their colour in the emissive map.
        tex, factor = mat["emissiveTexture"], np.ones(4, dtype=np.float32)
    if tex is None:
        rgba = tuple(int(round(c * 255)) for c in factor)
        return Image.new("RGBA", (8, 8), rgba)
    image = doc["images"][doc["textures"][tex["index"]]["source"]]
    raw, _ = _view(doc, binary, image["bufferView"])
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    img = img.resize((_pow2_size(img.width), _pow2_size(img.height)), Image.Resampling.LANCZOS)
    if not np.allclose(factor, 1.0):
        px = np.asarray(img, dtype=np.float32) * factor
        img = Image.fromarray(px.clip(0, 255).astype(np.uint8), "RGBA")
    return img


def load(path):
    doc, binary = _read_glb(path)
    pos, nrm, uv, tris, face_mat = [], [], [], [], []
    base = 0

    def visit(index, parent):
        nonlocal base
        node = doc["nodes"][index]
        world = parent @ _matrix(node)
        if "mesh" in node:
            linear = world[:3, :3]
            normal_m = np.linalg.inv(linear).T
            flip = np.linalg.det(linear) < 0
            for prim in doc["meshes"][node["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4:
                    continue
                attrs = prim["attributes"]
                p = _accessor(doc, binary, attrs["POSITION"]).astype(np.float64)
                n = len(p)
                idx = (_accessor(doc, binary, prim["indices"]).reshape(-1, 3).astype(np.int64)
                       if "indices" in prim else np.arange(n, dtype=np.int64).reshape(-1, 3))
                if flip:
                    idx = idx[:, ::-1]
                p = p @ linear.T + world[:3, 3]
                if "NORMAL" in attrs:
                    nn = _accessor(doc, binary, attrs["NORMAL"]).astype(np.float64) @ normal_m.T
                else:
                    nn = np.zeros_like(p)
                    fn = np.cross(p[idx[:, 1]] - p[idx[:, 0]], p[idx[:, 2]] - p[idx[:, 0]])
                    for k in range(3):
                        np.add.at(nn, idx[:, k], fn)
                nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-9)
                t = (_accessor(doc, binary, attrs["TEXCOORD_0"]).astype(np.float32) if "TEXCOORD_0" in attrs
                     else np.zeros((n, 2), dtype=np.float32))
                pos.append(p @ _TO_WOW.T)
                nrm.append(nn @ _TO_WOW.T)
                uv.append(t)
                tris.append(idx + base)
                face_mat.append(np.full(len(idx), prim.get("material", -1), dtype=np.int64))
                base += n
        for child in node.get("children", ()):
            visit(child, world)

    scene = doc["scenes"][doc.get("scene", 0)]
    for root in scene["nodes"]:
        visit(root, np.eye(4))
    assert pos, f"{path}: no triangle meshes"

    face_mat = np.concatenate(face_mat)
    used = sorted(set(face_mat.tolist()))
    materials = doc.get("materials", [])
    images, blends, names = [], [], []
    for m in used:
        mat = materials[m] if m >= 0 else {}
        images.append(_material_image(doc, binary, mat))
        blends.append(mat.get("alphaMode", "OPAQUE"))
        names.append(mat.get("name", f"m{m}"))
    remap = {m: i for i, m in enumerate(used)}
    return Model(np.concatenate(pos), np.concatenate(nrm), np.concatenate(uv), np.concatenate(tris),
                 np.array([remap[m] for m in face_mat.tolist()], dtype=np.int64), images, blends, names)


def select(model, drop=(), box=None):
    """Keep only the faces whose material isn't named in `drop` and whose centre lies in `box`, ((lo xyz), (hi xyz))
    as fractions of the model's bounding box; materials left with no faces go too."""
    lo, hi = model.pos.min(axis=0), model.pos.max(axis=0)
    keep = ~np.isin(model.face_mat, [i for i, n in enumerate(model.names) if n in drop])
    if box is not None:
        centre = (model.pos[model.tris].mean(axis=1) - lo) / np.maximum(hi - lo, 1e-9)
        keep &= np.all((centre >= np.array(box[0])) & (centre <= np.array(box[1])), axis=1)
    used = sorted(set(model.face_mat[keep].tolist()))
    remap = np.full(len(model.names), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    verts = np.unique(model.tris[keep])
    vmap = np.full(len(model.pos), -1, dtype=np.int64)
    vmap[verts] = np.arange(len(verts))
    model.pos, model.nrm, model.uv = model.pos[verts], model.nrm[verts], model.uv[verts]
    model.tris, model.face_mat = vmap[model.tris[keep]], remap[model.face_mat[keep]]
    model.images = [model.images[i] for i in used]
    model.blends = [model.blends[i] for i in used]
    model.names = [model.names[i] for i in used]
    return model


def fit(model, size, at, yaw_deg=0.0, axis="max"):
    """Scale so the model's `axis` extent ('x', 'y', 'z' or 'max') is `size` yards, turn it by yaw_deg about +Z, and
    put its footprint's centre at at[:2] with its lowest point at at[2]."""
    p = model.pos
    ext = p.max(axis=0) - p.min(axis=0)
    span = ext.max() if axis == "max" else ext["xyz".index(axis)]
    s = size / max(span, 1e-9)
    c, sn = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    r = np.array([[c, -sn, 0.0], [sn, c, 0.0], [0.0, 0.0, 1.0]])
    p = (p * s) @ r.T
    lo, hi = p.min(axis=0), p.max(axis=0)
    p += np.array([at[0] - (lo[0] + hi[0]) / 2, at[1] - (lo[1] + hi[1]) / 2, at[2] - lo[2]])
    model.pos = p
    model.nrm = model.nrm @ r.T
    return model
