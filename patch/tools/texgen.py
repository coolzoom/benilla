"""Procedural, seamlessly tiling textures (numpy) for original scene art. Each function returns a PIL RGBA image."""
import numpy as np
from PIL import Image


def noise(size, beta=2.0, seed=0):
    """Tileable 1/f^beta noise normalised to [0,1]."""
    rng = np.random.default_rng(seed)
    w = rng.standard_normal((size, size))
    f = np.fft.fftfreq(size)
    fx, fy = np.meshgrid(f, f, indexing="ij")
    r = np.sqrt(fx * fx + fy * fy)
    r[0, 0] = 1.0
    spec = np.fft.fft2(w) / r ** (beta / 2)
    spec[0, 0] = 0
    n = np.real(np.fft.ifft2(spec))
    n -= n.min()
    return n / max(n.max(), 1e-9)


def _grid(size):
    v = np.arange(size) / size
    return np.meshgrid(v, v, indexing="ij")  # (row, col) == (v, u)


def _rgba(rgb, alpha=None):
    rgb = np.clip(rgb, 0, 1)
    a = np.ones(rgb.shape[:2]) if alpha is None else np.clip(alpha, 0, 1)
    arr = np.dstack([rgb, a])
    return Image.fromarray((arr * 255).astype(np.uint8), "RGBA")


def _mix(c0, c1, t):
    t = t[..., None]
    return np.asarray(c0) * (1 - t) + np.asarray(c1) * t


def jade(size=512, seed=1):
    n = noise(size, 2.2, seed)
    veins = np.abs(np.sin((noise(size, 2.6, seed + 1) * 9.0) * np.pi))
    veins = 1 - np.clip(veins * 4, 0, 1)
    base = _mix((0.86, 0.85, 0.80), (0.97, 0.96, 0.92), n)
    base = base * (1 - 0.18 * veins[..., None]) + np.array([0.02, 0.03, 0.0]) * veins[..., None]
    return _rgba(base)


def jade_paving(size=512, seed=2, tiles=4):
    img = np.asarray(jade(size, seed), dtype=np.float64)[..., :3] / 255
    v, u = _grid(size)
    gu = np.abs(((u * tiles) % 1) - 0.5)
    gv = np.abs(((v * tiles) % 1) - 0.5)
    groove = np.clip((np.maximum(gu, gv) - 0.47) * 40, 0, 1)
    img = img * (1 - 0.35 * groove[..., None])
    return _rgba(img)


def gold(size=256, seed=3):
    n = noise(size, 1.8, seed)
    v, u = _grid(size)
    pattern = 0.5 + 0.5 * np.sin(u * 2 * np.pi * 8) * np.sin(v * 2 * np.pi * 8)
    base = _mix((0.62, 0.42, 0.10), (1.0, 0.82, 0.36), 0.6 * n + 0.4 * pattern)
    return _rgba(base)


def glazed_tile(size=256, seed=4, rows=8, cols=8):
    v, u = _grid(size)
    cu = (u * cols) % 1
    cv = (v * rows) % 1
    barrel = np.sin(cu * np.pi) ** 0.6
    lip = np.clip((cv - 0.88) * 12, 0, 1)
    n = noise(size, 2.0, seed)
    shade = 0.55 + 0.45 * barrel - 0.35 * lip + 0.08 * (n - 0.5)
    base = _mix((0.55, 0.32, 0.04), (1.0, 0.80, 0.25), np.clip(shade, 0, 1))
    return _rgba(base)


def red_lacquer(size=256, seed=5):
    n = noise(size, 2.4, seed)
    v, u = _grid(size)
    band = ((v > 0.06) & (v < 0.1)) | ((v > 0.9) & (v < 0.94))
    base = _mix((0.45, 0.04, 0.03), (0.72, 0.10, 0.06), n)
    base[band] = (0.95, 0.75, 0.30)
    return _rgba(base)


def stone(size=512, seed=6):
    n = noise(size, 2.0, seed)
    v, u = _grid(size)
    rows = 6
    cv = (v * rows) % 1
    row = np.floor(v * rows)
    cu = (u * 3 + 0.5 * (row % 2)) % 1
    mortar = np.clip((np.maximum(np.abs(cu - 0.5), np.abs(cv - 0.5)) - 0.46) * 30, 0, 1)
    base = _mix((0.70, 0.66, 0.60), (0.90, 0.87, 0.80), n)
    base = base * (1 - 0.4 * mortar[..., None])
    return _rgba(base)


def cloud(size=512, seed=7, alpha=False):
    n = noise(size, 2.8, seed)
    d = noise(size, 1.6, seed + 1)
    c = np.clip((n - 0.25) * 1.8 + 0.15 * (d - 0.5), 0, 1)
    rgb = _mix((0.62, 0.74, 0.86), (1.0, 0.97, 0.92), c)
    if alpha:
        return _rgba(rgb, np.clip((c - 0.2) * 1.6, 0, 1) ** 1.3)
    return _rgba(rgb)


def _smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def _puff(size, seed):
    """Cloud-puff density in [0,1] that reaches exactly 0 at the texture border (no visible card edges)."""
    v, u = _grid(size)
    r = np.sqrt((u - 0.5) ** 2 + (v - 0.5) ** 2) * 2
    n = noise(size, 2.4, seed)
    d = noise(size, 1.7, seed + 1)
    shape = (1 - r ** 1.5) * 1.3 + (n - 0.5) * 1.1 + (d - 0.5) * 0.3 - 0.2
    return np.clip(shape, 0, 1) * np.clip((1 - r) * 5, 0, 1), n


def cloud_puff(size=512, seed=27):
    """Sea-of-clouds puff: sunlit warm-white tops, cyan-blue shadowed body."""
    c, n = _puff(size, seed)
    rgb = _mix((0.62, 0.75, 0.88), (1.0, 0.96, 0.90), np.clip(c * 0.8 + 0.3 * n, 0, 1))
    return _rgba(rgb, _smooth(0.0, 0.7, c) * 0.45)


def cloud_rim(size=512, seed=37):
    """Backlit cloud for the sun side: cool grey-blue core, thin edges glowing amber (silver lining / rim light)."""
    c, n = _puff(size, seed)
    rim = (1 - _smooth(0.05, 0.6, c)) ** 1.3
    rgb = _mix((0.52, 0.62, 0.76), (1.0, 0.80, 0.48), np.clip(rim * 1.2 + 0.1 * n, 0, 1))
    return _rgba(rgb, _smooth(0.0, 0.6, c) * 0.5)


def beam(size=256, seed=41):
    """Volumetric light shaft (Tyndall effect) for additive crossed cards: u across, v along (v=0 at the sun end).

    Lengthwise streaks break the shaft into finer rays; it fades in from the cloud gap and softly out where it lands.
    """
    v, u = _grid(size)
    across = np.exp(-((u - 0.5) / 0.24) ** 2) * (1 - np.abs(2 * u - 1) ** 6)
    streak = noise(size, 1.3, seed)[size // 2]
    streak = 0.45 + 0.55 * (streak - streak.min()) / max(np.ptp(streak), 1e-9)
    along = _smooth(0.0, 0.3, v) * (1 - _smooth(0.6, 1.0, v)) * (1 - 0.35 * v)
    k = across * streak[None, :] * along
    rgb = np.ones((size, size, 3)) * np.array([1.0, 0.88, 0.62])
    return _rgba(rgb, k * 0.16)


def dragon_scale(size=256, seed=8, n_scales=8):
    v, u = _grid(size)
    su = (u * n_scales) % 1
    sv = (v * n_scales + 0.5 * (np.floor(u * n_scales) % 2)) % 1
    d = np.sqrt((su - 0.5) ** 2 + (sv - 0.2) ** 2)
    scale = np.clip(1 - d * 1.6, 0, 1)
    rim = np.clip((d - 0.42) * 12, 0, 1)
    n = noise(size, 2.0, seed)
    base = _mix((0.05, 0.32, 0.30), (0.25, 0.75, 0.62), scale * 0.8 + 0.2 * n)
    base = base * (1 - rim[..., None]) + np.array([1.0, 0.78, 0.30]) * rim[..., None]
    return _rgba(base)


def feather(size=256, seed=9):
    v, u = _grid(size)
    n = noise(size, 1.5, seed)
    barbs = 0.5 + 0.5 * np.sin((u * 40 + v * 6) * np.pi)
    grad = _mix((0.85, 0.12, 0.05), (1.0, 0.78, 0.22), np.clip(v * 1.2, 0, 1))
    base = grad * (0.8 + 0.2 * barbs[..., None]) * (0.9 + 0.1 * n[..., None])
    return _rgba(base)


def deity(size=512, seed=10):
    """Faint translucent golden glow used on the giant silhouette; fades toward the edges."""
    v, u = _grid(size)
    n = noise(size, 2.6, seed)
    edge = np.clip(np.minimum.reduce([u, 1 - u, v, 1 - v]) * 6, 0, 1)
    k = (0.35 + 0.45 * n) * edge * (0.4 + 0.6 * (1 - v))
    rgb = _mix((1.0, 0.78, 0.45), (1.0, 0.95, 0.82), n)
    return _rgba(rgb, k * 0.35)


def waterfall(size=256, seed=11):
    rng = np.random.default_rng(seed)
    v, u = _grid(size)
    streak = np.zeros((size, size))
    for _ in range(40):
        c = rng.random()
        w = 0.004 + rng.random() * 0.02
        streak += np.exp(-((((u - c + 0.5) % 1) - 0.5) / w) ** 2) * (0.4 + 0.6 * rng.random())
    n = noise(size, 1.2, seed)
    k = np.clip(streak * 0.6 + 0.3 * n, 0, 1)
    rgb = _mix((0.70, 0.82, 0.92), (1.0, 1.0, 1.0), k)
    return _rgba(rgb, 0.15 + 0.4 * k)


def foliage(size=256, seed=12):
    n = noise(size, 1.4, seed)
    m = noise(size, 2.4, seed + 1)
    base = _mix((0.10, 0.26, 0.12), (0.32, 0.52, 0.22), np.clip(n * 0.7 + m * 0.3, 0, 1))
    return _rgba(base)


def rock(size=256, seed=13):
    n = noise(size, 1.9, seed)
    m = noise(size, 2.8, seed + 1)
    base = _mix((0.36, 0.34, 0.32), (0.66, 0.62, 0.56), np.clip(n * 0.6 + m * 0.4, 0, 1))
    return _rgba(base)
