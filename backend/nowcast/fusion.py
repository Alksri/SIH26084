"""Multi-source data fusion onto the common 2-km grid.

1. Radar mosaic: best-quality-wins composite of all DWR sweeps (quality falls
   with range / beam height), plus low-level outflow (divergence) detected in
   the radial-velocity field.
2. Satellite: parallax-corrected TIR1 advected from its scan time to the
   analysis time (latency compensation), Lagrangian cloud-top cooling rate
   between consecutive images, and WV-IR difference (overshooting tops).
3. Lightning: flash density from the last 10 minutes.
4. Gap filling: where radar quality is poor, a pseudo-reflectivity estimated
   from IR cloud-top temperature + lightning density fills the composite,
   with a lower confidence score.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from .grid import Grid
from .ingest import IngestSnapshot
from .motion import advect
from .parallax import ParallaxCorrector


@dataclass
class Analysis:
    time: float
    dbz: np.ndarray               # fused reflectivity (dBZ, -10 = no echo)
    confidence: np.ndarray        # 0..1
    source_map: np.ndarray        # 0 none, 1 radar, 2 satellite/lightning proxy
    radar_coverage: np.ndarray    # bool
    outflow: np.ndarray           # radar-detected outflow speed (m/s)
    bt: np.ndarray | None         # TIR1 BT at analysis time (K)
    bt_trend: np.ndarray | None   # K / 15 min (Lagrangian)
    wv_ir: np.ndarray | None      # WV - IR (K)
    lightning_density: np.ndarray  # flashes km^-2 h^-1 (last 10 min)
    strikes_10min: np.ndarray
    inputs: dict = field(default_factory=dict)


class FusionEngine:
    def __init__(self, grid: Grid, sat_lon: float):
        self.grid = grid
        self.parallax = ParallaxCorrector(grid, sat_lon)
        self._parallax_by_lon: dict[float, ParallaxCorrector] = {sat_lon: self.parallax}
        self._radial_cache: dict[str, tuple] = {}

    # -------------------------------------------------------------- radar
    def _radial(self, site: dict, win):
        key = f"{site['id']}:{win}"
        if key not in self._radial_cache:
            n, e = self.grid.offsets_km(win, site["lat"], site["lon"])
            r = np.hypot(n, e)
            self._radial_cache[key] = (r.astype(np.float32), (e / np.maximum(r, 1e-3)).astype(np.float32),
                                       (n / np.maximum(r, 1e-3)).astype(np.float32))
        return self._radial_cache[key]

    def _outflow_from_vr(self, obs) -> np.ndarray:
        """Divergent radial-velocity couplets -> outflow speed estimate (m/s)."""
        p = obs.payload
        vr = p["vr"]
        valid = np.isfinite(vr)
        if valid.sum() < 50:
            return np.zeros(vr.shape, np.float32)
        r, ex, ey = self._radial(p["site"], p["window"])
        v = np.where(valid, vr, 0.0).astype(np.float32)
        w = valid.astype(np.float32)
        # normalised smoothing to suppress noise without bleeding across gaps
        vs = ndimage.gaussian_filter(v, 1.0) / np.maximum(ndimage.gaussian_filter(w, 1.0), 1e-3)
        gy, gx = np.gradient(vs)
        dvr_dr = (gx / self.grid.dx_km) * ex + (-gy / self.grid.dy_km) * ey  # m/s per km
        vmax = ndimage.maximum_filter(np.where(valid, vs, -99), 7)
        vmin = ndimage.minimum_filter(np.where(valid, vs, 99), 7)
        dv = np.clip(vmax - vmin, 0, 80)
        div = ndimage.maximum_filter(ndimage.gaussian_filter(dvr_dr, 1.0), 5) > 1.2
        out = np.where(div & valid & (r > 15), 0.5 * dv, 0.0)
        out = np.where(out > 6.0, out, 0.0)  # below this it is indistinguishable from noise/shear
        return ndimage.maximum_filter(out, 3).astype(np.float32)

    def radar_mosaic(self, radars):
        g = self.grid
        dbz = np.full((g.ny, g.nx), -10.0, np.float32)
        q = np.zeros((g.ny, g.nx), np.float32)
        outflow = np.zeros((g.ny, g.nx), np.float32)
        cov = np.zeros((g.ny, g.nx), bool)
        used = []
        for obs in radars:
            p = obs.payload
            i0, i1, j0, j1 = p["window"]
            d = np.nan_to_num(p["dbz"], nan=-10.0)
            qq = p["quality"]
            sub_q = q[i0:i1, j0:j1]
            better = qq > sub_q
            dbz[i0:i1, j0:j1] = np.where(better, d, dbz[i0:i1, j0:j1])
            q[i0:i1, j0:j1] = np.where(better, qq, sub_q)
            cov[i0:i1, j0:j1] |= qq > 0.05
            out = self._outflow_from_vr(obs)
            outflow[i0:i1, j0:j1] = np.maximum(outflow[i0:i1, j0:j1], out)
            used.append(obs.source_id)
        return dbz, q, cov, outflow, used

    # ---------------------------------------------------------- satellite
    def _corrector(self, obs) -> ParallaxCorrector:
        # each satellite views from its own longitude (INSAT-3DR 74 E, Himawari-9 140.7 E)
        lon = obs.payload.get("sat_lon")
        if lon is None:
            return self.parallax
        if lon not in self._parallax_by_lon:
            self._parallax_by_lon[lon] = ParallaxCorrector(self.grid, lon)
        return self._parallax_by_lon[lon]

    def _corrected(self, obs):
        if "tir1_pc" not in obs.payload:
            pc = self._corrector(obs)
            obs.payload["tir1_pc"] = pc.correct(obs.payload["tir1"])
            wv = obs.payload.get("wv")
            obs.payload["wv_pc"] = pc.correct(wv) if wv is not None and np.isfinite(wv).any() else None
        return obs.payload["tir1_pc"], obs.payload["wv_pc"]

    def satellite(self, t: float, sats, vi, vj):
        if not sats:
            return None, None, None, None
        latest = sats[-1]
        bt1, wv1 = self._corrected(latest)
        age_min = (t - latest.obs_time) / 60.0
        bt = advect(bt1, vi, vj, age_min, cval=300.0)
        wv_ir = None
        if wv1 is not None:
            wv_ir = advect(wv1 - bt1, vi, vj, age_min, cval=-30.0)
        trend = None
        prev = [s for s in sats[:-1] if 8 * 60 <= latest.obs_time - s.obs_time <= 40 * 60]
        if prev:
            p = prev[-1]
            bt0, _ = self._corrected(p)
            dt_min = (latest.obs_time - p.obs_time) / 60.0
            bt0_adv = advect(bt0, vi, vj, dt_min, cval=300.0)
            trend1 = (bt1 - bt0_adv) * (15.0 / dt_min)
            trend = advect(trend1.astype(np.float32), vi, vj, age_min, cval=0.0)
        return bt, trend, wv_ir, latest.obs_time

    # ---------------------------------------------------------- lightning
    def lightning_density(self, strikes, t: float):
        g = self.grid
        s = strikes[(strikes["t"] > t - 600) & (strikes["t"] <= t)]
        counts = np.zeros((g.ny, g.nx), np.float32)
        if s.size:
            i, j = g.ij(s["lat"], s["lon"])
            i = np.clip(np.round(i).astype(int), 0, g.ny - 1)
            j = np.clip(np.round(j).astype(int), 0, g.nx - 1)
            np.add.at(counts, (i, j), 1.0)
        dens = ndimage.gaussian_filter(counts, 1.5) / g.cell_area_km2 * 6.0  # per km^2 per hour
        return dens.astype(np.float32), s

    # --------------------------------------------------------------- fuse
    def fuse(self, snap: IngestSnapshot, vi, vj) -> Analysis:
        t = snap.time
        dbz_r, q, cov, outflow, radars_used = self.radar_mosaic(snap.radars)
        bt, trend, wv_ir, sat_time = self.satellite(t, snap.satellites, vi, vj)
        ld, strikes10 = self.lightning_density(snap.strikes, t)

        dbz = dbz_r.copy()
        source_map = np.where(dbz_r > 5, 1, 0).astype(np.uint8)
        conf = np.where(cov, q, 0.0).astype(np.float32)
        if bt is not None:
            proxy = np.interp(bt, [195.0, 210.0, 225.0, 240.0], [45.0, 38.0, 25.0, 0.0]).astype(np.float32)
            # convective cores sit under the coldest tops; flat anvil far from the core is mostly stratiform
            proxy -= 1.0 * np.clip(bt - ndimage.minimum_filter(bt, 9), 0, 20)
            proxy = proxy + 8.0 * np.log10(1.0 + 5.0 * ld)
            proxy = np.where(bt < 240.0, np.minimum(proxy, 56.0), -10.0)
            proxy = ndimage.gaussian_filter(proxy, 1.0)
            w = np.clip(q / 0.3, 0.0, 1.0)  # radar trusted fully above q=0.3
            blended = w * dbz_r + (1 - w) * np.maximum(dbz_r, proxy)
            use_proxy = (blended > dbz_r + 1.0) & (proxy > 15)
            dbz = np.where(use_proxy, blended, dbz_r).astype(np.float32)
            source_map = np.where(use_proxy, 2, source_map).astype(np.uint8)
            conf = np.where(use_proxy, np.maximum(conf, 0.35 + 0.1 * (ld > 0.5)), conf).astype(np.float32)
        elif not snap.radars:
            # lightning-only fallback: flash density implies convective cores
            lproxy = np.where(ld > 0.2, 35.0 + 8.0 * np.log10(1.0 + 5.0 * ld), -10.0)
            dbz = np.maximum(dbz, lproxy).astype(np.float32)
            source_map = np.where(lproxy > 0, 2, source_map).astype(np.uint8)
            conf = np.where(lproxy > 0, 0.3, conf).astype(np.float32)

        inputs = {
            "radars": radars_used,
            "radar_ages_s": {o.source_id: round(t - o.obs_time) for o in snap.radars},
            "satellite_age_s": None if sat_time is None else round(t - sat_time),
            "satellite_images": len(snap.satellites),
            "flashes_10min": int(strikes10.size),
            "radar_coverage_pct": round(100.0 * float(cov.mean()), 1),
            "proxy_pct": round(100.0 * float((source_map == 2).mean()), 2),
        }
        return Analysis(t, dbz, conf, source_map, cov, outflow, bt, trend, wv_ir, ld, strikes10, inputs)
