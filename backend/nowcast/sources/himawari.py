"""Real-time infrared satellite from NASA GIBS (free, no key): Himawari-9 AHI band 13 (10.4 um).

INSAT-3DR imagery needs a MOSDAC account, so the realtime mode uses the
Himawari "clean longwave infrared window" layer that NASA GIBS republishes
every 10 minutes (typically ~1 h behind real time). Himawari-9 sits at
140.7 E; East India (83-92 E) is inside its disk at a ~50 deg view angle,
so tops are parallax-corrected for that position (see ``sat_lon`` below).

GIBS serves a colour-mapped PNG. Its published colour map assigns every
colour to a 1 deg C brightness-temperature bin, so we invert it back to BT
(K) and request the image directly on the analysis grid (WMS, EPSG:4326).
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import ssl
import time
import urllib.request

import numpy as np

from ..grid import Grid
from .base import DataSource, Emit, Observation

log = logging.getLogger("nowcast.himawari")

LAYER = "Himawari_AHI_Band13_Clean_Infrared"
WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
COLORMAP = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/Clean_Longwave_Infrared_Window_Band.xml"
SAT_LON = 140.7
STEP_S = 600


def _ssl_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def parse_colormap(xml: str) -> tuple[np.ndarray, np.ndarray]:
    """GIBS colour map -> (rgb[n,3], bt_kelvin[n]) using each bin's midpoint."""
    rgbs, temps = [], []
    for rgb, value in re.findall(r'<ColorMapEntry rgb="(\d+,\d+,\d+)"[^>]*?value="([^"]+)"', xml):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", value)]
        if not nums:
            continue
        c = sum(nums) / len(nums)  # "(a,b]" -> midpoint; open-ended "<a"/">b" -> a/b
        rgbs.append([int(x) for x in rgb.split(",")])
        temps.append(c + 273.15)
    if len(rgbs) < 50:
        raise ValueError("colour map looks incomplete")
    return np.asarray(rgbs, np.float32), np.asarray(temps, np.float32)


class HimawariSource(DataSource):
    kind = "satellite"

    def __init__(self, grid: Grid, poll_s: float = 300.0):
        super().__init__()
        self.grid = grid
        self.id, self.label, self.cadence_s = "HIMAWARI-9", "Himawari-9 infrared via NASA GIBS (live)", 600.0
        self.poll_s = poll_s
        self.expected_delay_s = 5400.0  # GIBS publishes Himawari ~40-90 min after the scan
        self.ctx = _ssl_context()
        self.palette: tuple[np.ndarray, np.ndarray] | None = None
        self.last_time = 0.0

    def _get(self, url: str, timeout: float = 40.0) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "BUMBLEBLE-nowcast/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as r:
            return r.read()

    def _url(self, t: float) -> str:
        g = self.grid
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        return (f"{WMS}?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS={LAYER}&STYLES=&CRS=EPSG:4326"
                f"&BBOX={g.lat_min},{g.lon_min},{g.lat_max},{g.lon_max}&WIDTH={g.nx}&HEIGHT={g.ny}"
                f"&FORMAT=image/png&TIME={stamp}")

    def fetch(self, t: float) -> np.ndarray | None:
        """Brightness temperature (K) on the grid for scan time ``t``, or None if GIBS has no image yet."""
        from PIL import Image

        if self.palette is None:
            self.palette = parse_colormap(self._get(COLORMAP).decode("utf-8", "replace"))
        img = np.asarray(Image.open(io.BytesIO(self._get(self._url(t)))).convert("RGBA"))
        if img.shape[:2] != (self.grid.ny, self.grid.nx):
            img = np.asarray(Image.fromarray(img).resize((self.grid.nx, self.grid.ny), Image.NEAREST))
        alpha = img[..., 3]
        if (alpha == 0).mean() > 0.9:
            return None  # not published yet (GIBS returns a transparent image)
        rgb = img[..., :3].reshape(-1, 3).astype(np.float32)
        cols, inv = np.unique(rgb, axis=0, return_inverse=True)
        pal_rgb, pal_bt = self.palette
        # nearest palette colour (resampling can blend neighbouring bins)
        d = ((cols[:, None, :] - pal_rgb[None, :, :]) ** 2).sum(-1)
        bt = pal_bt[d.argmin(1)][inv.ravel()].reshape(self.grid.ny, self.grid.nx)
        return np.where(alpha == 0, np.nan, bt).astype(np.float32)

    async def run(self, emit: Emit) -> None:
        first = True
        while True:
            try:
                now = time.time()
                newest = None
                # GIBS lags ~40-90 min: probe back from now in 10-min steps for the newest published scan
                for k in range(2, 16):
                    t = (now // STEP_S - k) * STEP_S
                    if t <= self.last_time:
                        break
                    bt = await asyncio.to_thread(self.fetch, t)
                    if bt is not None:
                        newest = (t, bt)
                        break
                if newest:
                    frames = [newest]
                    if first:
                        # warm start: one earlier scan so cloud-top cooling trends exist immediately
                        prev_t = newest[0] - 2 * STEP_S
                        prev = await asyncio.to_thread(self.fetch, prev_t)
                        if prev is not None:
                            frames.insert(0, (prev_t, prev))
                    for t, bt in frames:
                        self.last_time = t
                        if self.enabled:
                            await emit(Observation(self.id, "satellite", float(t), {"tir1": bt, "wv": None, "sat_lon": SAT_LON},
                                                   meta={"product": "Himawari-9 AHI band 13 (NASA GIBS)"}))
                    first = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Himawari poll failed: %s", exc)
            await asyncio.sleep(self.poll_s)
