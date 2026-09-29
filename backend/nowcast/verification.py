"""Online verification of the reflectivity nowcast against later analyses.

For leads of 30/60/120 min the forecast >=35 dBZ mask is stored and, once
the valid time is analysed, compared with the observed mask (inside radar
coverage only).  A persistence (no-motion) forecast is scored alongside as
the baseline the system must beat.
"""
from __future__ import annotations

import collections

import numpy as np
from scipy import ndimage

THRESH = 35.0
LEADS = (30, 60, 120)


def _scores(fc: np.ndarray, ob: np.ndarray, mask: np.ndarray) -> tuple[int, int, int]:
    # 3x3 tolerance (~6 km) so near-misses of small cells are not double penalised
    fc_t = ndimage.binary_dilation(fc, iterations=1)
    ob_t = ndimage.binary_dilation(ob, iterations=1)
    hits = int((fc & ob_t & mask).sum())
    misses = int((ob & ~fc_t & mask).sum())
    fa = int((fc & ~ob_t & mask).sum())
    return hits, misses, fa


class Verifier:
    def __init__(self):
        self.pending: dict[int, list[tuple[int, np.ndarray, np.ndarray]]] = collections.defaultdict(list)
        self.samples = {L: collections.deque(maxlen=24) for L in LEADS}

    def add_forecast(self, t: float, leads: list[int], dbz_fc: np.ndarray, dbz_now: np.ndarray) -> None:
        for L in LEADS:
            if L not in leads:
                continue
            k = leads.index(L)
            valid = int(round((t + L * 60) / 60.0))
            self.pending[valid].append((L, dbz_fc[k].astype(np.float32) >= THRESH, dbz_now >= THRESH))

    def verify(self, t: float, dbz_obs: np.ndarray, coverage: np.ndarray) -> None:
        key = int(round(t / 60.0))
        for kk in [k for k in self.pending if k <= key - 3]:
            del self.pending[kk]
        items = []
        for kk in (key - 1, key, key + 1):
            items += self.pending.pop(kk, [])
        ob = dbz_obs >= THRESH
        for L, fc, persist in items:
            h, m, f = _scores(fc, ob, coverage)
            hp, mp, fp = _scores(persist, ob, coverage)
            if h + m + f + hp + mp + fp == 0:
                continue
            self.samples[L].append((h, m, f, hp, mp, fp))

    def summary(self) -> dict:
        out = {}
        for L, s in self.samples.items():
            if not s:
                out[str(L)] = None
                continue
            a = np.array(s).sum(axis=0)
            h, m, f, hp, mp, fp = (float(x) for x in a)

            def csi(h, m, f):
                return h / (h + m + f) if h + m + f else None

            out[str(L)] = {
                "csi": _r(csi(h, m, f)), "pod": _r(h / (h + m) if h + m else None),
                "far": _r(f / (h + f) if h + f else None), "csi_persistence": _r(csi(hp, mp, fp)),
                "n": len(s),
            }
        return out


def _r(x):
    return None if x is None else round(x, 3)
