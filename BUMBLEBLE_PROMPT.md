# BUMBLEBLE — Build Prompt

## Real-time, hyper-local thunderstorm nowcasting platform for India

You are an expert full-stack engineer, atmospheric-data engineer, GIS developer and UI/UX designer.

Build **BUMBLEBLE**, a polished, cloud-hosted web platform that turns real-time weather sensor data into **0–6 hour, 1–3 km resolution nowcasts** of severe convective storms: thunderstorms, lightning, hail, downburst winds and cloudbursts. Show them on an interactive GIS dashboard with **live countdown clocks to storm arrival** for cities, airports and farming districts.

The goal is a **production-quality early-warning product** that disaster managers, aviation and farmers can use, not a static weather map or a chatbot.

---

## 1. Core concept

Numerical weather models are too coarse and too slow for storms that develop in minutes at 1–5 km scales. BUMBLEBLE must:

1. Ingest high-frequency, mixed-format sensor streams in real time.
2. Fuse them onto one common 2 km grid.
3. Detect new storms forming before radar sees them (convective initiation).
4. Track existing storm cells and their motion, growth and decay.
5. Forecast four severe hazards every 10 minutes out to 6 hours: lightning density, hail probability, downburst gust speed and cloudburst risk (≥100 mm in 1 h).
6. Compute the arrival time and expected hazards for every monitored place.
7. Push everything live to the dashboard and to alerts.

It should feel like an operational forecasting workspace: live, calm, fast and trustworthy.

---

## 2. Data sources

| Source | Content | Status |
|---|---|---|
| Doppler Weather Radars (IMD DWR) | Reflectivity and radial velocity, ODIM_H5 | Adapter built; needs an IMD data feed |
| INSAT-3D/3DR/3DS (MOSDAC) | TIR1 10.8 µm and WV 6.7 µm brightness temperatures, HDF5 | Adapter built; needs MOSDAC registration |
| Ground lightning networks (IMD/IITM) | Flash time, location, type, peak current | HTTP push API and CSV/JSON drop folder |
| **RainViewer** (free) | Live global radar mosaic, 10-min frames | **Live today**; tile colours decoded back to dBZ |
| **Open-Meteo** (free) | CAPE, wind gusts, geocoding | **Live today** |
| **NASA GIBS / GPM IMERG** (free) | Half-hourly satellite rainfall overlay | **Live today** |

Every feed runs as an independent asynchronous source with quality control, latency tracking and OK / STALE / DOWN health status. **Losing a feed must degrade the system gracefully, never break it:** where radar is missing, a satellite + lightning proxy fills the gap at lower confidence.

---

## 3. Processing pipeline

```text
Ingest → QC → Fusion (2 km grid) → Motion → Detection → Nowcast 0–6 h → Hazards → Alerts / ETA → Dashboard
```

- **Fusion:**
  - Best-quality radar mosaic.
  - Radial-velocity divergence converted to outflow speed.
  - Satellite parallax correction, plus advection to the analysis time to compensate for delivery latency.
  - Lagrangian cloud-top cooling rate.
  - Lightning density.
- **Motion:** tile-wise FFT phase correlation on radar and on IR image pairs.
- **Detection:**
  - 40 dBZ storm cells, tracked between cycles.
  - Lightning-jump alerts (2σ method).
  - Satellite convective-initiation alerts, each verified later against radar and its lead time recorded.
- **Nowcast:**
  - Semi-Lagrangian extrapolation with growth/decay trends and lifetime decay.
  - Expected new cells injected at CI sites.
  - Neighbourhood probabilities whose radius grows with lead time.
- **Hazards:** VIL and VIL density (hail), Stewart (1991) gust formula combined with observed outflow, Z–R rainfall (cloudburst), and diagnosed lightning.
- **Verification:** live CSI / POD / FAR against later analyses, always compared with a persistence baseline.

Keep a structured internal representation (analysis, cells, CI candidates, places, events) as the source of truth. Do not rely on rendered images.

---

## 4. Application layout

### Landing page (`/`)

- Hero: **"See the storm before it arrives."**
- Live numbers pulled from the running engine: active storms, places at risk, latest analysis, grid resolution.
- Sections: Features, How it works (Ingest → Fuse → Detect → Forecast → Alert), a live embedded dashboard, Who it's for, and Data sources.
- Buttons: **Open live dashboard** and **Watch it work**.

### Dashboard (`/app`) — three-panel workspace

- **Left panel, map layers:**
  - Hazard layers: composite threat, worst threat in the next 1 h / 6 h, lightning, hail, gusts, cloudburst, rain next hour.
  - Observation layers: fused reflectivity, parallax-corrected IR, observed rain, fusion confidence.
  - Overlay toggles, live external data, opacity, live forecast skill.
- **Centre, GIS map:**
  - KPI strip and a severe-threat banner.
  - Storm cells with past and forecast tracks, new-storm rings, live lightning strikes, countdown clocks on the map.
  - Google Maps-style map-type picker: Default, Streets, Satellite, Hybrid, Terrain, Topographic.
  - A 0–6 h timeline with play; Space and arrow keys control it.
- **Right panel, tabs:**
  - **Arrivals:** ticking countdown cards filterable by cities / airports / farms, with hazard chips.
  - **Alerts:** new storms, lightning jumps, severe warnings, cloudbursts, feed outages, all-clears.
  - **✨ Ask AI:** the assistant (section 5).
  - **System:** feed health with fail/restore demo buttons, pipeline stats.

### Top bar

Brand, place search (built-in places plus worldwide geocoding), IST/UTC clocks, **Undo / Redo, Share, Export**, live status, English/हिन्दी, notifications and the light/dark switch.

---

## 5. AI assistant ("Ask AI")

Users control the dashboard in plain language, for example:

> "Which cities are at risk?" · "Show hail risk near Ranchi in 2 hours" · "Switch to satellite map" · "Turn on live radar" · "Dark mode" · "Summary"

The assistant **answers only from the latest nowcast data** and returns validated UI actions: `set_layer`, `set_lead`, `fly_to`, `set_basemap`, `set_theme`, `toggle_overlay`. The dashboard applies them, and each application creates an undoable version.

**Provider abstraction:** `AssistantProvider.respond(message, history, context)`.

- `ClaudeProvider` uses the official Anthropic SDK and runs only when `ANTHROPIC_API_KEY` is set **on the server**. Keys never reach the browser.
- **Demo mode** (`DemoProvider`) is a rule-based fallback that always works with no key.
- Any provider failure falls back to demo mode with a clear note.
- Model output is validated before any action runs.

---

## 6. Undo / redo, share and export

- **Versions:** every view change (layer, lead time, map type, theme, position) is a version. Undo/redo works from buttons and Ctrl+Z / Ctrl+Y and never reloads the page.
- **Share** copies a link that reproduces the exact view (`/app?lat&lon&z&layer&lead&basemap&theme`).
- **Export** must actually work:
  - a printable **bulletin** (print or save as PDF);
  - an **arrivals CSV**;
  - **GeoJSON** of storms, forecast tracks, places and CI alerts for QGIS/ArcGIS;
  - a **PNG** of the current hazard layer.

---

## 7. First-time experience

On the first visit, show **"What do you want to watch?"** with six starting points: Places at risk, Hail risk, Gusts & wind shear, Lightning, Cloudburst and Live radar. Clicking one immediately runs it through the assistant.

---

## 8. Modes

| Mode | Use |
|---|---|
| `realtime` (default) | Real RainViewer radar, real clock; analysed at each frame's own observation time. Satellite and lightning are shown honestly as "not connected" until operational access exists. |
| `simulated` | Built-in synthetic Nor'wester scenario for demos and testing: storm injection, feed-failure drills, adjustable speed. |
| `live` | Operational drop folders (ODIM_H5, INSAT HDF5, lightning CSV/JSON) plus HTTP lightning push. |

Regions (`NOWCAST_REGION`): `east`, `northeast`, `north`, `central`, `west`, `south`. Each is about 9°×8° at 2 km.

---

## 9. Design standard

- Minimal, premium, spacious; Inter and JetBrains Mono.
- Full **light and dark themes**, including an animated WebGL "flow glass" theme switch.
- Subtle animations that respect reduced motion.
- Responsive from 1920 px desktop to 375 px phones: panels become slide-overs rather than being scaled down.
- Useful empty states, and never a blank screen.

---

## 10. Cloud and quality requirements

- A single Docker container with configuration through environment variables, deployable free on Hugging Face Spaces, Render or Cloud Run.
- One analysis cycle (37 lead times × a 400×450 grid) completes in under 10 s on a laptop CPU.
- An automated test suite covers the pipeline, motion, advection, countdowns and rendering.
- Every visible control either works or clearly says why it is unavailable.
- **No fake data presented as real:** simulated mode is always labelled as simulated.

---

## 11. Final acceptance

A user can:

1. Open the landing page and see live numbers.
2. Open the dashboard and pick what to watch.
3. See real radar and storm tracks.
4. Scrub the timeline 0–6 h.
5. Read countdowns for their city, airport or farm.
6. Ask the assistant in plain language and watch the map respond.
7. Undo or redo.
8. Share the exact view.
9. Export a bulletin, CSV, GeoJSON or PNG.
10. Switch map type, theme and language.
11. Watch fusion degrade gracefully when a feed fails.
