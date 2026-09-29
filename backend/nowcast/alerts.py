"""Storm-arrival countdowns for cities, airports and farming districts.

ETA is taken from the first forecast frame in which the composite threat at
the place reaches Moderate (level 2), then refined to minute precision with
the motion of the responsible tracked cell (its edge crossing the place).
"""
from __future__ import annotations

import math

import numpy as np

from .detection import Cell
from .grid import Grid, bearing_deg, compass
from .hazards import LEVEL_NAMES
from .nowcast import Nowcast

ARRIVAL_LEVEL = 2


def _cell_arrival_min(cell: Cell, lat: float, lon: float, grid: Grid) -> float | None:
    """Minutes until the edge of a (moving) cell reaches the point, None if it misses."""
    # relative position of place w.r.t. cell, km (east, north)
    dx = (lon - cell.lon) * 111.195 * math.cos(math.radians(lat))
    dy = (lat - cell.lat) * 111.195
    u_km_min = cell.vj * grid.dx_km
    v_km_min = -cell.vi * grid.dy_km
    R = math.sqrt(cell.area_km2 / math.pi) + 6.0  # hazard footprint extends beyond the 40 dBZ core
    a = u_km_min ** 2 + v_km_min ** 2
    b = -2 * (dx * u_km_min + dy * v_km_min)
    c = dx * dx + dy * dy - R * R
    if c <= 0:
        return 0.0
    if a < 1e-6:
        return None
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    t = (-b - math.sqrt(disc)) / (2 * a)
    return t if t >= 0 else None


def place_forecasts(nc: Nowcast, cells: list[Cell], places: list[dict], grid: Grid) -> list[dict]:
    lv = nc.products["level"]
    leads = np.asarray(nc.leads)
    step = int(leads[1] - leads[0]) if len(leads) > 1 else 10
    results = []
    for p in places:
        loc = grid.ij_int(p["lat"], p["lon"])
        if loc is None:
            continue
        i, j = loc
        sl = (slice(max(i - 1, 0), i + 2), slice(max(j - 1, 0), j + 2))
        levels = lv[:, sl[0], sl[1]].reshape(len(leads), -1).max(axis=1)
        hits = np.nonzero(levels >= ARRIVAL_LEVEL)[0]
        entry = {**p, "status": "clear", "eta_min": None, "level_now": int(levels[0]),
                 "level_max": int(levels.max()), "level_name": LEVEL_NAMES[int(levels.max())],
                 "levels": levels.tolist(), "cell_id": None}
        if hits.size:
            k0 = int(hits[0])
            eta = float(leads[k0])
            # refine with the nearest-threat tracked cell
            best = None
            for c in cells:
                if c.level < ARRIVAL_LEVEL:
                    continue
                t_arr = _cell_arrival_min(c, p["lat"], p["lon"], grid)
                if t_arr is None:
                    continue
                lo = leads[k0 - 1] if k0 > 0 else 0.0
                if lo - 5 <= t_arr <= eta + step + 5 and (best is None or t_arr < best[0]):
                    best = (t_arr, c)
            if best is not None:
                eta = float(np.clip(best[0], leads[k0 - 1] if k0 > 0 else 0.0, eta + step))
                entry["cell_id"] = best[1].id
                entry["approach_from"] = compass(bearing_deg(p["lat"], p["lon"], best[1].lat, best[1].lon))
            if k0 == 0 or eta <= 0.5:
                entry["status"] = "impact"
                eta = 0.0
            else:
                entry["status"] = "approaching"
            entry["eta_min"] = round(eta, 1)
            # hazard summary over the impact window (first hour after arrival)
            k1 = min(len(leads), k0 + int(60 / step) + 1)
            win = slice(k0, k1)

            def pmax(name):
                return float(nc.products[name][win, sl[0], sl[1]].astype(np.float32).max())

            entry["hazards"] = {
                "hail_prob": round(pmax("hail"), 2),
                "gust_ms": round(pmax("gust"), 1),
                "lightning": round(pmax("lightning"), 2),
                "cloudburst_prob": round(pmax("cloudburst"), 2),
                "rain1h_mm": round(pmax("rain1h"), 1),
            }
            active = levels[k0:] >= 1
            dur = int(np.argmin(active)) if not active.all() else int(active.size)
            entry["duration_min"] = max(dur, 1) * step
            entry["level_window"] = int(levels[win].max())
        results.append(entry)
    order = {"impact": 0, "approaching": 1, "clear": 2}
    results.sort(key=lambda e: (order[e["status"]], e["eta_min"] if e["eta_min"] is not None else 1e9, -e["level_max"]))
    return results
