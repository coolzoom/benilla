"""Procedural mesh primitives producing wmo.Mesh objects (world units = yards, Z up)."""
import math

import numpy as np

from wmo import Mesh, POLY_RENDER


def _n(v):
    v = np.asarray(v, dtype=np.float64)
    l = np.linalg.norm(v)
    return v / l if l > 1e-9 else np.array([0.0, 0.0, 1.0])


def quad(m, p0, p1, p2, p3, mat, uv=((0, 0), (1, 0), (1, 1), (0, 1)), flags=POLY_RENDER, normal=None):
    """Counter-clockwise quad seen from the front."""
    n = normal if normal is not None else _n(np.cross(np.subtract(p1, p0), np.subtract(p3, p0)))
    i = [m.add_vertex(tuple(map(float, p)), tuple(map(float, n)), uv[k]) for k, p in enumerate((p0, p1, p2, p3))]
    m.add_tri(i[0], i[1], i[2], mat, flags)
    m.add_tri(i[0], i[2], i[3], mat, flags)


def box(m, lo, hi, mat, uv_scale=0.1, flags=POLY_RENDER, skip_bottom=False):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    s = uv_scale
    faces = [
        ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x1 - x0, y1 - y0)),   # top
        ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (x1 - x0, z1 - z0)),   # -y
        ((x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1 - x0, z1 - z0)),   # +y
        ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1), (y1 - y0, z1 - z0)),   # +x
        ((x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (y1 - y0, z1 - z0)),   # -x
    ]
    if not skip_bottom:
        faces.append(((x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0), (x1 - x0, y1 - y0)))
    for a, b, c, d, (w, h) in faces:
        quad(m, a, b, c, d, mat, uv=((0, 0), (w * s, 0), (w * s, h * s), (0, h * s)), flags=flags)


def grid_surface(m, fn, nu, nv, mat, flags=POLY_RENDER, uv_fn=None, closed_u=False):
    """fn(u, v) -> xyz for u,v in [0,1]; builds (nu x nv) quads with smooth normals."""
    us = np.linspace(0, 1, nu + 1)
    vs = np.linspace(0, 1, nv + 1)
    P = np.array([[fn(u, v) for v in vs] for u in us], dtype=np.float64)
    du = np.gradient(P, axis=0)
    dv = np.gradient(P, axis=1)
    if closed_u:
        du[0] = du[-1] = (P[1] - P[-2])
    N = np.cross(du, dv)
    N /= np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-9)
    idx = np.zeros((nu + 1, nv + 1), dtype=np.int64)
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            uv = uv_fn(u, v) if uv_fn else (u, v)
            idx[i, j] = m.add_vertex(tuple(P[i, j]), tuple(N[i, j]), (float(uv[0]), float(uv[1])))
    for i in range(nu):
        for j in range(nv):
            a, b, c, d = idx[i, j], idx[i + 1, j], idx[i + 1, j + 1], idx[i, j + 1]
            m.add_tri(a, b, c, mat, flags)
            m.add_tri(a, c, d, mat, flags)


def cylinder(m, center, radius, z0, z1, mat, seg=16, flags=POLY_RENDER, cap=True, uv_rep=(1, 1)):
    cx, cy = center

    def f(u, v):
        a = u * 2 * math.pi
        return (cx + radius * math.cos(a), cy + radius * math.sin(a), z0 + (z1 - z0) * v)
    grid_surface(m, f, seg, 1, mat, flags, uv_fn=lambda u, v: (u * uv_rep[0], v * uv_rep[1]), closed_u=True)
    if cap:
        disc(m, (cx, cy, z1), radius, mat, seg, flags)


def disc(m, c, r, mat, seg=24, flags=POLY_RENDER, up=True):
    ci = m.add_vertex(tuple(c), (0, 0, 1 if up else -1), (0.5, 0.5))
    ring = []
    for k in range(seg + 1):
        a = 2 * math.pi * k / seg
        ring.append(m.add_vertex((c[0] + r * math.cos(a), c[1] + r * math.sin(a), c[2]), (0, 0, 1 if up else -1),
                                 (0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a))))
    for k in range(seg):
        if up:
            m.add_tri(ci, ring[k], ring[k + 1], mat, flags)
        else:
            m.add_tri(ci, ring[k + 1], ring[k], mat, flags)


def torus_arc(m, center, axis_dir, R, r, a0, a1, mat, seg=48, rseg=12, flags=POLY_RENDER, uv_rep=(8, 1)):
    """Ring in the vertical plane spanned by axis_dir (horizontal) and Z; angles in radians from +axis_dir."""
    cx, cy, cz = center
    ax = _n((axis_dir[0], axis_dir[1], 0))
    side = np.array([-ax[1], ax[0], 0.0])

    def f(u, v):
        a = a0 + (a1 - a0) * u
        b = v * 2 * math.pi
        ring_c = np.array([cx, cy, cz]) + R * (math.cos(a) * ax + math.sin(a) * np.array([0, 0, 1.0]))
        radial = math.cos(a) * ax + math.sin(a) * np.array([0, 0, 1.0])
        return tuple(ring_c + r * (math.cos(b) * radial + math.sin(b) * side))
    grid_surface(m, f, seg, rseg, mat, flags, uv_fn=lambda u, v: (u * uv_rep[0], v * uv_rep[1]))


def sweep(m, path, radius_fn, mat, rseg=12, flags=POLY_RENDER, uv_rep=(20, 1), squash=1.0):
    """Tube along a polyline path (Nx3); radius_fn(t) with t in [0,1]."""
    path = np.asarray(path, dtype=np.float64)
    n = len(path)
    T = np.gradient(path, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    ref = np.array([0, 0, 1.0])
    frames = []
    for i in range(n):
        b = np.cross(T[i], ref)
        if np.linalg.norm(b) < 1e-3:
            b = np.cross(T[i], np.array([1.0, 0, 0]))
        b = _n(b)
        nn = np.cross(b, T[i])
        frames.append((nn, b))

    def f(u, v):
        i = min(int(round(u * (n - 1))), n - 1)
        nn, b = frames[i]
        a = v * 2 * math.pi
        r = radius_fn(u)
        return tuple(path[i] + r * (math.cos(a) * nn * squash + math.sin(a) * b))
    grid_surface(m, f, n - 1, rseg, mat, flags, uv_fn=lambda u, v: (u * uv_rep[0], v * uv_rep[1]))


def extrude_polygon(m, pts2d, origin, u_axis, v_axis, thickness, mat, flags=POLY_RENDER, uv_scale=None,
                    side_mat=None):
    """Extrude a simple polygon (list of (u,v)) laid out in the plane origin + u*u_axis + v*v_axis."""
    pts = np.asarray(pts2d, dtype=np.float64)
    o = np.asarray(origin, dtype=np.float64)
    U = np.asarray(u_axis, dtype=np.float64)
    V = np.asarray(v_axis, dtype=np.float64)
    N = _n(np.cross(U, V))
    mn = pts.min(axis=0)
    span = np.maximum(pts.max(axis=0) - mn, 1e-6)
    tris = _ear_clip(pts)
    for sgn in (1, -1):
        off = N * thickness * 0.5 * sgn
        ids = []
        for p in pts:
            uv = (p - mn) / span if uv_scale is None else p * uv_scale
            ids.append(m.add_vertex(tuple(o + p[0] * U + p[1] * V + off), tuple(N * sgn), (float(uv[0]),
                                                                                          float(1 - uv[1]))))
        for a, b, c in tris:
            if sgn > 0:
                m.add_tri(ids[a], ids[b], ids[c], mat, flags)
            else:
                m.add_tri(ids[a], ids[c], ids[b], mat, flags)
    sm = mat if side_mat is None else side_mat
    k = len(pts)
    for i in range(k):
        p, q = pts[i], pts[(i + 1) % k]
        a = o + p[0] * U + p[1] * V
        b = o + q[0] * U + q[1] * V
        h = N * thickness * 0.5
        quad(m, a - h, b - h, b + h, a + h, sm, flags=flags)


def _ear_clip(pts):
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    idx = list(range(n)) if area > 0 else list(range(n))[::-1]
    out = []

    def inside(p, a, b, c):
        def s(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
        d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 0:
                continue
            if any(inside(pts[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            out.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        out.append(tuple(idx))
    if area <= 0:
        out = [(c, b, a) for a, b, c in out]
    return out


def billboard(m, center, width, height, facing, mat, flags=0x04 | POLY_RENDER):
    """Vertical quad centred at center facing direction `facing` (xy)."""
    f = _n((facing[0], facing[1], 0))
    side = np.array([-f[1], f[0], 0.0])
    c = np.asarray(center, dtype=np.float64)
    hw = side * width / 2
    hh = np.array([0, 0, height / 2])
    quad(m, c - hw - hh, c + hw - hh, c + hw + hh, c - hw + hh, mat, uv=((0, 1), (1, 1), (1, 0), (0, 0)),
         flags=flags, normal=f)


def hip_roof(m, center, w, d, z, h, overhang, mat, curl=0.35, seg=8, flags=POLY_RENDER, uv_rep=6):
    """Chinese hip roof with concave slopes and upturned corners (xu: width along x, d along y)."""
    cx, cy = center
    W = w / 2 + overhang
    D = d / 2 + overhang
    r = max(W - D, W * 0.15)
    sides = [
        (((W, D), (-W, D)), ((r, 0), (-r, 0))),
        (((-W, D), (-W, -D)), ((-r, 0), (-r, 0))),
        (((-W, -D), (W, -D)), ((-r, 0), (r, 0))),
        (((W, -D), (W, D)), ((r, 0), (r, 0))),
    ]
    for (e0, e1), (r0, r1) in sides:
        def f(u, v, e0=e0, e1=e1, r0=r0, r1=r1):
            ex, ey = e0[0] + (e1[0] - e0[0]) * u, e0[1] + (e1[1] - e0[1]) * u
            rx, ry = r0[0] + (r1[0] - r0[0]) * u, r0[1] + (r1[1] - r0[1]) * u
            corner = (abs(2 * u - 1) ** 4) * (1 - v) ** 2
            return (cx + ex + (rx - ex) * v, cy + ey + (ry - ey) * v, z + h * (v ** 1.7) + curl * h * corner)
        grid_surface(m, f, seg, seg, mat, flags, uv_fn=lambda u, v: (u * uv_rep, v * uv_rep * 0.5))


def spline(points, n):
    """Catmull-Rom spline through points, n samples."""
    P = np.asarray(points, dtype=np.float64)
    P = np.vstack([P[0], P, P[-1]])
    out = []
    segs = len(P) - 3
    for k in range(n):
        t = k / (n - 1) * segs
        i = min(int(t), segs - 1)
        s = t - i
        p0, p1, p2, p3 = P[i], P[i + 1], P[i + 2], P[i + 3]
        out.append(0.5 * ((2 * p1) + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s * s +
                          (-p0 + 3 * p1 - 3 * p2 + p3) * s ** 3))
    return np.array(out)


def transform(mesh, offset=(0, 0, 0), yaw_deg=0.0, scale=1.0):
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    out = Mesh()
    for p, n, uv in zip(mesh.pos, mesh.nrm, mesh.uv):
        x, y, z = p[0] * scale, p[1] * scale, p[2] * scale
        out.add_vertex((x * c - y * s + offset[0], x * s + y * c + offset[1], z + offset[2]),
                       (n[0] * c - n[1] * s, n[0] * s + n[1] * c, n[2]), uv)
    out.faces = list(mesh.faces)
    return out
