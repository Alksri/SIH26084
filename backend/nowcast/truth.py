"""Synthetic "true atmosphere" used to drive the simulated sensor feeds.

It evolves a population of convective cells through a conceptual life cycle
(towering cumulus -> growth -> mature -> dissipation) and renders what each
sensor would see: reflectivity + radial velocity for each DWR, TIR1/WV
brightness temperatures for INSAT-3DR (with parallax + coarser footprint) and
flashes for a ground lightning network.  None of this is used by the
nowcasting pipeline itself - the pipeline only sees the sensor observations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .grid import KM_PER_DEG, Grid
from .parallax import parallax_unit_shift

MIN = 60.0


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


# Parameter ranges per storm archetype: (low, high)
KINDS = {
    "ordinary": dict(tc=(35, 45), tg=(15, 25), tm=(15, 25), td=(25, 35), peak=(45, 52), R=(4, 6),
                     aspect=(1.0, 1.4), min_bt=(214, 224), flash=(2, 6), outflow=(6, 10), overshoot=False),
    "hail": dict(tc=(35, 45), tg=(20, 30), tm=(40, 60), td=(30, 40), peak=(61, 67), R=(5, 7),
                 aspect=(1.0, 1.5), min_bt=(194, 202), flash=(22, 40), outflow=(12, 18), overshoot=True),
    "downburst": dict(tc=(35, 45), tg=(20, 25), tm=(20, 30), td=(30, 40), peak=(57, 61), R=(5, 7),
                      aspect=(1.0, 1.4), min_bt=(200, 208), flash=(12, 25), outflow=(26, 34), overshoot=True),
    "heavy_rain": dict(tc=(35, 45), tg=(25, 35), tm=(100, 150), td=(40, 60), peak=(55, 58), R=(7, 10),
                       aspect=(1.0, 1.6), min_bt=(204, 212), flash=(5, 12), outflow=(6, 10), overshoot=False),
    "squall": dict(tc=(30, 40), tg=(25, 35), tm=(180, 260), td=(40, 60), peak=(56, 62), R=(6, 8),
                   aspect=(2.2, 3.0), min_bt=(198, 206), flash=(15, 30), outflow=(22, 30), overshoot=True),
}

# Climatological CI hot-spots for pre-monsoon convection: (lat, lon, sigma_deg, weight, kind probs)
ZONES = [
    (23.4, 85.3, 0.9, 3.0, {"ordinary": .40, "hail": .30, "downburst": .25, "heavy_rain": .05}),   # Chota Nagpur
    (25.6, 86.0, 0.9, 2.0, {"ordinary": .45, "hail": .20, "downburst": .30, "heavy_rain": .05}),   # Bihar plains
    (23.2, 87.6, 0.6, 2.0, {"ordinary": .40, "hail": .25, "downburst": .30, "heavy_rain": .05}),   # Gangetic WB
    (21.0, 84.9, 0.7, 1.5, {"ordinary": .50, "hail": .20, "downburst": .20, "heavy_rain": .10}),   # Odisha interior
    (25.4, 91.5, 0.35, 1.2, {"ordinary": .20, "hail": .10, "downburst": .05, "heavy_rain": .65}),  # Meghalaya
    (26.7, 88.4, 0.35, 1.0, {"ordinary": .40, "hail": .30, "downburst": .10, "heavy_rain": .20}),  # Sub-Himalayan WB
    (23.8, 91.4, 0.45, 1.0, {"ordinary": .45, "hail": .15, "downburst": .15, "heavy_rain": .25}),  # Tripura
]


@dataclass
class TruthCell:
    id: int
    kind: str
    lat: float
    lon: float
    u: float  # m/s eastward
    v: float  # m/s northward
    t0: float
    tc: float
    tg: float
    tm: float
    td: float
    peak: float
    R: float
    aspect: float
    theta: float  # major-axis orientation (radians CCW from east)
    min_bt: float
    flash_max: float
    outflow_max: float
    overshoot: bool

    @property
    def total(self) -> float:
        return self.tc + self.tg + self.tm + self.td

    def echo(self, t: float) -> float:
        a = t - self.t0
        start = 0.75 * self.tc
        if a <= start:
            return 0.0
        if a < self.tc + self.tg:
            return float(smoothstep((a - start) / (self.tc + self.tg - start)))
        if a < self.tc + self.tg + self.tm:
            return 1.0
        if a < self.total:
            return float(1.0 - smoothstep((a - self.tc - self.tg - self.tm) / self.td))
        return 0.0

    def cloud(self, t: float) -> float:
        a = t - self.t0
        if a <= 0:
            return 0.0
        if a < self.tc:
            return float(0.5 * smoothstep(a / self.tc))
        if a < self.tc + self.tg:
            return float(0.5 + 0.5 * smoothstep((a - self.tc) / self.tg))
        if a < self.tc + self.tg + self.tm:
            return 1.0
        tail = self.td + 40 * MIN
        return float(max(0.0, 1.0 - smoothstep((a - self.tc - self.tg - self.tm) / tail)))

    def flash_rate(self, t: float) -> float:
        """Flashes per minute (total lightning)."""
        a = t - self.t0
        e = self.echo(t)
        if a < self.tc or e <= 0:
            return 0.0
        rate = self.flash_max * float(smoothstep((e - 0.55) / 0.35))
        if a > self.tc + self.tg + self.tm:  # dissipating: lightning dies faster than the echo
            rate *= e ** 1.5
        if self.kind in ("hail", "downburst", "squall"):
            # Lightning "jump" around the growth->mature transition precedes severe weather
            w = 0.3 * self.tg + 5 * MIN
            rate += 0.9 * self.flash_max * math.exp(-(((a - self.tc - self.tg) / w) ** 2))
        return rate

    def outflow(self, t: float) -> float:
        a = t - self.t0
        if self.kind == "squall":
            return self.outflow_max * self.echo(t) ** 2
        a_peak = self.tc + self.tg + self.tm + 0.3 * self.td
        w = 0.3 * self.td + 5 * MIN
        return self.outflow_max * math.exp(-(((a - a_peak) / w) ** 2)) * (1.0 if a > self.tc + self.tg else 0.0)

    def radius(self, t: float) -> float:
        return self.R * (0.55 + 0.45 * self.echo(t))

    def anvil_radius(self, t: float) -> float:
        a = t - self.t0
        grow = float(smoothstep(a / (self.tc + self.tg + self.tm)))
        base = self.R * 1.1
        return base + (3.2 * self.R * (1.0 + 0.3 * (self.aspect - 1.0)) - base) * grow

    def alive(self, t: float) -> bool:
        return t - self.t0 < self.total + 40 * MIN


class TruthModel:
    def __init__(self, grid: Grid, seed: int, sat_lon: float = 74.0):
        self.grid = grid
        self.rng = np.random.default_rng(seed)
        self.cells: list[TruthCell] = []
        self.t: float | None = None
        self._next_id = 1
        self._cache: dict[float, dict] = {}
        ny, nx = grid.ny, grid.nx
        lat, lon = grid.LAT, grid.LON

        # Static environment -------------------------------------------------
        self.sea = lat < np.interp(lon, [83.0, 84.9, 85.8, 86.4, 86.9, 87.5, 88.0, 88.8, 89.5, 90.5, 91.5, 91.9, 92.0],
                                   [18.0, 19.3, 19.8, 20.3, 21.0, 21.6, 21.65, 21.7, 21.9, 22.1, 22.4, 21.5, 20.0])
        self.bt_clear = np.where(self.sea, 297.5, 304.0).astype(np.float32)
        self.bt_clear -= np.clip((lat - 24.0) * 0.6, 0, None).astype(np.float32)  # cooler north
        # Steering flow: WNW flow (Nor'wester) weakening over the NE hills
        ne = 1.0 / (1.0 + np.exp(-((lon - 89.8) / 0.4))) * 1.0 / (1.0 + np.exp(-((lat - 24.6) / 0.3)))
        self.env_u = (12.0 * (1 - ne) + 3.0 * ne).astype(np.float32)
        self.env_v = (-5.0 * (1 - ne) - 0.5 * ne).astype(np.float32)

        # Frozen turbulence texture, translated with the mean flow
        noise = ndimage.gaussian_filter(self.rng.normal(size=(ny, nx)), 2.0)
        self.noise = (noise / noise.std()).astype(np.float32)
        cu = ndimage.gaussian_filter(self.rng.normal(size=(ny, nx)), 1.2)
        self.cu_noise = (cu / cu.std()).astype(np.float32)

        # Parallax geometry for a geostationary imager at sat_lon
        self.parallax_di, self.parallax_dj = parallax_unit_shift(grid, sat_lon)

    # ------------------------------------------------------------------ cells
    def steering(self, lat: float, lon: float) -> tuple[float, float]:
        loc = self.grid.ij_int(min(max(lat, self.grid.lat_min), self.grid.lat_max - 1e-6),
                               min(max(lon, self.grid.lon_min), self.grid.lon_max - 1e-6))
        if loc is None:
            return 10.0, -4.0
        i, j = loc
        return float(self.env_u[i, j]), float(self.env_v[i, j])

    def add_cell(self, kind: str, lat: float, lon: float, t0: float, u: float | None = None,
                 v: float | None = None, theta: float | None = None, **overrides) -> TruthCell:
        spec = KINDS[kind]
        r = self.rng

        def pick(key):
            lo, hi = spec[key]
            return float(r.uniform(lo, hi))

        su, sv = self.steering(lat, lon)
        if u is None:
            u = su + float(r.normal(0, 1.5))
            if kind in ("hail", "downburst"):  # right-moving supercells deviate
                u -= 1.5
                v_dev = -2.0
            else:
                v_dev = 0.0
        else:
            v_dev = 0.0
        if v is None:
            v = sv + v_dev + float(r.normal(0, 1.2))
        if kind == "heavy_rain":
            u *= 0.35
            v *= 0.35
        if theta is None:
            theta = math.atan2(v, u) + math.pi / 2 if kind == "squall" else float(r.uniform(0, math.pi))
        params = dict(
            tc=pick("tc") * MIN, tg=pick("tg") * MIN, tm=pick("tm") * MIN, td=pick("td") * MIN,
            peak=pick("peak"), R=pick("R"), aspect=pick("aspect"), min_bt=pick("min_bt"),
            flash_max=pick("flash"), outflow_max=pick("outflow"), overshoot=spec["overshoot"],
        )
        params.update(overrides)
        cell = TruthCell(id=self._next_id, kind=kind, lat=lat, lon=lon, u=u, v=v, t0=t0, theta=theta, **params)
        self._next_id += 1
        self.cells.append(cell)
        return cell

    def add_squall_line(self, lat: float, lon: float, t0: float, n: int = 6, length_km: float = 180.0,
                        u: float = 14.0, v: float = -5.0) -> list[TruthCell]:
        heading = math.atan2(v, u)
        along = heading + math.pi / 2  # line is perpendicular to motion
        out = []
        for k in range(n):
            s = (k / (n - 1) - 0.5) * length_km
            clat = lat + s * math.sin(along) / KM_PER_DEG
            clon = lon + s * math.cos(along) / (KM_PER_DEG * math.cos(math.radians(lat)))
            out.append(self.add_cell("squall", clat, clon, t0 - float(self.rng.uniform(0, 15)) * MIN,
                                     u=u + float(self.rng.normal(0, 0.8)), v=v + float(self.rng.normal(0, 0.6)),
                                     theta=along))
        return out

    def seed_scenario(self, t_start: float) -> None:
        """Initial weather situation for the demo (times relative to scenario start)."""
        T = t_start
        # 1. Nor'wester squall line over western West Bengal heading for Kolkata
        self.add_squall_line(23.05, 87.05, T - 75 * MIN, n=7, length_km=200.0, u=13.5, v=-5.0)
        # 2. Hail-bearing supercell west of Ranchi
        self.add_cell("hail", 23.52, 84.92, T - 65 * MIN, u=9.5, v=-4.0)
        # 3. Quasi-stationary heavy-rain (cloudburst-prone) cell on the Meghalaya plateau
        self.add_cell("heavy_rain", 25.36, 91.62, T - 70 * MIN, u=1.6, v=0.6, peak=58.5, R=8.5,
                      tm=170 * MIN)
        # 4. Downburst-producing storm north-west of Patna
        self.add_cell("downburst", 25.92, 84.55, T - 60 * MIN, u=10.0, v=-3.5)
        # 5. Young towering cumulus (convective initiation) in Odisha and North Bengal
        self.add_cell("hail", 20.78, 85.30, T - 12 * MIN, u=6.0, v=-4.5)
        self.add_cell("ordinary", 26.85, 88.10, T - 8 * MIN)
        # 6. Storm inside the radar gap (west Odisha / Chhattisgarh border)
        self.add_cell("hail", 22.55, 84.05, T - 55 * MIN, u=8.0, v=-3.0)
        # 7. A few ordinary cells
        self.add_cell("ordinary", 24.55, 87.55, T - 40 * MIN)
        self.add_cell("ordinary", 23.95, 91.05, T - 30 * MIN)

    def _spawn(self, t: float, dt: float) -> None:
        ist_hour = ((t / 3600.0) + 5.5) % 24
        diurnal = 0.25 + 0.75 * math.exp(-(((ist_hour - 16.0) / 3.0) ** 2))
        rate_per_h = 7.0 * diurnal
        n = self.rng.poisson(rate_per_h * dt / 3600.0)
        alive = sum(1 for c in self.cells if c.alive(t))
        weights = np.array([z[3] for z in ZONES])
        weights /= weights.sum()
        for _ in range(n):
            if alive >= 45:
                break
            z = ZONES[self.rng.choice(len(ZONES), p=weights)]
            lat = float(self.rng.normal(z[0], z[2]))
            lon = float(self.rng.normal(z[1], z[2]))
            if not self.grid.contains(lat, lon):
                continue
            kinds, probs = zip(*z[4].items())
            kind = str(self.rng.choice(kinds, p=np.array(probs) / sum(probs)))
            self.add_cell(kind, lat, lon, t - float(self.rng.uniform(0, dt)))
            alive += 1
        # Occasional organised squall line in the afternoon
        if self.rng.random() < 0.18 * diurnal * dt / 3600.0:
            lat = float(self.rng.uniform(23.0, 25.8))
            lon = float(self.rng.uniform(84.0, 85.6))
            self.add_squall_line(lat, lon, t, n=int(self.rng.integers(4, 7)), length_km=float(self.rng.uniform(110, 190)))

    def advance_to(self, t: float) -> None:
        if self.t is None:
            self.t = t
            return
        dt = t - self.t
        if dt <= 0:
            return
        for c in self.cells:
            c.lat += c.v * dt / 1000.0 / KM_PER_DEG
            c.lon += c.u * dt / 1000.0 / (KM_PER_DEG * math.cos(math.radians(c.lat)))
        self._spawn(t, dt)
        g = self.grid
        self.cells = [c for c in self.cells if c.alive(t) and
                      g.lat_min - 1.0 < c.lat < g.lat_max + 1.0 and g.lon_min - 1.0 < c.lon < g.lon_max + 1.0]
        self.t = t
        if len(self._cache) > 6:
            self._cache.clear()

    # --------------------------------------------------------------- renders
    def _noise_at(self, field: np.ndarray, t: float) -> np.ndarray:
        si = int(round(4.0 * t / (self.grid.dy_km * 1000.0))) % self.grid.ny   # ~4 m/s southward drift
        sj = int(round(10.0 * t / (self.grid.dx_km * 1000.0))) % self.grid.nx  # ~10 m/s eastward drift
        return np.roll(field, (si, sj), axis=(0, 1))

    def fields(self, t: float) -> dict:
        """True near-surface reflectivity (dBZ) and convective outflow wind (m/s)."""
        key = round(t, 1)
        if key in self._cache:
            return self._cache[key]
        g = self.grid
        zlin = np.zeros((g.ny, g.nx), np.float32)
        ou = np.zeros((g.ny, g.nx), np.float32)
        ov = np.zeros((g.ny, g.nx), np.float32)
        for c in self.cells:
            e = c.echo(t)
            if e > 0.02:
                dmax = 10.0 + (c.peak - 10.0) * e
                R = c.radius(t)
                win = g.window(c.lat, c.lon, R * c.aspect * 3.2)
                if win is not None:
                    n, ea = g.offsets_km(win, c.lat, c.lon)
                    ct, st = math.cos(c.theta), math.sin(c.theta)
                    xa = ea * ct + n * st
                    xc = -ea * st + n * ct
                    r2 = (xa / (R * c.aspect)) ** 2 + (xc / R) ** 2
                    dbz = dmax - 24.0 * r2
                    i0, i1, j0, j1 = win
                    zlin[i0:i1, j0:j1] += np.where(dbz > -5, 10.0 ** (dbz / 10.0), 0.0).astype(np.float32)
                    if c.kind == "squall" and e > 0.3:
                        # trailing stratiform region behind the convective line
                        hd = math.atan2(c.v, c.u)
                        off = 2.6 * R
                        slat = c.lat - off * math.sin(hd) / KM_PER_DEG
                        slon = c.lon - off * math.cos(hd) / (KM_PER_DEG * math.cos(math.radians(c.lat)))
                        n2, e2 = g.offsets_km(win, slat, slon)
                        xa2 = e2 * ct + n2 * st
                        xc2 = -e2 * st + n2 * ct
                        r2s = (xa2 / (R * c.aspect * 1.1)) ** 2 + (xc2 / (1.9 * R)) ** 2
                        dbs = 31.0 * e - 10.0 * r2s
                        zlin[i0:i1, j0:j1] += np.where(dbs > 5, 10.0 ** (dbs / 10.0), 0.0).astype(np.float32)
            of = c.outflow(t)
            if of > 1.0:
                Rd = 1.6 * c.radius(t) * (1.4 if c.kind == "squall" else 1.0)
                hd = math.atan2(c.v, c.u)
                clat = c.lat + 0.3 * Rd * math.sin(hd) / KM_PER_DEG
                clon = c.lon + 0.3 * Rd * math.cos(hd) / (KM_PER_DEG * math.cos(math.radians(c.lat)))
                win = g.window(clat, clon, Rd * 4.0)
                if win is not None:
                    n, ea = g.offsets_km(win, clat, clon)
                    r = np.hypot(n, ea) + 1e-3
                    x = r / Rd
                    ur = of * x * np.exp(0.5 * (1.0 - x * x))
                    i0, i1, j0, j1 = win
                    ou[i0:i1, j0:j1] += (ur * ea / r).astype(np.float32)
                    ov[i0:i1, j0:j1] += (ur * n / r).astype(np.float32)
        dbz = 10.0 * np.log10(zlin + 1e-4)
        dbz = np.maximum(dbz, -10.0).astype(np.float32)
        tex = self._noise_at(self.noise, t)
        dbz = np.where(dbz > 5, dbz + 2.2 * tex, dbz).astype(np.float32)
        out = {"dbz": dbz, "ou": ou, "ov": ov}
        self._cache[key] = out
        return out

    def render_ir(self, t: float) -> tuple[np.ndarray, np.ndarray]:
        """(TIR1 10.8um BT, WV 6.7um BT) in K as seen by the satellite (parallax, 4/8 km footprint)."""
        g = self.grid
        bt = self.bt_clear.copy()
        # scattered fair-weather cumulus / thin cirrus
        bt -= np.clip(self._noise_at(self.cu_noise, t) - 1.2, 0, None) * 3.0
        overshoot = np.zeros_like(bt)
        for c in self.cells:
            cl = c.cloud(t)
            if cl < 0.02:
                continue
            btc = 303.0
            top = btc - (btc - c.min_bt) * cl
            Ra = c.anvil_radius(t)
            hd = math.atan2(c.v, c.u) + 0.15  # upper-level flow slightly veered
            grow = float(smoothstep((t - c.t0) / (c.tc + c.tg + c.tm)))
            off = 0.35 * Ra * grow
            alat = c.lat + off * math.sin(hd) / KM_PER_DEG
            alon = c.lon + off * math.cos(hd) / (KM_PER_DEG * math.cos(math.radians(c.lat)))
            win = g.window(alat, alon, Ra * 2.4)
            if win is None:
                continue
            n, ea = g.offsets_km(win, alat, alon)
            ct, st = math.cos(hd), math.sin(hd)
            xa = ea * ct + n * st
            xc = -ea * st + n * ct
            r2 = (xa / (Ra * 1.35)) ** 2 + (xc / Ra) ** 2
            prof = np.exp(-(r2 ** 1.6))
            i0, i1, j0, j1 = win
            sub = btc - (btc - top) * prof
            bt[i0:i1, j0:j1] = np.minimum(bt[i0:i1, j0:j1], sub)
            if c.overshoot and c.echo(t) > 0.8:
                n2, e2 = g.offsets_km(win, c.lat, c.lon)
                d2 = (n2 ** 2 + e2 ** 2) / (0.9 * c.R) ** 2
                overshoot[i0:i1, j0:j1] = np.maximum(overshoot[i0:i1, j0:j1], 7.0 * c.echo(t) * np.exp(-d2))
        bt = bt - overshoot
        # parallax: tall clouds appear displaced away from the sub-satellite point
        height = np.clip((303.0 - bt) / 7.0, 0, 17.0)
        height = ndimage.gaussian_filter(ndimage.maximum_filter(height, 5), 1.5)
        di, dj = self.parallax_di * height, self.parallax_dj * height
        ii, jj = np.mgrid[0:g.ny, 0:g.nx].astype(np.float32)
        p_i, p_j = ii - di, jj - dj
        di2 = ndimage.map_coordinates(di, [p_i, p_j], order=1, mode="nearest")
        dj2 = ndimage.map_coordinates(dj, [p_i, p_j], order=1, mode="nearest")
        bt_app = ndimage.map_coordinates(bt, [ii - di2, jj - dj2], order=1, mode="nearest")
        tir = _degrade(bt_app, 2) + self.rng.normal(0, 0.25, bt.shape).astype(np.float32)
        wv_true = np.where(bt_app < 236.0, bt_app + np.interp(bt_app, [195, 215], [3.0, -3.0]), 238.0)
        wv = _degrade(np.minimum(wv_true, 238.5).astype(np.float32), 4) + self.rng.normal(0, 0.3, bt.shape).astype(np.float32)
        return tir.astype(np.float32), wv.astype(np.float32)

    def flashes(self, t1: float, t2: float) -> np.ndarray:
        """Detected flashes in [t1, t2) as a structured array."""
        recs = []
        dt_min = (t2 - t1) / MIN
        for c in self.cells:
            tm = 0.5 * (t1 + t2)
            rate = c.flash_rate(tm)
            if rate <= 0:
                continue
            n = self.rng.poisson(rate * dt_min)
            if n == 0:
                continue
            R = c.radius(tm)
            is_cg = self.rng.random(n) < 0.22
            sig = np.where(is_cg, 0.7 * R, 1.5 * R)
            hd = math.atan2(c.v, c.u)
            shift = np.where(is_cg, 0.0, 0.35 * R)
            dn = self.rng.normal(0, 1, n) * sig + shift * math.sin(hd)
            de = self.rng.normal(0, 1, n) * sig + shift * math.cos(hd)
            # network detection efficiency and location accuracy
            detected = self.rng.random(n) < np.where(is_cg, 0.92, 0.75)
            dn = dn + self.rng.normal(0, 0.4, n)
            de = de + self.rng.normal(0, 0.4, n)
            lat = c.lat + dn / KM_PER_DEG
            lon = c.lon + de / (KM_PER_DEG * math.cos(math.radians(c.lat)))
            ts = self.rng.uniform(t1, t2, n)
            ka = np.where(is_cg, -np.abs(self.rng.lognormal(3.2, 0.5, n)), self.rng.normal(0, 8, n))
            for k in np.nonzero(detected)[0]:
                recs.append((ts[k], lat[k], lon[k], 1 if is_cg[k] else 0, ka[k]))
        arr = np.array(recs, dtype=STRIKE_DTYPE) if recs else np.zeros(0, STRIKE_DTYPE)
        return arr


STRIKE_DTYPE = np.dtype([("t", "f8"), ("lat", "f4"), ("lon", "f4"), ("cg", "i1"), ("ka", "f4")])


def _degrade(field: np.ndarray, k: int) -> np.ndarray:
    """Simulate a coarser sensor footprint by block-averaging k x k cells."""
    ny, nx = field.shape
    py, px = (-ny) % k, (-nx) % k
    f = np.pad(field, ((0, py), (0, px)), mode="edge")
    blocks = f.reshape(f.shape[0] // k, k, f.shape[1] // k, k).mean(axis=(1, 3))
    up = np.repeat(np.repeat(blocks, k, axis=0), k, axis=1)
    return up[:ny, :nx].astype(np.float32)
