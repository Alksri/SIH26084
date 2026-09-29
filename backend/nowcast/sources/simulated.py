"""Simulated DWR / INSAT-3DR / lightning feeds driven by the synthetic atmosphere."""
from __future__ import annotations

import asyncio
import math
import zlib

import numpy as np

from ..clock import SimClock
from ..config import RadarSite, Settings
from ..grid import Grid
from ..truth import TruthModel
from .base import DataSource, Emit, Observation


def _aligned(t: float, cadence: float, offset: float = 0.0) -> float:
    return (math.floor((t - offset) / cadence) + 1) * cadence + offset


class _SimSource(DataSource):
    def __init__(self, clock: SimClock, truth: TruthModel, cadence_s: float, latency_s: float, offset_s: float = 0.0):
        super().__init__()
        self.clock, self.truth = clock, truth
        self.cadence_s, self.latency_s, self.offset_s = cadence_s, latency_s, offset_s

    def scan(self, t: float) -> Observation:  # pragma: no cover - abstract
        raise NotImplementedError

    async def run(self, emit: Emit) -> None:
        next_t = _aligned(self.clock.now(), self.cadence_s, self.offset_s)
        while True:
            await self.clock.sleep_until(next_t)
            scan_t = next_t
            next_t += self.cadence_s
            if self.clock.now() > next_t:  # fell behind (e.g. warm-up) - skip to the present
                next_t = _aligned(self.clock.now(), self.cadence_s, self.offset_s)
            self.truth.advance_to(max(scan_t, self.truth.t or scan_t))
            obs = self.scan(scan_t)
            asyncio.create_task(self._deliver(obs, emit))

    async def _deliver(self, obs: Observation, emit: Emit) -> None:
        await self.clock.sleep_until(obs.obs_time + self.latency_s)
        if self.enabled:
            await emit(obs)


class SimRadarSource(_SimSource):
    kind = "radar"

    def __init__(self, clock, truth, grid: Grid, site: RadarSite, settings: Settings):
        super().__init__(clock, truth, settings.radar_cadence_s, settings.radar_latency_s)
        self.site, self.grid = site, grid
        self.id, self.label = site.id, f"DWR {site.name}"
        self.win = grid.window(site.lat, site.lon, site.range_km)
        n, e = grid.offsets_km(self.win, site.lat, site.lon)
        self.r = np.hypot(n, e).astype(np.float32)
        self.ex = (e / np.maximum(self.r, 1e-3)).astype(np.float32)
        self.ey = (n / np.maximum(self.r, 1e-3)).astype(np.float32)
        self.in_range = self.r <= site.range_km
        self.beam_h = (self.r * math.sin(math.radians(site.elev_deg)) + self.r ** 2 / (2 * 8494.0)).astype(np.float32)
        rng = np.random.default_rng(zlib.crc32(site.id.encode()))
        self.rng = rng
        self.clutter = (rng.random(self.r.shape) < 0.035) & (self.r < 30.0)
        self.clutter_dbz = rng.uniform(33, 52, self.r.shape).astype(np.float32)

    def scan(self, t: float) -> Observation:
        f = self.truth.fields(t)
        i0, i1, j0, j1 = self.win
        dbz_t = f["dbz"][i0:i1, j0:j1]
        # range-dependent underestimation (beam broadening / overshooting) + receiver noise
        loss = 0.01 * self.r + 0.6 * np.clip(self.beam_h - 3.0, 0, None)
        dbz = dbz_t - loss + self.rng.normal(0, 1.0, dbz_t.shape).astype(np.float32)
        mds = -12.0 + 20.0 * np.log10(np.maximum(self.r, 1.0) / 10.0)
        dbz = np.where(dbz >= mds, dbz, -10.0)
        dbz = np.where(self.clutter, np.maximum(dbz, self.clutter_dbz), dbz)
        # radial velocity: environmental wind + low-level outflow (visible only where the beam is low)
        tr = self.truth
        low = np.exp(-self.beam_h / 1.2)
        u = tr.env_u[i0:i1, j0:j1] + f["ou"][i0:i1, j0:j1] * low
        v = tr.env_v[i0:i1, j0:j1] + f["ov"][i0:i1, j0:j1] * low
        vr = u * self.ex + v * self.ey + self.rng.normal(0, 1.0, dbz.shape).astype(np.float32)
        vr = np.where(self.clutter, self.rng.normal(0, 0.3, dbz.shape), vr)
        vr = np.where((dbz > 0) | (self.r < 60), vr, np.nan)
        dbz = np.where(self.in_range, dbz, np.nan)
        vr = np.where(self.in_range, vr, np.nan)
        quality = np.where(self.in_range, np.exp(-(self.r / 220.0) ** 2), 0.0)
        payload = {
            "window": self.win,
            "dbz": dbz.astype(np.float32),
            "vr": vr.astype(np.float32),
            "quality": quality.astype(np.float32),
            "site": {"id": self.site.id, "lat": self.site.lat, "lon": self.site.lon, "range_km": self.site.range_km},
        }
        return Observation(self.id, "radar", t, payload, meta={"product": "PPI 0.5deg DBZ/VRAD"})


class SimSatelliteSource(_SimSource):
    kind = "satellite"

    def __init__(self, clock, truth, settings: Settings):
        super().__init__(clock, truth, settings.sat_cadence_s, settings.sat_latency_s, offset_s=120.0)
        self.id, self.label = "INSAT-3DR", "INSAT-3DR Imager (TIR1 / WV)"

    def scan(self, t: float) -> Observation:
        tir, wv = self.truth.render_ir(t)
        return Observation(self.id, "satellite", t, {"tir1": tir, "wv": wv},
                           meta={"product": "L1C TIR1 10.8um / WV 6.7um", "parallax_corrected": False})


class SimLightningSource(_SimSource):
    kind = "lightning"

    def __init__(self, clock, truth, settings: Settings):
        super().__init__(clock, truth, settings.lightning_batch_s, settings.lightning_latency_s)
        self.id, self.label = "LLN", "Ground lightning network (IC+CG)"
        self._last: float | None = None

    def scan(self, t: float) -> Observation:
        t1 = self._last if self._last is not None else t - self.cadence_s
        self._last = t
        strikes = self.truth.flashes(t1, t)
        return Observation(self.id, "lightning", t, {"strikes": strikes}, meta={"window_s": t - t1})


def build_simulated_sources(clock: SimClock, truth: TruthModel, grid: Grid, settings: Settings) -> list[DataSource]:
    sources: list[DataSource] = [SimRadarSource(clock, truth, grid, site, settings) for site in settings.radars]
    sources.append(SimSatelliteSource(clock, truth, settings))
    sources.append(SimLightningSource(clock, truth, settings))
    return sources
