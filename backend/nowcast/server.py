"""FastAPI server: REST + WebSocket API and the GIS dashboard."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import os


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines); real environment variables win."""
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


_load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from . import assistant as ai  # noqa: E402
from . import rag  # noqa: E402
from . import exports  # noqa: E402
from .weather import WeatherService  # noqa: E402
from .engine import RASTER_PRODUCTS, NowcastEngine  # noqa: E402
from .render import LEGENDS, legend_stops  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

engine = NowcastEngine()
weather = WeatherService(engine.meta()["places"])
assistant_provider = ai.get_provider()
knowledge = rag.KnowledgeBase(embedder=getattr(assistant_provider, "embed", None))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(knowledge.refresh)  # index (and embed) the knowledge base once at startup
    await engine.start()
    yield
    await engine.stop()


app = FastAPI(title="BUMBLEBLE Convective Nowcasting System", version="1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND / "static"), name="static")
# The pages may also be hosted elsewhere (Netlify, Vercel, GitHub Pages) and call this API cross-origin.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def landing():
    return FileResponse(FRONTEND / "landing.html")


@app.get("/app")
def dashboard():
    return FileResponse(FRONTEND / "app.html")


PAGES = {"app", "arrivals", "alerts", "hazards", "assistant", "system"}


@app.get("/{page}")
def page(page: str):
    # one page per dashboard section; both /arrivals and /arrivals.html work (pages link with .html for static hosts)
    name = page[:-5] if page.endswith(".html") else page
    if name in ("index", "landing"):
        return FileResponse(FRONTEND / "landing.html")
    if name not in PAGES:
        raise HTTPException(404)
    return FileResponse(FRONTEND / f"{name}.html")


@app.get("/api/meta")
def meta():
    m = engine.meta()
    m["legends"] = {k: {**v, "stops": legend_stops(k)} for k, v in LEGENDS.items()}
    return m


@app.get("/api/state")
def state():
    if engine.snapshot is None:
        return JSONResponse({"type": "pending", "sim_now": engine.clock.now(), "warming_up": engine.warming_up,
                             "health": engine.ingest.health()})
    return engine.snapshot.summary


@app.get("/api/raster/{product}/{lead_idx}.png")
def raster(product: str, lead_idx: int):
    if product not in RASTER_PRODUCTS:
        raise HTTPException(404, "unknown product")
    png = engine.raster_png(product, lead_idx)
    if png is None:
        return Response(status_code=204)
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=600"})


@app.get("/api/point")
def point(lat: float, lon: float):
    p = engine.point(lat, lon)
    if p is None:
        raise HTTPException(404, "outside domain or no analysis yet")
    return p


# ---- live surface weather (Open-Meteo, free & keyless) ----
@app.get("/api/weather")
def weather_point(lat: float, lon: float):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "lat/lon out of range")
    try:
        return weather.point(lat, lon)
    except Exception as exc:
        raise HTTPException(502, f"weather service unavailable: {exc}")


@app.get("/api/weather/places")
def weather_places():
    try:
        return weather.places_now()
    except Exception as exc:
        raise HTTPException(502, f"weather service unavailable: {exc}")


class SpeedReq(BaseModel):
    speed: float


class SpawnReq(BaseModel):
    lat: float
    lon: float
    kind: str = "hail"
    mature: bool = False


class OutageReq(BaseModel):
    source_id: str
    enabled: bool


@app.post("/api/sim/speed")
def set_speed(req: SpeedReq):
    return {"speed": engine.set_speed(req.speed)}


@app.post("/api/sim/spawn")
def spawn(req: SpawnReq):
    try:
        return engine.spawn(req.lat, req.lon, req.kind, req.mature)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/sim/source")
def set_source(req: OutageReq):
    if not engine.set_source_enabled(req.source_id, req.enabled):
        raise HTTPException(404, "unknown source")
    return {"ok": True}


@app.post("/api/ingest/lightning")
async def push_lightning(records: list[dict]):
    """Push flash reports: [{"time": ISO|epoch, "lat":.., "lon":.., "type": "CG"|"IC", "peak_ka":..}]"""
    for s in engine.sources:
        if s.id == "LLN-PUSH":
            return {"accepted": await s.push(records)}
    raise HTTPException(409, "HTTP lightning push is only enabled in live mode")


class UserLocation(BaseModel):
    lat: float
    lon: float
    name: str = ""
    accuracy_m: float | None = None


class AskReq(BaseModel):
    message: str
    history: list[dict] = []
    location: UserLocation | None = None  # shared by the browser only after the user allows it


def _user_location_context(loc: UserLocation) -> dict:
    """Forecast + live weather at the user's own position, added to the assistant's context."""
    out = {"lat": round(loc.lat, 4), "lon": round(loc.lon, 4), "name": loc.name[:120], "accuracy_m": loc.accuracy_m}
    p = engine.point(loc.lat, loc.lon)
    if p is None:
        out["storm_forecast"] = "outside the forecast area (East & North-East India) - no storm nowcast here"
    else:
        lv, leads = p["level"], p["leads"]
        first = next((leads[i] for i, x in enumerate(lv) if x >= 2), None)
        out["storm_forecast"] = {"where": p["where"], "max_level_next_6h": max(lv), "level_now": lv[0],
                                 "minutes_until_moderate_or_worse": first,
                                 "max_hail_prob": round(max(p["hail"]), 2), "max_gust_kmh": round(max(p["gust"]) * 3.6)}
    try:
        out["weather_now"] = weather.point(loc.lat, loc.lon)["now"]
    except Exception:
        pass
    return out


@app.get("/api/assistant/info")
def assistant_info():
    model = getattr(assistant_provider, "last_model", None) or (getattr(assistant_provider, "models", [None])[0])
    return {"provider": assistant_provider.name, "model": model,
            "mode": "AI" if assistant_provider.name != "demo" else "Demo mode (no API key configured)",
            "knowledge_docs": len(knowledge.docs()), "embeddings": knowledge._vecs is not None if hasattr(knowledge, "_vecs") else False}


@app.post("/api/assistant")
def ask(req: AskReq):
    msg = req.message.strip()[:1000]
    if not msg:
        raise HTTPException(400, "empty message")
    summary = engine.snapshot.summary if engine.snapshot else None
    ctx = ai.build_context(summary, engine.places)
    if req.location is not None:
        ctx["user_location"] = _user_location_context(req.location)
    return ai.respond(assistant_provider, msg, req.history, ctx, engine.places, knowledge)


class DocReq(BaseModel):
    name: str
    text: str


@app.get("/api/knowledge")
def list_knowledge():
    return {"docs": knowledge.docs()}


@app.post("/api/knowledge")
def add_knowledge(req: DocReq):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "empty document")
    if len(text) > 400_000:
        raise HTTPException(413, "document too large (max ~400 KB of text)")
    name = knowledge.add_document(req.name or "document.md", text)
    return {"saved": name, "docs": knowledge.docs()}


@app.delete("/api/knowledge/{name}")
def delete_knowledge(name: str):
    if not knowledge.delete_document(name):
        raise HTTPException(404, "not found")
    return {"docs": knowledge.docs()}


@app.get("/api/knowledge/search")
def search_knowledge(q: str, k: int = 4):
    return {"results": knowledge.search(q, k=min(max(k, 1), 10))}


@app.get("/api/export/nowcast.geojson")
def export_geojson():
    if engine.snapshot is None:
        raise HTTPException(503, "no analysis yet")
    return Response(exports.geojson(engine.snapshot.summary), media_type="application/geo+json",
                    headers={"Content-Disposition": "attachment; filename=bumbleble-nowcast.geojson"})


@app.get("/api/export/places.csv")
def export_csv():
    if engine.snapshot is None:
        raise HTTPException(503, "no analysis yet")
    return Response(exports.places_csv(engine.snapshot.summary), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=bumbleble-arrivals.csv"})


@app.get("/api/export/bulletin.html")
def export_bulletin():
    if engine.snapshot is None:
        raise HTTPException(503, "no analysis yet")
    return Response(exports.bulletin_html(engine.snapshot.summary), media_type="text/html")


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    q = engine.subscribe()
    try:
        if engine.snapshot is not None:
            await websocket.send_json(engine.snapshot.summary)
        while True:
            msg = await q.get()
            await websocket.send_json(msg)
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        engine.unsubscribe(q)
