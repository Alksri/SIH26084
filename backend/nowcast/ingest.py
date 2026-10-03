"""Real-time ingestion engine.

Receives ``Observation`` objects from any number of asynchronous feeds,
applies per-sensor quality control, keeps short rolling buffers and tracks
feed health (latency, cadence, outages).  The analysis cycle takes an
immutable snapshot of these buffers so ingestion never blocks on compute.
"""
from __future__ import annotations

import collections
import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy import ndimage

from .grid import Grid
from .sources.base import Observation
from .truth import STRIKE_DTYPE

log = logging.getLogger("nowcast.ingest")


@dataclass
class FeedStats:
    id: str
    kind: str
    label: str
    cadence_s: float
    expected_delay_s: float = 0.0  # publication delay that is normal for this feed (e.g. NASA GIBS ~1 h)
    count: int = 0
    rejected: int = 0
    last_obs_time: float | None = None
    last_arrival: float | None = None
    latencies: collections.deque = field(default_factory=lambda: collections.deque(maxlen=20))
    qc_notes: str = ""

    def status(self, now: float) -> str:
        if self.last_arrival is None:
            return "WAITING"
        age = now - (self.last_obs_time or 0)
        if age > 3.0 * self.cadence_s + 600 + self.expected_delay_s:
            return "DOWN"
        if age > 1.6 * self.cadence_s + max(self.latency(), self.expected_delay_s, 0) + 60:
            return "STALE"
        return "OK"

    def latency(self) -> float:
        return float(np.mean(self.latencies)) if self.latencies else 0.0

    def to_dict(self, now: float) -> dict:
        return {
            "id": self.id, "kind": self.kind, "label": self.label, "cadence_s": self.cadence_s,
            "count": self.count, "rejected": self.rejected, "last_obs_time": self.last_obs_time,
            "latency_s": round(self.latency(), 1), "status": self.status(now), "qc": self.qc_notes,
        }


@dataclass
class IngestSnapshot:
    time: float
    radars: list[Observation]
    satellites: list[Observation]
    strikes: np.ndarray


class IngestEngine:
    def __init__(self, grid: Grid, clock_now: Callable[[], float], radar_max_age_s: float, sat_max_age_s: float):
        self.grid = grid
        self.now = clock_now
        self.radar_max_age_s = radar_max_age_s
        self.sat_max_age_s = sat_max_age_s
        self.radar_latest: dict[str, Observation] = {}
        self.sat_history: collections.deque[Observation] = collections.deque(maxlen=4)
        self._strike_chunks: collections.deque[np.ndarray] = collections.deque()
        self.stats: dict[str, FeedStats] = {}
        self.listeners: list[Callable[[Observation], None]] = []

    def register(self, source) -> None:
        self.stats[source.id] = FeedStats(source.id, source.kind, source.label, source.cadence_s,
                                          expected_delay_s=getattr(source, "expected_delay_s", 0.0))

    # ------------------------------------------------------------------ intake
    async def emit(self, obs: Observation) -> None:
        obs.arrival_time = self.now()
        st = self.stats.get(obs.source_id)
        if st is None:  # e.g. a new radar site appearing in an ODIM drop folder
            cadence = 600.0 if obs.kind == "radar" else 900.0 if obs.kind == "satellite" else 60.0
            st = self.stats[obs.source_id] = FeedStats(obs.source_id, obs.kind, obs.source_id, cadence)
        try:
            ok = self._qc(obs, st)
        except Exception as exc:
            log.exception("QC failure on %s", obs.source_id)
            ok, st.qc_notes = False, f"QC error: {exc}"
        if not ok:
            st.rejected += 1
            return
        st.count += 1
        st.last_obs_time = max(st.last_obs_time or 0.0, obs.obs_time)
        st.last_arrival = obs.arrival_time
        st.latencies.append(obs.arrival_time - obs.obs_time)
        self._store(obs)
        for fn in self.listeners:
            fn(obs)

    def _qc(self, obs: Observation, st: FeedStats) -> bool:
        if obs.kind == "radar":
            return self._qc_radar(obs, st)
        if obs.kind == "satellite":
            return self._qc_satellite(obs, st)
        if obs.kind == "lightning":
            return self._qc_lightning(obs, st)
        return False

    def _qc_radar(self, obs: Observation, st: FeedStats) -> bool:
        p = obs.payload
        dbz, vr = p["dbz"], p["vr"]
        if dbz is None or not np.isfinite(dbz).any():
            st.qc_notes = "empty sweep"
            return False
        prev = self.radar_latest.get(obs.source_id)
        if prev is not None and prev.obs_time >= obs.obs_time:
            st.qc_notes = "out-of-order scan dropped"
            return False
        d = np.nan_to_num(dbz, nan=-10.0)
        # 1) Zero-velocity ground clutter: strong, stationary, spatially noisy targets.
        vr0 = np.nan_to_num(vr, nan=99.0)
        texture = np.abs(d - ndimage.median_filter(d, 3))
        clutter = (d > 30) & (np.abs(vr0) < 0.8) & (texture > 6)
        # 2) Isolated speckle: echoes with no support from their neighbours.
        echo = d > 15
        support = ndimage.uniform_filter(echo.astype(np.float32), 3) * 9
        speckle = echo & (support < 3.5)
        bad = clutter | speckle
        d = np.where(bad, -10.0, d)
        p["dbz"] = np.where(np.isfinite(dbz), d, np.nan).astype(np.float32)
        p["vr"] = np.where(bad, np.nan, vr).astype(np.float32)
        st.qc_notes = f"clutter {int(clutter.sum())} px, speckle {int(speckle.sum())} px removed"
        return True

    def _qc_satellite(self, obs: Observation, st: FeedStats) -> bool:
        tir = obs.payload.get("tir1")
        if tir is None:
            st.qc_notes = "missing TIR1"
            return False
        bad = ~np.isfinite(tir) | (tir < 165) | (tir > 335)
        frac = float(bad.mean())
        if frac > 0.5:
            st.qc_notes = f"{frac:.0%} invalid pixels - rejected"
            return False
        if bad.any():
            # normalised convolution: fill gaps with the mean of valid neighbours
            good = (~bad).astype(np.float32)
            num = ndimage.uniform_filter(np.where(bad, 0.0, tir).astype(np.float32), 7)
            den = ndimage.uniform_filter(good, 7)
            filled = np.where(den > 0.05, num / np.maximum(den, 1e-6), 300.0)
            obs.payload["tir1"] = np.where(bad, filled, tir).astype(np.float32)
        if self.sat_history and self.sat_history[-1].obs_time >= obs.obs_time:
            st.qc_notes = "duplicate/out-of-order image dropped"
            return False
        st.qc_notes = f"{frac:.2%} invalid pixels repaired"
        return True

    def _qc_lightning(self, obs: Observation, st: FeedStats) -> bool:
        s = obs.payload["strikes"]
        if s.size == 0:
            st.qc_notes = "no flashes in batch"
            return True
        g = self.grid
        keep = (s["lat"] >= g.lat_min) & (s["lat"] <= g.lat_max) & (s["lon"] >= g.lon_min) & (s["lon"] <= g.lon_max)
        keep &= s["t"] <= self.now() + 60
        s = s[keep]
        # de-duplicate reports within 1 ms and ~100 m (overlapping sensors)
        if s.size > 1:
            key = np.round(s["t"], 3) * 1e6 + np.round(s["lat"], 3) * 1e3 + np.round(s["lon"], 3)
            _, idx = np.unique(key, return_index=True)
            s = s[np.sort(idx)]
        obs.payload["strikes"] = s
        st.qc_notes = f"{int(keep.size - keep.sum())} out-of-domain dropped"
        return True

    def _store(self, obs: Observation) -> None:
        if obs.kind == "radar":
            self.radar_latest[obs.source_id] = obs
        elif obs.kind == "satellite":
            self.sat_history.append(obs)
        elif obs.kind == "lightning":
            if obs.payload["strikes"].size:
                self._strike_chunks.append(obs.payload["strikes"])
            cutoff = self.now() - 3600
            while self._strike_chunks and self._strike_chunks[0]["t"].max() < cutoff:
                self._strike_chunks.popleft()

    # ---------------------------------------------------------------- snapshot
    def snapshot(self, t: float) -> IngestSnapshot:
        radars = [o for o in self.radar_latest.values() if 0 <= t - o.obs_time <= self.radar_max_age_s]
        sats = [o for o in self.sat_history if t - o.obs_time <= self.sat_max_age_s and o.obs_time <= t]
        strikes = self.strikes_between(t - 3600, t)
        return IngestSnapshot(t, radars, sats, strikes)

    def strikes_between(self, t1: float, t2: float) -> np.ndarray:
        if not self._strike_chunks:
            return np.zeros(0, STRIKE_DTYPE)
        s = np.concatenate(list(self._strike_chunks))
        return s[(s["t"] >= t1) & (s["t"] <= t2)]

    def health(self) -> list[dict]:
        now = self.now()
        return [st.to_dict(now) for st in self.stats.values()]
