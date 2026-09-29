import asyncio

import numpy as np
import pytest

from tests.driver import drive
from nowcast.config import Settings
from nowcast.engine import NowcastEngine
from nowcast.grid import Grid
from nowcast.motion import Advector, tile_vectors
from nowcast.render import colorize, encode_png


@pytest.fixture(scope="module")
def engine():
    eng = NowcastEngine(Settings(mode="simulated"))
    asyncio.run(drive(eng, eng.scenario_start + 10 * 60))
    return eng


def test_cycle_produces_full_nowcast(engine):
    snap = engine.snapshot
    assert snap is not None
    nc = snap.nowcast
    assert nc.leads[0] == 0 and nc.leads[-1] == 360
    for name, arr in nc.products.items():
        assert arr.shape == (len(nc.leads), engine.grid.ny, engine.grid.nx), name
        assert np.isfinite(arr.astype(np.float32)).all(), name
    assert 0 <= nc.products["hail"].astype(np.float32).max() <= 1


def test_storms_detected_and_tracked(engine):
    s = engine.snapshot.summary
    assert s["stats"]["n_cells"] >= 3
    assert any(c["level"] >= 3 for c in s["cells"])
    assert s["stats"]["motion_vectors"] > 0


def test_countdowns_for_threatened_places(engine):
    places = engine.snapshot.summary["places"]
    threatened = [p for p in places if p["status"] != "clear"]
    assert threatened, "scenario should threaten at least one place"
    for p in threatened:
        assert p["eta_min"] is not None and 0 <= p["eta_min"] <= 360
        assert set(p["hazards"]) >= {"hail_prob", "gust_ms", "lightning", "cloudburst_prob"}


def test_all_feeds_ingested(engine):
    health = {h["id"]: h for h in engine.snapshot.summary["health"]}
    assert all(h["count"] > 0 for h in health.values())


def test_nowcast_beats_persistence(engine):
    v = engine.snapshot.summary["verification"]["30"]
    if v is None:
        pytest.skip("not enough verification samples yet")
    assert v["csi"] > v["csi_persistence"]


def test_png_render(engine):
    png = engine.raster_png("level", 3)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_phase_correlation_recovers_shift():
    rng = np.random.default_rng(0)
    from scipy import ndimage
    a = np.clip(ndimage.gaussian_filter(rng.normal(size=(96, 96)), 3) * 60, 0, None).astype(np.float32)
    b = np.roll(a, (2, 5), axis=(0, 1))
    vecs = tile_vectors(a, b, dt_min=1.0, max_cells_per_min=20, min_frac=0.01)
    vi = np.median([v[2] for v in vecs])
    vj = np.median([v[3] for v in vecs])
    assert abs(vi - 2) < 0.5 and abs(vj - 5) < 0.5


def test_advection_translates_field():
    f = np.zeros((80, 80), np.float32)
    f[20, 20] = 1.0
    adv = Advector(np.full((80, 80), 0.5, np.float32), np.full((80, 80), 1.0, np.float32))
    adv.step(10)
    out = adv.sample(f, 0.0)
    i, j = np.unravel_index(np.argmax(out), out.shape)
    assert (i, j) == (25, 30)


def test_colorize_transparent_below_threshold():
    rgba = colorize("dbz", np.array([[0.0, 50.0]]))
    assert rgba[0, 0, 3] == 0 and rgba[0, 1, 3] > 0
    assert encode_png(rgba)[:4] == b"\x89PNG"
