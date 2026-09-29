"""Runtime configuration for the convective nowcasting system.

All values can be overridden with environment variables prefixed ``NOWCAST_``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _env(name: str, default):
    raw = os.environ.get(f"NOWCAST_{name}")
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    return type(default)(raw)


@dataclass(frozen=True)
class GridConfig:
    """Common analysis grid (regular lat/lon). 0.02 deg ~= 2.2 km N-S, ~2.0 km E-W."""

    lat_min: float = 19.5
    lat_max: float = 27.5
    lon_min: float = 83.0
    lon_max: float = 92.0
    res_deg: float = field(default_factory=lambda: _env("RES_DEG", 0.02))


# Regional analysis windows (~2 km grid each). Pick with NOWCAST_REGION.
REGIONS = {
    "east": (19.5, 27.5, 83.0, 92.0),        # WB, Odisha, Jharkhand, Bihar, NE plains (Nor'westers)
    "northeast": (22.0, 29.5, 88.0, 97.0),   # Assam, Meghalaya, Tripura, Arunachal
    "north": (24.0, 32.0, 72.5, 81.5),       # Delhi NCR, Haryana, Punjab, Uttarakhand, west UP
    "central": (19.0, 27.0, 75.0, 84.0),     # MP, Chhattisgarh, east UP
    "west": (15.5, 24.0, 68.5, 77.5),        # Gujarat, Maharashtra, Mumbai
    "south": (8.0, 16.0, 74.0, 83.0),        # Karnataka, Tamil Nadu, Kerala, Andhra
}


def _region_grid() -> "GridConfig":
    la0, la1, lo0, lo1 = REGIONS.get(_env("REGION", "east"), REGIONS["east"])
    return GridConfig(la0, la1, lo0, lo1)


@dataclass(frozen=True)
class RadarSite:
    id: str
    name: str
    lat: float
    lon: float
    range_km: float = 250.0
    elev_deg: float = 0.5


# IMD S/C-band Doppler Weather Radars covering East & North-East India.
DEFAULT_RADARS = (
    RadarSite("DWR-KOL", "Kolkata", 22.57, 88.35),
    RadarSite("DWR-PAT", "Patna", 25.59, 85.09),
    RadarSite("DWR-PDP", "Paradip", 20.26, 86.67),
    RadarSite("DWR-GPL", "Gopalpur", 19.27, 84.88),
    RadarSite("DWR-AGT", "Agartala", 23.89, 91.25),
    RadarSite("DWR-SOH", "Sohra (Cherrapunji)", 25.25, 91.73),
)


@dataclass
class Settings:
    grid: GridConfig = field(default_factory=_region_grid)
    radars: tuple = DEFAULT_RADARS

    # "realtime":  real radar from the free RainViewer API, real clock (default).
    # "simulated": built-in synthetic atmosphere drives all feeds (demo / testing).
    # "live":      operational file-drop (ODIM_H5 / INSAT HDF5 / lightning CSV) + HTTP push.
    mode: str = field(default_factory=lambda: _env("MODE", "realtime"))
    # Simulation speed-up factor (sim seconds per real second).
    speed: float = field(default_factory=lambda: _env("SPEED", 10.0))
    warmup_speed: float = field(default_factory=lambda: _env("WARMUP_SPEED", 150.0))
    warmup_minutes: float = field(default_factory=lambda: _env("WARMUP_MINUTES", 35.0))
    # Scenario start: a pre-monsoon (Nor'wester / Kalbaisakhi) afternoon, 14:30 IST.
    start_time: datetime = field(
        default_factory=lambda: datetime.fromisoformat(
            _env("START", "2026-04-18T09:00:00+00:00")
        ).astimezone(timezone.utc)
    )
    seed: int = field(default_factory=lambda: _env("SEED", 2026))

    # Analysis / forecast cadence
    analysis_interval_s: int = 300
    lead_step_min: int = 10
    max_lead_min: int = 360

    # Feed cadences and delivery latencies (seconds)
    radar_cadence_s: int = 300
    radar_latency_s: int = 90
    sat_cadence_s: int = 900
    sat_latency_s: int = 360
    sat_lon: float = 74.0  # INSAT-3DR sub-satellite longitude
    lightning_batch_s: int = 30
    lightning_latency_s: int = 10

    # Staleness limits used by the fusion step
    radar_max_age_s: int = 720
    sat_max_age_s: int = 2700

    # Live-mode drop folders (ODIM_H5 radar, INSAT-3D/3DR L1B HDF5, lightning CSV/JSON)
    drop_dir: str = field(default_factory=lambda: _env("DROP_DIR", "data/incoming"))

    @property
    def leads(self) -> list[int]:
        return list(range(0, self.max_lead_min + 1, self.lead_step_min))
