"""Adapters for real operational feeds.

* ``OdimRadarDropSource``  - IMD DWR volumes in ODIM_H5 (EUMETNET OPERA) format
  dropped into ``<drop_dir>/radar``.  Lowest sweep DBZH/VRADH -> common grid.
* ``InsatDropSource``      - INSAT-3D/3DR imager HDF5 (MOSDAC L1B/L1C) dropped
  into ``<drop_dir>/satellite``.  TIR1 counts -> BT via the embedded LUT,
  WV likewise, nearest-neighbour regrid from the Latitude/Longitude arrays.
* ``LightningDropSource``  - CSV / JSON-lines flash reports dropped into
  ``<drop_dir>/lightning`` (``time,lat,lon,type,peak_ka``).
* ``LightningPushSource``  - flashes POSTed to ``/api/ingest/lightning``.

``h5py`` is only needed for the HDF5 readers.  These readers follow the
published format specifications but have not been validated against live
IMD / MOSDAC files - check dataset names and scale factors against a sample
before relying on them operationally.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..grid import Grid
from ..truth import STRIKE_DTYPE
from .base import DataSource, Emit, Observation

log = logging.getLogger("nowcast.live")


class _DropFolderSource(DataSource):
    patterns: tuple[str, ...] = ()

    def __init__(self, folder: Path, poll_s: float = 5.0):
        super().__init__()
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.poll_s = poll_s
        self._seen: set[str] = set()

    def parse(self, path: Path) -> list[Observation]:  # pragma: no cover - abstract
        raise NotImplementedError

    async def run(self, emit: Emit) -> None:
        while True:
            files = sorted(p for pat in self.patterns for p in self.folder.glob(pat))
            for path in files:
                key = f"{path.name}:{path.stat().st_mtime_ns}"
                if key in self._seen:
                    continue
                self._seen.add(key)
                try:
                    observations = await asyncio.to_thread(self.parse, path)
                except Exception as exc:  # malformed file must not kill the feed
                    log.warning("%s: failed to parse %s: %s", self.id, path.name, exc)
                    continue
                if self.enabled:
                    for obs in observations:
                        await emit(obs)
            await asyncio.sleep(self.poll_s)


# --------------------------------------------------------------------------- radar
class OdimRadarDropSource(_DropFolderSource):
    kind = "radar"
    patterns = ("*.h5", "*.hdf", "*.hdf5")

    def __init__(self, folder: Path, grid: Grid, cadence_s: float = 600.0):
        super().__init__(folder)
        self.grid = grid
        self.id, self.label, self.cadence_s = "DWR-ODIM", "DWR network (ODIM_H5 drop)", cadence_s

    def parse(self, path: Path) -> list[Observation]:
        import h5py  # optional dependency

        with h5py.File(path, "r") as f:
            where = f["where"].attrs
            what = f["what"].attrs
            site_lat, site_lon = float(where["lat"]), float(where["lon"])
            source = _attr_str(what.get("source", b"")) or path.stem
            site_id = _odim_site_id(source)
            obs_time = _odim_time(_attr_str(what["date"]), _attr_str(what["time"]))
            # pick lowest-elevation sweep
            sweeps = [k for k in f.keys() if k.startswith("dataset")]
            sweeps.sort(key=lambda k: float(f[k]["where"].attrs.get("elangle", 0.0)))
            ds = f[sweeps[0]]
            sw = ds["where"].attrs
            nbins, nrays = int(sw["nbins"]), int(sw["nrays"])
            rscale = float(sw["rscale"]) / 1000.0
            rstart = float(sw.get("rstart", 0.0))
            fields = {}
            for key in ds.keys():
                if not key.startswith("data"):
                    continue
                dw = ds[key]["what"].attrs
                qty = _attr_str(dw["quantity"])
                raw = ds[key]["data"][()].astype(np.float32)
                val = raw * float(dw.get("gain", 1.0)) + float(dw.get("offset", 0.0))
                val[raw == float(dw.get("nodata", -1e30))] = np.nan
                val[raw == float(dw.get("undetect", -1e30))] = -10.0 if qty.startswith("DBZ") else np.nan
                fields[qty] = val
        range_km = rstart + nbins * rscale
        win = self.grid.window(site_lat, site_lon, range_km)
        n, e = self.grid.offsets_km(win, site_lat, site_lon)
        r = np.hypot(n, e)
        az = (np.degrees(np.arctan2(e, n)) + 360.0) % 360.0
        ray = np.clip((az / 360.0 * nrays).astype(int), 0, nrays - 1)
        b = ((r - rstart) / rscale).astype(int)
        inside = (b >= 0) & (b < nbins)
        b = np.clip(b, 0, nbins - 1)

        def sample(name):
            if name not in fields:
                return None
            out = fields[name][ray, b]
            return np.where(inside, out, np.nan).astype(np.float32)

        dbz = sample("DBZH")
        if dbz is None:
            dbz = sample("TH")
        vr = sample("VRADH")
        if vr is None:
            vr = np.full(r.shape, np.nan, np.float32)
        quality = np.where(inside, np.exp(-(r / 220.0) ** 2), 0.0).astype(np.float32)
        payload = {"window": win, "dbz": dbz, "vr": vr, "quality": quality,
                   "site": {"id": site_id, "lat": site_lat, "lon": site_lon, "range_km": range_km}}
        return [Observation(site_id, "radar", obs_time, payload, meta={"file": path.name})]


def _attr_str(v) -> str:
    if isinstance(v, bytes):
        return v.decode(errors="ignore").strip("\x00 ")
    if isinstance(v, np.ndarray):
        return _attr_str(v.item())
    return str(v)


def _odim_site_id(source: str) -> str:
    m = re.search(r"(?:NOD|RAD|PLC):([A-Za-z0-9]+)", source)
    return f"DWR-{(m.group(1) if m else source)[:8].upper()}"


def _odim_time(date: str, tm: str) -> float:
    return datetime.strptime(date + tm[:6], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()


# ----------------------------------------------------------------------- satellite
class InsatDropSource(_DropFolderSource):
    kind = "satellite"
    patterns = ("*.h5", "*.hdf5")

    def __init__(self, folder: Path, grid: Grid, cadence_s: float = 900.0):
        super().__init__(folder)
        self.grid = grid
        self.id, self.label, self.cadence_s = "INSAT", "INSAT-3D/3DR imager (HDF5 drop)", cadence_s
        self._tree_key = None
        self._tree_idx = None

    def parse(self, path: Path) -> list[Observation]:
        import h5py
        from scipy.spatial import cKDTree

        with h5py.File(path, "r") as f:
            tir = _insat_bt(f, "IMG_TIR1")
            wv = _insat_bt(f, "IMG_WV") if "IMG_WV" in f else None
            lat = _scaled(f["Latitude"])
            lon = _scaled(f["Longitude"])
            obs_time = _insat_time(path.name, f)
        lat, lon = np.squeeze(lat), np.squeeze(lon)
        tir = np.squeeze(tir)
        # Reuse the nearest-neighbour lookup while the navigation grid is unchanged.
        key = (lat.shape, float(np.nanmean(lat)), float(np.nanmean(lon)))
        if key != self._tree_key:
            good = np.isfinite(lat) & np.isfinite(lon)
            pts = np.column_stack([lat[good], lon[good]])
            tree = cKDTree(pts)
            dist, idx = tree.query(np.column_stack([self.grid.LAT.ravel(), self.grid.LON.ravel()]),
                                   distance_upper_bound=0.08)
            flat = np.flatnonzero(good)
            valid = np.isfinite(dist)
            lookup = np.full(dist.shape, -1, np.int64)
            lookup[valid] = flat[idx[valid]]
            self._tree_key, self._tree_idx = key, lookup
        lookup = self._tree_idx

        def regrid(a):
            if a is None:
                return None
            flat = np.squeeze(a).ravel()
            out = np.where(lookup >= 0, flat[np.clip(lookup, 0, None)], np.nan)
            return out.reshape(self.grid.ny, self.grid.nx).astype(np.float32)

        wv_g = regrid(wv)
        if wv_g is None:
            wv_g = np.full((self.grid.ny, self.grid.nx), np.nan, np.float32)
        payload = {"tir1": regrid(tir), "wv": wv_g}
        return [Observation(self.id, "satellite", obs_time, payload, meta={"file": path.name})]


def _scaled(ds) -> np.ndarray:
    a = ds[()].astype(np.float64)
    fill = ds.attrs.get("_FillValue")
    if fill is not None:
        a[a == float(np.ravel(fill)[0])] = np.nan
    sf = ds.attrs.get("scale_factor")
    off = ds.attrs.get("add_offset")
    if sf is not None:
        a = a * float(np.ravel(sf)[0])
    if off is not None:
        a = a + float(np.ravel(off)[0])
    return a


def _insat_bt(f, name: str) -> np.ndarray:
    counts = f[name][()]
    lut_name = f"{name}_TEMP"
    if lut_name in f:
        lut = f[lut_name][()].astype(np.float32)
        return lut[np.clip(counts, 0, lut.size - 1)]
    return _scaled(f[name]).astype(np.float32)


def _insat_time(name: str, f) -> float:
    m = re.search(r"(\d{2}[A-Z]{3}\d{4})_(\d{4})", name)
    if m:
        return datetime.strptime(m.group(1) + m.group(2), "%d%b%Y%H%M").replace(tzinfo=timezone.utc).timestamp()
    for key in ("Acquisition_Start_Time", "Acquisition_Time_in_GMT"):
        if key in f.attrs:
            s = _attr_str(f.attrs[key])
            for fmt in ("%d-%b-%YT%H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(s[:20], fmt).replace(tzinfo=timezone.utc).timestamp()
                except ValueError:
                    pass
    return path_mtime(f.filename)


def path_mtime(p: str) -> float:
    return Path(p).stat().st_mtime


# ----------------------------------------------------------------------- lightning
def strikes_from_records(records) -> np.ndarray:
    """Records: iterable of dicts with time (ISO or epoch), lat, lon, [type], [peak_ka]."""
    out = []
    for r in records:
        t = r.get("time", r.get("t"))
        if isinstance(t, str):
            t = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        typ = str(r.get("type", "CG")).upper()
        out.append((float(t), float(r["lat"]), float(r["lon"]), 1 if typ.startswith("CG") else 0,
                    float(r.get("peak_ka", r.get("ka", 0.0)) or 0.0)))
    return np.array(out, dtype=STRIKE_DTYPE) if out else np.zeros(0, STRIKE_DTYPE)


class LightningDropSource(_DropFolderSource):
    kind = "lightning"
    patterns = ("*.csv", "*.json", "*.jsonl")

    def __init__(self, folder: Path):
        super().__init__(folder, poll_s=2.0)
        self.id, self.label, self.cadence_s = "LLN-FILE", "Lightning network (file drop)", 60.0

    def parse(self, path: Path) -> list[Observation]:
        if path.suffix == ".csv":
            with path.open(newline="") as fh:
                recs = list(csv.DictReader(fh))
        else:
            text = path.read_text()
            recs = json.loads(text) if text.lstrip().startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]
        strikes = strikes_from_records(recs)
        t = float(strikes["t"].max()) if strikes.size else path.stat().st_mtime
        return [Observation(self.id, "lightning", t, {"strikes": strikes}, meta={"file": path.name})]


class LightningPushSource(DataSource):
    kind = "lightning"

    def __init__(self):
        super().__init__()
        self.id, self.label, self.cadence_s = "LLN-PUSH", "Lightning network (HTTP push)", 60.0
        self._emit: Emit | None = None

    async def run(self, emit: Emit) -> None:
        self._emit = emit
        while True:
            await asyncio.sleep(3600)

    async def push(self, records) -> int:
        strikes = strikes_from_records(records)
        if self._emit is not None and strikes.size and self.enabled:
            await self._emit(Observation(self.id, "lightning", float(strikes["t"].max()), {"strikes": strikes}))
        return int(strikes.size)


def build_live_sources(drop_dir: str, grid: Grid) -> list[DataSource]:
    root = Path(drop_dir)
    return [
        OdimRadarDropSource(root / "radar", grid),
        InsatDropSource(root / "satellite", grid),
        LightningDropSource(root / "lightning"),
        LightningPushSource(),
    ]
