# Convective Storm Nowcasting System (0–6 h, ~2 km)

A real-time, multi-source data-fusion nowcasting system for severe convective storms (thunderstorms, hail, downbursts, cloudbursts) over East & North-East India. It includes an interactive GIS dashboard with hazard zones and live storm-arrival countdowns.

```
 DWR radars (DBZ + VRAD) ─┐
 INSAT-3DR TIR1 / WV ─────┼─► Ingestion engine ─► Fusion (2 km grid) ─► Motion ─► Detection ─► Nowcast 0-6 h ─► Alerts / ETA ─► Dashboard
 Lightning network ───────┘   QC, latency,          radar mosaic,         phase-    cells, LJ,    advection +      countdowns,     (WebSocket
 (file drop / HTTP push)      health, buffers       parallax, gap-fill    corr.     CI            hazards          events          + PNG tiles)
```

## Quick start (no technical knowledge needed)

1. On Windows, open PowerShell in this folder and run `./run.ps1`. The first run installs everything, which takes a few minutes.
2. Open **http://localhost:8000** in your browser. That's the home page. Click **Open live dashboard**, or go straight to **http://localhost:8000/app**.
3. In the dashboard:
   - **Find a place:** type a city, airport or district in the search box, or click anywhere on the map.
   - **See the future:** press ▶ on the timeline at the bottom to watch storms move over the next 6 hours.
   - **Check arrivals:** the **Arrivals** tab on the right counts down to each storm's arrival. It shows how bad the storm will be and what to do.
   - **Ask a question:** the **Ask AI** tab answers questions like "Which cities are at risk?"
   - **Get help:** press **?** at any time to see the welcome guide again. The **अ** button switches to Hindi.

Danger levels: **Yellow** = stay alert · **Orange** = plan to be indoors · **Red** = go indoors before it arrives · **Purple** = take shelter now.

> This is a prototype. It gives guidance only, so always follow official IMD warnings.

## Run

```powershell
./run.ps1            # creates .venv, installs requirements, serves http://localhost:8000
```

Or run it by hand: `pip install -r requirements.txt`, then `python -m uvicorn nowcast.server:app --app-dir backend --port 8000`.

The default mode is **simulated**. A built-in synthetic atmosphere drives realistic DWR, INSAT-3DR and lightning feeds for a pre-monsoon Nor'wester afternoon. The simulated time starts at 14:30 IST on 18 Apr 2026, after a 35-minute spin-up, and runs at 10× speed. You can change the speed from the header. The scenario includes:
- a squall line heading for Kolkata;
- a hailstorm near Ranchi;
- a quasi-stationary cloudburst cell over Meghalaya;
- a downburst storm near Patna;
- a storm in a radar gap (west Odisha);
- new storms forming (convective initiation) in Odisha and North Bengal.

Configuration uses environment variables: `NOWCAST_MODE=simulated|live`, `NOWCAST_SPEED`, `NOWCAST_START`, `NOWCAST_SEED`, `NOWCAST_DROP_DIR`.

Tests: `python -m pytest tests`. Offline benchmark or scenario replay: `python -m tests.driver 90` (simulated minutes).

## What each stage does

| Stage | Module | Method |
|---|---|---|
| Ingestion | `ingest.py` | Async feeds → QC → rolling buffers. Radar QC: zero-velocity clutter filter and speckle removal. Satellite: range check and gap repair. Lightning: domain filtering and de-duplication. Tracks per-feed latency and cadence, and flags OK/STALE/DOWN. |
| Fusion | `fusion.py`, `parallax.py` | Best-quality-wins DWR mosaic (quality falls with range and beam height). Radial-velocity divergence → outflow speed. INSAT TIR1 is parallax-corrected (INSAT-3DR at 74°E) and advected from scan time to analysis time to compensate latency. Lagrangian cloud-top cooling rate and WV–IR difference. In radar gaps, a satellite+lightning pseudo-reflectivity fills in, with a lower confidence score. |
| Motion | `motion.py` | Tile-wise FFT phase correlation on radar composites **and** on IR image pairs, Gaussian-interpolated to a dense field and smoothed in time. |
| Detection | `detection.py` | 40 dBZ cell identification and tracking; life-cycle trend. **Lightning jump** (Schultz 2σ). **Convective initiation** (SATCAST-style: BT < 273 K, cooling ≤ −4 K/15 min, no ≥35 dBZ echo yet). Each CI alert is later verified against radar, and the realised lead time is recorded. |
| Nowcast | `nowcast.py` | Backward semi-Lagrangian RK2 extrapolation in 10-min steps to 6 h. Includes cell growth/decay trends, lifetime decay, expected new cells at CI sites, scale-dependent smoothing, and neighbourhood probabilities whose radius grows with lead time. |
| Hazards | `hazards.py` | **Lightning** flash density: advected observed plus diagnosed from forecast Z and cloud-top temperature. **Hail** probability: VIL density, core strength and cloud-top BT. **Downburst gust**: Stewart (1991) VIL/echo-top formula, combined with radar-observed outflow. **Cloudburst**: P(≥100 mm in the next hour) from Z = 300R^1.4 accumulations (IMD definition). The composite threat has 5 levels, from None to Extreme. |
| Alerts | `alerts.py`, `engine.py` | For ~45 cities, airports and farming districts: ETA = first frame reaching Moderate threat, refined to the minute by the approaching cell's motion. Also reports expected hazards and duration. Events cover CI, lightning jumps, severe warnings, cloudbursts, feed outages and all-clears. |
| Verification | `verification.py` | Live CSI/POD/FAR of the ≥35 dBZ forecast at T+30/60/120 min vs. later analyses, alongside a persistence baseline. |

## Dashboard

- **Layers:** composite threat per lead time; max-threat swaths for the next 1, 3 and 6 h; lightning density; hail probability; downburst gust; cloudburst probability; rain in the next hour; fused reflectivity; parallax-corrected IR; observed 1-h rain; fusion confidence.
- **Time slider** from 0 to 6 h, with animation.
- **Storm cells** show past and forecast tracks and full attributes.
- **CI alerts** appear as pulsing rings. Lightning strikes stream live.
- **Countdowns:** ticking clocks on the map and in the side panel, filterable by city, airport or rural area.
- **Point inspector:** click the map for a 6-hour hazard timeline at that spot.
- **Demo controls (simulated mode):** inject storms anywhere, or **fail and restore any feed** to watch fusion degrade gracefully.

## Real data (live mode)

`NOWCAST_MODE=live` switches to a real-time clock and the adapters in `sources/live.py`:
- `data/incoming/radar/*.h5` — DWR volumes in **ODIM_H5**. The lowest sweep's DBZH/VRADH is regridded onto the 2 km grid.
- `data/incoming/satellite/*.h5` — **INSAT-3D/3DR imager HDF5** (MOSDAC). IMG_TIR1/IMG_WV counts are converted to BT via the embedded LUT, then regridded.
- `data/incoming/lightning/*.csv|*.jsonl` (columns `time,lat,lon,type,peak_ka`), or `POST /api/ingest/lightning`.

The HDF5 readers need `pip install h5py`. They follow the published formats but **have not been validated against real IMD/MOSDAC files**. Check dataset names and scale factors against a sample before operational use.

## Hosting anywhere (Netlify, Vercel, GitHub Pages)

The pages in `frontend/` are plain files and work on any static host. They pick their data source automatically:

| Setup | What you get |
|---|---|
| **Pages + engine** — put your engine's https address in `frontend/static/config.js` (`window.BUMBLEBLE_API = "https://…hf.space"`) | Everything: 2 km radar + satellite nowcast, all map layers, AI assistant |
| **Pages only** — leave `config.js` empty, or the engine is down | **Browser mode**: storm risk per place from free Open-Meteo 15-minute forecasts, live weather, live RainViewer radar loop and wind on the map, rule-based assistant. Detailed 2 km layers, downloads and the knowledge base need the engine. |

- **Netlify:** connect the repo; `netlify.toml` publishes `frontend/`.
- **Vercel:** import the repo; `vercel.json` serves `frontend/`.
- **GitHub Pages:** Settings → Pages → Source: *GitHub Actions*; `.github/workflows/pages.yml` publishes `frontend/` on every push to `main`.
- **Engine:** run the `Dockerfile` on Hugging Face Spaces or Render (below). The server allows cross-origin requests, so pages on any of the hosts above can use it.

All links are relative, so the site also works under a GitHub Pages sub-path (`/your-repo/`). The 📍 location button needs https, which all of these hosts provide.

## Cloud deployment (free)

The app is a single container (`Dockerfile`), so it runs on any container host. WebSockets must be supported.

| Host | Free tier | How |
|---|---|---|
| **Hugging Face Spaces** (recommended) | 2 vCPU, 16 GB RAM, always free | New Space → SDK *Docker* → push this repo. Add the variable `PORT=7860`. |
| Render.com | 512 MB RAM, sleeps when idle | New → Blueprint → this repo (`render.yaml` uses a 3 km grid to fit in memory). |
| Google Cloud Run | 2M requests/month free | `gcloud run deploy --source . --memory 2Gi --timeout 3600` (needs billing enabled). |
| Railway / Fly.io | small trial credits | Deploy from the Dockerfile. |

`NOWCAST_RES_DEG` sets the grid spacing: `0.02` ≈ 2 km, needs about 1 GB RAM; `0.03` ≈ 3 km, needs about 400 MB.

## Data sources & APIs

**Real-time mode (`NOWCAST_MODE=realtime`, the default) runs entirely on free, keyless cloud APIs, so it works on any host with no accounts:**

| Feed | API | What it gives | Delay |
|---|---|---|---|
| Radar | RainViewer `weather-maps.json` | Rain/storm reflectivity, every 10 min | ~10 min |
| Satellite | NASA GIBS WMS, `Himawari_AHI_Band13_Clean_Infrared` | Infrared cloud-top temperature (decoded from GIBS's published colour map), parallax-corrected for Himawari-9 at 140.7°E | ~40–90 min |
| Weather | Open-Meteo `/v1/forecast` | Current temperature, humidity, wind, gusts, rain, conditions, CAPE, and the next hours. Served by `GET /api/weather?lat=&lon=` (anywhere on Earth) and `GET /api/weather/places`, cached 10 min | ~15 min |
| Lightning | none free | Estimated from radar + satellite. A real network can push strikes to `POST /api/ingest/lightning` | — |

The map's wind-flow and rain-loop animations use Open-Meteo and RainViewer directly from the browser.

**Already built into the dashboard (free, no API key):**
- **Open-Meteo** — real-time instability (CAPE, lifted index, gusts, rain chance) for any point you click.
- **RainViewer** — live global radar composite overlay.
- **NASA GIBS (GPM IMERG)** — satellite precipitation overlay.
- **Esri World Gray Canvas** — light and dark basemaps.
- **Leaflet** — the map library.

**Operational feeds for live mode (free, but need registration or an agreement):**
- **MOSDAC (ISRO)**, mosdac.gov.in — INSAT-3D/3DR/3DS imager HDF5 (TIR1, WV). Free registration; the `InsatDropSource` adapter reads these files.
- **IMD** — DWR volumes (ODIM_H5) and nowcast bulletins, available by institutional request. Public imagery is on mausam.imd.gov.in. The `OdimRadarDropSource` adapter reads these volumes.
- **IITM Pune lightning network (Damini)** — lightning data by request. Blitzortung.org offers community lightning data, non-commercial use only. Either can feed `POST /api/ingest/lightning`.
- **NOAA / NASA Earthdata** — free, with a login. Global IMERG rainfall and GFS data for NWP blending.

## API

`GET /api/meta`, `GET /api/state`, `GET /api/raster/{product}/{lead_idx}.png`, `GET /api/point?lat=&lon=`, `WS /ws` (cycle/tick/strike messages), `POST /api/sim/speed|spawn|source`, `POST /api/ingest/lightning`.

## Limitations

- The skill numbers shown come from the synthetic scenario, not from real storms. The empirical thresholds (hail, gust, CI score) are literature-based and hand-tuned; they need calibration against Indian observations before operational use.
- Nowcasting is pure extrapolation; there is no NWP blending. Skill beyond ~2–3 h therefore drops, which the widening probabilities and reliability decay deliberately reflect.
- The satellite+lightning gap-fill under-estimates organised systems. When the Kolkata DWR is failed during the demo, parts of the squall line fall below Moderate.
- One cycle takes ~7 s on a laptop CPU for 37 lead times × a 400×450 grid.
