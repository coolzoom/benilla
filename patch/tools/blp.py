"""BLP2 writer in the two encodings stock 1.12.1 data uses.

Opaque textures are DXT1 (compression 2, alpha depth 0, alpha type 0), the bulk of texture.MPQ. Translucent textures
are palettized (compression 1, alpha depth 8, alpha type 8), as on the item texture components: soft alpha gradients
(light shafts, cloud puffs) keep all 256 alpha levels, which DXT3's 4-bit alpha would band.
"""
import struct

import numpy as np
from PIL import Image

HEADER_SIZE = 20 + 64 + 64
PALETTE_SIZE = 1024


def _pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def _levels(img, mips):
    out = [img]
    while mips and (out[-1].size != (1, 1)) and len(out) < 16:
        w, h = out[-1].size
        out.append(out[-1].resize((max(1, w // 2), max(1, h // 2)), Image.Resampling.BOX))
    return out


def _rgb565(c):
    c = np.clip(np.rint(c), 0, 255).astype(np.int32)
    return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)


def _expand565(v):
    r = (v >> 11) & 31
    g = (v >> 5) & 63
    b = v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], axis=-1).astype(np.float32)


def dxt1(rgb):
    """(H, W, 3) uint8 -> DXT1 blocks. Endpoints span each block's principal colour axis; four-colour mode only."""
    h, w = rgb.shape[:2]
    ph, pw = max(4, (h + 3) // 4 * 4), max(4, (w + 3) // 4 * 4)
    a = np.zeros((ph, pw, 3), np.float32)
    a[:h, :w] = rgb
    if h < ph:
        a[h:, :w] = a[h - 1:h, :w]
    if w < pw:
        a[:, w:] = a[:, w - 1:w]
    blocks = a.reshape(ph // 4, 4, pw // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)
    mean = blocks.mean(axis=1, keepdims=True)
    d = blocks - mean
    cov = np.einsum("nki,nkj->nij", d, d)
    axis = np.ones((len(blocks), 3), np.float32)
    for _ in range(8):
        axis = np.einsum("nij,nj->ni", cov, axis)
        axis /= np.maximum(np.linalg.norm(axis, axis=1, keepdims=True), 1e-6)
    t = np.einsum("nki,ni->nk", d, axis)
    lo = mean[:, 0] + axis * t.min(axis=1, keepdims=True)
    hi = mean[:, 0] + axis * t.max(axis=1, keepdims=True)
    c0, c1 = _rgb565(hi), _rgb565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    p0, p1 = _expand565(c0), _expand565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=1)
    idx = np.argmin(((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1), axis=2)
    idx[c0 == c1] = 0
    bits = (idx.astype(np.uint32) << (2 * np.arange(16, dtype=np.uint32))).sum(axis=1, dtype=np.uint64)
    out = np.zeros(len(blocks), dtype=[("c0", "<u2"), ("c1", "<u2"), ("i", "<u4")])
    out["c0"], out["c1"], out["i"] = c0, c1, bits.astype(np.uint32)
    return out.tobytes()


def _palettize(levels):
    rgb0 = levels[0].convert("RGB")
    pal_img = rgb0.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = np.zeros((256, 4), np.uint8)
    p = np.array(pal_img.getpalette()[:768], np.uint8).reshape(-1, 3)
    palette[:len(p), :3] = p[:, ::-1]   # BGRA
    data = []
    for lv in levels:
        q = lv.convert("RGB").quantize(palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG)
        idx = np.asarray(q, np.uint8)
        alpha = np.asarray(lv, np.uint8)[..., 3]
        data.append(idx.tobytes() + alpha.tobytes())
    return palette.tobytes(), data


def encode(img, alpha=True, mips=True):
    img = img.convert("RGBA")
    w, h = img.size
    assert w == _pow2(w) and h == _pow2(h), f"BLP size must be power of two, got {w}x{h}"
    levels = _levels(img, mips)
    if alpha:
        palette, data = _palettize(levels)
        hdr = struct.pack("<4sIBBBBII", b"BLP2", 1, 1, 8, 8, 1 if mips else 0, w, h)
    else:
        palette = b"\0" * PALETTE_SIZE
        data = [dxt1(np.asarray(lv.convert("RGB"), np.uint8)) for lv in levels]
        hdr = struct.pack("<4sIBBBBII", b"BLP2", 1, 2, 0, 0, 1 if mips else 0, w, h)
    offsets, sizes, off = [], [], HEADER_SIZE + PALETTE_SIZE
    for lv in data:
        offsets.append(off)
        sizes.append(len(lv))
        off += len(lv)
    offsets += [0] * (16 - len(offsets))
    sizes += [0] * (16 - len(sizes))
    return hdr + struct.pack("<16I", *offsets) + struct.pack("<16I", *sizes) + palette + b"".join(data)


def _undxt1(data, w, h):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    b = np.frombuffer(data, dtype=[("c0", "<u2"), ("c1", "<u2"), ("i", "<u4")], count=bw * bh)
    c0, c1 = b["c0"].astype(np.int32), b["c1"].astype(np.int32)
    p0, p1 = _expand565(c0), _expand565(c1)
    four = (c0 > c1)[:, None]
    p2 = np.where(four, (2 * p0 + p1) / 3, (p0 + p1) / 2)
    p3 = np.where(four, (p0 + 2 * p1) / 3, 0)
    pal = np.stack([p0, p1, p2, p3], axis=1)
    idx = (b["i"][:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    px = np.take_along_axis(pal, idx[..., None].astype(np.int64).repeat(3, -1), axis=1)
    img = px.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 3)[:h, :w]
    return np.dstack([img, np.full((h, w), 255.0)]).astype(np.uint8)


def decode(data):
    """Top mip as a PIL RGBA image; reads the two encodings encode() writes (used by tests)."""
    magic, ver, enc, abits, atype, mips, w, h = struct.unpack_from("<4sIBBBBII", data)
    assert magic == b"BLP2" and ver == 1
    off, size = struct.unpack_from("<I", data, 20)[0], struct.unpack_from("<I", data, 84)[0]
    lv = data[off:off + size]
    if enc == 2:
        return Image.fromarray(_undxt1(lv, w, h), "RGBA")
    assert enc == 1 and abits == 8
    pal = np.frombuffer(data, np.uint8, PALETTE_SIZE, HEADER_SIZE).reshape(256, 4)
    idx = np.frombuffer(lv, np.uint8, w * h).reshape(h, w)
    a = np.frombuffer(lv, np.uint8, w * h, w * h).reshape(h, w)
    rgb = pal[idx][..., [2, 1, 0]]
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")
