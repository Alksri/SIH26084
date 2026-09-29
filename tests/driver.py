"""Deterministic offline driver: steps the simulated feeds and the analysis
cycle with a manual clock (no real-time waiting). Used by tests and for
benchmarking / tuning:  python -m tests.driver
"""
from __future__ import annotations

import asyncio
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from nowcast.config import Settings  # noqa: E402
from nowcast.engine import NowcastEngine  # noqa: E402


async def drive(engine: NowcastEngine, t_end: float, step_s: float = 30.0, on_cycle=None):
    cur = [engine.clock.now()]
    engine.clock.now = lambda: cur[0]
    engine.ingest.now = engine.clock.now
    srcs = engine.sources
    next_scan = {s.id: math.floor(cur[0] / s.cadence_s) * s.cadence_s + s.cadence_s + getattr(s, "offset_s", 0.0) for s in srcs}
    pending = []
    interval = engine.settings.analysis_interval_s
    next_an = math.floor(cur[0] / interval) * interval + interval + engine.settings.radar_latency_s + 15
    t = cur[0]
    while t <= t_end:
        cur[0] = t
        engine.truth.advance_to(t)
        for s in srcs:
            while t >= next_scan[s.id]:
                obs = s.scan(next_scan[s.id])
                pending.append((next_scan[s.id] + s.latency_s, s, obs))
                next_scan[s.id] += s.cadence_s
        pending.sort(key=lambda x: x[0])
        while pending and pending[0][0] <= t:
            _, s, obs = pending.pop(0)
            if s.enabled:
                await engine.ingest.emit(obs)
        if t >= next_an:
            snap_in = engine.ingest.snapshot(next_an)
            if snap_in.radars or snap_in.satellites:
                snap = engine.run_cycle(snap_in)
                engine.snapshot = snap
                if on_cycle:
                    on_cycle(engine, snap)
            next_an += interval
        t += step_s
    return engine.snapshot


def _report(engine, snap):
    s = snap.summary
    st = s["stats"]
    imp = [p for p in s["places"] if p["status"] != "clear"]
    print(f"[{s['time_iso']}] cycle {s['cycle']:3d} {st['cycle_s']:.2f}s (nowcast {st['nowcast_s']:.2f}s) "
          f"cells={st['n_cells']} ci={st['n_ci']} vec={st['motion_vectors']} lvl_now={st['max_level_now']} "
          f"lvl6h={st['max_level_6h']} proxy={s['inputs']['proxy_pct']}% flashes10={s['inputs']['flashes_10min']} "
          f"threatened={len(imp)}")


if __name__ == "__main__":
    settings = Settings(mode="simulated")
    eng = NowcastEngine(settings)
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 90
    t_end = eng.scenario_start + minutes * 60
    wall = time.perf_counter()
    snap = asyncio.run(drive(eng, t_end, on_cycle=_report))
    print(f"wall {time.perf_counter() - wall:.1f}s")
    s = snap.summary
    print("\nCELLS")
    for c in s["cells"]:
        print(f"  #{c['id']:3d} {c['where']:<32} dbz={c['max_dbz']:5.1f} vil={c['max_vil']:5.1f} bt={c['min_bt']} "
              f"fr={c['flash_rate']:5.1f} hail={c['hail']:.2f} gust={c['gust']:4.1f} of={c['outflow']:4.1f} lvl={c['level']} "
              f"{c['stage']:<11} {c['speed_kmh']:4.0f}km/h->{c['heading_deg']:3.0f} src={c['source']} LJ={c['lightning_jump']}")
    print("\nCI")
    for c in s["ci"]:
        print(f"  {c}")
    print(f"CI mean lead: {s['ci_lead_mean_min']} (n={s['ci_verified_n']})")
    print("\nPLACES (threatened)")
    for p in s["places"]:
        if p["status"] != "clear":
            print(f"  {p['name']:<28} {p['status']:<11} eta={p['eta_min']} lvl={p['level_window']} {p.get('hazards')} dur={p.get('duration_min')}")
    print("\nVERIFICATION", s["verification"])
    print("\nEVENTS")
    for e in list(eng.events)[:25]:
        print("  ", e["kind"], "|", e["text"])
    print("\nHEALTH")
    for h in s["health"]:
        print("  ", h["id"], h["status"], h["count"], h["latency_s"], h["qc"])
