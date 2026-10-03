/* BUMBLEBLE — shared nav + data helpers for the multi-page views. Exposes window.BB. */
(() => {
  "use strict";
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} } };

  // theme: same storage key as the map dashboard so the choice carries across pages
  const root = document.documentElement;
  const theme = new URLSearchParams(location.search).get("theme") || store.get("theme")
    || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  root.dataset.theme = theme;

  const PAGES = [
    { href: "app.html", key: "map", ico: "🗺️", label: "Map" },
    { href: "arrivals.html", key: "arrivals", ico: "⏱️", label: "Arrivals" },
    { href: "alerts.html", key: "alerts", ico: "🔔", label: "Alerts" },
    { href: "hazards.html", key: "hazards", ico: "⚠️", label: "Hazards" },
    { href: "assistant.html", key: "assistant", ico: "✨", label: "Ask AI" },
    { href: "system.html", key: "system", ico: "📡", label: "System" },
  ];
  const LEVELS = ["None", "Low", "Moderate", "High", "Extreme"];
  const ADVICE = ["No action needed.", "Stay alert and keep an eye on the sky.",
    "Plan to be indoors when it arrives. Secure loose objects.",
    "Go indoors before it arrives. Avoid trees, open fields and water.",
    "Take shelter now in a strong building. Stay away from windows."];

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // epoch seconds -> "HH:MM" (or "HH:MM:SS") in IST
  const fmtIST = (t, sec = false) => new Date((t + 19800) * 1000).toISOString().substr(11, sec ? 8 : 5);
  const fmtCD = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ":" : "") + String(m).padStart(2, "0") + ":" + String(x).padStart(2, "0"); };
  // ---------- API: BUMBLEBLE server if reachable, otherwise the in-browser engine (static/lite.js) ----------
  // static/config.js may set window.BUMBLEBLE_API = "https://your-space.hf.space" when the pages are hosted
  // separately (Netlify, Vercel, GitHub Pages). Empty = same site as the pages.
  const API = String(window.BUMBLEBLE_API || "").replace(/\/+$/, "");
  const url = (path) => API + path;
  let mode = null, modeP = null; // "server" | "browser"
  const scriptBase = (document.currentScript && document.currentScript.src) || location.href;
  function loadLite() {
    return new Promise((res, rej) => {
      if (window.BB_LITE) return res();
      const sc = document.createElement("script");
      sc.src = new URL("lite.js", scriptBase).href; sc.onload = res; sc.onerror = () => rej(new Error("browser engine missing"));
      document.head.appendChild(sc);
    });
  }
  function resolveMode() {
    if (modeP) return modeP;
    modeP = (async () => {
      try {
        const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 8000);
        const r = await fetch(url("/api/meta"), { cache: "no-store", signal: ctl.signal }); clearTimeout(t);
        mode = r.ok && (r.headers.get("content-type") || "").includes("json") ? "server" : "browser";
      } catch (_) { mode = "browser"; }
      if (mode === "browser") await loadLite();
      document.documentElement.dataset.apiMode = mode;
      return mode;
    })();
    return modeP;
  }
  async function request(method, u, body) {
    if (!u.startsWith("/api/")) { const r = await fetch(u); if (!r.ok) throw new Error(r.status); return r.json(); }
    if (await resolveMode() === "browser") return method === "GET" ? BB_LITE.get(u) : method === "DELETE" ? BB_LITE.del(u) : BB_LITE.post(u, body);
    const r = await fetch(url(u), method === "GET" ? {} : { method, headers: { "Content-Type": "application/json" }, body: body == null ? undefined : JSON.stringify(body) });
    if (!r.ok) { let d = r.status; try { d = (await r.json()).detail || d; } catch (_) {} throw new Error(d); }
    return r.json();
  }
  const getJSON = (u) => request("GET", u);
  const post = (u, b) => request("POST", u, b);
  const del = (u) => request("DELETE", u);

  // the simulation clock can run faster than real time; interpolate it between server messages
  const clock = { at: 0, real: 0, speed: 1 };
  const sync = (m) => { if (m && m.sim_now != null) { clock.at = m.sim_now; clock.real = performance.now(); clock.speed = m.speed ?? clock.speed; } };
  const now = () => clock.at + ((performance.now() - clock.real) / 1000) * clock.speed;

  // ---------- nav ----------
  function nav(active) {
    const links = PAGES.map((p) => `<a href="${p.href}" class="${p.key === active ? "on" : ""}" ${p.key === active ? 'aria-current="page"' : ""}>
      <span aria-hidden="true">${p.ico}</span>${p.label}${p.key === "alerts" || p.key === "arrivals" ? `<b class="badge hidden" data-badge="${p.key}"></b>` : ""}</a>`).join("");
    document.body.dataset.page = active; // per-page accent colours in pages.css
    const el = document.createElement("header");
    el.className = "bb-nav";
    el.innerHTML = `<div class="bb-nav-in">
        <a class="bb-brand" href="./" title="BUMBLEBLE home"><span class="bb-logo"><svg viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/></svg></span>BUMBLEBLE</a>
        <nav class="bb-links" aria-label="Pages">${links}</nav>
        <div class="bb-right">
          <span class="bb-status" id="bb-status"><i></i><span>Connecting…</span></span>
          <button class="bb-icon" id="bb-theme" title="Switch light / dark" aria-label="Switch light or dark theme">${root.dataset.theme === "dark" ? "☀️" : "🌙"}</button>
          <button class="bb-icon bb-burger" id="bb-burger" aria-label="Open menu" aria-expanded="false">☰</button>
        </div></div>
      <div class="bb-drawer" id="bb-drawer">${links}</div>`;
    document.body.prepend(el);
    el.querySelector("#bb-theme").onclick = (e) => {
      const t = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = t; store.set("theme", t); e.currentTarget.textContent = t === "dark" ? "☀️" : "🌙";
      root.dispatchEvent(new Event("themechange"));
    };
    const burger = el.querySelector("#bb-burger"), drawer = el.querySelector("#bb-drawer");
    burger.onclick = () => { const o = drawer.classList.toggle("open"); burger.setAttribute("aria-expanded", String(o)); burger.textContent = o ? "✕" : "☰"; };
    addEventListener("keydown", (e) => { if (e.key === "Escape" && drawer.classList.contains("open")) burger.click(); });
  }
  function setStatus(kind, text) {
    const s = document.getElementById("bb-status"); if (!s) return;
    s.className = "bb-status " + kind; s.querySelector("span").textContent = text;
  }
  function setBadge(key, n) {
    document.querySelectorAll(`[data-badge="${key}"]`).forEach((b) => { b.textContent = n; b.classList.toggle("hidden", !n); });
  }
  function updateBadges(sum) {
    setBadge("arrivals", sum.places.filter((p) => p.status !== "clear").length);
    setBadge("alerts", sum.events.filter((e) => e.severity >= 3).length);
  }

  // ---------- live data ----------
  // live({ onCycle(summary), onTick(msg), onStrikes(list) }) — loads meta + state, then follows the websocket.
  async function live(h = {}) {
    let meta = null;
    if (await resolveMode() === "browser") return liveBrowser(h);
    try { meta = await getJSON("/api/meta"); } catch (_) { setStatus("off", "Server offline"); }
    let st = null;
    try { st = await getJSON("/api/state"); sync(st); } catch (_) {}
    const modeText = () => !meta ? "Live" : meta.mode === "simulated" ? "Demo" : meta.mode === "realtime" ? "Live data" : "Live";
    if (st && st.type === "cycle") { updateBadges(st); setStatus("live", modeText()); h.onCycle && h.onCycle(st, meta); }
    else if (st) { setStatus("warm", "Starting up…"); h.onPending && h.onPending(st, meta); }
    const connect = () => {
      let ws;
      const wsUrl = API ? API.replace(/^http/, "ws") + "/ws" : (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
      try { ws = new WebSocket(wsUrl); } catch (_) { return; }
      ws.onclose = () => { setStatus("off", "Reconnecting…"); setTimeout(connect, 2500); };
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        if (m.type === "cycle") { sync(m); updateBadges(m); setStatus("live", modeText()); h.onCycle && h.onCycle(m, meta); }
        else if (m.type === "tick") { sync(m); if (m.warming_up) setStatus("warm", "Starting up…"); h.onTick && h.onTick(m, meta); }
        else if (m.type === "strikes") h.onStrikes && h.onStrikes(m.strikes);
      };
    };
    if (meta) connect();
    linkServerFiles();
    return meta;
  }
  // links to server files (downloads): point them at the API host, or hide them when there is no server
  function linkServerFiles() {
    document.querySelectorAll('a[href^="/api/"]').forEach((a) => {
      if (mode === "browser") a.style.display = "none"; else a.href = url(a.getAttribute("href"));
    });
  }
  // browser mode: recompute from free cloud forecasts every 10 minutes (no websocket)
  async function liveBrowser(h) {
    const s = document.getElementById("bb-status");
    if (s) s.title = "The BUMBLEBLE server isn't connected, so forecasts are computed in your browser from free Open-Meteo data.";
    const meta = await BB_LITE.get("/api/meta");
    const run = async () => {
      try { const st = await BB_LITE.get("/api/state"); sync(st); updateBadges(st); setStatus("live", "Browser mode"); h.onCycle && h.onCycle(st, meta); }
      catch (_) { setStatus("off", "Offline"); }
    };
    await run(); setInterval(run, 10 * 60 * 1000);
    linkServerFiles();
    return meta;
  }

  // ---------- the user's own location (browser Geolocation API — always asks permission first) ----------
  // Resolves { lat, lon, accuracy (m), name } or rejects with a plain-language Error.
  // The place name comes from BigDataCloud's free, keyless client-side reverse geocoder.
  async function placeName(lat, lon) {
    try {
      const j = await getJSON(`https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lon}&localityLanguage=en`);
      return [j.locality || j.city, j.city !== j.locality ? j.city : "", j.principalSubdivision].filter(Boolean).join(", ") || j.countryName || "";
    } catch (_) { return ""; }
  }
  function locate() {
    return new Promise((resolve, reject) => {
      if (!("geolocation" in navigator)) return reject(new Error("This browser can't share your location."));
      if (!window.isSecureContext) return reject(new Error("Location needs a secure (https) page."));
      navigator.geolocation.getCurrentPosition(async (pos) => {
        const lat = +pos.coords.latitude.toFixed(5), lon = +pos.coords.longitude.toFixed(5);
        store.set("geo-ok", "1");
        resolve({ lat, lon, accuracy: Math.round(pos.coords.accuracy || 0), name: await placeName(lat, lon) });
      }, (err) => {
        reject(new Error(err.code === 1 ? "Location permission was blocked. Allow it from the 🔒 icon next to the address bar, then try again."
          : err.code === 3 ? "Finding your location took too long. Please try again." : "Your location isn't available right now."));
      }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
    });
  }
  // true when the user already granted permission earlier (so we can locate without a prompt)
  async function locationGranted() {
    try { return (await navigator.permissions.query({ name: "geolocation" })).state === "granted"; } catch (_) { return false; }
  }

  window.BB = { store, esc, fmtIST, fmtCD, getJSON, post, del, url, mode: () => mode, resolveMode, now, sync, nav, setStatus, live, LEVELS, ADVICE, PAGES, locate, locationGranted, placeName };
})();
