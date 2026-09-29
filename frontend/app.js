/* StormSense dashboard — vanilla JS + Leaflet. */
(() => {
  "use strict";

  // ------------------------------------------------------------ i18n
  const I18N = {
    en: {
      tagline: "Convective storm nowcast · 0–6 h · hyper-local", search: "Search city, airport or district…", analysis: "Analysis",
      layers: "Map layers", overlays: "Overlays", live_ext: "Live external data", opacity: "Layer opacity", skill: "Live forecast skill",
      ov_cells: "Storm cells & tracks", ov_strikes: "Live lightning", ov_ci: "New-storm (CI) alerts", ov_clocks: "Countdowns on map",
      ov_motion: "Storm motion vectors", ov_radars: "Radar coverage", tab_cd: "Arrivals", tab_alerts: "Alerts", tab_sys: "System",
      f_all: "All", f_city: "Cities", f_air: "Airports", f_agri: "Farms", feeds: "Data feeds", pipeline: "Pipeline", demo: "Demo",
      demo_hint: "Click anywhere on the map to see its 6-hour hazard timeline or to inject a storm. Use “fail” on a feed to show graceful degradation.",
      now: "Now", impact: "IMPACT NOW", arrives: "arrives in", lasts: "lasts", from: "from", clear_all: "No place is under a Moderate or higher threat in the next 6 hours.",
      k_storms: "Active storms", k_max: "Max threat", k_places: "Places at risk", k_ci: "New storms forming", k_feeds: "Feeds online", k_skill: "30-min skill",
      banner: "Severe thunderstorm within 60 min:", hail: "Hail", gust: "Gust", light: "Lightning", cloud: "Cloudburst",
      lv: ["None", "Low", "Moderate", "High", "Extreme"], threat: "threat",
    },
    hi: {
      tagline: "तूफ़ान नाउकास्ट · 0–6 घंटे · स्थानीय", search: "शहर, हवाई अड्डा या ज़िला खोजें…", analysis: "विश्लेषण",
      layers: "मानचित्र परतें", overlays: "ओवरले", live_ext: "लाइव बाहरी डेटा", opacity: "पारदर्शिता", skill: "पूर्वानुमान सटीकता",
      ov_cells: "तूफ़ान कोशिकाएँ और मार्ग", ov_strikes: "लाइव बिजली", ov_ci: "नए तूफ़ान की चेतावनी", ov_clocks: "मानचित्र पर उलटी गिनती",
      ov_motion: "तूफ़ान की दिशा", ov_radars: "रडार कवरेज", tab_cd: "आगमन", tab_alerts: "चेतावनियाँ", tab_sys: "सिस्टम",
      f_all: "सभी", f_city: "शहर", f_air: "हवाई अड्डे", f_agri: "खेत", feeds: "डेटा स्रोत", pipeline: "प्रणाली", demo: "डेमो",
      demo_hint: "किसी स्थान का 6 घंटे का खतरा देखने या तूफ़ान जोड़ने के लिए मानचित्र पर क्लिक करें।",
      now: "अभी", impact: "अभी प्रभाव", arrives: "पहुँचेगा", lasts: "अवधि", from: "दिशा", clear_all: "अगले 6 घंटों में कोई गंभीर खतरा नहीं।",
      k_storms: "सक्रिय तूफ़ान", k_max: "अधिकतम खतरा", k_places: "खतरे में स्थान", k_ci: "बनते तूफ़ान", k_feeds: "सक्रिय स्रोत", k_skill: "30-मिनट सटीकता",
      banner: "60 मिनट में गंभीर आंधी-तूफ़ान:", hail: "ओले", gust: "हवा", light: "बिजली", cloud: "बादल फटना",
      lv: ["कोई नहीं", "कम", "मध्यम", "उच्च", "अत्यधिक"], threat: "खतरा",
    },
  };
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} } };
  let lang = store.get("lang") || "en";
  const T = (k) => (I18N[lang][k] ?? I18N.en[k] ?? k);
  function applyI18n() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = T(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = T(el.dataset.i18nPh); });
  }

  const PRODUCTS = [
    { grp: "Hazard zones" },
    { id: "level", name: "Composite threat", sub: "All hazards, per lead time", ico: "⚠️", sw: "#ef4444", lead: true },
    { id: "level_60", name: "Worst in next 1 h", sub: "Max threat swath", ico: "⏱️", sw: "#f97316", lead: false, legend: "level" },
    { id: "level_360", name: "Worst in next 6 h", sub: "Max threat swath", ico: "🗓️", sw: "#d946ef", lead: false, legend: "level" },
    { grp: "Severe parameters" },
    { id: "lightning", name: "Lightning density", sub: "flashes / km² / h", ico: "⚡", sw: "#facc15", lead: true },
    { id: "hail", name: "Hail probability", sub: "VIL density + cloud top", ico: "🧊", sw: "#a855f7", lead: true },
    { id: "gust", name: "Downburst gusts", sub: "m/s, radar + VIL", ico: "🌪️", sw: "#fb923c", lead: true },
    { id: "cloudburst", name: "Cloudburst risk", sub: "P(≥100 mm in 1 h)", ico: "🌧️", sw: "#3b82f6", lead: true },
    { id: "rain1h", name: "Rain next hour", sub: "mm", ico: "💧", sw: "#0ea5e9", lead: true },
    { grp: "Fused observations" },
    { id: "dbz", name: "Radar reflectivity", sub: "DWR mosaic + gap-fill", ico: "📡", sw: "#22c55e", lead: true },
    { id: "ir", name: "INSAT-3DR infrared", sub: "Parallax-corrected", ico: "🛰️", sw: "#64748b", lead: false },
    { id: "qpe1h", name: "Rain last hour", sub: "Observed accumulation", ico: "📈", sw: "#06b6d4", lead: false },
    { id: "confidence", name: "Fusion confidence", sub: "Radar vs proxy quality", ico: "🎯", sw: "#14b8a6", lead: false },
  ];
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const LVC = () => ["#94a3b8", css("--l1"), css("--l2"), css("--l3"), css("--l4")];

  const S = { meta: null, sum: null, product: "level", leadIdx: 0, playing: null, simAt: 0, realAt: 0, speed: 1,
    strikes: [], filter: "all", overlay: null, seenEvents: new Set(), notify: store.get("notify") === "1" };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const simNow = () => S.simAt + ((performance.now() - S.realAt) / 1000) * S.speed;
  const fmtIST = (t, sec = true) => new Date((t + 19800) * 1000).toISOString().substr(11, sec ? 8 : 5);
  const fmtCD = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ":" : "") + String(m).padStart(2, "0") + ":" + String(x).padStart(2, "0"); };
  const post = (u, b) => fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).then((r) => r.json());
  const syncClock = (m) => { if (m.sim_now == null) return; S.simAt = m.sim_now; S.realAt = performance.now(); S.speed = m.speed ?? S.speed; };

  // ------------------------------------------------------------ map + theme
  const map = L.map("map", { zoomControl: false, preferCanvas: true, zoomSnap: 0.25 }).setView([23.4, 87.5], 7);
  L.control.zoom({ position: "topleft" }).addTo(map);
  map.createPane("labels"); map.getPane("labels").style.zIndex = 450; map.getPane("labels").style.pointerEvents = "none";
  // ---------- basemaps: Google-Maps-style picker, all free & keyless ----------
  const AGS = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  const esri = (svc) => `${AGS}${svc}/MapServer/tile/{z}/{y}/{x}`;
  const ESRI_ATTR = "Tiles © Esri — Esri, Maxar, Earthstar Geographics, HERE, Garmin, © OpenStreetMap";
  const BASEMAPS = {
    auto: { name: "Default", thumb: () => esri(`Canvas/World_${isDark() ? "Dark" : "Light"}_Gray_Base`),
      layers: () => [[esri(`Canvas/World_${isDark() ? "Dark" : "Light"}_Gray_Base`), { maxZoom: 16 }],
        [esri(`Canvas/World_${isDark() ? "Dark" : "Light"}_Gray_Reference`), { maxZoom: 16, pane: "labels" }]], attr: ESRI_ATTR },
    streets: { name: "Streets", thumb: () => esri("World_Street_Map"),
      layers: () => [[esri("World_Street_Map"), { maxZoom: 19 }]], attr: ESRI_ATTR },
    satellite: { name: "Satellite", thumb: () => esri("World_Imagery"),
      layers: () => [[esri("World_Imagery"), { maxZoom: 19 }]], attr: ESRI_ATTR },
    hybrid: { name: "Hybrid", thumb: () => esri("World_Imagery"),
      layers: () => [[esri("World_Imagery"), { maxZoom: 19 }],
        [esri("Reference/World_Transportation"), { maxZoom: 19, pane: "labels", opacity: 0.8 }],
        [esri("Reference/World_Boundaries_and_Places"), { maxZoom: 19, pane: "labels" }]], attr: ESRI_ATTR },
    terrain: { name: "Terrain", thumb: () => esri("World_Terrain_Base"),
      layers: () => [[esri("World_Terrain_Base"), { maxZoom: 13 }],
        [esri("Reference/World_Reference_Overlay"), { maxZoom: 13, pane: "labels" }]], attr: ESRI_ATTR },
    topo: { name: "Topographic", thumb: () => "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
      layers: () => [["https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", { maxZoom: 17, subdomains: "abc" }]],
      attr: "© OpenStreetMap contributors, SRTM · style © OpenTopoMap (CC-BY-SA)" },
  };
  const isDark = () => document.documentElement.dataset.theme === "dark";
  const bmParam = new URLSearchParams(location.search).get("basemap");
  let baseKey = [bmParam, store.get("basemap")].find((k) => k && BASEMAPS[k]) || "auto";
  let baseLayers = [];
  function setBasemap() {
    baseLayers.forEach((l) => map.removeLayer(l));
    const bm = BASEMAPS[baseKey];
    baseLayers = bm.layers().map(([url, opt], k) => L.tileLayer(url, { ...opt, attribution: k ? "" : bm.attr }).addTo(map));
    baseLayers[0].bringToBack();
    // imagery basemaps are dark; give the map area a matching backdrop
    document.getElementById("map").classList.toggle("imagery", baseKey === "satellite" || baseKey === "hybrid");
    document.querySelector('meta[name="theme-color"]').content = isDark() ? "#0b1220" : "#ffffff";
    drawBasemapPicker();
  }
  // tile coordinates of a zoom-5 tile over India for the thumbnails
  const thumbUrl = (tpl) => tpl.replace("{s}", "a").replace("{z}", "5").replace("{x}", "23").replace("{y}", "13");
  function drawBasemapPicker() {
    const box = document.getElementById("basemap-picker");
    if (!box) return;
    const cur = BASEMAPS[baseKey];
    box.innerHTML = `<button class="bm-current" title="Map type" aria-haspopup="true">
        <img src="${thumbUrl(cur.thumb())}" alt=""><span>${cur.name}</span></button>
      <div class="bm-menu">${Object.entries(BASEMAPS).map(([k, b]) => `<button data-bm="${k}" class="${k === baseKey ? "on" : ""}">
        <img src="${thumbUrl(b.thumb())}" alt="" loading="lazy"><span>${b.name}</span></button>`).join("")}</div>`;
    box.querySelector(".bm-current").onclick = (e) => { e.stopPropagation(); box.classList.toggle("open"); };
    box.querySelectorAll("[data-bm]").forEach((b) => b.onclick = (e) => {
      e.stopPropagation(); baseKey = b.dataset.bm; store.set("basemap", baseKey); box.classList.remove("open"); setBasemap(); commit();
    });
  }
  const BasemapControl = L.Control.extend({
    options: { position: "bottomleft" },
    onAdd() {
      const div = L.DomUtil.create("div", "basemap-picker"); div.id = "basemap-picker";
      L.DomEvent.disableClickPropagation(div); L.DomEvent.disableScrollPropagation(div);
      return div;
    },
  });
  new BasemapControl().addTo(map);
  document.addEventListener("click", () => { const b = document.getElementById("basemap-picker"); if (b) b.classList.remove("open"); });
  // the theme switch (theme-switch.js) flips data-theme and fires "themechange"
  document.documentElement.addEventListener("themechange", () => { setBasemap(); if (S.sum) renderAll(); commit(); });
  $("btn-lang").onclick = () => { lang = lang === "en" ? "hi" : "en"; store.set("lang", lang); applyI18n(); if (S.sum) renderAll(); };
  setBasemap(); applyI18n();

  const canvas = L.canvas({ padding: 0.3 });
  const layers = { cells: L.layerGroup().addTo(map), strikes: L.layerGroup().addTo(map), ci: L.layerGroup().addTo(map),
    clocks: L.layerGroup().addTo(map), motion: L.layerGroup(), radars: L.layerGroup() };
  const ovMap = { "ov-cells": "cells", "ov-strikes": "strikes", "ov-ci": "ci", "ov-clocks": "clocks", "ov-motion": "motion", "ov-radars": "radars" };
  for (const [id, key] of Object.entries(ovMap)) $(id).onchange = (e) => e.target.checked ? layers[key].addTo(map) : map.removeLayer(layers[key]);

  // ---------- real-time external data (free, keyless) ----------
  // RainViewer: latest frame from weather-maps.json -> {host}{path}/256/{z}/{x}/{y}/2/1_1.png, refreshed every 5 min.
  // NASA GIBS: GPM IMERG half-hourly precipitation rate (GIBS id for GPM_3IMERGHH), "default" time = latest available.
  const RV_API = "https://api.rainviewer.com/public/weather-maps.json";
  const GIBS_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/IMERG_Precipitation_Rate_30min/default/default/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png";
  const ext = { rv: null, rvTimer: null, rvPath: null, gibs: null };
  const note = (t) => { $("ext-note").textContent = t; };
  async function loadRainViewer() {
    const j = await (await fetch(RV_API, { cache: "no-store" })).json();
    const fr = j.radar.past[j.radar.past.length - 1];
    if (fr.path === ext.rvPath && ext.rv) return;
    const url = `${j.host}${fr.path}/256/{z}/{x}/{y}/2/1_1.png`;
    if (ext.rv) ext.rv.setUrl(url);
    else ext.rv = L.tileLayer(url, { opacity: 0.7, maxNativeZoom: 7, maxZoom: 16, zIndex: 350, attribution: "Radar © RainViewer" }).addTo(map);
    ext.rvPath = fr.path;
    note(`RainViewer live radar · frame ${new Date(fr.time * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })} IST · auto-refresh 5 min`);
  }
  async function setRainViewer(on) {
    $("ov-rainviewer").checked = on; $("mb-rv").classList.toggle("on", on);
    clearInterval(ext.rvTimer);
    if (!on) { if (ext.rv) map.removeLayer(ext.rv); ext.rv = null; ext.rvPath = null; return; }
    try { await loadRainViewer(); ext.rvTimer = setInterval(() => loadRainViewer().catch(() => {}), 5 * 60 * 1000); }
    catch (_) { note("RainViewer unreachable — check the internet connection."); setRainViewer(false); }
  }
  function setGibs(on) {
    $("ov-gibs").checked = on; $("mb-gibs").classList.toggle("on", on);
    if (!on) { if (ext.gibs) map.removeLayer(ext.gibs); ext.gibs = null; return; }
    ext.gibs = L.tileLayer(GIBS_URL, { opacity: 0.75, maxNativeZoom: 6, maxZoom: 16, zIndex: 340,
      attribution: "NASA GIBS / GPM IMERG" }).addTo(map);
    ext.gibs.on("tileerror", () => note("NASA GIBS tiles unavailable for this area/time."));
    note("NASA GPM IMERG half-hourly satellite rainfall (latest available, ~4 h latency).");
  }
  $("ov-rainviewer").onchange = (e) => setRainViewer(e.target.checked);
  $("ov-gibs").onchange = (e) => setGibs(e.target.checked);

  // quick toggle buttons on the map itself
  const MapButtons = L.Control.extend({
    options: { position: "topleft" },
    onAdd() {
      const box = L.DomUtil.create("div", "leaflet-bar map-toggles");
      box.innerHTML = `<button id="mb-rv" title="Live radar (RainViewer)">📡<span>Radar</span></button>
        <button id="mb-gibs" title="Satellite rain (NASA GPM IMERG)">🛰️<span>IMERG</span></button>`;
      L.DomEvent.disableClickPropagation(box);
      return box;
    },
  });
  new MapButtons().addTo(map);
  $("mb-rv").onclick = () => setRainViewer(!$("ov-rainviewer").checked);
  $("mb-gibs").onclick = () => setGibs(!$("ov-gibs").checked);

  // ------------------------------------------------------------ panels / mobile
  const scrim = $("scrim");
  const openPanel = (id) => { $(id).classList.add("open"); scrim.classList.add("on"); };
  const closePanels = () => { document.querySelectorAll(".panel").forEach((p) => p.classList.remove("open")); scrim.classList.remove("on"); };
  $("btn-left").onclick = () => openPanel("left"); $("btn-right").onclick = () => openPanel("right");
  scrim.onclick = closePanels; document.querySelectorAll("[data-close]").forEach((b) => b.onclick = closePanels);
  document.querySelectorAll(".tab").forEach((b) => b.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("on", p.id === "tab-" + b.dataset.tab));
  });
  document.querySelectorAll("#filter button").forEach((b) => b.onclick = () => {
    document.querySelectorAll("#filter button").forEach((x) => x.classList.toggle("on", x === b)); S.filter = b.dataset.f; drawCountdowns();
  });

  // ------------------------------------------------------------ notifications
  const nb = $("btn-notify");
  nb.classList.toggle("active", S.notify);
  nb.onclick = async () => {
    if (!S.notify && "Notification" in window && Notification.permission !== "granted") await Notification.requestPermission();
    S.notify = !S.notify; store.set("notify", S.notify ? "1" : "0"); nb.classList.toggle("active", S.notify);
    toast(S.notify ? "Alerts on" : "Alerts off", S.notify ? "You'll be notified about High / Extreme threats." : "", 1);
  };
  function toast(title, text, sev = 3) {
    const el = document.createElement("div"); el.className = "toast";
    el.style.borderLeftColor = LVC()[Math.min(sev, 4)];
    el.innerHTML = `<b>${esc(title)}</b>${esc(text)}`; $("toasts").appendChild(el);
    setTimeout(() => el.remove(), 7000);
  }

  // ------------------------------------------------------------ products
  function buildProducts() {
    const box = $("products"); box.innerHTML = "";
    for (const p of PRODUCTS) {
      if (p.grp) { box.insertAdjacentHTML("beforeend", `<div class="pgroup">${p.grp}</div>`); continue; }
      const b = document.createElement("button");
      b.className = "prod" + (p.id === S.product ? " sel" : "");
      b.innerHTML = `<span class="sw" style="background:${p.sw}22">${p.ico}</span><span><b>${p.name}</b><small>${p.sub}</small></span>`;
      b.onclick = () => { S.product = p.id; buildProducts(); refreshRaster(); drawLegend(); closePanels(); commit(); };
      box.appendChild(b);
    }
  }
  const prodInfo = () => PRODUCTS.find((p) => p.id === S.product) || {};

  const setLead = (i) => { S.leadIdx = i; $("lead").value = i; refreshRaster(); updateLeadText(); drawCells(); };
  $("lead").oninput = (e) => { setLead(+e.target.value); commit(); };
  $("opacity").oninput = (e) => S.overlay && S.overlay.setOpacity(+e.target.value);
  const togglePlay = () => {
    const btn = $("play");
    if (S.playing) { clearInterval(S.playing); S.playing = null; btn.classList.remove("on"); return; }
    if (!prodInfo().lead) { S.product = "level"; buildProducts(); drawLegend(); }
    btn.classList.add("on"); preload();
    S.playing = setInterval(() => setLead((S.leadIdx + 1) % S.meta.leads.length), 600);
  };
  $("play").onclick = togglePlay;
  document.addEventListener("keydown", (e) => {
    if (!S.meta || (e.target.tagName === "INPUT" && e.target.type !== "range") || e.target.tagName === "SELECT") return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if (e.code === "ArrowRight") setLead(Math.min(S.leadIdx + 1, S.meta.leads.length - 1));
    if (e.code === "ArrowLeft") setLead(Math.max(S.leadIdx - 1, 0));
  });
  $("speed").onchange = (e) => post("/api/sim/speed", { speed: +e.target.value }).then((r) => { S.simAt = simNow(); S.realAt = performance.now(); S.speed = r.speed; });

  function updateLeadText() {
    const lead = S.meta ? S.meta.leads[S.leadIdx] : 0, p = prodInfo();
    const h = Math.floor(lead / 60), m = lead % 60;
    $("lead-text").textContent = p.lead === false ? p.name : lead === 0 ? T("now") : `+${h ? h + " h " : ""}${m ? m + " min" : ""}`;
    $("valid-time").textContent = S.sum ? "valid " + fmtIST(S.sum.time + (p.lead === false ? 0 : lead * 60), false) + " IST" : "--";
  }
  const rasterUrl = (prod, idx) => { const p = PRODUCTS.find((x) => x.id === prod); return `/api/raster/${prod}/${p && p.lead ? idx : 0}.png?c=${S.sum ? S.sum.cycle : 0}`; };
  function refreshRaster() {
    if (!S.meta || !S.sum) return;
    const url = rasterUrl(S.product, S.leadIdx);
    $("export-png").href = url;
    if (!S.overlay) S.overlay = L.imageOverlay(url, S.meta.bounds, { opacity: +$("opacity").value, className: "raster" }).addTo(map);
    else { const im = new Image(); im.onload = () => S.overlay.setUrl(url); im.src = url; }
    updateLeadText();
  }
  const preload = () => S.meta && S.meta.leads.forEach((_, i) => { new Image().src = rasterUrl(S.product, i); });
  function drawLegend() {
    if (!S.meta) return;
    const key = prodInfo().legend || S.product, lg = S.meta.legends[key];
    if (!lg) return;
    if (key === "level") {
      $("legend").innerHTML = `<div class="t">${lg.title}</div><div class="bar">${[1, 2, 3, 4].map((k) => `<span style="background:${LVC()[k]}"></span>`).join("")}</div>
        <div class="ticks">${T("lv").slice(1).map((n) => `<span>${n}</span>`).join("")}</div>`;
      return;
    }
    const st = lg.stops, tk = [st[0], st[Math.floor(st.length / 2)], st[st.length - 1]];
    $("legend").innerHTML = `<div class="t">${lg.title}${lg.unit ? " · " + lg.unit : ""}</div><div class="bar">${st.map((s) => `<span style="background:${s.c}"></span>`).join("")}</div>
      <div class="ticks">${tk.map((s) => `<span>${s.v}</span>`).join("")}</div>`;
  }

  // ------------------------------------------------------------ KPIs & banner
  function drawKPIs() {
    const s = S.sum, lv = s.stats.max_level_now, placed = s.places.filter((p) => p.status !== "clear").length;
    const ok = s.health.filter((h) => h.status === "OK").length, v = s.verification["30"];
    const k = (label, val, extra = "", color = "") => `<div class="kpi card"><small>${label}</small><b style="color:${color}">${val}<span>${extra}</span></b></div>`;
    $("kpis").innerHTML = k(T("k_storms"), s.stats.n_cells) + k(T("k_max"), T("lv")[lv], "", LVC()[lv]) + k(T("k_places"), placed, "", placed ? LVC()[3] : "")
      + k(T("k_ci"), s.ci.filter((c) => !c.verified).length) + k(T("k_feeds"), ok, "/" + s.health.length, ok < s.health.length ? css("--warn") : "")
      + (v ? k(T("k_skill"), v.csi, " CSI") : "");
  }
  function drawBanner() {
    const w = S.sum.places.filter((p) => p.status !== "clear" && (p.level_window || 0) >= 3 && (p.eta_min ?? 999) <= 60), b = $("banner");
    if (!w.length) { b.classList.add("hidden"); return; }
    b.classList.remove("hidden");
    b.innerHTML = `⚠️ <span>${T("banner")} <b>${w.slice(0, 4).map((p) => esc(p.name)).join(", ")}</b>${w.length > 4 ? " +" + (w.length - 4) : ""}</span>`;
    b.onclick = () => { document.querySelector('[data-tab="countdown"]').click(); openPanel("right"); map.flyTo([w[0].lat, w[0].lon], 9); };
  }

  // ------------------------------------------------------------ cells, CI, motion, radars
  function trackPos(c, lead) {
    const tr = c.track; if (!lead) return [c.lat, c.lon];
    const k = tr.findIndex((p) => p[2] >= lead);
    if (k === -1) return [tr[tr.length - 1][0], tr[tr.length - 1][1]];
    if (k === 0) return [tr[0][0], tr[0][1]];
    const a = tr[k - 1], b = tr[k], f = (lead - a[2]) / (b[2] - a[2]);
    return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])];
  }
  function drawCells() {
    layers.cells.clearLayers(); if (!S.sum) return;
    const lead = S.meta.leads[S.leadIdx], C = LVC();
    for (const c of S.sum.cells) {
      const col = C[c.level];
      if (c.past && c.past.length > 1) L.polyline(c.past, { color: css("--muted"), weight: 2, opacity: .7, renderer: canvas }).addTo(layers.cells);
      L.polyline(c.track.map((p) => [p[0], p[1]]), { color: col, weight: 2.5, dashArray: "6 6", renderer: canvas }).addTo(layers.cells);
      c.track.slice(1).forEach((p) => L.circleMarker([p[0], p[1]], { radius: 3, color: col, fillColor: col, fillOpacity: 1, weight: 1, renderer: canvas })
        .bindTooltip(`+${p[2]} min`, { direction: "top" }).addTo(layers.cells));
      const pos = trackPos(c, lead), r = Math.max(6, Math.sqrt(c.area_km2 / Math.PI) * 1.2);
      L.circle(pos, { radius: r * 1000, color: col, weight: 2.5, fillColor: col, fillOpacity: .08, dashArray: lead ? "4 4" : null })
        .bindPopup(() => cellPopup(c), { maxWidth: 340 }).addTo(layers.cells);
      L.marker(pos, { icon: L.divIcon({ className: "cell-label", html: `#${c.id}${c.lightning_jump ? " ⚡" : ""}`, iconAnchor: [-10, 7] }), interactive: false }).addTo(layers.cells);
    }
  }
  function cellPopup(c) {
    const r = (k, v) => `<span>${k}</span><span>${v}</span>`, col = LVC()[c.level];
    return `<div class="pop"><h3>Storm #${c.id} <span class="pill-lvl" style="background:${col}">${T("lv")[c.level]}</span></h3>
      <div class="sub">${esc(c.where)} · ${c.stage} · ${c.age_min} min old</div><div class="grid">
      ${r("Reflectivity", `${c.max_dbz} dBZ (${c.trend >= 0 ? "+" : ""}${c.trend} dB/10 min)`)}${r("VIL", c.max_vil + " kg/m²")}
      ${r("Cloud top", c.min_bt == null ? "n/a" : c.min_bt + " K")}${r("Lightning", `${c.flash_rate} /min${c.lightning_jump ? " · <b style='color:var(--l2)'>JUMP ⚡</b>" : ""}`)}
      ${r("Hail chance", Math.round(c.hail * 100) + "%")}${r("Peak gust", `${Math.round(c.gust * 3.6)} km/h`)}
      ${r("Moving", `${c.speed_kmh} km/h → ${c.heading_deg}°`)}${r("Seen by", c.source === "radar" ? "Doppler radar" : "Satellite + lightning (radar gap)")}</div></div>`;
  }
  function drawCI() {
    layers.ci.clearLayers();
    for (const c of S.sum.ci) if (!c.verified) L.marker([c.lat, c.lon], { icon: L.divIcon({ className: "", html: '<div class="ci-icon"></div>', iconSize: [24, 24], iconAnchor: [12, 12] }) })
      .bindPopup(`<div class="pop"><h3>🌱 New storm forming</h3><div class="sub">${esc(c.where)}</div><div class="grid">
        <span>Probability</span><span>${Math.round(c.prob * 100)}%</span><span>Cloud top</span><span>${c.min_bt} K</span>
        <span>Cooling</span><span>${c.cooling} K / 15 min</span><span>Tracked</span><span>${c.age_min} min</span></div>
        <p class="fine">Towering cloud cooling fast, no strong radar echo yet — thunderstorm likely within ~15–45 min.</p></div>`).addTo(layers.ci);
  }
  function drawMotion() {
    layers.motion.clearLayers();
    for (const [la, lo, u, v] of S.sum.arrows) {
      const e = [la + v * .02, lo + u * .02 / Math.cos(la * Math.PI / 180)];
      L.polyline([[la, lo], e], { color: css("--brand"), weight: 1.8, renderer: canvas }).addTo(layers.motion);
      L.circleMarker(e, { radius: 2, color: css("--brand"), renderer: canvas }).addTo(layers.motion);
    }
  }
  function drawRadars() {
    layers.radars.clearLayers();
    for (const r of S.meta.radars) {
      L.circle([r.lat, r.lon], { radius: r.range_km * 1000, color: css("--brand"), weight: 1, fill: false, dashArray: "4 6", interactive: false }).addTo(layers.radars);
      L.circleMarker([r.lat, r.lon], { radius: 5, color: css("--brand"), fillOpacity: 1 }).bindTooltip(r.name + " DWR").addTo(layers.radars);
    }
  }
  function drawStrikes() {
    const now = simNow();
    S.strikes = S.strikes.filter((s) => now - s[2] < 600).slice(-6000);
    layers.strikes.clearLayers();
    const dark = document.documentElement.dataset.theme === "dark";
    for (const [la, lo, t, cg] of S.strikes) {
      const age = (now - t) / 600, col = age < .1 ? (dark ? "#fff" : "#7c3aed") : age < .4 ? "#facc15" : "#f97316";
      L.circleMarker([la, lo], { radius: cg ? 2.8 : 1.7, color: col, weight: cg ? 1 : 0, fillColor: col, fillOpacity: Math.max(.15, 1 - age),
        opacity: Math.max(.15, 1 - age), renderer: canvas, interactive: false }).addTo(layers.strikes);
    }
  }

  // ------------------------------------------------------------ countdowns
  const typeIco = (t) => t === "airport" ? "✈️" : t === "agri" ? "🌾" : "🏙️";
  function drawCountdowns() {
    if (!S.sum) return;
    const th = S.sum.places.filter((p) => p.status !== "clear");
    $("n-threat").textContent = th.length;
    const list = th.filter((p) => S.filter === "all" || p.type === S.filter);
    if (!list.length) { $("countdowns").innerHTML = `<div class="empty"><div class="big">☀️</div>${T("clear_all")}</div>`; return; }
    $("countdowns").innerHTML = list.map((p) => {
      const h = p.hazards || {}, lv = p.level_window || p.level_max, now = p.status === "impact";
      const cell = (ico, lab, val, bad) => `<div class="${bad ? "bad" : ""}"><b>${val}</b><small>${ico} ${lab}</small></div>`;
      return `<div class="cd l${lv}" data-lat="${p.lat}" data-lon="${p.lon}"><div class="cd-row"><div>
          <div class="cd-name">${typeIco(p.type)} ${esc(p.name)}</div>
          <div class="cd-sub">${p.state}${p.approach_from ? ` · ${T("from")} ${p.approach_from}` : ""} · ${T("lasts")} ~${p.duration_min} min</div>
          <span class="lvl-badge">${T("lv")[lv]} ${T("threat")}</span></div>
        <div class="cd-time ${now ? "now" : ""}" data-eta="${now ? "" : S.sum.time + p.eta_min * 60}">
          <span class="mono">${now ? T("impact") : "--:--"}</span><small>${now ? "" : T("arrives")}</small></div></div>
        ${now ? "" : `<div class="progress"><i data-eta="${S.sum.time + p.eta_min * 60}" style="width:0"></i></div>`}
        <div class="hz">${cell("🧊", T("hail"), Math.round(h.hail_prob * 100) + "%", h.hail_prob >= .3)}${cell("🌪️", T("gust"), Math.round(h.gust_ms * 3.6) + "<small> km/h</small>", h.gust_ms >= 20)}
          ${cell("⚡", T("light"), h.lightning, h.lightning >= 2)}${cell("🌧️", T("cloud"), Math.round(h.cloudburst_prob * 100) + "%", h.cloudburst_prob >= .3)}</div></div>`;
    }).join("");
    $("countdowns").querySelectorAll(".cd").forEach((el) => el.onclick = () => { map.flyTo([+el.dataset.lat, +el.dataset.lon], 9.5); closePanels(); });
    tick();
  }
  function drawMapClocks() {
    layers.clocks.clearLayers();
    for (const p of S.sum.places) {
      if (p.status === "clear") continue;
      const lv = p.level_window || p.level_max, tgt = S.sum.time + (p.eta_min || 0) * 60;
      L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", iconAnchor: [-6, 10],
        html: `<div class="map-clock l${lv}" data-eta="${p.status === "impact" ? "" : tgt}">${esc(p.name)}<b>${p.status === "impact" ? T("now") : "--:--"}</b></div>` }) }).addTo(layers.clocks);
      L.circleMarker([p.lat, p.lon], { radius: 4.5, color: "#fff", weight: 1.5, fillColor: LVC()[lv], fillOpacity: 1 }).addTo(layers.clocks);
    }
  }
  function tick() {
    const now = simNow();
    document.querySelectorAll(".cd-time[data-eta]").forEach((el) => {
      if (!el.dataset.eta) return; const rem = +el.dataset.eta - now;
      el.querySelector(".mono").textContent = rem <= 0 ? T("now") : fmtCD(rem); el.classList.toggle("soon", rem < 1800);
    });
    document.querySelectorAll(".progress i").forEach((el) => { const rem = +el.dataset.eta - now; el.style.width = Math.max(0, Math.min(100, 100 - rem / 36)) + "%"; });
    document.querySelectorAll(".map-clock[data-eta]").forEach((el) => { if (!el.dataset.eta) return; const rem = +el.dataset.eta - now; el.querySelector("b").textContent = rem <= 0 ? T("now") : fmtCD(rem); });
  }

  // ------------------------------------------------------------ alerts / system
  const EV_ICO = { warning: "⚠️", ci: "🌱", ljump: "⚡", cloudburst: "🌧️", clear: "✅", feed: "📡", demo: "🧪", info: "ℹ️" };
  function drawEvents() {
    const ev = S.sum.events;
    $("n-alerts").textContent = ev.filter((e) => e.severity >= 2).length;
    $("events").innerHTML = ev.map((e) => `<div class="ev s${e.severity}" data-lat="${e.lat ?? ""}" data-lon="${e.lon ?? ""}"><div class="ic">${EV_ICO[e.kind] || "•"}</div>
      <div><div class="tx">${esc(e.text)}</div><div class="meta">${fmtIST(e.time, false)} IST · ${e.kind}</div></div></div>`).join("") || `<div class="empty">No events yet.</div>`;
    $("events").querySelectorAll(".ev").forEach((el) => el.onclick = () => { if (el.dataset.lat) { map.flyTo([+el.dataset.lat, +el.dataset.lon], 9); closePanels(); } });
    const first = S.seenEvents.size === 0;
    for (const e of ev) {
      if (S.seenEvents.has(e.id)) continue; S.seenEvents.add(e.id);
      if (first || e.severity < 3) continue;
      toast(e.kind === "cloudburst" ? "Cloudburst risk" : "Severe weather warning", e.text, e.severity);
      if (S.notify && "Notification" in window && Notification.permission === "granted") new Notification("StormSense", { body: e.text });
    }
  }
  function drawFeeds(health) {
    const sim = S.meta && S.meta.mode === "simulated";
    $("feeds").innerHTML = health.map((h) => {
      const down = h.status === "DOWN" || h.status === "STALE", age = h.last_obs_time ? Math.round((simNow() - h.last_obs_time) / 60) + "m" : "--";
      return `<div class="feed" title="${esc(h.qc)}"><span class="dot ${h.status}"></span><span>${esc(h.label)}</span>
        <span class="lat mono">${age} · ${Math.round(h.latency_s)}s</span>
        ${sim ? `<button class="mini-btn ${down ? "" : "danger"}" data-src="${h.id}" data-en="${down ? 1 : 0}">${down ? "restore" : "fail"}</button>` : "<span></span>"}</div>`;
    }).join("");
    $("feeds").querySelectorAll("button").forEach((b) => b.onclick = () => post("/api/sim/source", { source_id: b.dataset.src, enabled: b.dataset.en === "1" }));
  }
  function drawStats() {
    const s = S.sum, i = s.inputs, st = s.stats, kv = (k, v) => `<div><span>${k}</span><span>${v}</span></div>`;
    $("stats").innerHTML = kv("Grid", `${S.meta.dx_km} × ${S.meta.dy_km} km`) + kv("Radars fused", i.radars.length) + kv("Radar coverage", i.radar_coverage_pct + "%")
      + kv("Satellite gap-fill", i.proxy_pct + "%") + kv("Satellite age", i.satellite_age_s == null ? "n/a" : Math.round(i.satellite_age_s / 60) + " min")
      + kv("Flashes / 10 min", i.flashes_10min) + kv("Motion vectors", st.motion_vectors)
      + kv("New-storm lead time", s.ci_lead_mean_min == null ? "--" : `${s.ci_lead_mean_min} min (n=${s.ci_verified_n})`) + kv("Cycle compute", st.cycle_s + " s");
    const rows = Object.entries(s.verification).map(([L, x]) => x ? `<tr><td>+${L} min</td><td><b>${x.csi}</b></td><td>${x.pod}</td><td>${x.far}</td><td>${x.csi_persistence}</td></tr>`
      : `<tr><td>+${L} min</td><td colspan="4" style="text-align:center;color:var(--muted)">collecting…</td></tr>`).join("");
    $("verif").innerHTML = `<table class="verif"><tr><th>Lead</th><th>CSI</th><th>POD</th><th>FAR</th><th>Persist.</th></tr>${rows}</table>
      <p class="fine">Forecast ≥35 dBZ vs. later radar. Persistence = “storm doesn’t move” baseline.</p>`;
  }

  // ------------------------------------------------------------ search
  const sInput = $("search"), sRes = $("search-results");
  // 1) monitored places (instant, with live ETA)  2) any place on Earth via Open-Meteo geocoding (free, no key)
  let hits = [], active = 0, geoTimer = null, geoSeq = 0, pin = null;
  const inDomain = (p) => S.meta && p.lat >= S.meta.bounds[0][0] && p.lat <= S.meta.bounds[1][0] && p.lon >= S.meta.bounds[0][1] && p.lon <= S.meta.bounds[1][1];
  function statusOf(p) {
    const f = p.id && S.sum && S.sum.places.find((x) => x.id === p.id);
    if (f) return f.status === "clear" ? "✓ clear" : f.status === "impact" ? "⚠ " + T("impact") : `⏱ ETA ${Math.round(f.eta_min)} min`;
    return inDomain(p) ? "in forecast area" : "real-time weather";
  }
  function renderHits(loading) {
    sRes.innerHTML = hits.map((p, k) => `<div data-k="${k}" class="${k === active ? "act" : ""}">
        <span>${typeIco(p.type)} ${esc(p.name)} <small>${esc(p.sub || p.state || "")}</small></span><small>${statusOf(p)}</small></div>`).join("")
      + (loading ? `<div><small>Searching all places…</small></div>` : hits.length ? "" : `<div><small>No place found</small></div>`);
    sRes.classList.add("on");
    sRes.querySelectorAll("[data-k]").forEach((el) => {
      el.onmousedown = (e) => e.preventDefault(); // keep focus so the list doesn't close before click
      el.onclick = () => go(hits[+el.dataset.k]);
    });
  }
  sInput.oninput = () => {
    const q = sInput.value.trim();
    clearTimeout(geoTimer);
    if (!q) { sRes.classList.remove("on"); hits = []; return; }
    const ql = q.toLowerCase();
    const local = (S.meta ? S.meta.places : []).filter((p) => p.name.toLowerCase().includes(ql) || p.state.toLowerCase() === ql)
      .slice(0, 6).map((p) => ({ ...p, sub: p.state }));
    hits = local; active = 0;
    renderHits(q.length >= 2);
    if (q.length < 2) return;
    const seq = ++geoSeq;
    geoTimer = setTimeout(async () => {
      try {
        const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=10&language=en&format=json`);
        const j = await r.json();
        if (seq !== geoSeq) return; // a newer keystroke superseded this request
        const seen = new Set(local.map((p) => p.name.toLowerCase()));
        const geo = (j.results || [])
          .sort((a, b) => (b.country_code === "IN") - (a.country_code === "IN") || (b.population || 0) - (a.population || 0))
          .filter((g) => !seen.has(g.name.toLowerCase()) || g.country_code !== "IN")
          .slice(0, 8 - local.length)
          .map((g) => ({ name: g.name, lat: g.latitude, lon: g.longitude, type: "city",
            sub: [g.admin1, g.country].filter(Boolean).join(", ") }));
        hits = local.concat(geo);
      } catch (_) { /* offline: keep local hits */ }
      if (seq === geoSeq && document.activeElement === sInput) renderHits(false);
    }, 250);
  };
  sInput.onkeydown = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); if (!hits.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : hits.length - 1)) % hits.length; renderHits(false);
    }
    if (e.key === "Enter" && hits[active]) go(hits[active]);
    if (e.key === "Escape") { sRes.classList.remove("on"); sInput.blur(); }
  };
  sInput.onfocus = () => { if (sInput.value.trim()) sInput.oninput(); };
  function go(p) {
    sRes.classList.remove("on"); sInput.value = p.name; sInput.blur(); closePanels();
    if (pin) map.removeLayer(pin);
    pin = L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 26],
      html: '<div class="search-pin">📍</div>' }) }).addTo(map);
    map.flyTo([p.lat, p.lon], inDomain(p) ? 9.5 : 8, { duration: 1.2 });
    map.once("moveend", () => inspect(L.latLng(p.lat, p.lon)));
  }
  document.addEventListener("click", (e) => { if (!e.target.closest(".search")) sRes.classList.remove("on"); });

  // ------------------------------------------------------------ point inspector (+ Open-Meteo environment)
  map.on("click", (e) => inspect(e.latlng));
  async function inspect(ll) {
    const { lat, lng } = ll;
    const pop = L.popup({ maxWidth: 360 }).setLatLng(ll).setContent('<div class="pop">Loading…</div>').openOn(map);
    let d = null; try { const r = await fetch(`/api/point?lat=${lat}&lon=${lng}`); if (r.ok) d = await r.json(); } catch (_) {}
    const sim = S.meta && S.meta.mode === "simulated";
    const btns = sim ? `<div class="btns"><button class="mini-btn" data-k="hail" data-m="0">🌱 Start a storm here</button>
      <button class="mini-btn" data-k="downburst" data-m="1">🌪️ Drop downburst storm</button><button class="mini-btn" data-k="heavy_rain" data-m="1">🌧️ Drop cloudburst storm</button></div>` : "";
    if (!d) {
      // outside the nowcast domain: still show real-time atmosphere from Open-Meteo
      pop.setContent(`<div class="pop"><h3>${lat.toFixed(3)}°N, ${lng.toFixed(3)}°E</h3><div class="sub">Outside the nowcast domain</div>
        <div class="env">Loading Open-Meteo…</div></div>`);
      openMeteo(pop.getElement().querySelector(".env"), lat, lng);
      return;
    }
    const n = d.now, mx = Math.max(...d.level), first = d.level.findIndex((x) => x >= 2), C = LVC();
    pop.setContent(`<div class="pop"><h3>${esc(d.where)}</h3>
      <div class="sub">Next 6 h: <span class="pill-lvl" style="background:${C[mx]}">${T("lv")[mx]}</span>${first > 0 ? ` from +${d.leads[first]} min` : first === 0 ? " now" : ""}</div>
      <div class="grid"><span>Radar now</span><span>${n.dbz > 5 ? n.dbz + " dBZ" : "no echo"} (${n.source})</span>
      <span>Cloud top</span><span>${n.bt == null ? "n/a" : n.bt + " K"}${n.bt_trend != null ? ` · ${n.bt_trend} K/15 min` : ""}</span>
      <span>Lightning</span><span>${n.lightning} fl/km²/h</span><span>Rain last hour</span><span>${n.qpe1h} mm</span>
      <span>Worst hail / gust</span><span>${Math.round(Math.max(...d.hail) * 100)}% · ${Math.round(Math.max(...d.gust) * 3.6)} km/h</span></div>
      <canvas width="640" height="240"></canvas><div class="env">Loading real-time atmosphere (Open-Meteo)…</div>${btns}</div>`);
    const el = pop.getElement();
    drawTimeline(el.querySelector("canvas"), d);
    el.querySelectorAll("[data-k]").forEach((b) => b.onclick = () => post("/api/sim/spawn", { lat, lon: lng, kind: b.dataset.k, mature: b.dataset.m === "1" })
      .then(() => { map.closePopup(); toast("Storm injected", "It will appear in the next analysis cycle.", 1); }));
    openMeteo(el.querySelector(".env"), lat, lng);
  }

  // Open-Meteo (free, keyless): current + hourly CAPE and 10 m wind gusts for the clicked point
  async function openMeteo(envEl, lat, lon) {
    if (!envEl) return;
    try {
      const u = `https://api.open-meteo.com/v1/forecast?latitude=${lat.toFixed(4)}&longitude=${lon.toFixed(4)}`
        + `&hourly=cape,wind_gusts_10m&current=cape,wind_gusts_10m&timezone=Asia%2FKolkata&forecast_days=1`;
      const r = await fetch(u);
      if (!r.ok) throw new Error(r.status);
      const j = await r.json(), c = j.current || {}, h = j.hourly || {};
      // next 6 hourly values from the current hour
      const i0 = Math.max(0, (h.time || []).findIndex((t) => t >= (c.time || "").slice(0, 13)));
      const nxt = (a) => (a || []).slice(i0, i0 + 6).filter((x) => x != null);
      const capeMax = Math.max(0, ...nxt(h.cape)), gustMax = Math.max(0, ...nxt(h.wind_gusts_10m));
      const cape = c.cape ?? 0, gust = c.wind_gusts_10m ?? 0;
      const inst = (v) => v >= 2500 ? ["very unstable", "var(--l3)"] : v >= 1000 ? ["unstable", "var(--l2)"] : v >= 300 ? ["marginal", "var(--l1)"] : ["stable", "var(--ok)"];
      const [txt, col] = inst(Math.max(cape, capeMax));
      envEl.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <b>🌍 Real-time atmosphere</b><span class="pill-lvl" style="background:${col}">${txt}</span></div>
        <div class="grid"><span>CAPE now</span><span><b>${Math.round(cape)}</b> J/kg</span>
          <span>Wind gust now</span><span><b>${Math.round(gust)}</b> km/h</span>
          <span>Max next 6 h</span><span>${Math.round(capeMax)} J/kg · ${Math.round(gustMax)} km/h</span></div>
        <div class="fine">Open-Meteo · ${esc((c.time || "").replace("T", " "))} IST</div>`;
    } catch (_) { envEl.textContent = "Open-Meteo unavailable — check the internet connection."; }
  }
  function drawTimeline(cv, d) {
    const x = cv.getContext("2d"), W = cv.width, H = cv.height, n = d.leads.length, pad = 30, bw = (W - pad) / n, C = LVC();
    x.clearRect(0, 0, W, H);
    d.level.forEach((lv, i) => { x.fillStyle = C[lv]; x.globalAlpha = lv ? .9 : .15; x.fillRect(pad + i * bw, H - 34, bw - 2, 14); });
    x.globalAlpha = 1;
    const line = (a, max, col) => { x.strokeStyle = col; x.lineWidth = 3; x.beginPath();
      a.forEach((v, i) => { const px = pad + i * bw + bw / 2, py = H - 44 - Math.min(Math.max(v, 0), max) / max * (H - 70); i ? x.lineTo(px, py) : x.moveTo(px, py); }); x.stroke(); };
    line(d.dbz, 70, "#22c55e"); line(d.hail, 1, "#a855f7"); line(d.gust, 40, "#f97316"); line(d.lightning, 8, "#eab308");
    x.fillStyle = css("--muted"); x.font = "600 18px Inter, sans-serif";
    [0, 60, 120, 180, 240, 300, 360].forEach((m) => { const i = d.leads.indexOf(m); if (i >= 0) x.fillText(m ? m / 60 + "h" : "now", pad + i * bw, H - 4); });
    [["radar", "#22c55e"], ["hail", "#a855f7"], ["gust", "#f97316"], ["lightning", "#eab308"]].forEach(([t, c], k) => { x.fillStyle = c; x.fillText("● " + t, pad + k * 120, 20); });
  }

  // ------------------------------------------------------------ view history (undo / redo)
  // Every user or assistant change to the view (layer, lead time, map type, theme, position) is a version.
  const H = { stack: [], idx: -1, applying: false, timer: null };
  const viewState = () => ({ product: S.product, leadIdx: S.leadIdx, basemap: baseKey, theme: document.documentElement.dataset.theme,
    center: [+map.getCenter().lat.toFixed(4), +map.getCenter().lng.toFixed(4)], zoom: +map.getZoom().toFixed(2) });
  const sameView = (a, b) => a && b && JSON.stringify(a) === JSON.stringify(b);
  function commit() {
    if (H.applying || !S.meta) return;
    clearTimeout(H.timer);
    H.timer = setTimeout(() => {
      const v = viewState();
      if (sameView(v, H.stack[H.idx])) return;
      H.stack = H.stack.slice(0, H.idx + 1); H.stack.push(v);
      if (H.stack.length > 60) H.stack.shift();
      H.idx = H.stack.length - 1; updateHistoryButtons();
    }, 450);
  }
  function applyView(v) {
    H.applying = true;
    S.product = v.product; buildProducts(); drawLegend();
    if (v.basemap !== baseKey) { baseKey = v.basemap; store.set("basemap", baseKey); }
    if (v.theme !== document.documentElement.dataset.theme) setTheme(v.theme, false);
    setBasemap(); setLead(v.leadIdx);
    map.flyTo(v.center, v.zoom, { duration: 0.6 });
    map.once("moveend", () => { H.applying = false; });
    setTimeout(() => { H.applying = false; }, 900);
    updateHistoryButtons();
  }
  function updateHistoryButtons() { $("btn-undo").disabled = H.idx <= 0; $("btn-redo").disabled = H.idx >= H.stack.length - 1; }
  const undo = () => { if (H.idx > 0) { H.idx--; applyView(H.stack[H.idx]); } };
  const redo = () => { if (H.idx < H.stack.length - 1) { H.idx++; applyView(H.stack[H.idx]); } };
  $("btn-undo").onclick = undo; $("btn-redo").onclick = redo;
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || ["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
    if (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey)) { e.preventDefault(); redo(); }
  });
  map.on("moveend", commit);
  function setTheme(t, record = true) {
    document.documentElement.dataset.theme = t; store.set("theme", t);
    $("btn-theme").setAttribute("aria-checked", String(t === "dark"));
    setBasemap(); if (S.sum) renderAll(); if (record) commit();
  }

  // ------------------------------------------------------------ share link
  function readShareParams() {
    const q = new URLSearchParams(location.search), out = {};
    const lat = parseFloat(q.get("lat")), lon = parseFloat(q.get("lon")), z = parseFloat(q.get("z"));
    if (isFinite(lat) && isFinite(lon)) out.view = { center: [lat, lon], zoom: isFinite(z) ? z : 8 };
    if (q.get("layer") && PRODUCTS.some((p) => p.id === q.get("layer"))) out.layer = q.get("layer");
    const lead = parseInt(q.get("lead"), 10);
    if (isFinite(lead)) out.leadIdx = Math.max(0, Math.round(lead / 10));
    return out;
  }
  $("btn-share").onclick = async () => {
    const v = viewState(), u = new URL(location.origin + "/app");
    u.searchParams.set("lat", v.center[0]); u.searchParams.set("lon", v.center[1]); u.searchParams.set("z", v.zoom);
    u.searchParams.set("layer", v.product); u.searchParams.set("lead", S.meta.leads[v.leadIdx]);
    u.searchParams.set("basemap", v.basemap); u.searchParams.set("theme", v.theme);
    try { await navigator.clipboard.writeText(u.href); toast("Link copied", "Anyone opening it sees this exact map, layer and time.", 1); }
    catch (_) { prompt("Copy this link:", u.href); }
  };

  // ------------------------------------------------------------ export menu
  const exWrap = document.querySelector(".export-wrap");
  $("btn-export").onclick = (e) => { e.stopPropagation(); exWrap.classList.toggle("open"); };
  document.addEventListener("click", (e) => { if (!e.target.closest(".export-wrap")) exWrap.classList.remove("open"); });
  $("export-menu").querySelectorAll("a").forEach((a) => a.addEventListener("click", (e) => {
    if (!S.sum) { e.preventDefault(); toast("Not ready yet", "Wait for the first analysis to finish.", 1); return; }
    exWrap.classList.remove("open");
  }));

  // ------------------------------------------------------------ AI assistant
  const AI = { history: [], busy: false };
  const AI_CHIPS = ["Which cities are at risk?", "Summary", "Show hail risk in 2 hours", "Zoom to Kolkata",
    "Switch to satellite map", "Turn on live radar", "Show lightning now", "Dark mode"];
  $("ai-chips").innerHTML = AI_CHIPS.map((c) => `<button type="button">${esc(c)}</button>`).join("");
  $("ai-chips").querySelectorAll("button").forEach((b) => b.onclick = () => askAI(b.textContent));
  const PROVIDER_NAMES = { gemini: "Gemini", claude: "Claude", demo: "Demo mode" };
  fetch("/api/assistant/info").then((r) => r.json()).then((j) => {
    $("ai-mode").textContent = j.provider === "demo" ? "Demo mode" : `AI · ${PROVIDER_NAMES[j.provider] || j.provider}`;
    $("ai-mode").title = `${j.mode}${j.model ? " — " + j.model : ""} · RAG: ${j.knowledge_docs} docs${j.embeddings ? " (semantic + keyword)" : " (keyword)"}`;
  }).catch(() => { $("ai-mode").textContent = "offline"; });

  // ---------- knowledge base (RAG) panel
  $("kb-btn").onclick = () => { $("kb-panel").classList.toggle("hidden"); loadKB(); };
  async function loadKB() {
    try {
      const j = await (await fetch("/api/knowledge")).json();
      $("kb-count").textContent = j.docs.length;
      $("kb-list").innerHTML = j.docs.map((d) => `<div class="kb-doc"><span>📄 ${esc(d.name)} <small>${d.chunks} passages</small></span>
        <button type="button" class="mini-btn danger" data-del="${esc(d.name)}" title="Remove">✕</button></div>`).join("") || `<div class="fine">No documents yet.</div>`;
      $("kb-list").querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
        if (!confirm(`Remove ${b.dataset.del} from the knowledge base?`)) return;
        await fetch("/api/knowledge/" + encodeURIComponent(b.dataset.del), { method: "DELETE" }); loadKB();
      });
    } catch (_) { $("kb-list").innerHTML = `<div class="fine">Knowledge base unavailable.</div>`; }
  }
  async function saveDoc(name, text) {
    const r = await fetch("/api/knowledge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, text }) });
    if (!r.ok) { toast("Could not add document", (await r.json()).detail || r.status, 2); return; }
    toast("Added to knowledge base", name + " is now searchable by the assistant.", 1); loadKB();
  }
  $("kb-file").onchange = async (e) => { for (const f of e.target.files) saveDoc(f.name, await f.text()); e.target.value = ""; };
  $("kb-save").onclick = () => {
    const t = $("kb-text").value.trim(); if (!t) return;
    saveDoc(($("kb-name").value.trim() || "note") + ".md", `# ${$("kb-name").value.trim() || "Note"}\n\n${t}`);
    $("kb-text").value = ""; $("kb-name").value = "";
  };
  loadKB();
  const md = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
  function aiBubble(role, html) {
    const el = document.createElement("div"); el.className = "ai-msg " + role; el.innerHTML = html;
    $("ai-log").appendChild(el); $("ai-log").scrollTop = $("ai-log").scrollHeight; return el;
  }
  aiBubble("bot", "Hi! I’m the <b>BUMBLEBLE</b> assistant. Ask about storms, places at risk or hazards — or tell me what to show on the map.");
  $("ai-form").onsubmit = (e) => { e.preventDefault(); askAI($("ai-input").value); };
  $("ai-input").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askAI($("ai-input").value); } };
  async function askAI(text) {
    text = (text || "").trim(); if (!text || AI.busy) return;
    document.querySelector('[data-tab="ai"]').click();
    $("ai-input").value = ""; AI.busy = true;
    aiBubble("me", esc(text));
    const wait = aiBubble("bot typing", "<span></span><span></span><span></span>");
    try {
      const r = await fetch("/api/assistant", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: AI.history.slice(-8) }) });
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      const j = await r.json();
      wait.remove();
      const srcs = (j.sources || []).filter((s) => new RegExp("\\[" + s.n + "\\]").test(j.reply || "") || j.provider === "demo").slice(0, 3);
      const cite = srcs.length ? `<div class="ai-src">📚 ${srcs.map((s) => `<span title="${esc(s.title)}">[${s.n}] ${esc(s.doc.replace(/\.(md|txt)$/, "").replace(/^\d+_/, "").replace(/_/g, " "))}</span>`).join("")}</div>` : "";
      const who = j.model ? `<div class="ai-model">${esc(PROVIDER_NAMES[j.provider] || j.provider)} · ${esc(j.model)}</div>` : "";
      aiBubble("bot", md(j.reply || "Done.") + cite + who);
      AI.history.push({ role: "user", content: text }, { role: "assistant", content: j.reply || "" });
      runActions(j.actions || []);
    } catch (err) {
      wait.remove();
      aiBubble("bot error", "Sorry — the assistant is unavailable right now (" + esc(String(err.message || err)) + ").");
    } finally { AI.busy = false; }
  }
  function runActions(actions) {
    for (const a of actions) {
      if (a.type === "set_layer") { S.product = a.layer; buildProducts(); refreshRaster(); drawLegend(); }
      else if (a.type === "set_lead") {
        const i = S.meta.leads.indexOf(a.lead_min);
        if (i >= 0) { if (!prodInfo().lead) { S.product = "level"; buildProducts(); drawLegend(); } setLead(i); }
      } else if (a.type === "fly_to") map.flyTo([a.lat, a.lon], a.zoom || 9, { duration: 1.1 });
      else if (a.type === "set_basemap") { baseKey = a.basemap; store.set("basemap", baseKey); setBasemap(); }
      else if (a.type === "set_theme") setTheme(a.theme, false);
      else if (a.type === "toggle_overlay") {
        if (a.overlay === "rainviewer") setRainViewer(a.on);
        else if (a.overlay === "gibs") setGibs(a.on);
        else { const id = "ov-" + a.overlay, el = $(id); if (el && el.checked !== a.on) { el.checked = a.on; el.onchange({ target: el }); } }
      }
    }
    if (actions.length) commit();
  }

  // ------------------------------------------------------------ lightning accents (never over the map)
  const isLight = () => document.documentElement.dataset.theme === "light";
  if (window.Lightning) {
    Lightning.mount($("fx-logo"), { hue: 215, speed: 1.8, intensity: 0.9, size: 1.2, maxDpr: 2 });
    // a faint bolt drifting behind the left part of the top bar
    const top = Lightning.mount($("fx-topbar"), { hue: 228, speed: 0.9, intensity: 0.28, size: 1.4, maxDpr: 1, light: isLight });
    const t0 = performance.now();
    setInterval(() => top.set({ xOffset: Math.sin((performance.now() - t0) / 9000) * 2.2 }), 120);
  }

  // ------------------------------------------------------------ first-time onboarding
  function maybeOnboard() {
    const qs = new URLSearchParams(location.search);
    if (store.get("onboarded") || qs.has("lat") || qs.has("embed")) return;
    $("onboard").classList.remove("hidden");
    const fx = window.Lightning ? Lightning.mount($("fx-onboard"), { hue: 222, speed: 1.4, intensity: 0.55, size: 2, light: isLight }) : null;
    const done = () => { $("onboard").classList.add("hidden"); store.set("onboarded", "1"); if (fx) fx.destroy(); };
    $("onboard").querySelectorAll("[data-q]").forEach((b) => b.onclick = () => { done(); openPanel("right"); askAI(b.dataset.q); });
    $("onboard-skip").onclick = done;
  }

  // ------------------------------------------------------------ data flow
  function renderAll() {
    refreshRaster(); drawCells(); drawCI(); drawMotion(); drawCountdowns(); drawMapClocks(); drawEvents();
    drawFeeds(S.sum.health); drawStats(); drawKPIs(); drawBanner(); drawStrikes(); drawLegend(); buildProducts(); drawRadars();
  }
  function onCycle(sum) {
    S.sum = sum; syncClock(sum); S.strikes = sum.strikes.slice();
    $("analysis-time").textContent = fmtIST(sum.time, false);
    renderAll(); if (S.playing) preload();
  }
  function onTick(m) {
    syncClock(m); drawFeeds(m.health);
    const b = $("mode-badge"), sim = S.meta.mode === "simulated";
    b.className = "status-pill " + (m.warming_up ? "warm" : "live");
    b.querySelector("span").textContent = m.warming_up ? "Spinning up…" : sim ? "SIMULATION" : S.meta.mode === "realtime" ? "LIVE DATA" : "LIVE";
    const sel = $("speed"); if (document.activeElement !== sel && !m.warming_up) sel.value = String(m.speed);
  }
  function connect() {
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.onclose = () => { const b = $("mode-badge"); b.className = "status-pill off"; b.querySelector("span").textContent = "Reconnecting"; setTimeout(connect, 2000); };
    ws.onmessage = (ev) => { const m = JSON.parse(ev.data);
      if (m.type === "cycle") onCycle(m); else if (m.type === "tick") onTick(m); else if (m.type === "strikes") S.strikes.push(...m.strikes); };
  }
  async function init() {
    S.meta = await (await fetch("/api/meta")).json();
    $("lead").max = S.meta.leads.length - 1;
    if (S.meta.mode !== "simulated") $("speed").style.display = "none";
    if (S.meta.mode === "realtime") S.product = "dbz"; // open on the real radar mosaic
    map.invalidateSize();
    const shared = readShareParams();
    if (shared.view) map.setView(shared.view.center, shared.view.zoom); else map.fitBounds(S.meta.bounds, { padding: [10, 10] });
    if (shared.layer) S.product = shared.layer;
    if (shared.leadIdx != null) S.leadIdx = Math.min(shared.leadIdx, S.meta.leads.length - 1);
    $("lead").value = S.leadIdx; // keep the slider handle in sync with a shared lead time
    L.rectangle(S.meta.bounds, { color: css("--brand"), weight: 1, fill: false, dashArray: "2 6", interactive: false }).addTo(map);
    buildProducts(); drawLegend(); drawRadars();
    const st = await (await fetch("/api/state")).json(); syncClock(st);
    if (st.type === "cycle") onCycle(st);
    else { $("countdowns").innerHTML = `<div class="empty"><div class="big">⏳</div>Spinning up — first forecast in a few seconds…</div>`; drawFeeds(st.health || []); }
    connect();
    maybeOnboard();
    setTimeout(commit, 600); // first history entry
    // ?ask=... opens the assistant with a question (handy for demos and shared links)
    const ask = new URLSearchParams(location.search).get("ask");
    if (ask) setTimeout(() => { openPanel("right"); askAI(ask); }, 400);
    setInterval(() => { const t = simNow(); $("clock-ist").textContent = fmtIST(t); $("clock-utc").textContent = new Date(t * 1000).toISOString().substr(11, 5); tick(); }, 250);
    setInterval(() => { if (S.sum && map.hasLayer(layers.strikes)) drawStrikes(); }, 2000);
  }
  init();
})();
