"""Orchestrates ingestion -> fusion -> motion -> detection -> nowcast -> alerts.

Feeds run as independent asyncio tasks.  Every ``analysis_interval_s`` the
engine snapshots the ingest buffers and runs the analysis/nowcast cycle in a
worker thread, then publishes a compact JSON summary to dashboard clients.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from . import hazards as hz
from .alerts import place_forecasts
from .clock import SimClock
from .config import Settings
from .detection import CellTracker, CIDetector, describe_location
from .fusion import Analysis, FusionEngine
from .grid import Grid
from .ingest import IngestEngine, IngestSnapshot
from .motion import MotionEstimator, ir_feature, reflectivity_feature
from .nowcast import PRODUCTS, Nowcast, NowcastModel
from .places import PLACES
from .render import MercatorRows, colorize, encode_png
from .verification import Verifier

log = logging.getLogger("nowcast.engine")

RASTER_PRODUCTS = set(PRODUCTS) | {"ir", "confidence", "qpe1h", "level_60", "level_180", "level_360"}


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Snapshot:
    cycle: int
    time: float
    analysis: Analysis
    nowcast: Nowcast
    qpe1h: np.ndarray
    summary: dict


class NowcastEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = s = settings or Settings()
        self.grid = Grid(s.grid)
        self.simulated = s.mode == "simulated"
        self.realtime = s.mode == "realtime"
        start = s.start_time.timestamp()
        if self.simulated:
            self.clock = SimClock(start - s.warmup_minutes * 60, s.warmup_speed)
            from .truth import TruthModel

            self.truth = TruthModel(self.grid, s.seed, s.sat_lon)
            self.truth.seed_scenario(start)
            self.truth.advance_to(self.clock.now())
        else:
            self.clock = SimClock(None, 1.0)
            self.truth = None
        self.scenario_start = start
        self.warming_up = self.simulated
        self.ingest = IngestEngine(self.grid, self.clock.now, s.radar_max_age_s, s.sat_max_age_s)
        self.fusion = FusionEngine(self.grid, s.sat_lon)
        vi0, vj0 = self.grid.ms_to_cells_per_min(10.0, -4.0)
        self.motion = MotionEstimator((self.grid.ny, self.grid.nx), float(vi0), float(vj0),
                                      max_cells_per_min=float(np.hypot(*self.grid.ms_to_cells_per_min(40.0, 0.0))))
        self.tracker = CellTracker(self.grid)
        self.ci = CIDetector(self.grid)
        self.model = NowcastModel(self.grid, s.leads)
        self.verifier = Verifier()
        self.places = [p for p in PLACES if self.grid.contains(p["lat"], p["lon"])]
        self.merc = MercatorRows(self.grid)
        self.sources = self._build_sources()
        for src in self.sources:
            self.ingest.register(src)
        self.ingest.listeners.append(self._on_obs)
        self.snapshot: Snapshot | None = None
        self.cycle = 0
        self.events: collections.deque = collections.deque(maxlen=200)
        self._event_id = 0
        self._comp_hist: collections.deque = collections.deque(maxlen=6)
        self._rain_hist: collections.deque = collections.deque(maxlen=16)
        self._place_state: dict[str, dict] = {}
        self._health_state: dict[str, str] = {}
        self._png_cache: dict[tuple, bytes] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._tasks: list[asyncio.Task] = []
        self._busy = False
        self.last_cycle_s = 0.0
        self._frame_q: asyncio.Queue | None = None  # realtime: one analysis per radar frame

    def _build_sources(self):
        if self.simulated:
            from .sources.simulated import build_simulated_sources

            return build_simulated_sources(self.clock, self.truth, self.grid, self.settings)
        from .sources.live import LightningPushSource, build_live_sources

        if self.realtime:
            from .sources.rainviewer import NotConnectedSource, RainViewerSource

            return [
                RainViewerSource(self.grid),
                NotConnectedSource("INSAT-3DR", "satellite", "INSAT-3DR imager - needs MOSDAC access", 900.0),
                NotConnectedSource("LLN", "lightning", "Lightning network - needs IMD/IITM feed", 60.0),
                LightningPushSource(),
            ]
        return build_live_sources(self.settings.drop_dir, self.grid)

    # ============================================================ lifecycle
    async def start(self) -> None:
        for src in self.sources:
            self._tasks.append(asyncio.create_task(self._run_source(src), name=src.id))
        if self.realtime:
            self._frame_q = asyncio.Queue()
            self._tasks.append(asyncio.create_task(self._frame_loop(), name="analysis"))
        else:
            self._tasks.append(asyncio.create_task(self._analysis_loop(), name="analysis"))
        self._tasks.append(asyncio.create_task(self._tick_loop(), name="tick"))
        if self.simulated:
            self._tasks.append(asyncio.create_task(self._warmup_watch(), name="warmup"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_source(self, src) -> None:
        while True:
            try:
                await src.run(self.ingest.emit)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("source %s crashed - restarting in 5 s", src.id)
                await asyncio.sleep(5)

    async def _warmup_watch(self) -> None:
        await self.clock.sleep_until(self.scenario_start)
        self.clock.set_speed(self.settings.speed)
        self.warming_up = False
        self.add_event("info", "System online - nowcast cycling every 5 min, 0-6 h lead time", None, None)

    async def _analysis_loop(self) -> None:
        interval = self.settings.analysis_interval_s
        offset = self.settings.radar_latency_s + 15 if self.simulated else 0
        next_t = math.floor(self.clock.now() / interval) * interval + offset
        if next_t <= self.clock.now():
            next_t += interval
        loop = asyncio.get_running_loop()
        while True:
            await self.clock.sleep_until(next_t)
            snap_in = self.ingest.snapshot(next_t)
            if snap_in.radars or snap_in.satellites or snap_in.strikes.size:
                try:
                    self._busy = True
                    snap = await loop.run_in_executor(None, self.run_cycle, snap_in)
                    self._set_snapshot(snap)
                except Exception:
                    log.exception("analysis cycle failed")
                finally:
                    self._busy = False
            next_t += interval
            while next_t < self.clock.now():
                next_t += interval

    async def _frame_loop(self) -> None:
        """Realtime mode: analyse each radar frame at its own observation time."""
        loop = asyncio.get_running_loop()
        while True:
            t = await self._frame_q.get()
            snap_in = self.ingest.snapshot(t)
            try:
                self._busy = True
                snap = await loop.run_in_executor(None, self.run_cycle, snap_in)
                self._set_snapshot(snap)
            except Exception:
                log.exception("analysis cycle failed")
            finally:
                self._busy = False

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(2.0)
            self._check_health()
            self.publish({"type": "tick", "sim_now": self.clock.now(), "speed": self.clock.speed,
                          "server_real": time.time(), "warming_up": self.warming_up,
                          "health": self.ingest.health(), "busy": self._busy})

    # ============================================================ pub/sub
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, msg: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def _on_obs(self, obs) -> None:
        if self._frame_q is not None and obs.kind == "radar":
            self._frame_q.put_nowait(obs.obs_time)
        if obs.kind == "lightning":
            s = obs.payload["strikes"]
            if s.size:
                s = s[-600:]
                self.publish({"type": "strikes", "strikes": [[round(float(a), 4), round(float(b), 4), round(float(t), 1), int(c)]
                                                             for a, b, t, c in zip(s["lat"], s["lon"], s["t"], s["cg"])]})

    def _set_snapshot(self, snap: Snapshot) -> None:
        self.snapshot = snap
        self._png_cache.clear()
        self.publish(snap.summary)

    # ============================================================ events
    def add_event(self, kind: str, text: str, lat, lon, severity: int = 0) -> None:
        self._event_id += 1
        self.events.appendleft({"id": self._event_id, "time": self.clock.now(), "kind": kind, "text": text,
                                "lat": lat, "lon": lon, "severity": severity})

    def _check_health(self) -> None:
        for h in self.ingest.health():
            prev = self._health_state.get(h["id"])
            cur = h["status"]
            if prev is not None and prev != cur:
                if cur in ("DOWN", "STALE"):
                    self.add_event("feed", f"Feed {h['label']} is {cur} - fusion falling back to remaining sensors",
                                   None, None, severity=2 if cur == "DOWN" else 1)
                elif cur == "OK" and prev in ("DOWN", "STALE"):
                    self.add_event("feed", f"Feed {h['label']} restored", None, None)
            self._health_state[h["id"]] = cur

    # ============================================================ the cycle
    def run_cycle(self, snap_in: IngestSnapshot) -> Snapshot:
        t0 = time.perf_counter()
        t = snap_in.time
        g = self.grid
        an = self.fusion.fuse(snap_in, self.motion.vi, self.motion.vj)

        # --- motion from radar composites and IR image pairs
        pairs = []
        feat = reflectivity_feature(an.dbz)
        prev = [h for h in self._comp_hist if 8 * 60 <= t - h[0] <= 25 * 60]
        if prev:
            h = min(prev, key=lambda h: abs(t - h[0] - 600))
            pairs.append((h[1], feat, (t - h[0]) / 60.0))
        sats = snap_in.satellites
        if len(sats) >= 2:
            s1 = sats[-1]
            s0 = [s for s in sats[:-1] if 10 * 60 <= s1.obs_time - s.obs_time <= 40 * 60]
            if s0:
                b0, _ = self.fusion._corrected(s0[-1])
                b1, _ = self.fusion._corrected(s1)
                pairs.append((ir_feature(b0), ir_feature(b1), (s1.obs_time - s0[-1].obs_time) / 60.0))
        self._comp_hist.append((t, feat))
        vi, vj = self.motion.update(pairs)

        # --- analysis-time diagnostics for cell attributes
        et = hz.echo_top_m(an.bt, an.dbz)
        vil = hz.vil_kg_m2(an.dbz, et)
        hail = hz.hail_index(an.dbz, vil, et, an.bt)
        gust = np.maximum(hz.stewart_gust_ms(vil, et), an.outflow)
        cells = self.tracker.track(self.tracker.identify(an, vil, hail, gust, vi, vj), t)
        cis = self.ci.detect(an, cells, t)

        nc = self.model.run(an, vi, vj, cells, self.tracker.labels, cis)
        lv0 = nc.products["level"][0]
        for c in cells:
            i0, i1, j0, j1 = c.mask_slice
            c.level = int(lv0[i0:i1, j0:j1].max())
        places = place_forecasts(nc, cells, self.places, g)

        self.verifier.verify(t, an.dbz, an.radar_coverage)
        self.verifier.add_forecast(t, nc.leads, nc.products["dbz"], an.dbz)

        rain = hz.rain_rate_mm_h(an.dbz)
        self._rain_hist.append((t, rain))
        while self._rain_hist and t - self._rain_hist[0][0] > 3600 - 1:
            self._rain_hist.popleft()
        qpe = np.zeros_like(rain)
        # each frame represents the interval since the previous one (5 min simulated, 10 min RainViewer)
        prev_t = None
        for tt, r in self._rain_hist:
            dt_s = self.settings.analysis_interval_s if prev_t is None else min(tt - prev_t, 900.0)
            qpe += r * (dt_s / 3600.0)
            prev_t = tt

        self._events_for_cycle(t, cells, cis, places)
        self.cycle += 1
        self.last_cycle_s = time.perf_counter() - t0
        summary = self._summary(t, an, nc, cells, cis, places, vi, vj)
        return Snapshot(self.cycle, t, an, nc, qpe.astype(np.float32), summary)

    def _events_for_cycle(self, t, cells, cis, places) -> None:
        for c in cis:
            if not c.notified and c.prob >= 0.5 and c.verified_at is None:
                c.notified = True
                self.add_event("ci", f"Convective initiation {describe_location(c.lat, c.lon, self.places)} "
                                     f"(P={c.prob:.0%}, cloud-top cooling {c.cooling:.0f} K/15 min)",
                               c.lat, c.lon, severity=1)
            if c.verified_at == t:
                self.add_event("ci", f"CI confirmed by radar {describe_location(c.lat, c.lon, self.places)} - "
                                     f"satellite lead time {(t - c.first_detected) / 60:.0f} min", c.lat, c.lon)
        for c in cells:
            if c.lightning_jump_at == t:
                self.add_event("ljump", f"Lightning jump in storm #{c.id} {describe_location(c.lat, c.lon, self.places)} "
                                        f"({c.flash_rate:.0f} fl/min) - severe weather likely in 10-30 min",
                               c.lat, c.lon, severity=2)
        for p in places:
            st = self._place_state.get(p["id"], {"level": 0, "cb": False})
            lvl = p.get("level_window", 0) if p["status"] != "clear" else 0
            eta = p["eta_min"]
            if lvl >= 3 and lvl > st["level"] and eta is not None and eta <= 120:
                hzd = p["hazards"]
                parts = []
                if hzd["hail_prob"] >= 0.3:
                    parts.append(f"hail {hzd['hail_prob']:.0%}")
                if hzd["gust_ms"] >= 15:
                    parts.append(f"gusts {hzd['gust_ms'] * 3.6:.0f} km/h")
                if hzd["lightning"] >= 1:
                    parts.append("intense lightning")
                if hzd["cloudburst_prob"] >= 0.2:
                    parts.append(f"cloudburst risk {hzd['cloudburst_prob']:.0%}")
                when = "NOW" if p["status"] == "impact" else f"in {eta:.0f} min"
                self.add_event("warning", f"{hz.LEVEL_NAMES[lvl].upper()} threat for {p['name']} {when}: "
                                          f"{', '.join(parts) or 'severe thunderstorm'}", p["lat"], p["lon"], severity=lvl)
            elif st["level"] >= 2 and p["status"] == "clear":
                self.add_event("clear", f"All clear for {p['name']}", p["lat"], p["lon"])
            cb = p["status"] != "clear" and p["hazards"]["cloudburst_prob"] >= 0.4
            if cb and not st["cb"]:
                self.add_event("cloudburst", f"Cloudburst risk near {p['name']}: P(>=100 mm in 1 h) = "
                                             f"{p['hazards']['cloudburst_prob']:.0%} within the forecast neighbourhood",
                                             p["lat"], p["lon"], severity=3)
            self._place_state[p["id"]] = {"level": lvl, "cb": cb}

    # ============================================================ outputs
    def _summary(self, t, an, nc, cells, cis, places, vi, vj) -> dict:
        g = self.grid
        cell_js = []
        for c in cells:
            u, v = g.cells_per_min_to_ms(c.vi, c.vj)
            track = []
            for m in (0, 15, 30, 45, 60, 90, 120):
                la, lo = g.latlon(c.i + c.vi * m, c.j + c.vj * m)
                track.append([round(float(la), 4), round(float(lo), 4), m])
            past = [[round(float(x[4]), 4), round(float(x[5]), 4)] for x in c.history if len(x) > 5]
            cell_js.append({
                "id": c.id, "lat": round(c.lat, 4), "lon": round(c.lon, 4), "area_km2": round(c.area_km2, 1),
                "max_dbz": round(c.max_dbz, 1), "max_vil": round(c.max_vil, 1),
                "min_bt": None if c.min_bt is None or not np.isfinite(c.min_bt) else round(c.min_bt, 1),
                "flash_rate": round(c.flash_rate, 1), "lightning_jump": c.lightning_jump_at is not None,
                "hail": round(c.hail, 2), "gust": round(c.gust, 1), "outflow": round(c.outflow, 1),
                "stage": c.stage, "trend": round(c.trend_dbz_10min, 1), "level": c.level, "source": c.source,
                "speed_kmh": round(float(np.hypot(u, v)) * 3.6, 1),
                "heading_deg": round((math.degrees(math.atan2(float(u), float(v))) + 360) % 360, 0),
                "age_min": round((t - c.first_seen) / 60.0), "track": track, "past": past,
                "where": describe_location(c.lat, c.lon, self.places),
            })
        ci_js = [{
            "id": c.id, "lat": round(c.lat, 4), "lon": round(c.lon, 4), "prob": round(c.prob, 2),
            "min_bt": round(c.min_bt, 1), "cooling": round(c.cooling, 1), "area_km2": round(c.area_km2, 1),
            "age_min": round((t - c.first_detected) / 60.0), "verified": c.verified_at is not None,
            "where": describe_location(c.lat, c.lon, self.places),
        } for c in cis]
        # motion arrows on a ~40 km lattice where there is weather
        arrows = []
        step = 20
        u_all, v_all = g.cells_per_min_to_ms(vi, vj)
        wx = (an.dbz > 20) | ((an.bt < 250) if an.bt is not None else False)
        for i in range(step // 2, g.ny, step):
            for j in range(step // 2, g.nx, step):
                if wx[max(i - step // 2, 0):i + step // 2, max(j - step // 2, 0):j + step // 2].any():
                    la, lo = g.latlon(i, j)
                    arrows.append([round(float(la), 3), round(float(lo), 3), round(float(u_all[i, j]), 1), round(float(v_all[i, j]), 1)])
        s10 = an.strikes_10min[-3000:]
        return {
            "type": "cycle", "cycle": self.cycle, "time": t, "time_iso": iso(t), "sim_now": self.clock.now(),
            "speed": self.clock.speed, "server_real": time.time(), "mode": self.settings.mode,
            "warming_up": self.warming_up, "leads": nc.leads, "inputs": an.inputs,
            "health": self.ingest.health(), "cells": cell_js, "ci": ci_js, "places": places,
            "events": list(self.events)[:80], "verification": self.verifier.summary(),
            "ci_lead_mean_min": None if self.ci.mean_lead_min() is None else round(self.ci.mean_lead_min(), 1),
            "ci_verified_n": len(self.ci.verified),
            "stats": {"cycle_s": round(self.last_cycle_s, 2), "nowcast_s": round(nc.compute_s, 2),
                      "n_cells": len(cells), "n_ci": len(ci_js), "motion_vectors": self.motion.n_vectors,
                      "max_level_now": int(nc.products["level"][0].max()),
                      "max_level_6h": int(nc.swaths["level_360"].max())},
            "arrows": arrows,
            "strikes": [[round(float(a), 4), round(float(b), 4), round(float(ts), 1), int(cg)]
                        for a, b, ts, cg in zip(s10["lat"], s10["lon"], s10["t"], s10["cg"])],
        }

    def meta(self) -> dict:
        g = self.grid
        return {
            "bounds": g.bounds(), "res_deg": g.res, "dx_km": round(g.dx_km, 2), "dy_km": round(g.dy_km, 2),
            "shape": [g.ny, g.nx], "leads": self.settings.leads, "mode": self.settings.mode,
            "radars": [{"id": r.id, "name": r.name, "lat": r.lat, "lon": r.lon, "range_km": r.range_km}
                       for r in self.settings.radars] if self.simulated else [],
            "places": self.places, "sat_lon": self.settings.sat_lon,
            "sources": [s.describe() for s in self.sources],
            "analysis_interval_s": self.settings.analysis_interval_s,
        }

    def raster_png(self, product: str, lead_idx: int) -> bytes | None:
        snap = self.snapshot
        if snap is None or product not in RASTER_PRODUCTS:
            return None
        key = (snap.cycle, product, lead_idx)
        if key in self._png_cache:
            return self._png_cache[key]
        an, nc = snap.analysis, snap.nowcast
        if product in nc.products:
            k = int(np.clip(lead_idx, 0, len(nc.leads) - 1))
            data = nc.products[product][k].astype(np.float32) if product != "level" else nc.products[product][k]
            cmap = product
        elif product.startswith("level_"):
            data, cmap = nc.swaths[product], "level"
        elif product == "ir":
            if an.bt is None:
                return None
            data, cmap = an.bt, "ir"
        elif product == "confidence":
            data, cmap = np.where(an.dbz > 15, an.confidence, np.nan), "confidence"
        else:
            data, cmap = snap.qpe1h, "qpe1h"
        png = encode_png(self.merc(colorize(cmap, data)), level=3)
        if len(self._png_cache) > 400:
            self._png_cache.clear()
        self._png_cache[key] = png
        return png

    def point(self, lat: float, lon: float) -> dict | None:
        snap = self.snapshot
        loc = self.grid.ij_int(lat, lon)
        if snap is None or loc is None:
            return None
        i, j = loc
        sl = (slice(max(i - 1, 0), i + 2), slice(max(j - 1, 0), j + 2))
        nc, an = snap.nowcast, snap.analysis

        def series(name):
            a = nc.products[name][:, sl[0], sl[1]].astype(np.float32)
            return [round(float(x), 2) for x in a.reshape(a.shape[0], -1).max(axis=1)]

        out = {"lat": lat, "lon": lon, "leads": nc.leads, "where": describe_location(lat, lon, self.places)}
        for p in PRODUCTS:
            out[p] = series(p)
        out["now"] = {
            "dbz": round(float(an.dbz[i, j]), 1),
            "bt": None if an.bt is None else round(float(an.bt[i, j]), 1),
            "bt_trend": None if an.bt_trend is None else round(float(an.bt_trend[i, j]), 1),
            "lightning": round(float(an.lightning_density[i, j]), 2),
            "confidence": round(float(an.confidence[i, j]), 2),
            "source": ["none", "radar", "satellite+lightning proxy"][int(an.source_map[i, j])],
            "radar_coverage": bool(an.radar_coverage[i, j]),
            "outflow": round(float(an.outflow[i, j]), 1),
            "qpe1h": round(float(snap.qpe1h[i, j]), 1),
        }
        return out

    # ============================================================ controls
    def set_speed(self, speed: float) -> float:
        if self.simulated and not self.warming_up:
            self.clock.set_speed(float(np.clip(speed, 0.0, 120.0)))
        return self.clock.speed

    def set_source_enabled(self, source_id: str, enabled: bool) -> bool:
        for s in self.sources:
            if s.id == source_id:
                s.enabled = enabled
                self.add_event("feed", f"{'Restored' if enabled else 'Simulated outage of'} {s.label}", None, None,
                               severity=0 if enabled else 1)
                return True
        return False

    def spawn(self, lat: float, lon: float, kind: str = "hail", mature: bool = False) -> dict:
        if not self.simulated or not self.grid.contains(lat, lon):
            raise ValueError("storm injection is only available in simulated mode, inside the domain")
        from .truth import KINDS

        if kind not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        now = self.clock.now()
        c = self.truth.add_cell(kind, lat, lon, now)
        if mature:
            c.t0 = now - (c.tc + c.tg) - 60
        self.add_event("demo", f"Demo: injected {'mature' if mature else 'initiating'} {kind.replace('_', ' ')} storm "
                               f"{describe_location(lat, lon, self.places)}", lat, lon)
        return {"id": c.id, "kind": kind, "mature": mature}
