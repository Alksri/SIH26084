"""Severe-storm parameter diagnostics from fused (radar + satellite + lightning) fields.

References for the empirical relations used:
* VIL: Greene & Clark (1972), single-layer form VIL = 3.44e-6 Z^(4/7) dH.
* VIL density > ~3.5 g m^-3 as a large-hail discriminator: Amburn & Wolf (1997).
* Peak downburst gust from VIL and echo top: Stewart (1991),
  W = sqrt(20.628571 VIL - 3.125e-6 ET^2)  [m/s, VIL kg m^-2, ET m].
* Convective Z-R: Z = 300 R^1.4 (WSR-88D / IMD convective), hail-capped at 56 dBZ.
* Cloudburst: IMD definition, >= 100 mm rainfall in one hour over a small area.
"""
from __future__ import annotations

import numpy as np

from .parallax import cloud_top_height_km

CLOUDBURST_MM_PER_H = 100.0
LEVEL_NAMES = ["None", "Low", "Moderate", "High", "Extreme"]


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def echo_top_m(bt: np.ndarray | None, dbz: np.ndarray) -> np.ndarray:
    """18-dBZ echo top estimate: IR cloud-top height scaled, or a reflectivity-only fallback."""
    fallback = np.clip(4000.0 + 200.0 * (dbz - 20.0), 3000.0, 13000.0)
    if bt is None:
        return fallback.astype(np.float32)
    h = cloud_top_height_km(np.nan_to_num(bt, nan=300.0)) * 1000.0 * 0.85
    return np.where(np.isfinite(bt), np.maximum(h, 0.6 * fallback), fallback).astype(np.float32)


def vil_kg_m2(dbz: np.ndarray, et_m: np.ndarray) -> np.ndarray:
    z = 10.0 ** (np.clip(dbz, -10.0, 60.0) / 10.0)
    depth = 0.5 * et_m
    vil = 3.44e-6 * z ** (4.0 / 7.0) * depth
    return np.where(dbz > 18, vil, 0.0).astype(np.float32)


def stewart_gust_ms(vil: np.ndarray, et_m: np.ndarray) -> np.ndarray:
    return np.sqrt(np.clip(20.628571 * vil - 3.125e-6 * et_m ** 2, 0.0, None)).astype(np.float32)


def rain_rate_mm_h(dbz: np.ndarray) -> np.ndarray:
    z = 10.0 ** (np.clip(dbz, -10.0, 56.0) / 10.0)
    r = (z / 300.0) ** (1.0 / 1.4)
    return np.where(dbz > 15, r, 0.0).astype(np.float32)


def hail_index(dbz: np.ndarray, vil: np.ndarray, et_m: np.ndarray, bt: np.ndarray | None) -> np.ndarray:
    """0..1 likelihood of hail at the ground from VIL density, core strength and cloud-top coldness."""
    vild = 1000.0 * vil / np.maximum(et_m, 3000.0)  # g m^-3
    h = sigmoid((vild - 3.5) / 0.35) * sigmoid((dbz - 56.0) / 1.8)
    if bt is not None:
        h = h * np.where(np.isfinite(bt), sigmoid((226.0 - np.nan_to_num(bt, nan=300.0)) / 4.0), 0.75)
    return h.astype(np.float32)


def threat_level(p40, p50, lightning, hail, gust, cloudburst) -> np.ndarray:
    lvl = np.zeros(p40.shape, np.uint8)
    lvl[(p40 >= 0.15) | (lightning >= 0.3)] = 1
    lvl[(p50 >= 0.3) | (hail >= 0.25) | (gust >= 15.0) | (lightning >= 2.0) | (cloudburst >= 0.2)] = 2
    lvl[(hail >= 0.5) | (gust >= 22.0) | (lightning >= 5.0) | (cloudburst >= 0.4)] = 3
    lvl[(hail >= 0.75) | (gust >= 28.0) | (cloudburst >= 0.65)] = 4
    return lvl
