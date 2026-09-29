"""Real-time radar from RainViewer's free public API (no key).

RainViewer mosaics national radar networks, including IMD's DWRs where they
share data. Every ~10 min a new frame appears in ``weather-maps.json``. We
download the zoom-7 tiles (~1.1 km/px over India) that cover the analysis
domain, convert the "Universal Blue" colours back to dBZ with RainViewer's
published colour table, and resample the Web-Mercator mosaic onto the common
lat/lon grid.

Limitations: RainViewer only offers reflectivity (no radial velocity, so no
radar-observed outflow). Transparent pixels mean either "no echo" or "no
radar", which cannot be told apart. Coverage depends on which Indian radars
RainViewer currently receives.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import ssl
import urllib.request

import numpy as np

from ..grid import Grid
from .base import DataSource, Emit, Observation
from .rv_colors import UNIVERSAL_BLUE

log = logging.getLogger("nowcast.rainviewer")

API = "https://api.rainviewer.com/public/weather-maps.json"
ZOOM = 7
TILE = 256


def _ssl_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # certifi missing: fall back to the system store
        return ssl.create_default_context()


def _lut():
    """24-bit RGB -> dBZ lookup (NaN = colour not in the table)."""
    lut = np.full(1 << 24, np.nan, np.float32)
    for hexcol, dbz in UNIVERSAL_BLUE:
        lut[int(hexcol, 16)] = dbz
    return lut


class RainViewerSource(DataSource):
    kind = "radar"

    def __init__(self, grid: Grid, poll_s: float = 60.0, backfill: int = 3):
        super().__init__()
        self.grid = grid
        self.id, self.label, self.cadence_s = "RAINVIEWER", "RainViewer radar mosaic (live)", 600.0
        self.poll_s = poll_s
        self.backfill = backfill
        self.ctx = _ssl_context()
        self.lut = _lut()
        self.last_time = 0
        # Web-Mercator pixel coordinates of every grid cell at ZOOM
        n = TILE * 2 ** ZOOM
        lat = np.radians(grid.LAT)
        self.px = (grid.LON + 180.0) / 360.0 * n
        self.py = (1.0 - np.log(np.tan(lat) + 1.0 / np.cos(lat)) / math.pi) / 2.0 * n
        self.tx0, self.tx1 = int(self.px.min() // TILE), int(self.px.max() // TILE)
        self.ty0, self.ty1 = int(self.py.min() // TILE), int(self.py.max() // TILE)

    def _get(self, url: str, timeout: float = 20.0) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "StormSense-nowcast/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as r:
            return r.read()

    def fetch_frame(self, host: str, frame: dict) -> Observation:
        from PIL import Image

        nx, ny = self.tx1 - self.tx0 + 1, self.ty1 - self.ty0 + 1
        mosaic = np.full((ny * TILE, nx * TILE), np.nan, np.float32)
        for ty in range(self.ty0, self.ty1 + 1):
            for tx in range(self.tx0, self.tx1 + 1):
                url = f"{host}{frame['path']}/{TILE}/{ZOOM}/{tx}/{ty}/2/0_0.png"
                try:
                    img = Image.open(io.BytesIO(self._get(url))).convert("RGBA")
                except Exception as exc:
                    log.warning("tile %s/%s failed: %s", tx, ty, exc)
                    continue
                a = np.asarray(img, dtype=np.uint32)
                rgb = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
                dbz = self.lut[rgb]
                dbz = np.where(a[..., 3] == 0, -10.0, dbz)
                # colours not in the table (edge anti-aliasing): treat as weak echo
                dbz = np.where(np.isnan(dbz), -10.0, dbz)
                oy, ox = (ty - self.ty0) * TILE, (tx - self.tx0) * TILE
                mosaic[oy:oy + TILE, ox:ox + TILE] = dbz
        ix = np.clip((self.px - self.tx0 * TILE).astype(int), 0, mosaic.shape[1] - 1)
        iy = np.clip((self.py - self.ty0 * TILE).astype(int), 0, mosaic.shape[0] - 1)
        dbz = mosaic[iy, ix].astype(np.float32)
        missing = np.isnan(dbz)
        dbz = np.where(missing, -10.0, dbz).astype(np.float32)
        quality = np.where(missing, 0.0, 0.7).astype(np.float32)
        g = self.grid
        payload = {
            "window": (0, g.ny, 0, g.nx), "dbz": dbz, "vr": np.full(dbz.shape, np.nan, np.float32),
            "quality": quality,
            "site": {"id": self.id, "lat": float(g.lat0), "lon": float(0.5 * (g.lon_min + g.lon_max)), "range_km": 0.0},
        }
        return Observation(self.id, "radar", float(frame["time"]), payload,
                           meta={"product": "RainViewer composite reflectivity", "path": frame["path"]})

    async def run(self, emit: Emit) -> None:
        first = True
        while True:
            try:
                maps = json.loads(await asyncio.to_thread(self._get, API))
                host, past = maps["host"], maps["radar"]["past"]
                new = [f for f in past if f["time"] > self.last_time]
                if first:
                    new = new[-self.backfill:]  # warm start: motion + trends need history
                    first = False
                for frame in new:
                    obs = await asyncio.to_thread(self.fetch_frame, host, frame)
                    self.last_time = frame["time"]
                    if self.enabled:
                        await emit(obs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("RainViewer poll failed: %s", exc)
            await asyncio.sleep(self.poll_s)


class NotConnectedSource(DataSource):
    """Placeholder that shows a required-but-unavailable operational feed in the health panel."""

    def __init__(self, id: str, kind: str, label: str, cadence_s: float):
        super().__init__()
        self.id, self.kind, self.label, self.cadence_s = id, kind, label, cadence_s

    async def run(self, emit: Emit) -> None:
        while True:
            await asyncio.sleep(3600)
