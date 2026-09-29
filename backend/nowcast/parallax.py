"""Geostationary parallax geometry and correction.

Tall convective tops seen from INSAT-3D/3DR (74-82 E) appear displaced away
from the sub-satellite point by roughly H * tan(zenith) - about 9 km for a
15 km anvil over Kolkata, i.e. several 2-km grid cells.  We correct this
before fusing satellite with radar so cloud-top cooling lines up with the
radar echoes underneath.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from .grid import Grid


def parallax_unit_shift(grid: Grid, sat_lon: float) -> tuple[np.ndarray, np.ndarray]:
    """Apparent displacement (rows, cols) per km of cloud height for a geostationary view."""
    Re, Rs = 6371.0, 42164.0
    lat = np.radians(grid.LAT)
    dlon = np.radians(grid.LON - sat_lon)
    cosg = np.cos(lat) * np.cos(dlon)
    sing = np.sqrt(np.clip(1 - cosg ** 2, 0, None))
    tan_zen = sing / (cosg - Re / Rs)
    # azimuth of the pixel as seen from the sub-satellite point (0N, sat_lon)
    az = np.arctan2(np.sin(dlon) * np.cos(lat), np.sin(lat))
    d_north = tan_zen * np.cos(az)
    d_east = tan_zen * np.sin(az)
    di = (-d_north / grid.dy_km).astype(np.float32)
    dj = (d_east / grid.dx_km).astype(np.float32)
    return di, dj


def cloud_top_height_km(bt: np.ndarray, bt_surface: float = 303.0) -> np.ndarray:
    """Crude cloud-top height from IR brightness temperature (moist-adiabatic ~7 K/km)."""
    return np.clip((bt_surface - bt) / 7.0, 0.0, 17.0)


class ParallaxCorrector:
    def __init__(self, grid: Grid, sat_lon: float):
        self.grid = grid
        self.di, self.dj = parallax_unit_shift(grid, sat_lon)
        self.ii, self.jj = np.mgrid[0:grid.ny, 0:grid.nx].astype(np.float32)

    def correct(self, bt_obs: np.ndarray) -> np.ndarray:
        """Move observed cloud tops back over their true ground position."""
        h = cloud_top_height_km(bt_obs)
        h = ndimage.gaussian_filter(ndimage.maximum_filter(h, 5), 1.5)
        di_o, dj_o = self.di * h, self.dj * h
        # Fixed-point iteration: d(x0) = D_obs(x0 + d(x0))
        pi, pj = self.ii + di_o, self.jj + dj_o
        for _ in range(2):
            di = ndimage.map_coordinates(di_o, [pi, pj], order=1, mode="nearest")
            dj = ndimage.map_coordinates(dj_o, [pi, pj], order=1, mode="nearest")
            pi, pj = self.ii + di, self.jj + dj
        return ndimage.map_coordinates(bt_obs, [pi, pj], order=1, mode="nearest").astype(np.float32)
