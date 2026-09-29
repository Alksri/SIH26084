"""Server-side rendering of grid products to transparent PNG overlays.

Rows are resampled from the regular lat/lon grid to Web-Mercator spacing so
that the overlay registers exactly on slippy-map basemaps (a plain stretch
would misplace features by up to ~10 km over an 8-degree domain).
"""
from __future__ import annotations

import math
import struct
import zlib

import numpy as np

from .grid import Grid

# (value, r, g, b, a) stops; values below the first stop are transparent
COLORMAPS = {
    "dbz": [(15, 0, 236, 236, 110), (20, 1, 160, 246, 170), (25, 0, 0, 246, 190), (30, 0, 255, 0, 200),
            (35, 0, 200, 0, 210), (40, 0, 144, 0, 220), (45, 255, 255, 0, 230), (50, 231, 192, 0, 235),
            (55, 255, 144, 0, 240), (60, 255, 0, 0, 245), (65, 214, 0, 0, 250), (70, 192, 0, 192, 255)],
    "lightning": [(0.05, 255, 255, 150, 60), (0.3, 255, 230, 60, 150), (1.0, 255, 170, 0, 200),
                  (3.0, 255, 80, 0, 225), (6.0, 230, 0, 60, 240), (12.0, 255, 255, 255, 250)],
    "hail": [(0.05, 120, 220, 120, 70), (0.2, 200, 240, 60, 140), (0.4, 255, 220, 0, 190),
             (0.6, 255, 130, 0, 220), (0.8, 235, 20, 40, 240), (1.0, 200, 0, 200, 250)],
    "gust": [(8, 150, 200, 255, 50), (12, 120, 230, 200, 120), (15, 255, 240, 80, 170), (20, 255, 160, 0, 205),
             (25, 240, 40, 30, 230), (30, 180, 0, 200, 245), (40, 255, 255, 255, 250)],
    "cloudburst": [(0.05, 140, 200, 255, 70), (0.2, 60, 140, 255, 150), (0.4, 40, 60, 240, 200),
                   (0.6, 150, 40, 230, 225), (0.8, 230, 0, 200, 245)],
    "rain1h": [(2, 170, 220, 255, 70), (10, 90, 170, 255, 140), (25, 30, 90, 240, 180), (50, 60, 200, 60, 200),
               (75, 255, 200, 0, 220), (100, 255, 60, 0, 235), (150, 200, 0, 200, 250)],
    "qpe1h": [(2, 170, 220, 255, 70), (10, 90, 170, 255, 140), (25, 30, 90, 240, 180), (50, 60, 200, 60, 200),
              (75, 255, 200, 0, 220), (100, 255, 60, 0, 235), (150, 200, 0, 200, 250)],
    # IR: inverted (colder = more opaque / colourful)
    "ir": [(-300, 0, 0, 0, 0), (-262, 160, 160, 160, 30), (-245, 220, 220, 220, 120), (-232, 120, 220, 255, 160),
           (-221, 30, 120, 255, 190), (-211, 0, 210, 80, 210), (-204, 255, 230, 0, 225), (-198, 255, 60, 0, 240),
           (-190, 230, 0, 230, 250)],
    "confidence": [(0.02, 200, 60, 60, 90), (0.3, 230, 170, 40, 100), (0.6, 120, 200, 90, 100), (1.0, 40, 160, 255, 110)],
}

LEVEL_RGBA = np.array([[0, 0, 0, 0], [255, 235, 59, 95], [255, 152, 0, 140], [244, 40, 40, 170], [206, 0, 220, 190]],
                      np.uint8)

LEGENDS = {
    "dbz": {"unit": "dBZ", "title": "Reflectivity"},
    "lightning": {"unit": "fl km⁻² h⁻¹", "title": "Lightning density"},
    "hail": {"unit": "prob.", "title": "Hail probability"},
    "gust": {"unit": "m/s", "title": "Downburst gust"},
    "cloudburst": {"unit": "prob.", "title": "Cloudburst (≥100 mm/h) probability"},
    "rain1h": {"unit": "mm", "title": "Rain next 1 h"},
    "qpe1h": {"unit": "mm", "title": "Observed rain last 1 h"},
    "ir": {"unit": "K", "title": "INSAT-3DR TIR1 BT"},
    "confidence": {"unit": "", "title": "Fusion confidence"},
    "level": {"unit": "", "title": "Composite threat"},
}


def legend_stops(name: str) -> list:
    if name == "level":
        return [{"v": k, "c": f"rgba({r},{g},{b},{a / 255:.2f})"} for k, (r, g, b, a) in enumerate(LEVEL_RGBA.tolist())][1:]
    stops = COLORMAPS[name]
    sign = -1 if name == "ir" else 1
    return [{"v": sign * v, "c": f"rgba({r},{g},{b},{max(a, 150) / 255:.2f})"} for v, r, g, b, a in stops if v > -299]


def colorize(name: str, data: np.ndarray) -> np.ndarray:
    if name == "level":
        return LEVEL_RGBA[np.clip(data.astype(np.int64), 0, 4)]
    stops = COLORMAPS[name]
    v = data.astype(np.float32)
    if name == "ir":
        v = -v
    xs = np.array([s[0] for s in stops], np.float32)
    rgba = np.empty(v.shape + (4,), np.uint8)
    for c in range(4):
        rgba[..., c] = np.interp(v, xs, np.array([s[c + 1] for s in stops], np.float32)).astype(np.uint8)
    rgba[..., 3] = np.where((v >= xs[0]) & np.isfinite(v), rgba[..., 3], 0)
    return rgba


class MercatorRows:
    def __init__(self, grid: Grid):
        def merc(lat):
            return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

        y_top, y_bot = merc(grid.lat_max), merc(grid.lat_min)
        n = grid.ny
        ys = y_top + (np.arange(n) + 0.5) / n * (y_bot - y_top)
        lats = np.degrees(2 * np.arctan(np.exp(ys)) - math.pi / 2)
        rows = np.round((grid.lat_max - lats) / grid.res - 0.5).astype(int)
        self.rows = np.clip(rows, 0, n - 1)

    def __call__(self, a: np.ndarray) -> np.ndarray:
        return a[self.rows]


def encode_png(rgba: np.ndarray, level: int = 6) -> bytes:
    h, w, _ = rgba.shape
    raw = np.concatenate([np.zeros((h, 1), np.uint8), rgba.reshape(h, w * 4)], axis=1).tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, level)) + chunk(b"IEND", b"")
