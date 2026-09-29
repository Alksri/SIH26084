"""0-6 h convective nowcast.

Lagrangian extrapolation of the fused state along the estimated motion field
(backward semi-Lagrangian, RK2 trajectories), with

* cell-based growth/decay trends that saturate with lead time,
* a generic lifetime decay of convective intensity beyond ~20 min,
* injection of expected new cells at satellite-detected CI locations,
* scale-dependent smoothing that removes unpredictable small scales,
* neighbourhood-maximum probabilities whose radius grows with lead time.

Hazard products per lead time:
  dbz         forecast reflectivity (dBZ)
  lightning   total flash density (flashes km^-2 h^-1)
  hail        probability of hail (0-1)
  gust        expected peak downburst / outflow gust (m/s)
  cloudburst  probability of >= 100 mm in the following hour (0-1)
  rain1h      expected rainfall in the following hour (mm)
  level       composite threat level 0..4
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from . import hazards as hz
from .detection import CICandidate, Cell
from .fusion import Analysis
from .grid import Grid
from .motion import Advector

PRODUCTS = ("dbz", "lightning", "hail", "gust", "cloudburst", "rain1h", "level")


@dataclass
class Nowcast:
    time: float
    leads: list[int]
    products: dict[str, np.ndarray]   # name -> (n_leads, ny, nx)
    swaths: dict[str, np.ndarray]     # 'level_60', 'level_180', 'level_360'
    compute_s: float = 0.0

    def lead_index(self, lead_min: int) -> int:
        return int(np.argmin(np.abs(np.asarray(self.leads) - lead_min)))


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


class NowcastModel:
    def __init__(self, grid: Grid, leads: list[int]):
        self.grid = grid
        self.leads = leads

    # neighbourhood radius (km) and reliability as a function of lead time
    @staticmethod
    def radius_km(lead: float) -> float:
        return min(2.0 + 0.1 * lead, 30.0)

    @staticmethod
    def reliability(lead: float) -> float:
        return float(np.exp(-lead / 300.0))

    def _nbhd(self, field: np.ndarray, lead: float) -> np.ndarray:
        size = 2 * int(round(self.radius_km(lead) / self.grid.mean_dx_km)) + 1
        if size <= 5:
            m = ndimage.maximum_filter(field, size=size) if size > 1 else field
            if size / 4.0 >= 0.6:
                m = ndimage.gaussian_filter(m, size / 4.0, truncate=2.5)
            return m * self.reliability(lead)
        # large radii: work on a 2x block-max grid (4x fewer pixels), then expand
        ny, nx = field.shape
        f = np.pad(field, ((0, ny % 2), (0, nx % 2)), mode="edge")
        c = f.reshape(f.shape[0] // 2, 2, f.shape[1] // 2, 2).max(axis=(1, 3))
        cs = max(3, size // 2 | 1)
        c = ndimage.maximum_filter(c, size=cs)
        c = ndimage.gaussian_filter(c, cs / 4.0, truncate=2.5)
        m = np.repeat(np.repeat(c, 2, axis=0), 2, axis=1)[:ny, :nx]
        return m * self.reliability(lead)

    def growth_field(self, labels: np.ndarray | None, cells: list[Cell]) -> np.ndarray:
        g = self.grid
        G = np.zeros((g.ny, g.nx), np.float32)
        if labels is None or not cells:
            return G
        lut = np.zeros(int(labels.max()) + 1, np.float32)
        for c in cells:
            if c.label <= labels.max():
                trend = c.trend_dbz_10min
                if c.stage == "new":
                    trend = 2.0  # newly identified cells are usually still growing
                lut[c.label] = np.clip(trend, -8.0, 6.0)
        mask = ndimage.binary_dilation(labels > 0, iterations=4)
        raw = lut[labels]
        w = (labels > 0).astype(np.float32)
        num = ndimage.gaussian_filter(raw, 3.0)
        den = ndimage.gaussian_filter(w, 3.0)
        G = np.where(mask, num / np.maximum(den, 1e-3), 0.0)
        return G.astype(np.float32)

    def ci_seed(self, candidates: list[CICandidate]) -> np.ndarray | None:
        g = self.grid
        active = [c for c in candidates if c.verified_at is None and c.prob >= 0.3]
        if not active:
            return None
        seed = np.zeros((g.ny, g.nx), np.float32)
        ii, jj = np.mgrid[0:g.ny, 0:g.nx]
        for c in active:
            sl = (slice(max(int(c.i) - 12, 0), min(int(c.i) + 13, g.ny)), slice(max(int(c.j) - 12, 0), min(int(c.j) + 13, g.nx)))
            d2 = (ii[sl] - c.i) ** 2 + (jj[sl] - c.j) ** 2
            seed[sl] = np.maximum(seed[sl], c.prob * np.exp(-d2 / (2 * 3.0 ** 2)))
        return seed

    def run(self, an: Analysis, vi: np.ndarray, vj: np.ndarray, cells: list[Cell], labels: np.ndarray | None,
            candidates: list[CICandidate]) -> Nowcast:
        import time as _time

        t0 = _time.perf_counter()
        g = self.grid
        nL = len(self.leads)
        shape = (nL, g.ny, g.nx)
        out = {p: np.zeros(shape, np.float16) for p in PRODUCTS if p != "level"}
        out["level"] = np.zeros(shape, np.uint8)
        rain_frames = np.zeros(shape, np.float32)
        nb_frames: list[tuple[np.ndarray, np.ndarray]] = []

        G = self.growth_field(labels, cells)
        seed = self.ci_seed(candidates)
        bt0 = an.bt
        has_bt = bt0 is not None
        bt_trend = an.bt_trend if an.bt_trend is not None else None
        outflow0 = an.outflow
        has_outflow = bool(outflow0.max() > 0)
        adv = Advector(vi, vj)
        prev_lead = 0
        dbz_max_obs = float(an.dbz.max())

        for k, L in enumerate(self.leads):
            if L > prev_lead:
                adv.step(L - prev_lead, substeps=2 if L - prev_lead >= 10 else 1)
                prev_lead = L
            if L == 0:
                z_adv, g_adv = an.dbz, G
                ld_adv = an.lightning_density
                bt_adv = bt0 if has_bt else None
                of_adv = outflow0
                seed_adv = seed
            else:
                z_adv = adv.sample(an.dbz, -10.0)
                g_adv = adv.sample(G, 0.0)
                ld_adv = adv.sample(an.lightning_density, 0.0)
                bt_adv = adv.sample(bt0, 300.0) if has_bt else None
                of_adv = adv.sample(outflow0, 0.0) if has_outflow else outflow0
                seed_adv = adv.sample(seed, 0.0) if seed is not None else None

            # --- intensity evolution -------------------------------------
            tau = 20.0
            growth = g_adv * (tau * (1 - np.exp(-L / tau)) / 10.0)
            conv = np.clip((z_adv - 20.0) / 20.0, 0.0, 1.0)
            decay = 0.055 * max(L - 20.0, 0.0) * conv
            z = np.where(z_adv > 5.0, z_adv + growth * conv - decay, z_adv)
            z = np.minimum(z, dbz_max_obs + 6.0)
            bt = None
            if has_bt:
                bt = bt_adv
                if bt_trend is not None and L > 0:
                    tr_adv = adv.sample(bt_trend, 0.0)
                    bt = bt + np.clip(tr_adv, -15, 5) * min(L, 30.0) / 15.0 * 0.5
                    bt = np.clip(bt, 185.0, 320.0)
            # --- expected new cells at CI locations ----------------------
            if seed_adv is not None and L > 0:
                if L <= 90:
                    peak = 25.0 + 28.0 * float(_smoothstep((L - 5.0) / 40.0))
                else:
                    peak = 53.0 - 0.3 * (L - 90.0)
                if peak > 10:
                    zci = np.where(seed_adv > 0.05, peak + 10.0 * np.log10(np.maximum(seed_adv, 1e-3)), -10.0)
                    z = np.maximum(z, zci)
                    if bt is not None and L >= 30:
                        bt = np.where(seed_adv > 0.15, np.minimum(bt, 218.0), bt)
            # --- scale-dependent smoothing --------------------------------
            sig = 0.015 * L
            if sig >= 0.5:
                z = ndimage.gaussian_filter(z, sig)
            z = z.astype(np.float32)

            # --- hazard diagnostics ---------------------------------------
            et = hz.echo_top_m(bt, z)
            vil = hz.vil_kg_m2(z, et)
            hail_raw = hz.hail_index(z, vil, et, bt)
            gust_raw = hz.stewart_gust_ms(vil, et)
            if has_outflow:
                gust_raw = np.maximum(gust_raw, of_adv * float(np.exp(-L / 25.0)))
            cold = hz.sigmoid((235.0 - bt) / 5.0) if bt is not None else 1.0
            ld_diag = 0.04 * np.clip(z - 38.0, 0, None) ** 1.5 * cold
            ld = np.maximum(ld_adv * float(np.exp(-L / 40.0)), ld_diag)
            rain_frames[k] = hz.rain_rate_mm_h(z)

            lsig = max(0.8, self.radius_km(L) / 4.0 / g.mean_dx_km)
            out["dbz"][k] = z
            out["lightning"][k] = ndimage.gaussian_filter(ld, lsig) * (self.reliability(L) ** 0.5)
            out["hail"][k] = np.clip(self._nbhd(hail_raw, L), 0, 1)
            gust_d = ndimage.maximum_filter(gust_raw, 5)
            if L > 0:
                gust_d = ndimage.gaussian_filter(gust_d, lsig)
            out["gust"][k] = gust_d
            p40 = self._nbhd((z >= 40.0).astype(np.float32), L)
            p50 = self._nbhd((z >= 50.0).astype(np.float32), L)
            nb_frames.append((p40.astype(np.float16), p50.astype(np.float16)))

        # --- cloudburst: rainfall in the hour following each lead -----------
        step = self.leads[1] - self.leads[0] if nL > 1 else 10
        n_hr = max(1, int(round(60 / step)))
        csum = np.cumsum(np.concatenate([np.zeros((1, g.ny, g.nx), np.float32), rain_frames]), axis=0)
        for k, L in enumerate(self.leads):
            k2 = min(k + n_hr, nL)
            frames = k2 - k
            acc = (csum[k2] - csum[k]) * (step / 60.0) * (n_hr / frames)
            out["rain1h"][k] = acc
            cb = hz.sigmoid((acc - hz.CLOUDBURST_MM_PER_H) / 12.0)
            cb = np.where(acc > 40.0, cb, 0.0)
            out["cloudburst"][k] = np.clip(self._nbhd(cb.astype(np.float32), L), 0, 1)
            p40, p50 = nb_frames[k]
            out["level"][k] = hz.threat_level(
                p40.astype(np.float32), p50.astype(np.float32), out["lightning"][k].astype(np.float32),
                out["hail"][k].astype(np.float32), out["gust"][k].astype(np.float32),
                out["cloudburst"][k].astype(np.float32))

        run_max = np.maximum.accumulate(out["level"], axis=0)
        swaths = {}
        for win in (60, 180, 360):
            idx = int(np.searchsorted(self.leads, win, side="right") - 1)
            swaths[f"level_{win}"] = run_max[max(idx, 0)]
        return Nowcast(an.time, list(self.leads), out, swaths, compute_s=_time.perf_counter() - t0)
