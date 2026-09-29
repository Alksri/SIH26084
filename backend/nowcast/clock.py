"""Simulation-aware clock. In live mode it simply tracks wall-clock UTC."""
from __future__ import annotations

import asyncio
import time


class SimClock:
    def __init__(self, start_epoch: float | None = None, speed: float = 1.0):
        self._base_sim = time.time() if start_epoch is None else float(start_epoch)
        self._base_real = time.monotonic()
        self._speed = float(speed)

    @property
    def speed(self) -> float:
        return self._speed

    def now(self) -> float:
        return self._base_sim + (time.monotonic() - self._base_real) * self._speed

    def set_speed(self, speed: float) -> None:
        now = self.now()
        self._base_sim = now
        self._base_real = time.monotonic()
        self._speed = max(0.0, float(speed))

    async def sleep_until(self, t_sim: float) -> None:
        while True:
            remaining = t_sim - self.now()
            if remaining <= 0:
                return
            if self._speed <= 0:
                await asyncio.sleep(0.25)
                continue
            await asyncio.sleep(min(remaining / self._speed, 0.25))

    async def sleep(self, seconds: float) -> None:
        await self.sleep_until(self.now() + seconds)
