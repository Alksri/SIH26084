/* BUMBLEBLE — live map page (/app). Map-first: arrivals, alerts, AI and system details live on their own pages. */
(() => {
  "use strict";
  const qs = new URLSearchParams(location.search);
  const EMBED = qs.has("embed");
  if (EMBED) document.body.classList.add("embed"); else BB.nav("map");
  const { esc, fmtIST, fmtCD, store, LEVELS, ADVICE } = BB;
  const $ = (id) => document.getElementById(id);
  const css = (v) => getComputedStyle(document.body).getPropertyValue(v).trim();
  const LVC = () => ["#94a3b8", css("--l1"), css("--l2"), css("--l3"), css("--l4")];

  const PRODUCTS = [
    { grp: "Danger overview" },
    { id: "level", name: "Overall storm danger", sub: "All hazards combined — start here", ico: "⚠️", sw: "#ef4444", lead: true },
    { id: "level_60", name: "Worst in the next hour", sub: "Highest danger anywhere in 1 h", ico: "⏱️", sw: "#f97316", lead: false, legend: "level" },
    { id: "level_360", name: "Worst in the next 6 hours", sub: "Highest danger anywhere in 6 h", ico: "🗓️", sw: "#d946ef", lead: false, legend: "level" },
    { grp: "Individual hazards" },
    { id: "lightning", name: "Lightning", sub: "How often lightning strikes", ico: "⚡", sw: "#facc15", lead: true },
    { id: "hail", name: "Hail", sub: "Chance of hailstones", ico: "🧊", sw: "#a855f7", lead: true },
    { id: "gust", name: "Strong winds", sub: "Sudden gusts from storms", ico: "🌪️", sw: "#fb923c", lead: true },
    { id: "cloudburst", name: "Cloudburst", sub: "Chance of 100 mm+ rain in an hour", ico: "🌧️", sw: "#3b82f6", lead: true },
    { id: "rain1h", name: "Rain in the next hour", sub: "Expected rainfall, mm", ico: "💧", sw: "#0ea5e9", lead: true },
    { grp: "What sensors see now" },
    { id: "dbz", name: "Weather radar", sub: "Rain and storm intensity", ico: "📡", sw: "#22c55e", lead: true },
    { id: "ir", name: "Satellite clouds", sub: "INSAT-3DR infrared image", ico: "🛰️", sw: "#64748b", lead: false },
    { id: "qpe1h", name: "Rain in the last hour", sub: "Measured rainfall, mm", ico: "📈", sw: "#06b6d4", lead: false },
    { id: "confidence", name: "Data confidence", sub: "How reliable the map is", ico: "🎯", sw: "#14b8a6", lead: false },
  ];
  const prod = (id) => PRODUCTS.find((p) => p.id === id) || PRODUCTS[1];

  const S = { meta: null, sum: null, product: "level", leadIdx: 0, playing: null, overlay: null, strikes: [] };

  // ------------------------------------------------------------ map + basemaps
  const map = L.map("map", { zoomControl: false, preferCanvas: true, zoomSnap: 0.25, minZoom: 2, worldCopyJump: true,
    maxBounds: [[-85, -540], [85, 540]], maxBoundsViscosity: 1 }).setView([23.4, 87.5], 7);
  L.control.zoom({ position: "topright" }).addTo(map);
  // quick jumps: whole world <-> the storm-forecast area
  const ViewControl = L.Control.extend({
    options: { position: "topright" },
    onAdd() {
      const box = L.DomUtil.create("div", "leaflet-bar m-view");
      box.innerHTML = `<a href="#" role="button" id="v-world" title="Show the whole world" aria-label="Show the whole world">🌍</a>
        <a href="#" role="button" id="v-area" title="Back to the storm-forecast area" aria-label="Back to the storm-forecast area">🎯</a>`;
      L.DomEvent.disableClickPropagation(box);
      box.querySelector("#v-world").onclick = (e) => { e.preventDefault(); map.flyTo([20, 80], 2, { duration: 1.2 }); };
      box.querySelector("#v-area").onclick = (e) => { e.preventDefault(); if (S.meta) map.flyToBounds(S.meta.bounds, { padding: [20, 20], duration: 1.2 }); };
      return box;
    },
  });
  new ViewControl().addTo(map);
  map.createPane("labels"); map.getPane("labels").style.zIndex = 450; map.getPane("labels").style.pointerEvents = "none";
  const isDark = () => document.documentElement.dataset.theme === "dark";
  const esri = (s) => `https://server.arcgisonline.com/ArcGIS/rest/services/${s}/MapServer/tile/{z}/{y}/{x}`;
  const BASEMAPS = {
    auto: { name: "Default", thumb: () => esri(`Canvas/World_${isDark() ? "Dark" : "Light"}_Gray_Base`),
      layers: () => [[esri(`Canvas/World_${isDark() ? "Dark" : "Light"}_Gray_Base`), { maxZoom: 16 }],
        [esri(`Canvas/World_${isDark() ? "Dark" : "Light"}_Gray_Reference`), { maxZoom: 16, pane: "labels" }]] },
    streets: { name: "Streets", thumb: () => esri("World_Street_Map"), layers: () => [[esri("World_Street_Map"), { maxZoom: 19 }]] },
    satellite: { name: "Satellite", thumb: () => esri("World_Imagery"), layers: () => [[esri("World_Imagery"), { maxZoom: 19 }]] },
    hybrid: { name: "Satellite + labels", thumb: () => esri("World_Imagery"), layers: () => [[esri("World_Imagery"), { maxZoom: 19 }],
      [esri("Reference/World_Transportation"), { maxZoom: 19, pane: "labels", opacity: .7 }],
      [esri("Reference/World_Boundaries_and_Places"), { maxZoom: 19, pane: "labels" }]] },
    terrain: { name: "Terrain", thumb: () => esri("World_Terrain_Base"), layers: () => [[esri("World_Terrain_Base"), { maxZoom: 13 }],
      [esri("Reference/World_Reference_Overlay"), { maxZoom: 13, pane: "labels" }]] },
    topo: { name: "Topographic", thumb: () => "https://a.tile.opentopomap.org/{z}/{x}/{y}.png", attr: "© OpenStreetMap, SRTM · © OpenTopoMap",
      layers: () => [["https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", { maxZoom: 17, subdomains: "abc" }]] },
  };
  // a zoom-5 tile over eastern India for the previews
  const thumbUrl = (t) => t.replace("{s}", "a").replace("{z}", "5").replace("{x}", "23").replace("{y}", "13");
  let baseKey = [qs.get("basemap"), store.get("basemap")].find((k) => k && BASEMAPS[k]) || "auto", baseLayers = [];
  function setBasemap() {
    baseLayers.forEach((l) => map.removeLayer(l));
    const bm = BASEMAPS[baseKey];
    baseLayers = bm.layers().map(([u, o], k) => L.tileLayer(u, { ...o, attribution: k ? "" : bm.attr || "Tiles © Esri" }).addTo(map));
    baseLayers[0].bringToBack();
    $("mt-thumb").src = thumbUrl(bm.thumb());
    $("basemaps").innerHTML = Object.entries(BASEMAPS).map(([k, b]) =>
      `<button type="button" data-bm="${k}" class="${k === baseKey ? "on" : ""}" aria-pressed="${k === baseKey}">
        <img src="${thumbUrl(b.thumb())}" alt="" loading="lazy"><span>${b.name}</span></button>`).join("");
    $("basemaps").querySelectorAll("[data-bm]").forEach((b) => b.onclick = () => { baseKey = b.dataset.bm; store.set("basemap", baseKey); setBasemap(); });
  }
  setBasemap();

  // ------------------------------------------------------------ map type menu
  const mtMenu = $("mt-menu"), mtBtn = $("mt-btn");
  const openMT = (on) => { mtMenu.classList.toggle("hidden", !on); mtBtn.setAttribute("aria-expanded", String(on)); };
  mtBtn.onclick = (e) => { e.stopPropagation(); openMT(mtMenu.classList.contains("hidden")); };
  $("mt-close").onclick = () => openMT(false);
  mtMenu.onclick = (e) => e.stopPropagation();
  L.DomEvent.disableClickPropagation(mtMenu); L.DomEvent.disableScrollPropagation(mtMenu);
  document.addEventListener("click", () => openMT(false));
  const fxNote = (t) => { $("fx-note").textContent = t || ""; };

  // ------------------------------------------------------------ animation: live wind flow (Open-Meteo, free, keyless)
  // A 12×12 grid of current 10 m winds around the forecast area drives particles drawn on a canvas over the map.
  const wind = { on: false, grid: null, parts: [], raf: 0, timer: 0, reload: 0, seq: 0, zoom: 0, B: null };
  const wc = $("wind-canvas"), wx = wc.getContext("2d");
  function sizeWind() {
    const r = $("map").getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
    wc.width = r.width * dpr; wc.height = r.height * dpr; wc.style.width = r.width + "px"; wc.style.height = r.height + "px";
    wc.style.top = r.top + "px"; wc.style.left = r.left + "px"; wx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  // grid box = current view + 15% margin (lon kept unwrapped so it matches map coordinates; wrapped only for the request)
  function viewBox() {
    const b = map.getBounds(), dLat = (b.getNorth() - b.getSouth()) * .15, dLon = (b.getEast() - b.getWest()) * .15;
    const B = { s: Math.max(-80, b.getSouth() - dLat), n: Math.min(80, b.getNorth() + dLat), w: b.getWest() - dLon, e: b.getEast() + dLon, nx: 16, ny: 12 };
    if (B.e - B.w > 360) { const c = (B.e + B.w) / 2; B.w = c - 180; B.e = c + 180; }
    return B;
  }
  const wrapLon = (x) => ((x + 180) % 360 + 360) % 360 - 180;
  async function loadWind() {
    const B = viewBox(), lats = [], lons = [], seq = ++wind.seq;
    for (let j = 0; j < B.ny; j++) for (let i = 0; i < B.nx; i++) {
      lats.push((B.s + (B.n - B.s) * j / (B.ny - 1)).toFixed(2)); lons.push(wrapLon(B.w + (B.e - B.w) * i / (B.nx - 1)).toFixed(2));
    }
    const j = await BB.getJSON(`https://api.open-meteo.com/v1/forecast?latitude=${lats.join(",")}&longitude=${lons.join(",")}`
      + "&current=wind_speed_10m,wind_direction_10m&wind_speed_unit=ms");
    const arr = Array.isArray(j) ? j : [j];
    if (seq !== wind.seq) return; // a newer view superseded this request
    wind.B = B; wind.zoom = map.getZoom();
    // meteorological direction = where the wind blows FROM; u east-ward, v north-ward
    wind.grid = arr.map((r) => { const sp = r.current.wind_speed_10m, d = r.current.wind_direction_10m * Math.PI / 180; return [-sp * Math.sin(d), -sp * Math.cos(d)]; });
    const max = Math.max(...arr.map((r) => r.current.wind_speed_10m));
    fxNote(`Wind: live surface wind from Open-Meteo · strongest ${Math.round(max * 3.6)} km/h in view.`);
  }
  function windAt(lat, lon) {
    const B = wind.B, g = wind.grid; if (!g || !B) return null;
    const fx = (lon - B.w) / (B.e - B.w) * (B.nx - 1), fy = (lat - B.s) / (B.n - B.s) * (B.ny - 1);
    if (fx < 0 || fy < 0 || fx > B.nx - 1 || fy > B.ny - 1) return null;
    const i = Math.min(B.nx - 2, Math.floor(fx)), jj = Math.min(B.ny - 2, Math.floor(fy)), a = fx - i, b = fy - jj, k = (x, y) => g[y * B.nx + x];
    const mix = (c) => (k(i, jj)[c] * (1 - a) + k(i + 1, jj)[c] * a) * (1 - b) + (k(i, jj + 1)[c] * (1 - a) + k(i + 1, jj + 1)[c] * a) * b;
    return [mix(0), mix(1)];
  }
  const spawn = (p) => { p.x = Math.random() * wc.clientWidth; p.y = Math.random() * wc.clientHeight; p.age = Math.random() * 80 | 0; return p; };
  function resetParticles() {
    const n = Math.min(2600, Math.round(wc.clientWidth * wc.clientHeight / 650));
    wind.parts = Array.from({ length: n }, () => spawn({})); wx.clearRect(0, 0, wc.width, wc.height);
  }
  const windColor = (sp) => isDark()
    ? (sp < 3 ? "rgba(186,230,253,.55)" : sp < 7 ? "rgba(125,211,252,.75)" : sp < 12 ? "rgba(253,224,71,.85)" : "rgba(251,146,60,.9)")
    : (sp < 3 ? "rgba(30,64,120,.4)" : sp < 7 ? "rgba(3,105,161,.6)" : sp < 12 ? "rgba(180,83,9,.75)" : "rgba(194,65,12,.85)");
  function windFrame() {
    if (!wind.on) return;
    wx.globalCompositeOperation = "destination-in"; wx.fillStyle = "rgba(0,0,0,.93)"; wx.fillRect(0, 0, wc.clientWidth, wc.clientHeight);
    wx.globalCompositeOperation = "source-over"; wx.lineWidth = 1.3; wx.lineCap = "round";
    const scale = Math.max(0.17, 0.18 * Math.pow(1.35, map.getZoom() - 6));
    for (const p of wind.parts) {
      const ll = map.containerPointToLatLng([p.x, p.y]), w = windAt(ll.lat, ll.lng);
      if (!w || ++p.age > 110) { spawn(p); p.age = 0; continue; }
      const sp = Math.hypot(w[0], w[1]), nx = p.x + w[0] * scale, ny = p.y - w[1] * scale;
      wx.strokeStyle = windColor(sp); wx.beginPath(); wx.moveTo(p.x, p.y); wx.lineTo(nx, ny); wx.stroke();
      p.x = nx; p.y = ny;
      if (nx < 0 || ny < 0 || nx > wc.clientWidth || ny > wc.clientHeight) spawn(p);
    }
    wind.raf = requestAnimationFrame(windFrame);
  }
  async function setWind(on) {
    wind.on = on; $("fx-wind").checked = on; store.set("fx-wind", on ? "1" : "0"); cancelAnimationFrame(wind.raf); clearInterval(wind.timer);
    wc.classList.toggle("hidden", !on);
    if (!on) { wx.clearRect(0, 0, wc.width, wc.height); return; }
    sizeWind(); resetParticles();
    try { if (!wind.grid) await loadWind(); } catch (_) { fxNote("Wind data unavailable — check the internet connection."); setWind(false); return; }
    wind.timer = setInterval(() => loadWind().catch(() => {}), 15 * 60 * 1000);
    if (wind.on) windFrame();
  }
  map.on("movestart zoomstart", () => { if (wind.on) { cancelAnimationFrame(wind.raf); wx.clearRect(0, 0, wc.width, wc.height); } });
  // re-fetch the wind grid when the view leaves the loaded box or the zoom changes a lot
  const viewCovered = () => { const B = wind.B, b = map.getBounds();
    return B && b.getSouth() >= B.s && b.getNorth() <= B.n && b.getWest() >= B.w && b.getEast() <= B.e && Math.abs(map.getZoom() - wind.zoom) < 1.5; };
  map.on("moveend zoomend", () => {
    if (!wind.on) return;
    cancelAnimationFrame(wind.raf); resetParticles(); windFrame();
    clearTimeout(wind.reload);
    if (!viewCovered()) wind.reload = setTimeout(() => loadWind().catch(() => fxNote("Wind data unavailable for this view.")), 500);
  });
  addEventListener("resize", () => { if (wind.on) { sizeWind(); resetParticles(); } });
  $("fx-wind").onchange = (e) => setWind(e.target.checked);

  // ------------------------------------------------------------ animation: rain radar loop (RainViewer, last ~2 h, real data)
  const rain = { on: false, layers: [], frames: [], i: 0, timer: 0 };
  async function setRain(on) {
    rain.on = on; $("fx-rain").checked = on; store.set("fx-rain", on ? "1" : "0");
    clearInterval(rain.timer); rain.layers.forEach((l) => map.removeLayer(l)); rain.layers = []; $("rain-badge").classList.add("hidden");
    if (!on) return;
    try {
      const j = await BB.getJSON("https://api.rainviewer.com/public/weather-maps.json");
      rain.frames = j.radar.past.slice(-12); rain.i = 0;
      rain.layers = rain.frames.map((f) => L.tileLayer(`${j.host}${f.path}/256/{z}/{x}/{y}/2/1_1.png`,
        { opacity: 0, maxNativeZoom: 7, maxZoom: 16, zIndex: 360, attribution: "Radar © RainViewer" }).addTo(map));
    } catch (_) { fxNote("Rain radar unavailable — check the internet connection."); $("fx-rain").checked = false; rain.on = false; return; }
    if (!rain.on) { rain.layers.forEach((l) => map.removeLayer(l)); rain.layers = []; return; }
    $("rain-badge").classList.remove("hidden");
    const step = () => {
      rain.layers.forEach((l, k) => l.setOpacity(k === rain.i ? .75 : 0));
      const f = rain.frames[rain.i], last = rain.i === rain.frames.length - 1;
      $("rain-time").textContent = fmtIST(f.time) + " IST" + (last ? " · latest" : "");
      rain.i = (rain.i + 1) % rain.frames.length;
    };
    step(); rain.timer = setInterval(step, 700);
    fxNote("Rain radar: real radar images from the last 2 hours, played as a loop (RainViewer).");
  }
  $("fx-rain").onchange = (e) => setRain(e.target.checked);

  // ------------------------------------------------------------ animation: lightning flashes for each new strike
  const flashes = L.layerGroup().addTo(map);
  function flashStrikes(list) {
    if (!$("fx-flash").checked || !list || !list.length) return;
    for (const [la, lo] of list.slice(-40)) {
      const m = L.marker([la, lo], { interactive: false, icon: L.divIcon({ className: "", iconSize: [36, 36], iconAnchor: [18, 18], html: '<div class="flash"></div>' }) }).addTo(flashes);
      setTimeout(() => flashes.removeLayer(m), 1000);
    }
  }
  $("fx-flash").checked = store.get("fx-flash") !== "0";
  $("fx-flash").onchange = (e) => store.set("fx-flash", e.target.checked ? "1" : "0");
  document.documentElement.addEventListener("themechange", () => { setBasemap(); if (S.sum) renderAll(); else drawLegend(); });

  const canvas = L.canvas({ padding: 0.3 });
  const layers = { cells: L.layerGroup().addTo(map), strikes: L.layerGroup().addTo(map), ci: L.layerGroup().addTo(map),
    clocks: L.layerGroup().addTo(map), radars: L.layerGroup() };
  for (const key of Object.keys(layers)) {
    const el = $("ov-" + key);
    el.onchange = () => el.checked ? layers[key].addTo(map) : map.removeLayer(layers[key]);
  }

  // ------------------------------------------------------------ layer sheet
  const sheet = $("layer-sheet"), lbtn = $("layer-btn");
  const openSheet = (on) => { sheet.classList.toggle("hidden", !on); lbtn.setAttribute("aria-expanded", String(on)); };
  lbtn.onclick = (e) => { e.stopPropagation(); openSheet(sheet.classList.contains("hidden")); };
  $("sheet-close").onclick = () => openSheet(false);
  sheet.onclick = (e) => e.stopPropagation();
  L.DomEvent.disableClickPropagation(sheet); L.DomEvent.disableScrollPropagation(sheet);
  document.addEventListener("click", () => openSheet(false));

  function buildProducts() {
    $("products").innerHTML = PRODUCTS.map((p) => p.grp ? `<div class="m-grp">${p.grp}</div>` :
      `<button type="button" class="m-prod ${p.id === S.product ? "sel" : ""}" data-p="${p.id}">
        <span class="m-layer-ico" style="--sw:${p.sw}">${p.ico}</span><span><b>${p.name}</b><small>${p.sub}</small></span></button>`).join("");
    $("products").querySelectorAll("[data-p]").forEach((b) => b.onclick = () => setProduct(b.dataset.p, true));
    const p = prod(S.product);
    $("layer-ico").textContent = p.ico; $("layer-ico").style.setProperty("--sw", p.sw); $("layer-name").textContent = p.name;
  }
  function setProduct(id, closeAfter) {
    S.product = prod(id).id; buildProducts(); refreshRaster(); drawLegend();
    syncTimeline();
    if (closeAfter && matchMedia("(max-width: 760px)").matches) openSheet(false);
  }
  $("opacity").oninput = (e) => S.overlay && S.overlay.setOpacity(+e.target.value);

  // ------------------------------------------------------------ raster, timeline, legend
  const rasterUrl = (id, i) => BB.url(`/api/raster/${id}/${prod(id).lead ? i : 0}.png?c=${S.sum ? S.sum.cycle : 0}`);
  function refreshRaster() {
    if (!S.meta || !S.sum) return;
    if (S.meta.mode === "browser") { updateLeadText(); return; } // no 2 km layers without the engine
    const url = rasterUrl(S.product, S.leadIdx);
    if (!S.overlay) S.overlay = L.imageOverlay(url, S.meta.bounds, { opacity: +$("opacity").value, className: "raster" }).addTo(map);
    else { const im = new Image(); im.onload = () => S.overlay.setUrl(url); im.src = url; }
    updateLeadText();
  }
  function updateLeadText() {
    const p = prod(S.product), lead = S.meta ? S.meta.leads[S.leadIdx] : 0, h = Math.floor(lead / 60), m = lead % 60;
    $("tw-kicker").textContent = !p.lead ? "This layer shows" : lead === 0 ? "Showing" : "Forecast for";
    $("lead-text").textContent = !p.lead ? "Latest observation" : lead === 0 ? "Right now" : `In ${h ? h + " h " : ""}${m ? m + " min" : ""}`.trim();
    $("valid-time").textContent = S.sum ? fmtIST(S.sum.time + (p.lead ? lead * 60 : 0)) + " IST" : "--:--";
    syncTimeline();
  }
  // time widget: progress fill, passed blocks, active hour label, button states
  function syncTimeline() {
    if (!S.meta) return;
    const n = S.meta.leads.length - 1, live = prod(S.product).lead, i = live ? S.leadIdx : 0, lead = S.meta.leads[i];
    $("lead").disabled = !live; $("timeline").classList.toggle("static", !live);
    $("tw-fill").style.setProperty("--p", n ? (i / n) * 100 + "%" : "0%");
    $("tw-strip").querySelectorAll("i").forEach((el, k) => el.classList.toggle("past", k <= i));
    $("tw-ticks").querySelectorAll("button").forEach((b) => b.classList.toggle("on", live && +b.dataset.min === lead));
    $("step-back").disabled = !live || i === 0; $("step-fwd").disabled = !live || i === n;
    $("go-now").hidden = !live || i === 0;
  }
  // one block per 10 min, coloured by the worst danger expected at any watched place at that time
  function drawStrip() {
    if (!S.meta) return;
    const C = LVC(), worst = S.meta.leads.map((_, k) => S.sum ? Math.max(0, ...S.sum.places.map((p) => (p.levels || [])[k] || 0)) : 0);
    $("tw-strip").innerHTML = worst.map((lv, k) => `<i class="${lv ? "lv" : ""}" style="${lv ? `background:${C[lv]}` : ""}"
      title="${S.meta.leads[k] ? "+" + S.meta.leads[k] + " min" : "now"}: ${LEVELS[lv]}"></i>`).join("");
    syncTimeline();
  }
  const setLead = (i) => { if (!S.meta) return; S.leadIdx = Math.max(0, Math.min(i, S.meta.leads.length - 1)); $("lead").value = S.leadIdx; refreshRaster(); updateLeadText(); drawCells(); };
  $("lead").oninput = (e) => setLead(+e.target.value);
  const ensureLive = () => { if (!prod(S.product).lead) setProduct("level"); };
  $("step-back").onclick = () => { ensureLive(); setLead(S.leadIdx - 1); };
  $("step-fwd").onclick = () => { ensureLive(); setLead(S.leadIdx + 1); };
  $("go-now").onclick = () => setLead(0);
  $("tw-ticks").querySelectorAll("button").forEach((b) => b.onclick = () => { ensureLive(); setLead(S.meta.leads.indexOf(+b.dataset.min)); });
  function togglePlay() {
    const btn = $("play");
    if (S.playing) { clearInterval(S.playing); S.playing = null; btn.classList.remove("on"); return; }
    if (!S.meta) return;
    if (!prod(S.product).lead) setProduct("level");
    btn.classList.add("on");
    S.meta.leads.forEach((_, i) => { new Image().src = rasterUrl(S.product, i); });
    S.playing = setInterval(() => setLead((S.leadIdx + 1) % S.meta.leads.length), 650);
  }
  $("play").onclick = togglePlay;
  document.addEventListener("keydown", (e) => {
    if (!S.meta || ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName) && e.target.type !== "range") return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if (e.code === "ArrowRight") setLead(Math.min(S.leadIdx + 1, S.meta.leads.length - 1));
    if (e.code === "ArrowLeft") setLead(Math.max(S.leadIdx - 1, 0));
    if (e.key === "Escape") openSheet(false);
  });
  function drawLegend() {
    if (!S.meta) return;
    const p = prod(S.product), key = p.legend || p.id, lg = S.meta.legends[key];
    if (!lg) { $("legend").innerHTML = ""; return; }
    if (key === "level") {
      $("legend").innerHTML = `<div class="t">Storm danger</div><div class="bar">${[1, 2, 3, 4].map((k) => `<span style="background:${LVC()[k]}"></span>`).join("")}</div>
        <div class="ticks">${LEVELS.slice(1).map((n) => `<span>${n}</span>`).join("")}</div><div class="tip">Orange or worse: plan to be indoors.</div>`;
      return;
    }
    const st = lg.stops, tk = [st[0], st[Math.floor(st.length / 2)], st[st.length - 1]];
    $("legend").innerHTML = `<div class="t">${esc(p.name)}${lg.unit ? ` <span style="color:var(--muted);font-weight:500">· ${esc(lg.unit)}</span>` : ""}</div>
      <div class="bar">${st.map((s) => `<span style="background:${s.c}"></span>`).join("")}</div>
      <div class="ticks">${tk.map((s) => `<span>${s.v}</span>`).join("")}</div><div class="tip">${esc(p.sub)}</div>`;
  }

  // ------------------------------------------------------------ summary chip + banner
  function drawSummary() {
    const s = S.sum, risk = s.places.filter((p) => p.status !== "clear"), lv = s.stats.max_level_now, el = $("summary");
    const storms = `<b>${s.stats.n_cells}</b> storm${s.stats.n_cells === 1 ? "" : "s"} tracked`;
    if (!risk.length) {
      el.classList.remove("risk"); el.style.removeProperty("--lc");
      $("summary-text").innerHTML = `${storms} · <b>no places at risk</b> in the next 6 h`;
      return;
    }
    const soon = risk.slice().sort((a, b) => (a.eta_min ?? 0) - (b.eta_min ?? 0))[0], wl = Math.max(...risk.map((p) => p.level_window || p.level_max));
    el.classList.add("risk"); el.style.setProperty("--lc", LVC()[wl]);
    $("summary-text").innerHTML = `<b>${risk.length}</b> place${risk.length === 1 ? "" : "s"} at risk · ${soon.status === "impact" ? `<b>${esc(soon.name)}</b> now`
      : `next: <b>${esc(soon.name)}</b> in ${Math.max(1, Math.round(soon.eta_min))} min`} · max ${LEVELS[Math.max(lv, wl)]}`;
  }
  function drawBanner() {
    const w = S.sum.places.filter((p) => p.status !== "clear" && (p.level_window || 0) >= 3 && (p.eta_min ?? 999) <= 60), b = $("banner");
    if (!w.length) { b.classList.add("hidden"); return; }
    b.classList.remove("hidden");
    b.innerHTML = `⚠️ <span>Severe thunderstorm within 60 min: <b>${w.slice(0, 3).map((p) => esc(p.name)).join(", ")}</b>${w.length > 3 ? " +" + (w.length - 3) : ""} — tap to see</span>`;
    b.onclick = () => map.flyTo([w[0].lat, w[0].lon], 9);
  }

  // ------------------------------------------------------------ storms, new storms, places, lightning, radars
  const toC = (k) => Math.round(k - 273.15);
  const dirName = (d) => ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][Math.round(((d % 360) + 360) % 360 / 45) % 8];
  const rainWord = (z) => z >= 55 ? "very violent, hail likely" : z >= 45 ? "very heavy rain" : z >= 35 ? "heavy rain" : z >= 20 ? "moderate rain" : z > 5 ? "light rain" : "no rain";
  const lvlPill = (lv) => `<span class="lvl-pill l${lv}" style="background:${LVC()[lv]}">${LEVELS[lv]}</span>`;
  function trackPos(c, lead) {
    const tr = c.track; if (!lead || !tr || !tr.length) return [c.lat, c.lon];
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
      if (c.past && c.past.length > 1) L.polyline(c.past, { color: css("--muted"), weight: 2, opacity: .7, renderer: canvas, interactive: false }).addTo(layers.cells);
      if (c.track) L.polyline(c.track.map((p) => [p[0], p[1]]), { color: col, weight: 2.5, dashArray: "6 6", renderer: canvas, interactive: false }).addTo(layers.cells);
      const r = Math.max(6, Math.sqrt(c.area_km2 / Math.PI) * 1.2);
      L.circle(trackPos(c, lead), { radius: r * 1000, color: col, weight: 2.5, fillColor: col, fillOpacity: .1, dashArray: lead ? "4 4" : null })
        .bindPopup(() => cellPopup(c), { maxWidth: 340 }).addTo(layers.cells);
      L.marker(trackPos(c, lead), { icon: L.divIcon({ className: "cell-label", html: `#${c.id}${c.lightning_jump ? " ⚡" : ""}`, iconAnchor: [-10, 7] }), interactive: false }).addTo(layers.cells);
    }
  }
  function cellPopup(c) {
    const trend = c.trend > 1 ? "getting stronger" : c.trend < -1 ? "weakening" : "holding steady";
    return `<div class="pop"><h3>Storm #${c.id} ${lvlPill(c.level)}</h3><div class="sub">${esc(c.where)} · ${c.age_min} min old</div>
      <p class="adv">👉 ${ADVICE[Math.max(1, c.level)]}</p>
      <div class="facts"><span>Moving</span><span>towards the ${dirName(c.heading_deg)} at ${c.speed_kmh} km/h</span>
        <span>Strength</span><span>${rainWord(c.max_dbz)}, ${trend}</span>
        <span>Hail chance</span><span>${Math.round(c.hail * 100)}%</span><span>Strongest gust</span><span>${Math.round(c.gust * 3.6)} km/h</span>
        <span>Lightning</span><span>${c.flash_rate} strikes/min${c.lightning_jump ? " · <b>sudden surge ⚡</b>" : ""}</span></div>
      <details><summary>Technical details</summary><div class="facts" style="margin-top:6px"><span>Reflectivity</span><span>${c.max_dbz} dBZ</span>
        <span>VIL</span><span>${c.max_vil} kg/m²</span><span>Cloud top</span><span>${c.min_bt == null ? "n/a" : `${toC(c.min_bt)} °C`}</span>
        <span>Seen by</span><span>${c.source === "radar" ? "Doppler radar" : "Satellite + lightning"}</span></div></details></div>`;
  }
  function drawCI() {
    layers.ci.clearLayers();
    for (const c of S.sum.ci) if (!c.verified) L.marker([c.lat, c.lon], { icon: L.divIcon({ className: "", html: '<div class="ci-icon"></div>', iconSize: [24, 24], iconAnchor: [12, 12] }) })
      .bindPopup(`<div class="pop"><h3>🌱 New storm forming</h3><div class="sub">${esc(c.where)}</div>
        <p class="say">A tall cloud is growing fast here. A thunderstorm is likely within about 15–45 minutes.</p>
        <div class="facts"><span>Chance</span><span>${Math.round(c.prob * 100)}%</span><span>Cloud top</span><span>${toC(c.min_bt)} °C</span></div></div>`).addTo(layers.ci);
  }
  function drawClocks() {
    layers.clocks.clearLayers();
    for (const p of S.sum.places) {
      if (p.status === "clear") continue;
      const lv = p.level_window || p.level_max, tgt = p.status === "impact" ? "" : S.sum.time + (p.eta_min || 0) * 60;
      L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", iconAnchor: [-6, 10],
        html: `<div class="map-clock l${lv}" data-eta="${tgt}">${esc(p.name)}<b>${tgt ? "--:--" : "NOW"}</b></div>` }) })
        .on("click", () => inspect(L.latLng(p.lat, p.lon))).addTo(layers.clocks);
      L.circleMarker([p.lat, p.lon], { radius: 5, color: "#fff", weight: 1.5, fillColor: LVC()[lv], fillOpacity: 1 }).addTo(layers.clocks);
    }
    tick();
  }
  function tick() {
    const now = BB.now();
    document.querySelectorAll(".map-clock[data-eta]").forEach((el) => {
      if (!el.dataset.eta) return; const rem = +el.dataset.eta - now;
      el.querySelector("b").textContent = rem <= 0 ? "NOW" : fmtCD(rem);
    });
  }
  function drawStrikes() {
    const now = BB.now();
    S.strikes = S.strikes.filter((s) => now - s[2] < 600).slice(-6000);
    layers.strikes.clearLayers();
    for (const [la, lo, t, cg] of S.strikes) {
      const age = (now - t) / 600, col = age < .1 ? (isDark() ? "#fff" : "#7c3aed") : age < .4 ? "#facc15" : "#f97316";
      L.circleMarker([la, lo], { radius: cg ? 2.8 : 1.7, color: col, weight: cg ? 1 : 0, fillColor: col, fillOpacity: Math.max(.15, 1 - age),
        opacity: Math.max(.15, 1 - age), renderer: canvas, interactive: false }).addTo(layers.strikes);
    }
  }
  function drawRadars() {
    layers.radars.clearLayers();
    for (const r of S.meta.radars || []) {
      L.circle([r.lat, r.lon], { radius: r.range_km * 1000, color: css("--brand"), weight: 1, fill: false, dashArray: "4 6", interactive: false }).addTo(layers.radars);
      L.circleMarker([r.lat, r.lon], { radius: 5, color: css("--brand"), fillOpacity: 1 }).bindTooltip(esc(r.name) + " radar").addTo(layers.radars);
    }
  }

  // ------------------------------------------------------------ click anywhere: what to expect here
  map.on("click", (e) => { openSheet(false); openMT(false); inspect(e.latlng); });
  async function inspect(ll, title) {
    hideHint();
    // keep the popup clear of the floating search/summary (top) and the time widget (bottom), scroll if still too tall
    const pop = L.popup({ maxWidth: 340, maxHeight: Math.max(260, innerHeight - 330), autoPanPaddingTopLeft: [20, 150], autoPanPaddingBottomRight: [20, 175] }).setLatLng(ll).setContent('<div class="pop"><p class="say">Loading the forecast for this spot…</p></div>').openOn(map);
    const wxP = BB.getJSON(`/api/weather?lat=${ll.lat.toFixed(3)}&lon=${ll.wrap().lng.toFixed(3)}`).catch(() => null);
    let d = null; try { d = await BB.getJSON(`/api/point?lat=${ll.lat}&lon=${ll.lng}`); } catch (_) {}
    if (!d) {
      pop.setContent(`<div class="pop"><h3>${title || `${ll.lat.toFixed(2)}°N, ${ll.wrap().lng.toFixed(2)}°E`}</h3><div class="wx"><p class="say">Loading live weather…</p></div>
        <p class="fine">Storm danger forecasts cover East &amp; North-East India only — press 🎯 (top right) to go there.</p></div>`);
      fillWeather(pop, wxP);
      return;
    }
    const C = LVC(), mx = Math.max(...d.level), first = d.level.findIndex((x) => x >= 2), n = d.now, t0 = S.sum ? S.sum.time : 0;
    const say = mx >= 2 ? `Storm danger reaches <b>${LEVELS[mx]}</b> ${first === 0 ? "<b>right now</b>" : `in about <b>${d.leads[first]} min</b>${t0 ? ` (around ${fmtIST(t0 + d.leads[first] * 60)} IST)` : ""}`}.`
      : mx === 1 ? "Some storm activity is possible nearby, but nothing serious is expected." : "No storms are expected here in the next 6 hours. ☀️";
    const strip = d.level.map((lv, i) => `<i style="background:${lv ? C[lv] : "var(--surface-3)"}" title="${d.leads[i] ? "+" + d.leads[i] + " min" : "now"}: ${LEVELS[lv]}"></i>`).join("");
    const sim = S.meta && S.meta.mode === "simulated";
    pop.setContent(`<div class="pop"><h3>${title || esc(d.where)}</h3>${title ? `<div class="sub">${esc(d.where)}</div>` : ""}<div class="sub">Next 6 hours: ${lvlPill(mx)}</div>
      <p class="say">${say}</p>${mx >= 1 ? `<p class="adv">👉 ${ADVICE[mx]}</p>` : ""}<div class="wx"></div>
      <div class="lbl">Danger over the next 6 hours</div><div class="strip">${strip}</div><div class="strip-t"><span>Now</span><span>2h</span><span>4h</span><span>6h</span></div>
      <div class="facts"><span>Right now</span><span>${rainWord(n.dbz)}</span><span>Rain last hour</span><span>${n.qpe1h} mm</span>
        <span>Worst hail chance</span><span>${Math.round(Math.max(...d.hail) * 100)}%</span><span>Strongest gust</span><span>${Math.round(Math.max(...d.gust) * 3.6)} km/h</span></div>
      <div class="acts"><a href="assistant.html?ask=${encodeURIComponent(`Is ${d.where.replace(/^(over|near) /, "")} safe in the next 6 hours?`)}">✨ Ask AI about this spot</a>
        ${sim ? `<button type="button" data-k="hail" data-m="0">🌱 Add a test storm here</button>` : ""}</div></div>`);
    fillWeather(pop, wxP);
    const b = pop.getElement() && pop.getElement().querySelector("[data-k]");
    if (b) b.onclick = () => BB.post("/api/sim/spawn", { lat: ll.lat, lon: ll.lng, kind: b.dataset.k, mature: b.dataset.m === "1" })
      .then(() => { map.closePopup(); toast("Test storm added", "It will appear with the next forecast update."); });
  }

  // live surface weather in the popup (Open-Meteo via /api/weather): works anywhere on Earth
  async function fillWeather(pop, wxP) {
    const w = await wxP, el = pop.getElement() && pop.getElement().querySelector(".wx");
    if (!el) return;
    if (!w || !w.now) { el.innerHTML = `<p class="fine">Live weather unavailable right now.</p>`; return; }
    const n = w.now, r = (v, u = "") => v == null ? "–" : Math.round(v) + u;
    const hrs = (w.hours || []).slice(1, 7).map((h) => `<div><small>${esc(h.time.slice(11, 16))}</small><span>${h.icon}</span><b>${r(h.temp_c, "°")}</b>
      <small class="${h.rain_prob >= 50 ? "wet" : ""}">💧${r(h.rain_prob, "%")}</small></div>`).join("");
    el.innerHTML = `<div class="wx-now"><span class="wx-ico">${n.icon}</span><div><b class="wx-t">${r(n.temp_c, "°C")}</b>
        <span>${esc(n.text)}${n.thunder ? " ⚡" : ""}</span><small>Feels like ${r(n.feels_c, "°C")}</small></div></div>
      <div class="wx-grid"><span>💧 Humidity <b>${r(n.humidity, "%")}</b></span><span>🌬️ Wind <b>${r(n.wind_kmh)} km/h ${esc(n.wind_from || "")}</b></span>
        <span>💨 Gusts <b>${r(n.gust_kmh)} km/h</b></span><span>🌧️ Rain now <b>${n.rain_mm == null ? "–" : n.rain_mm + " mm"}</b></span></div>
      ${hrs ? `<div class="lbl" style="margin-top:10px">Next hours</div><div class="wx-hours">${hrs}</div>` : ""}
      <p class="fine">Live weather · Open-Meteo · updated ${esc((n.time || "").slice(11, 16))} local time</p>`;
  }

  // ------------------------------------------------------------ search
  const sIn = $("search"), sRes = $("search-results");
  let hits = [], act = 0, gTimer = null, gSeq = 0, pin = null;
  const typeIco = (t) => t === "airport" ? "✈️" : t === "agri" ? "🌾" : "🏙️";
  const inDomain = (p) => S.meta && p.lat >= S.meta.bounds[0][0] && p.lat <= S.meta.bounds[1][0] && p.lon >= S.meta.bounds[0][1] && p.lon <= S.meta.bounds[1][1];
  function statusOf(p) {
    const f = p.id && S.sum && S.sum.places.find((x) => x.id === p.id);
    if (f) return f.status === "clear" ? "✓ clear" : f.status === "impact" ? "⚠ storm now" : `⏱ in ${Math.round(f.eta_min)} min`;
    return inDomain(p) ? "in forecast area" : "outside forecast area";
  }
  function renderHits(loading) {
    sRes.innerHTML = hits.map((p, k) => `<button type="button" data-k="${k}" class="${k === act ? "act" : ""}">
        <span>${typeIco(p.type)} ${esc(p.name)} <small>${esc(p.sub || "")}</small></span><small>${statusOf(p)}</small></button>`).join("")
      + (loading ? `<div class="note">Searching all places…</div>` : hits.length ? "" : `<div class="note">No place found</div>`);
    sRes.classList.remove("hidden");
    sRes.querySelectorAll("[data-k]").forEach((el) => { el.onmousedown = (e) => e.preventDefault(); el.onclick = () => go(hits[+el.dataset.k]); });
  }
  sIn.oninput = () => {
    const q = sIn.value.trim(); clearTimeout(gTimer);
    if (!q) { sRes.classList.add("hidden"); hits = []; return; }
    const ql = q.toLowerCase();
    const local = (S.meta ? S.meta.places : []).filter((p) => p.name.toLowerCase().includes(ql) || p.state.toLowerCase() === ql).slice(0, 6).map((p) => ({ ...p, sub: p.state }));
    hits = local; act = 0; renderHits(q.length >= 2);
    if (q.length < 2) return;
    const seq = ++gSeq;
    gTimer = setTimeout(async () => {
      try {
        const j = await BB.getJSON(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=10&language=en&format=json`);
        if (seq !== gSeq) return;
        const seen = new Set(local.map((p) => p.name.toLowerCase()));
        hits = local.concat((j.results || []).sort((a, b) => (b.country_code === "IN") - (a.country_code === "IN") || (b.population || 0) - (a.population || 0))
          .filter((g) => !seen.has(g.name.toLowerCase())).slice(0, 8 - local.length)
          .map((g) => ({ name: g.name, lat: g.latitude, lon: g.longitude, type: "city", sub: [g.admin1, g.country].filter(Boolean).join(", ") })));
      } catch (_) { /* offline: keep local hits */ }
      if (seq === gSeq && document.activeElement === sIn) renderHits(false);
    }, 250);
  };
  sIn.onkeydown = (e) => {
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && hits.length) { e.preventDefault(); act = (act + (e.key === "ArrowDown" ? 1 : hits.length - 1)) % hits.length; renderHits(false); }
    if (e.key === "Enter" && hits[act]) go(hits[act]);
    if (e.key === "Escape") { sRes.classList.add("hidden"); sIn.blur(); }
  };
  sIn.onblur = () => setTimeout(() => sRes.classList.add("hidden"), 150);
  // ------------------------------------------------------------ my location
  const me = { marker: null, ring: null };
  async function locateMe(fly = true) {
    const btn = $("btn-locate"); btn.classList.add("busy");
    try {
      const p = await BB.locate(), ll = L.latLng(p.lat, p.lon);
      if (me.marker) { map.removeLayer(me.marker); map.removeLayer(me.ring); }
      me.ring = L.circle(ll, { radius: Math.max(p.accuracy, 30), color: "#3b82f6", weight: 1, fillColor: "#3b82f6", fillOpacity: .12, interactive: false }).addTo(map);
      me.marker = L.marker(ll, { title: "You are here", icon: L.divIcon({ className: "", iconSize: [22, 22], iconAnchor: [11, 11], html: '<div class="me-dot"></div>' }) })
        .on("click", () => inspect(ll, meTitle(p))).addTo(map);
      btn.classList.add("on");
      if (fly) { map.flyTo(ll, Math.max(map.getZoom(), 10), { duration: 1.2 }); map.once("moveend", () => inspect(ll, meTitle(p))); }
    } catch (e) { toast("Couldn't get your location", e.message); }
    finally { btn.classList.remove("busy"); }
  }
  const meTitle = (p) => `📍 You are here${p.name ? ` — ${esc(p.name)}` : ""}<small class="me-acc">accurate to about ${p.accuracy < 1000 ? p.accuracy + " m" : (p.accuracy / 1000).toFixed(1) + " km"}</small>`;
  $("btn-locate").onclick = (e) => { e.preventDefault(); locateMe(true); };

  function go(p) {
    sRes.classList.add("hidden"); sIn.value = p.name; sIn.blur();
    if (pin) map.removeLayer(pin);
    pin = L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 26], html: '<div class="search-pin">📍</div>' }) }).addTo(map);
    map.flyTo([p.lat, p.lon], inDomain(p) ? 9.5 : 8, { duration: 1.1 });
    map.once("moveend", () => inspect(L.latLng(p.lat, p.lon)));
  }

  // ------------------------------------------------------------ share, toasts, hints
  $("btn-share").onclick = async () => {
    const c = map.getCenter(), u = new URL("app.html", location.href);
    u.searchParams.set("lat", c.lat.toFixed(4)); u.searchParams.set("lon", c.lng.toFixed(4)); u.searchParams.set("z", map.getZoom().toFixed(2));
    u.searchParams.set("layer", S.product); if (S.meta) u.searchParams.set("lead", S.meta.leads[S.leadIdx]); u.searchParams.set("basemap", baseKey);
    try { await navigator.clipboard.writeText(u.href); toast("Link copied", "Anyone opening it sees this map, layer and time."); }
    catch (_) { prompt("Copy this link:", u.href); }
  };
  function toast(title, text) {
    const el = document.createElement("div"); el.className = "m-toast";
    el.innerHTML = `<b>${esc(title)}</b>${esc(text)}`; $("toasts").appendChild(el); setTimeout(() => el.remove(), 6000);
  }
  const hideHint = () => { $("hint").classList.add("hidden"); store.set("map-hint", "0"); };
  $("hint").querySelector("button").onclick = hideHint;

  // ------------------------------------------------------------ data flow
  function renderAll() {
    refreshRaster(); drawCells(); drawCI(); drawClocks(); drawStrikes(); drawLegend(); drawSummary(); drawBanner(); drawRadars(); buildProducts(); drawStrip();
  }
  async function init() {
    const q = { lat: parseFloat(qs.get("lat")), lon: parseFloat(qs.get("lon")), z: parseFloat(qs.get("z")), lead: parseInt(qs.get("lead"), 10) };
    if (qs.get("layer") && PRODUCTS.some((p) => p.id === qs.get("layer"))) S.product = qs.get("layer");
    buildProducts();
    const meta = await BB.live({
      onCycle: (sum, m) => { S.meta = S.meta || m; S.sum = sum; S.strikes = (sum.strikes || []).slice(); renderAll(); },
      onStrikes: (list) => { S.strikes.push(...list); flashStrikes(list); },
      onPending: () => { $("summary-text").textContent = "Preparing the first forecast… a few seconds"; },
    });
    if (!meta) { $("summary-text").textContent = "Forecast server offline — retrying…"; setTimeout(() => location.reload(), 20000); return; }
    S.meta = meta;
    $("lead").max = meta.leads.length - 1;
    if (isFinite(q.lead)) S.leadIdx = Math.min(meta.leads.length - 1, Math.max(0, Math.round(q.lead / 10)));
    $("lead").value = S.leadIdx; drawStrip();
    if (isFinite(q.lat) && isFinite(q.lon)) map.setView([q.lat, q.lon], isFinite(q.z) ? q.z : 8);
    else map.fitBounds(meta.bounds, { padding: [20, 20] });
    drawLegend(); drawRadars(); updateLeadText();
    if (S.sum) renderAll();
    if (meta.mode === "simulated" && store.get("demo-note") !== "0") {
      $("demo-note").classList.remove("hidden");
      $("demo-note").querySelector("button").onclick = () => { $("demo-note").classList.add("hidden"); store.set("demo-note", "0"); };
    }
    // permission already given on an earlier visit: show the blue dot quietly (fly there only if no place was linked)
    if (!EMBED && await BB.locationGranted()) locateMe(!(isFinite(q.lat) && isFinite(q.lon)));
    if (!EMBED && store.get("map-hint") !== "0") { $("hint").classList.remove("hidden"); setTimeout(hideHint, 15000); }
    const fx = (qs.get("fx") || "").split(",");
    if (fx.includes("wind") || store.get("fx-wind") === "1") setWind(true);
    if (fx.includes("rain") || store.get("fx-rain") === "1" || meta.mode === "browser") setRain(true);
    if (meta.mode === "browser") {
      $("products").insertAdjacentHTML("beforebegin", `<div class="m-browser-note">🌐 <b>Browser mode</b> — the BUMBLEBLE engine isn't connected,
        so the detailed 2 km layers are off. The map shows <b>live rain radar</b>, and storm danger for each place comes from free weather-model forecasts.</div>`);
      $("products").classList.add("browser-off");
    }
    setInterval(tick, 1000);
    setInterval(() => { if (S.sum && map.hasLayer(layers.strikes)) drawStrikes(); }, 2000);
  }
  init();
})();
