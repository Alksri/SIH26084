"""Storm-cell identification/tracking, lightning-jump detection and
satellite-based convective-initiation (CI) detection.

* Cells: TITAN-style 40 dBZ objects on the fused composite, matched between
  cycles by predicted-position proximity.
* Lightning jump: Schultz et al. (2009) "2-sigma" algorithm on the per-cell
  total flash rate - a 5-30 min precursor of hail / damaging winds.
* CI: SATCAST-style interest fields (Mecikalski & Bedka 2006): cloud tops
  below 273 K that are cooling faster than -4 K / 15 min, not yet associated
  with a >=35 dBZ echo.  Candidates are tracked, and when a radar cell later
  forms underneath, the realised CI lead time is recorded.
"""
from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from .fusion import Analysis
from .grid import Grid, bearing_deg, compass, haversine_km
from .hazards import sigmoid


@dataclass
class Cell:
    id: int
    time: float
    lat: float
    lon: float
    i: float
    j: float
    area_km2: float
    max_dbz: float
    max_vil: float
    min_bt: float | None
    flash_rate: float           # flashes / min (last 10 min)
    hail: float
    gust: float
    outflow: float
    vi: float                   # cells/min
    vj: float
    first_seen: float
    source: str                 # "radar" / "proxy"
    history: collections.deque = field(default_factory=lambda: collections.deque(maxlen=16))
    lightning_jump_at: float | None = None
    trend_dbz_10min: float = 0.0
    stage: str = "new"
    level: int = 0
    mask_slice: tuple | None = None
    label: int = 0


@dataclass
class CICandidate:
    id: int
    lat: float
    lon: float
    i: float
    j: float
    first_detected: float
    last_seen: float
    prob: float
    min_bt: float
    cooling: float  # K / 15 min (negative)
    area_km2: float
    verified_at: float | None = None
    verified_cell: int | None = None
    notified: bool = False


class CellTracker:
    def __init__(self, grid: Grid):
        self.grid = grid
        self.cells: list[Cell] = []
        self._next = 1
        self.labels: np.ndarray | None = None

    def identify(self, an: Analysis, vil: np.ndarray, hail: np.ndarray, gust: np.ndarray,
                 vi: np.ndarray, vj: np.ndarray) -> list[Cell]:
        g = self.grid
        core = ndimage.binary_opening(an.dbz >= 40.0, iterations=1)
        labels, n = ndimage.label(core)
        self.labels = labels
        objs = ndimage.find_objects(labels)
        zlin = 10.0 ** (np.clip(an.dbz, -10, 70) / 10.0)
        found = []
        for k, sl in enumerate(objs, start=1):
            if sl is None:
                continue
            m = labels[sl] == k
            npx = int(m.sum())
            if npx < 4:
                continue
            w = zlin[sl] * m
            ii, jj = np.mgrid[sl[0], sl[1]]
            ci = float((ii * w).sum() / w.sum())
            cj = float((jj * w).sum() / w.sum())
            lat, lon = g.latlon(ci, cj)
            area = float(npx * g.cell_area_km2[int(ci), 0])
            # dilated neighbourhood for lightning / cloud-top attributes
            pad = 4
            s0 = slice(max(sl[0].start - pad, 0), min(sl[0].stop + pad, g.ny))
            s1 = slice(max(sl[1].start - pad, 0), min(sl[1].stop + pad, g.nx))
            big = ndimage.binary_dilation(labels[s0, s1] == k, iterations=pad)
            fr = float((an.lightning_density[s0, s1] * g.cell_area_km2[s0] * big).sum() / 60.0)
            min_bt = float(np.nanmin(np.where(big, an.bt[s0, s1], np.nan))) if an.bt is not None else None
            src = "proxy" if (an.source_map[sl][m] == 2).mean() > 0.5 else "radar"
            ic, jc = int(round(ci)), int(round(cj))
            found.append(Cell(
                id=0, time=an.time, lat=float(lat), lon=float(lon), i=ci, j=cj, area_km2=area,
                max_dbz=float(an.dbz[sl][m].max()), max_vil=float(vil[s0, s1][big].max()),
                min_bt=min_bt, flash_rate=fr, hail=float(hail[s0, s1][big].max()),
                gust=float(gust[s0, s1][big].max()), outflow=float(an.outflow[s0, s1][big].max()),
                vi=float(vi[ic, jc]), vj=float(vj[ic, jc]), first_seen=an.time, source=src,
                mask_slice=(s0.start, s0.stop, s1.start, s1.stop), label=k,
            ))
        return found

    def track(self, found: list[Cell], t: float) -> list[Cell]:
        prev = self.cells
        pairs = []
        for a_idx, p in enumerate(prev):
            dt = (t - p.time) / 60.0
            pi, pj = p.i + p.vi * dt, p.j + p.vj * dt
            for b_idx, c in enumerate(found):
                d_km = math.hypot((c.i - pi) * self.grid.dy_km, (c.j - pj) * self.grid.dx_km)
                gate = 12.0 + 0.5 * math.sqrt(max(p.area_km2, c.area_km2))
                if d_km <= gate:
                    pairs.append((d_km, a_idx, b_idx))
        pairs.sort()
        used_a, used_b = set(), set()
        for d, a_idx, b_idx in pairs:
            if a_idx in used_a or b_idx in used_b:
                continue
            used_a.add(a_idx)
            used_b.add(b_idx)
            p, c = prev[a_idx], found[b_idx]
            dt = (t - p.time) / 60.0
            c.id, c.first_seen, c.history, c.lightning_jump_at = p.id, p.first_seen, p.history, p.lightning_jump_at
            if dt > 0:
                mvi, mvj = (c.i - p.i) / dt, (c.j - p.j) / dt
                # blend measured centroid motion with the motion field (centroids jitter as cells evolve)
                c.vi = 0.35 * mvi + 0.35 * p.vi + 0.3 * c.vi
                c.vj = 0.35 * mvj + 0.35 * p.vj + 0.3 * c.vj
        for c in found:
            if c.id == 0:
                c.id = self._next
                self._next += 1
            c.history.append((t, c.max_dbz, c.max_vil, c.flash_rate, c.lat, c.lon))
            self._lifecycle(c, t)
        self.cells = found
        return found

    def _lifecycle(self, c: Cell, t: float) -> None:
        h = [x for x in c.history if t - x[0] <= 15 * 60]
        if len(h) >= 2 and h[-1][0] > h[0][0]:
            c.trend_dbz_10min = (h[-1][1] - h[0][1]) / ((h[-1][0] - h[0][0]) / 600.0)
        else:
            c.trend_dbz_10min = 0.0
        if len(c.history) < 2:
            c.stage = "new"
        elif c.trend_dbz_10min > 2.5:
            c.stage = "developing"
        elif c.trend_dbz_10min < -2.5:
            c.stage = "dissipating"
        else:
            c.stage = "mature"
        # Lightning jump (2-sigma): DFRDT now vs std of previous DFRDTs
        fr = [x[3] for x in c.history]
        ts = [x[0] for x in c.history]
        if len(fr) >= 5:
            d = [(fr[k] - fr[k - 1]) / max((ts[k] - ts[k - 1]) / 60.0, 1.0) for k in range(1, len(fr))]
            sigma = float(np.std(d[:-1])) if len(d) > 2 else 0.0
            if fr[-1] >= 8.0 and d[-1] > max(2.0 * sigma, 0.4):
                c.lightning_jump_at = t
        if c.lightning_jump_at is not None and t - c.lightning_jump_at > 40 * 60:
            c.lightning_jump_at = None


class CIDetector:
    def __init__(self, grid: Grid):
        self.grid = grid
        self.candidates: list[CICandidate] = []
        self._next = 1
        self.verified: collections.deque = collections.deque(maxlen=50)  # realised lead times (min)

    def detect(self, an: Analysis, cells: list[Cell], t: float) -> list[CICandidate]:
        g = self.grid
        if an.bt is None or an.bt_trend is None:
            self._verify(cells, t)
            return self.candidates
        bt, tr = an.bt, an.bt_trend
        no_echo = ndimage.maximum_filter(an.dbz, 5) < 35.0
        # exclude spreading anvils of existing storms (their edges also "cool")
        if cells:
            near = np.zeros_like(no_echo)
            for c in cells:
                i0, i1, j0, j1 = c.mask_slice
                near[max(i0 - 12, 0):i1 + 12, max(j0 - 12, 0):j1 + 12] = True
            no_echo &= ~near
        interest = (bt < 273.0) & (bt > 225.0) & (tr <= -4.0) & no_echo
        interest = ndimage.binary_opening(interest, iterations=1)
        labels, n = ndimage.label(interest)
        new = []
        for k, sl in enumerate(ndimage.find_objects(labels), start=1):
            if sl is None:
                continue
            m = labels[sl] == k
            if m.sum() < 5:
                continue
            ii, jj = np.mgrid[sl[0], sl[1]]
            w = np.clip(-tr[sl], 0, None) * m
            ci, cj = float((ii * w).sum() / max(w.sum(), 1e-6)), float((jj * w).sum() / max(w.sum(), 1e-6))
            cool = float(tr[sl][m].min())
            mbt = float(bt[sl][m].min())
            weak_echo = float(an.dbz[sl][m].max()) >= 15.0
            wvir = float(an.wv_ir[sl][m].max()) if an.wv_ir is not None else -20.0
            s0 = slice(max(sl[0].start - 3, 0), min(sl[0].stop + 3, g.ny))
            s1 = slice(max(sl[1].start - 3, 0), min(sl[1].stop + 3, g.nx))
            flashes = float(an.lightning_density[s0, s1].max()) > 0.05
            score = (0.08 * (-cool - 8.0) + 0.04 * (262.0 - mbt) + 0.6 * weak_echo + 0.6 * flashes
                     + 0.04 * (wvir + 15.0) - 0.6)
            prob = float(sigmoid(score))
            lat, lon = g.latlon(ci, cj)
            new.append((float(lat), float(lon), ci, cj, prob, mbt, cool, float(m.sum() * g.cell_area_km2[int(ci), 0])))
        # associate with existing candidates
        for lat, lon, ci, cj, prob, mbt, cool, area in new:
            best, best_d = None, 25.0
            for c in self.candidates:
                if c.verified_at is not None:
                    continue
                d = float(haversine_km(lat, lon, c.lat, c.lon))
                if d < best_d:
                    best, best_d = c, d
            if best is None:
                self.candidates.append(CICandidate(self._next, lat, lon, ci, cj, t, t, prob, mbt, cool, area))
                self._next += 1
            else:
                best.lat, best.lon, best.i, best.j = lat, lon, ci, cj
                best.last_seen, best.prob = t, max(prob, 0.7 * best.prob + 0.3 * prob)
                best.min_bt, best.cooling, best.area_km2 = mbt, cool, area
        self._verify(cells, t)
        # candidates move with the flow between detections
        self.candidates = [c for c in self.candidates
                           if (c.verified_at is None and t - c.last_seen <= 30 * 60)
                           or (c.verified_at is not None and t - c.verified_at <= 30 * 60)]
        return self.candidates

    def _verify(self, cells: list[Cell], t: float) -> None:
        for c in self.candidates:
            if c.verified_at is not None:
                continue
            for cell in cells:
                if t - cell.first_seen > 15 * 60:
                    continue
                if float(haversine_km(c.lat, c.lon, cell.lat, cell.lon)) < 25.0:
                    c.verified_at, c.verified_cell = t, cell.id
                    self.verified.append((t - c.first_detected) / 60.0)
                    break

    def mean_lead_min(self) -> float | None:
        return float(np.mean(self.verified)) if self.verified else None


def describe_location(lat: float, lon: float, places) -> str:
    best, best_d = None, 1e9
    for p in places:
        d = float(haversine_km(lat, lon, p["lat"], p["lon"]))
        if d < best_d:
            best, best_d = p, d
    if best is None:
        return f"{lat:.2f}N {lon:.2f}E"
    if best_d < 5:
        return f"over {best['name']}"
    return f"{best_d:.0f} km {compass(bearing_deg(best['lat'], best['lon'], lat, lon))} of {best['name']}"
