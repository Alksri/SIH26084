/* BUMBLEBLE browser engine ("browser mode").
 *
 * Used automatically when the BUMBLEBLE server can't be reached — e.g. the pages are hosted on Netlify,
 * Vercel or GitHub Pages without the Python engine. It answers the same /api/... requests the pages make,
 * computed in the visitor's browser from free, keyless cloud APIs:
 *   - Open-Meteo 15-minute forecasts (weather code, rain, gusts) + hourly CAPE  -> storm danger per place
 *   - Open-Meteo current weather                                               -> /api/weather*
 * Storm danger here comes from weather-model forecasts, not the 2 km radar + satellite nowcast, so it is
 * coarser; the map shows real RainViewer radar alongside it.
 */
(() => {
  "use strict";
  const PLACES = [{"id":"kolkata","name":"Kolkata","state":"WB","lat":22.572,"lon":88.364,"type":"city"},{"id":"howrah","name":"Howrah","state":"WB","lat":22.595,"lon":88.263,"type":"city"},{"id":"VECC","name":"Kolkata Airport (CCU)","state":"WB","lat":22.654,"lon":88.447,"type":"airport"},{"id":"durgapur","name":"Durgapur","state":"WB","lat":23.52,"lon":87.312,"type":"city"},{"id":"asansol","name":"Asansol","state":"WB","lat":23.683,"lon":86.983,"type":"city"},{"id":"bardhaman","name":"Bardhaman","state":"WB","lat":23.233,"lon":87.861,"type":"agri"},{"id":"bankura","name":"Bankura","state":"WB","lat":23.232,"lon":87.07,"type":"agri"},{"id":"midnapore","name":"Medinipur","state":"WB","lat":22.424,"lon":87.319,"type":"agri"},{"id":"kharagpur","name":"Kharagpur","state":"WB","lat":22.346,"lon":87.232,"type":"city"},{"id":"haldia","name":"Haldia","state":"WB","lat":22.06,"lon":88.11,"type":"city"},{"id":"krishnanagar","name":"Krishnanagar","state":"WB","lat":23.405,"lon":88.49,"type":"agri"},{"id":"malda","name":"Malda","state":"WB","lat":25.011,"lon":88.141,"type":"agri"},{"id":"siliguri","name":"Siliguri","state":"WB","lat":26.727,"lon":88.395,"type":"city"},{"id":"VEBD","name":"Bagdogra Airport (IXB)","state":"WB","lat":26.681,"lon":88.328,"type":"airport"},{"id":"coochbehar","name":"Cooch Behar","state":"WB","lat":26.324,"lon":89.451,"type":"agri"},{"id":"ranchi","name":"Ranchi","state":"JH","lat":23.344,"lon":85.31,"type":"city"},{"id":"VERC","name":"Ranchi Airport (IXR)","state":"JH","lat":23.314,"lon":85.321,"type":"airport"},{"id":"jamshedpur","name":"Jamshedpur","state":"JH","lat":22.805,"lon":86.203,"type":"city"},{"id":"dhanbad","name":"Dhanbad","state":"JH","lat":23.796,"lon":86.43,"type":"city"},{"id":"bokaro","name":"Bokaro","state":"JH","lat":23.669,"lon":86.151,"type":"city"},{"id":"hazaribagh","name":"Hazaribagh","state":"JH","lat":23.992,"lon":85.361,"type":"agri"},{"id":"gumla","name":"Gumla","state":"JH","lat":23.044,"lon":84.542,"type":"agri"},{"id":"patna","name":"Patna","state":"BR","lat":25.594,"lon":85.138,"type":"city"},{"id":"VEPT","name":"Patna Airport (PAT)","state":"BR","lat":25.591,"lon":85.088,"type":"airport"},{"id":"gaya","name":"Gaya","state":"BR","lat":24.796,"lon":85.008,"type":"city"},{"id":"muzaffarpur","name":"Muzaffarpur","state":"BR","lat":26.12,"lon":85.391,"type":"agri"},{"id":"bhagalpur","name":"Bhagalpur","state":"BR","lat":25.244,"lon":86.972,"type":"city"},{"id":"darbhanga","name":"Darbhanga","state":"BR","lat":26.152,"lon":85.897,"type":"agri"},{"id":"purnia","name":"Purnia","state":"BR","lat":25.778,"lon":87.475,"type":"agri"},{"id":"chapra","name":"Chhapra","state":"BR","lat":25.78,"lon":84.73,"type":"agri"},{"id":"bhubaneswar","name":"Bhubaneswar","state":"OD","lat":20.296,"lon":85.825,"type":"city"},{"id":"VEBS","name":"Bhubaneswar Airport (BBI)","state":"OD","lat":20.244,"lon":85.818,"type":"airport"},{"id":"cuttack","name":"Cuttack","state":"OD","lat":20.463,"lon":85.883,"type":"city"},{"id":"balasore","name":"Balasore","state":"OD","lat":21.494,"lon":86.933,"type":"city"},{"id":"angul","name":"Angul","state":"OD","lat":20.84,"lon":85.102,"type":"agri"},{"id":"dhenkanal","name":"Dhenkanal","state":"OD","lat":20.658,"lon":85.596,"type":"agri"},{"id":"keonjhar","name":"Keonjhar","state":"OD","lat":21.629,"lon":85.582,"type":"agri"},{"id":"rourkela","name":"Rourkela","state":"OD","lat":22.26,"lon":84.854,"type":"city"},{"id":"sambalpur","name":"Sambalpur","state":"OD","lat":21.466,"lon":83.982,"type":"agri"},{"id":"guwahati","name":"Guwahati","state":"AS","lat":26.144,"lon":91.736,"type":"city"},{"id":"VEGT","name":"Guwahati Airport (GAU)","state":"AS","lat":26.106,"lon":91.586,"type":"airport"},{"id":"shillong","name":"Shillong","state":"ML","lat":25.578,"lon":91.893,"type":"city"},{"id":"sohra","name":"Sohra (Cherrapunji)","state":"ML","lat":25.271,"lon":91.732,"type":"agri"},{"id":"agartala","name":"Agartala","state":"TR","lat":23.831,"lon":91.286,"type":"city"},{"id":"VEAT","name":"Agartala Airport (IXA)","state":"TR","lat":23.887,"lon":91.241,"type":"airport"}];
  const BOUNDS = [[19.5, 83.0], [27.5, 92.0]];
  const LEADS = Array.from({ length: 37 }, (_, i) => i * 10);
  const LEVELS = ["None", "Low", "Moderate", "High", "Extreme"];
  const OM = "https://api.open-meteo.com/v1/forecast";
  const TTL = 10 * 60 * 1000;
  const WMO = {
    0: ["Clear sky", "☀️"], 1: ["Mainly clear", "🌤️"], 2: ["Partly cloudy", "⛅"], 3: ["Overcast", "☁️"], 45: ["Fog", "🌫️"], 48: ["Freezing fog", "🌫️"],
    51: ["Light drizzle", "🌦️"], 53: ["Drizzle", "🌦️"], 55: ["Heavy drizzle", "🌧️"], 56: ["Freezing drizzle", "🌧️"], 57: ["Freezing drizzle", "🌧️"],
    61: ["Light rain", "🌦️"], 63: ["Rain", "🌧️"], 65: ["Heavy rain", "🌧️"], 66: ["Freezing rain", "🌧️"], 67: ["Freezing rain", "🌧️"],
    71: ["Light snow", "🌨️"], 73: ["Snow", "🌨️"], 75: ["Heavy snow", "❄️"], 77: ["Snow grains", "🌨️"],
    80: ["Light showers", "🌦️"], 81: ["Showers", "🌧️"], 82: ["Violent showers", "⛈️"], 85: ["Snow showers", "🌨️"], 86: ["Heavy snow showers", "❄️"],
    95: ["Thunderstorm", "⛈️"], 96: ["Thunderstorm with hail", "⛈️"], 99: ["Severe thunderstorm with hail", "⛈️"],
  };
  const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const icon = (code, isDay = 1) => (code <= 1 && !isDay ? "🌙" : (WMO[code] || ["", "🌡️"])[1]);

  // ---------------------------------------------------------------- fetch + cache
  const cache = new Map();
  async function getJ(u) {
    for (let a = 0; ; a++) {
      try { const r = await fetch(u); if (!r.ok) throw new Error("Open-Meteo " + r.status); return await r.json(); }
      catch (e) { if (a >= 2) throw e; await new Promise((res) => setTimeout(res, 1200 * (a + 1))); }
    }
  }
  function cached(key, fn) {
    const hit = cache.get(key);
    if (hit && Date.now() - hit.t < TTL) return hit.p;
    const p = fn().catch((e) => { cache.delete(key); throw e; });
    cache.set(key, { t: Date.now(), p });
    return p;
  }
  const list = (pts, f) => pts.map((p) => (+p[f]).toFixed(3)).join(",");
  function forecast(pts) {
    return getJ(`${OM}?latitude=${list(pts, "lat")}&longitude=${list(pts, "lon")}`
      + "&minutely_15=precipitation,weather_code,wind_gusts_10m&hourly=cape&current=precipitation,weather_code"
      + "&past_minutely_15=1&forecast_minutely_15=28&forecast_hours=8&timezone=GMT").then((r) => (Array.isArray(r) ? r : [r]));
  }

  // ---------------------------------------------------------------- forecast -> danger levels
  // Same 0-4 scale as the server: Low / Moderate / High / Extreme.
  function levelOf(code, mm15, gust, cape) {
    const rate = mm15 * 4; // mm per hour
    let lv = 0;
    if (code >= 95) lv = 2;
    if (code === 96 || code === 99) lv = 3;
    if (code === 82 || rate >= 20) lv = Math.max(lv, 2);
    if (rate >= 50) lv = Math.max(lv, 3);
    if (rate >= 100) lv = 4;
    if (gust >= 60) lv = Math.max(lv, 2);
    if (gust >= 80) lv = Math.max(lv, 3);
    if (gust >= 100) lv = 4;
    if (!lv && (code >= 80 || (code >= 61 && cape > 1000))) lv = 1;
    return lv;
  }
  const ts = (s) => Date.parse(s + "Z") / 1000;
  function series(row, now) {
    const m = row.minutely_15 || {}, h = row.hourly || {};
    const mt = (m.time || []).map(ts), ht = (h.time || []).map(ts);
    const at = (times, t, span) => { let k = times.findIndex((x) => t >= x && t < x + span); if (k < 0) k = t < times[0] ? 0 : times.length - 1; return k; };
    const out = { level: [], gust: [], hail: [], lightning: [], cloudburst: [], rain1h: [], dbz: [] };
    for (const lead of LEADS) {
      const t = now + lead * 60, k = at(mt, t, 900), hk = at(ht, t, 3600);
      const code = +(m.weather_code || [])[k] || 0, mm = +(m.precipitation || [])[k] || 0, gust = +(m.wind_gusts_10m || [])[k] || 0;
      const cape = +(h.cape || [])[hk] || 0, rate = mm * 4;
      out.level.push(levelOf(code, mm, gust, cape));
      out.gust.push(gust / 3.6);
      out.hail.push(code === 96 || code === 99 ? 0.6 : code >= 95 && cape > 2500 ? 0.25 : 0);
      out.lightning.push(code >= 95 ? (cape > 2000 ? 4 : 2) : 0);
      out.cloudburst.push(Math.min(1, rate / 100));
      out.rain1h.push(rate);
      out.dbz.push(rate > 0.1 ? Math.round(10 * Math.log10(200 * Math.pow(rate, 1.6))) : -10);
    }
    return out;
  }
  const max = (a) => Math.max(0, ...a);

  // ---------------------------------------------------------------- /api/state
  let cycle = 0;
  function hashId(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); }
  const hhmm = (t) => new Date((t + 19800) * 1000).toISOString().substr(11, 5);
  async function state() {
    const now = Date.now() / 1000;
    const rows = await cached("state", () => forecast(PLACES));
    const places = PLACES.map((p, k) => {
      const s = series(rows[k] || {}, now), lv = s.level, first = lv.findIndex((x) => x >= 2);
      const status = first === 0 ? "impact" : first > 0 ? "approaching" : "clear", win = max(lv);
      const out = { ...p, status, eta_min: first >= 0 ? LEADS[first] : null, level_now: lv[0], level_max: win, level_name: LEVELS[win], levels: lv, cell_id: null };
      if (status !== "clear") Object.assign(out, {
        level_window: win, duration_min: Math.max(10, lv.filter((x) => x >= 2).length * 10), approach_from: null,
        hazards: { hail_prob: max(s.hail), gust_ms: max(s.gust), lightning: max(s.lightning), cloudburst_prob: max(s.cloudburst) },
      });
      return out;
    });
    const risk = places.filter((p) => p.status !== "clear");
    const events = [{ id: 1, time: now, kind: "info", severity: 0, lat: null, lon: null,
      text: "Browser mode: storm risk comes from Open-Meteo weather-model forecasts because the BUMBLEBLE 2 km engine is not connected." }];
    for (const p of risk) events.push({ id: hashId(p.id + p.level_window + Math.floor((p.eta_min || 0) / 30)), time: now, kind: "warning",
      severity: p.level_window, lat: p.lat, lon: p.lon,
      text: `${LEVELS[p.level_window]} thunderstorm risk for ${p.name}${p.status === "impact" ? " now" : ` from about ${hhmm(now + p.eta_min * 60)} IST`} (forecast model).` });
    const fetched = now;
    return {
      type: "cycle", cycle: ++cycle, time: now, time_iso: new Date(now * 1000).toISOString(), sim_now: now, speed: 1, server_real: now,
      mode: "browser", warming_up: false, leads: LEADS,
      inputs: { radars: [], radar_ages_s: {}, radar_coverage_pct: 0, proxy_pct: 0, satellite_age_s: null, satellite_images: 0, flashes_10min: 0 },
      health: [
        { id: "OPEN-METEO", kind: "model", label: "Open-Meteo forecast (computed in your browser)", cadence_s: 900, count: 1, rejected: 0,
          last_obs_time: fetched, latency_s: 0, status: "OK", qc: "15-minute weather-model forecast" },
        { id: "RAINVIEWER", kind: "radar", label: "RainViewer radar (map display)", cadence_s: 600, count: 1, rejected: 0,
          last_obs_time: fetched, latency_s: 0, status: "OK", qc: "shown on the map as the rain radar loop" },
        { id: "ENGINE", kind: "engine", label: "BUMBLEBLE 2 km radar + satellite engine — not connected", cadence_s: 600, count: 0, rejected: 0,
          last_obs_time: null, latency_s: 0, status: "WAITING", qc: "set BUMBLEBLE_API in static/config.js to connect it" },
      ],
      cells: [], ci: [], places, events, verification: { 30: null, 60: null, 120: null }, ci_lead_mean_min: null, ci_verified_n: 0,
      stats: { n_cells: places.filter((p) => p.level_now >= 1).length, max_level_now: Math.max(0, ...places.map((p) => p.level_now)), cycle_s: 0, motion_vectors: 0 },
      arrows: [], strikes: [],
    };
  }

  // ---------------------------------------------------------------- /api/point (works anywhere on Earth)
  const km = (a, b, c, d) => { const r = Math.PI / 180, x = (d - b) * r * Math.cos((a + c) / 2 * r), y = (c - a) * r; return 6371 * Math.hypot(x, y); };
  function where(lat, lon) {
    let best = null;
    for (const p of PLACES) { const d = km(lat, lon, p.lat, p.lon); if (!best || d < best.d) best = { p, d }; }
    if (best && best.d < 3) return `over ${best.p.name}`;
    if (best && best.d < 60) return `${Math.round(best.d)} km from ${best.p.name}`;
    return `${lat.toFixed(2)}°N, ${lon.toFixed(2)}°E`;
  }
  async function point(lat, lon) {
    const now = Date.now() / 1000, key = `pt:${lat.toFixed(2)},${lon.toFixed(2)}`;
    const [row] = await cached(key, () => forecast([{ lat, lon }]));
    const s = series(row, now), c = row.current || {};
    return { lat, lon, leads: LEADS, where: where(lat, lon), ...s,
      now: { dbz: s.dbz[0], bt: null, bt_trend: null, lightning: s.lightning[0], confidence: 0.5, source: "model", radar_coverage: false, outflow: 0, qpe1h: +(c.precipitation || 0) } };
  }

  // ---------------------------------------------------------------- /api/weather*
  const CUR = "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,rain,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,cape,is_day";
  function summarise(c) {
    const code = +c.weather_code || 0, wd = c.wind_direction_10m;
    return { time: c.time, text: (WMO[code] || ["Unknown"])[0], icon: icon(code, c.is_day ?? 1), code,
      temp_c: c.temperature_2m, feels_c: c.apparent_temperature, humidity: c.relative_humidity_2m, cloud: c.cloud_cover,
      rain_mm: c.precipitation, wind_kmh: c.wind_speed_10m, gust_kmh: c.wind_gusts_10m,
      wind_from: wd == null ? null : COMPASS[Math.round(wd / 45) % 8], cape: c.cape, thunder: code >= 95 };
  }
  function weatherPoint(lat, lon) {
    lat = +lat.toFixed(2); lon = +lon.toFixed(2);
    return cached(`wx:${lat},${lon}`, async () => {
      const j = await getJ(`${OM}?latitude=${lat}&longitude=${lon}&current=${CUR}`
        + "&hourly=temperature_2m,precipitation_probability,precipitation,weather_code,wind_gusts_10m,is_day&forecast_hours=7&timezone=auto");
      const h = j.hourly || {};
      return { lat, lon, now: summarise(j.current || {}), source: "Open-Meteo", fetched: Date.now() / 1000,
        hours: (h.time || []).map((t, i) => ({ time: t, temp_c: h.temperature_2m[i], rain_prob: h.precipitation_probability[i],
          rain_mm: h.precipitation[i], gust_kmh: h.wind_gusts_10m[i], icon: icon(+h.weather_code[i] || 0, h.is_day[i]) })) };
    });
  }
  function weatherPlaces() {
    return cached("wxplaces", async () => {
      const r = await getJ(`${OM}?latitude=${list(PLACES, "lat")}&longitude=${list(PLACES, "lon")}&current=${CUR}&timezone=Asia%2FKolkata`);
      const arr = Array.isArray(r) ? r : [r];
      return { places: Object.fromEntries(PLACES.map((p, k) => [p.id, summarise((arr[k] || {}).current || {})])), source: "Open-Meteo", fetched: Date.now() / 1000 };
    });
  }

  // ---------------------------------------------------------------- assistant (rule-based in browser mode)
  async function assistant(body) {
    const msg = String(body.message || ""), m = msg.toLowerCase(), loc = body.location;
    const out = (reply, actions = []) => ({ provider: "demo", model: null, reply, actions, sources: [] });
    if (loc && /\b(me|my|here|i)\b/.test(m)) {
      const [p, w] = await Promise.all([point(loc.lat, loc.lon), weatherPoint(loc.lat, loc.lon).catch(() => null)]);
      const lv = max(p.level), first = p.level.findIndex((x) => x >= 2);
      let r = `**Your location: ${loc.name || `${loc.lat.toFixed(3)}, ${loc.lon.toFixed(3)}`}.** `;
      r += first < 0 ? `No dangerous storm is forecast here in the next 6 hours (highest level: ${LEVELS[lv]}). `
        : `Storm danger reaches **${LEVELS[lv]}** ${first === 0 ? "now" : `in about ${LEADS[first]} min`}. Plan to be indoors before then. `;
      if (w) r += `Weather now: ${w.now.text.toLowerCase()}, ${Math.round(w.now.temp_c)}°C, humidity ${w.now.humidity}%, wind ${Math.round(w.now.wind_kmh)} km/h. `;
      return out(r + "Always follow official IMD warnings.", [{ type: "fly_to", place: loc.name || "your location", lat: loc.lat, lon: loc.lon, zoom: 10 }]);
    }
    const st = await state();
    const named = st.places.find((p) => m.includes(p.name.toLowerCase().split(" ")[0]));
    if (named) {
      const w = await weatherPlaces().catch(() => null), wx = w && w.places[named.id];
      let r = named.status === "clear" ? `**${named.name}:** no dangerous storm is forecast in the next 6 hours.`
        : `**${named.name}:** ${LEVELS[named.level_window]} storm risk ${named.status === "impact" ? "now" : `from about ${hhmm(st.time + named.eta_min * 60)} IST`}. ${"Plan to be indoors before then."}`;
      if (wx) r += ` Weather now: ${wx.text.toLowerCase()}, ${Math.round(wx.temp_c)}°C.`;
      return out(r + " Always follow official IMD warnings.", [{ type: "fly_to", place: named.name, lat: named.lat, lon: named.lon, zoom: 9.5 }]);
    }
    if (/risk|safe|danger|storm|which|summary|situation|thunder/.test(m)) {
      const risk = st.places.filter((p) => p.status !== "clear").sort((a, b) => a.eta_min - b.eta_min);
      if (!risk.length) return out(`None of the ${st.places.length} watched places has a Moderate or worse storm forecast in the next 6 hours. Always follow official IMD warnings.`);
      return out(`**${risk.length} place${risk.length === 1 ? "" : "s"} at risk:**\n` + risk.slice(0, 6).map((p) =>
        `- ${p.name}: ${LEVELS[p.level_window]}${p.status === "impact" ? " now" : ` from ~${hhmm(st.time + p.eta_min * 60)} IST`}`).join("\n")
        + "\nAlways follow official IMD warnings.", [{ type: "set_layer", layer: "level" }]);
    }
    return out("I'm running in **browser mode** (the BUMBLEBLE AI server isn't connected), so I can answer simple questions: "
      + "“Which cities are at risk?”, “Is Patna safe?” or “Am I safe where I am?”. For full AI answers, connect the server in static/config.js.");
  }

  // ---------------------------------------------------------------- router
  const META = {
    mode: "browser", places: PLACES, leads: LEADS, bounds: BOUNDS, radars: [], dx_km: 2.04, dy_km: 2.22, sat_lon: null,
    legends: { level: { title: "Storm danger", unit: "", stops: [1, 2, 3, 4].map((v) => ({ v, c: "" })) } },
  };
  const needServer = (what) => { throw new Error(`${what} needs the BUMBLEBLE server (browser mode).`); };
  async function get(path) {
    const u = new URL(path, "http://x"), q = (k) => parseFloat(u.searchParams.get(k));
    switch (u.pathname) {
      case "/api/meta": return META;
      case "/api/state": return state();
      case "/api/point": return point(q("lat"), q("lon"));
      case "/api/weather": return weatherPoint(q("lat"), q("lon"));
      case "/api/weather/places": return weatherPlaces();
      case "/api/assistant/info": return { provider: "demo", mode: "browser mode — rule-based answers", model: null, knowledge_docs: 0, embeddings: false };
      case "/api/knowledge": return { docs: [] };
      default: throw new Error(`${u.pathname} is not available in browser mode`);
    }
  }
  async function post(path, body = {}) {
    const p = new URL(path, "http://x").pathname;
    if (p === "/api/assistant") return assistant(body);
    if (p.startsWith("/api/sim/")) needServer("Demo controls");
    if (p.startsWith("/api/knowledge")) needServer("The knowledge base");
    throw new Error(`${p} is not available in browser mode`);
  }
  window.BB_LITE = { get, post, del: (p) => post(p) };
})();
