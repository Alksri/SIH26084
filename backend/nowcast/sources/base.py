"""Source abstraction for the ingestion engine.

Every feed - simulated or real - produces ``Observation`` objects already
mapped onto the common analysis grid, and hands them to the ingestion engine
through an async ``emit`` callback.  Regridding (polar -> cartesian, satellite
swath -> grid) is therefore the adapter's job; QC, time alignment and fusion
are the engine's.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class Observation:
    source_id: str          # e.g. "DWR-KOL", "INSAT-3DR", "LLN"
    kind: str               # "radar" | "satellite" | "lightning"
    obs_time: float         # epoch seconds (scan / valid time)
    payload: dict[str, Any]
    arrival_time: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


Emit = Callable[[Observation], Awaitable[None]]


class DataSource(abc.ABC):
    id: str
    kind: str
    label: str
    cadence_s: float

    def __init__(self) -> None:
        self.enabled = True  # False simulates a feed outage

    @abc.abstractmethod
    async def run(self, emit: Emit) -> None:
        """Produce observations forever, calling ``emit`` for each one."""

    def describe(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "cadence_s": self.cadence_s}
