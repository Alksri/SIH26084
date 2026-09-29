"""Common analysis grid shared by every data source.

Rows run north -> south (image order), columns west -> east.
Velocities inside the pipeline are expressed in grid cells per minute
(``vi`` = rows/min, positive southward; ``vj`` = cols/min, positive eastward).
"""
from __future__ import annotations

import math

import numpy as np

from .config import GridConfig

KM_PER_DEG = 111.195


class Grid:
    def __init__(self, cfg: GridConfig):
        self.cfg = cfg
        self.res = cfg.res_deg
        self.lat_min, self.lat_max = cfg.lat_min, cfg.lat_max
        self.lon_min, self.lon_max = cfg.lon_min, cfg.lon_max
        self.ny = int(round((cfg.lat_max - cfg.lat_min) / cfg.res_deg))
        self.nx = int(round((cfg.lon_max - cfg.lon_min) / cfg.res_deg))
        self.lats = (cfg.lat_max - (np.arange(self.ny) + 0.5) * cfg.res_deg).astype(np.float64)
        self.lons = (cfg.lon_min + (np.arange(self.nx) + 0.5) * cfg.res_deg).astype(np.float64)
        self.LAT, self.LON = np.meshgrid(self.lats, self.lons, indexing="ij")
        self.lat0 = 0.5 * (cfg.lat_min + cfg.lat_max)
        self.dy_km = cfg.res_deg * KM_PER_DEG
        self.dx_km = cfg.res_deg * KM_PER_DEG * math.cos(math.radians(self.lat0))
        # Per-row cell area (km^2) for density products.
        self.cell_area_km2 = (
            self.dy_km * cfg.res_deg * KM_PER_DEG * np.cos(np.radians(self.lats))
        )[:, None].astype(np.float32)
        self.mean_dx_km = 0.5 * (self.dx_km + self.dy_km)

    # --- index helpers -------------------------------------------------
    def ij(self, lat, lon):
        i = (self.lat_max - np.asarray(lat)) / self.res - 0.5
        j = (np.asarray(lon) - self.lon_min) / self.res - 0.5
        return i, j

    def ij_int(self, lat: float, lon: float) -> tuple[int, int] | None:
        i, j = self.ij(lat, lon)
        i, j = int(round(float(i))), int(round(float(j)))
        if 0 <= i < self.ny and 0 <= j < self.nx:
            return i, j
        return None

    def latlon(self, i, j):
        lat = self.lat_max - (np.asarray(i) + 0.5) * self.res
        lon = self.lon_min + (np.asarray(j) + 0.5) * self.res
        return lat, lon

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max

    def window(self, lat: float, lon: float, radius_km: float):
        """Row/col bounding box (i0, i1, j0, j1) of a circle, clipped to the grid."""
        di = radius_km / self.dy_km
        dj = radius_km / (KM_PER_DEG * self.res * max(math.cos(math.radians(lat)), 0.2))
        ci, cj = self.ij(lat, lon)
        i0 = max(int(math.floor(ci - di)), 0)
        i1 = min(int(math.ceil(ci + di)) + 1, self.ny)
        j0 = max(int(math.floor(cj - dj)), 0)
        j1 = min(int(math.ceil(cj + dj)) + 1, self.nx)
        if i0 >= i1 or j0 >= j1:
            return None
        return i0, i1, j0, j1

    def offsets_km(self, win, lat0: float, lon0: float):
        """(north_km, east_km) offsets of the cells in ``win`` from a reference point."""
        i0, i1, j0, j1 = win
        north = (self.lats[i0:i1, None] - lat0) * KM_PER_DEG
        east = (self.lons[None, j0:j1] - lon0) * KM_PER_DEG * math.cos(math.radians(lat0))
        return np.broadcast_to(north, (i1 - i0, j1 - j0)), np.broadcast_to(east, (i1 - i0, j1 - j0))

    # --- velocity conversion -------------------------------------------
    def ms_to_cells_per_min(self, u, v):
        """(east m/s, north m/s) -> (vi, vj) in cells/min."""
        vi = -np.asarray(v) * 60.0 / (self.dy_km * 1000.0)
        vj = np.asarray(u) * 60.0 / (self.dx_km * 1000.0)
        return vi, vj

    def cells_per_min_to_ms(self, vi, vj):
        u = np.asarray(vj) * self.dx_km * 1000.0 / 60.0
        v = -np.asarray(vi) * self.dy_km * 1000.0 / 60.0
        return u, v

    def bounds(self):
        return [[self.lat_min, self.lon_min], [self.lat_max, self.lon_max]]


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(bearing: float) -> str:
    return _COMPASS[int((bearing + 11.25) // 22.5) % 16]
