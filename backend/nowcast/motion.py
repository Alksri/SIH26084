"""Storm motion estimation and semi-Lagrangian advection.

Motion vectors come from tile-wise FFT phase correlation between successive
fused reflectivity composites and between successive (parallax-corrected)
IR images, so motion is still known where radar coverage is missing.
Sparse tile vectors are spread to a dense field with Gaussian-weighted
interpolation, blended with a background (previous field / steering flow),
and smoothed in time.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

TILE = 48
STRIDE = 24


def _phase_corr_shift(a: np.ndarray, b: np.ndarray):
    """Shift (di, dj) such that b(x) ~= a(x - d). Returns (di, dj, peak)."""
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])).astype(np.float32)
    fa = np.fft.fft2((a - a.mean()) * win)
    fb = np.fft.fft2((b - b.mean()) * win)
    r = fb * np.conj(fa)
    r /= np.abs(r) + 1e-9
    c = np.real(np.fft.ifft2(r))
    k = int(np.argmax(c))
    pi, pj = divmod(k, c.shape[1])
    peak = float(c[pi, pj])

    def sub(cm, c0, cp):
        den = cm - 2 * c0 + cp
        return 0.0 if abs(den) < 1e-9 else 0.5 * (cm - cp) / den

    n0, n1 = c.shape
    di = pi + sub(c[(pi - 1) % n0, pj], c[pi, pj], c[(pi + 1) % n0, pj])
    dj = pj + sub(c[pi, (pj - 1) % n1], c[pi, pj], c[pi, (pj + 1) % n1])
    if di > n0 / 2:
        di -= n0
    if dj > n1 / 2:
        dj -= n1
    return di, dj, peak


def tile_vectors(prev: np.ndarray, curr: np.ndarray, dt_min: float, max_cells_per_min: float,
                 min_frac: float = 0.03, min_peak: float = 0.06):
    """Sparse motion vectors (ci, cj, vi, vj, weight) from two feature images (>0 = signal)."""
    ny, nx = curr.shape
    out = []
    for i0 in range(0, ny - TILE + 1, STRIDE):
        for j0 in range(0, nx - TILE + 1, STRIDE):
            a = prev[i0:i0 + TILE, j0:j0 + TILE]
            b = curr[i0:i0 + TILE, j0:j0 + TILE]
            fa, fb = (a > 0).mean(), (b > 0).mean()
            if fa < min_frac or fb < min_frac:
                continue
            di, dj, peak = _phase_corr_shift(a, b)
            if peak < min_peak:
                continue
            vi, vj = di / dt_min, dj / dt_min
            if np.hypot(vi, vj) > max_cells_per_min:
                continue
            out.append((i0 + TILE / 2, j0 + TILE / 2, vi, vj, peak * min(fa, fb) ** 0.5))
    return out


def dense_field(vectors, shape, background: tuple[np.ndarray, np.ndarray], sigma_cells: float = 40.0,
                bg_weight: float = 0.02):
    """Gaussian-weighted interpolation of sparse vectors onto a coarse grid, then upsample."""
    ny, nx = shape
    step = 8
    ci = np.arange(step / 2, ny, step)
    cj = np.arange(step / 2, nx, step)
    CI, CJ = np.meshgrid(ci, cj, indexing="ij")
    bg_vi = ndimage.zoom(background[0], (len(ci) / ny, len(cj) / nx), order=1)
    bg_vj = ndimage.zoom(background[1], (len(ci) / ny, len(cj) / nx), order=1)
    num_i = bg_vi * bg_weight
    num_j = bg_vj * bg_weight
    den = np.full(CI.shape, bg_weight)
    for (vi0, vj0, vi, vj, w) in vectors:
        k = w * np.exp(-((CI - vi0) ** 2 + (CJ - vj0) ** 2) / (2 * sigma_cells ** 2))
        num_i += k * vi
        num_j += k * vj
        den += k
    vi_c, vj_c = num_i / den, num_j / den
    vi_f = ndimage.zoom(vi_c, (ny / vi_c.shape[0], nx / vi_c.shape[1]), order=1)
    vj_f = ndimage.zoom(vj_c, (ny / vj_c.shape[0], nx / vj_c.shape[1]), order=1)
    vi_f = _fit(vi_f, shape)
    vj_f = _fit(vj_f, shape)
    return ndimage.gaussian_filter(vi_f, 6).astype(np.float32), ndimage.gaussian_filter(vj_f, 6).astype(np.float32)


def _fit(a: np.ndarray, shape) -> np.ndarray:
    ny, nx = shape
    a = a[:ny, :nx]
    if a.shape != (ny, nx):
        a = np.pad(a, ((0, ny - a.shape[0]), (0, nx - a.shape[1])), mode="edge")
    return a


class MotionEstimator:
    def __init__(self, shape, default_vi: float, default_vj: float, max_cells_per_min: float):
        self.shape = shape
        self.vi = np.full(shape, default_vi, np.float32)
        self.vj = np.full(shape, default_vj, np.float32)
        self.max_v = max_cells_per_min
        self.n_vectors = 0
        self.last_vectors: list = []

    def update(self, pairs: list[tuple[np.ndarray, np.ndarray, float]]):
        """pairs: list of (prev_feature, curr_feature, dt_min)."""
        vectors = []
        for prev, curr, dt in pairs:
            if dt <= 0:
                continue
            vectors += tile_vectors(prev, curr, dt, self.max_v)
        self.n_vectors = len(vectors)
        self.last_vectors = vectors
        if not vectors:
            return self.vi, self.vj
        vi, vj = dense_field(vectors, self.shape, (self.vi, self.vj))
        # temporal smoothing for stability
        self.vi = (0.5 * self.vi + 0.5 * vi).astype(np.float32)
        self.vj = (0.5 * self.vj + 0.5 * vj).astype(np.float32)
        return self.vi, self.vj


def reflectivity_feature(dbz: np.ndarray) -> np.ndarray:
    return np.clip(np.nan_to_num(dbz, nan=-10.0) - 18.0, 0, 42).astype(np.float32)


def ir_feature(bt: np.ndarray) -> np.ndarray:
    return np.clip(255.0 - np.nan_to_num(bt, nan=300.0), 0, 60).astype(np.float32)


def bilinear(field: np.ndarray, pi: np.ndarray, pj: np.ndarray, cval: float | None = None) -> np.ndarray:
    """Fast float32 bilinear sampling (much faster than ndimage.map_coordinates for order=1).

    cval=None clamps to the edge ("nearest"); otherwise points outside get cval.
    """
    ny, nx = field.shape
    ci = np.clip(pi, 0, ny - 1.001)
    cj = np.clip(pj, 0, nx - 1.001)
    i0 = ci.astype(np.int32)
    j0 = cj.astype(np.int32)
    fi = (ci - i0).astype(np.float32)
    fj = (cj - j0).astype(np.float32)
    flat = field.ravel()
    k = i0 * nx + j0
    a = flat[k]
    b = flat[k + 1]
    c = flat[k + nx]
    d = flat[k + nx + 1]
    top = a + (b - a) * fj
    bot = c + (d - c) * fj
    out = top + (bot - top) * fi
    if cval is not None:
        outside = (pi < -0.5) | (pi > ny - 0.5) | (pj < -0.5) | (pj > nx - 0.5)
        out = np.where(outside, np.float32(cval), out)
    return out.astype(np.float32, copy=False)


class Advector:
    """Backward semi-Lagrangian trajectories through a (steady, smooth) motion field.

    Trajectories are integrated on a 4x coarser lattice (the displacement field
    is as smooth as the motion field) and bilinearly expanded to full
    resolution; interpolation weights are computed once per lead time and
    shared by every advected field.
    """

    C = 4

    def __init__(self, vi: np.ndarray, vj: np.ndarray):
        self.ny, self.nx = vi.shape
        C = self.C
        self.ci = np.arange(0, self.ny + C, C, dtype=np.float32)
        self.cj = np.arange(0, self.nx + C, C, dtype=np.float32)
        CI, CJ = np.meshgrid(self.ci, self.cj, indexing="ij")
        self.vi, self.vj = vi, vj
        self.pi, self.pj = CI.copy(), CJ.copy()
        self.CI, self.CJ = CI, CJ
        self.minutes = 0.0
        self._weights = None

    def step(self, minutes: float, substeps: int = 2) -> None:
        h = minutes / substeps
        for _ in range(substeps):
            vi1 = bilinear(self.vi, self.pi, self.pj)
            vj1 = bilinear(self.vj, self.pi, self.pj)
            mi, mj = self.pi - 0.5 * h * vi1, self.pj - 0.5 * h * vj1
            self.pi = self.pi - h * bilinear(self.vi, mi, mj)
            self.pj = self.pj - h * bilinear(self.vj, mi, mj)
        self.minutes += minutes
        self._weights = None

    def _full(self):
        if self._weights is None:
            ny, nx, C = self.ny, self.nx, self.C
            di = self.pi - self.CI
            dj = self.pj - self.CJ
            ii, jj = np.mgrid[0:ny, 0:nx].astype(np.float32)
            fi_i, fj_j = ii / C, jj / C
            pi = ii + bilinear(di, fi_i, fj_j)
            pj = jj + bilinear(dj, fi_i, fj_j)
            ci = np.clip(pi, 0, ny - 1.001)
            cj = np.clip(pj, 0, nx - 1.001)
            i0 = ci.astype(np.int32)
            j0 = cj.astype(np.int32)
            k = (i0 * nx + j0).ravel()
            fi = (ci - i0).astype(np.float32)
            fj = (cj - j0).astype(np.float32)
            outside = (pi < -0.5) | (pi > ny - 0.5) | (pj < -0.5) | (pj > nx - 0.5)
            self._weights = (k, fi, fj, outside)
        return self._weights

    def sample(self, field: np.ndarray, cval: float) -> np.ndarray:
        k, fi, fj, outside = self._full()
        flat = field.astype(np.float32, copy=False).ravel()
        nx = self.nx
        shape = (self.ny, self.nx)
        a = flat[k].reshape(shape)
        b = flat[k + 1].reshape(shape)
        c = flat[k + nx].reshape(shape)
        d = flat[k + nx + 1].reshape(shape)
        top = a + (b - a) * fj
        out = top + (c + (d - c) * fj - top) * fi
        if outside.any():
            out[outside] = cval
        return out

def advect(field: np.ndarray, vi: np.ndarray, vj: np.ndarray, minutes: float, cval: float) -> np.ndarray:
    if abs(minutes) < 1e-3:
        return field
    adv = Advector(vi if minutes > 0 else -vi, vj if minutes > 0 else -vj)
    adv.step(abs(minutes), substeps=max(1, int(abs(minutes) // 10) + 1))
    return adv.sample(field, cval)
