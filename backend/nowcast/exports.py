"""Downloadable products: GeoJSON for GIS tools, CSV of arrivals, printable bulletin."""
from __future__ import annotations

import csv
import html
import io
import json
from datetime import datetime, timedelta, timezone

LEVELS = ["None", "Low", "Moderate", "High", "Extreme"]
IST = timezone(timedelta(hours=5, minutes=30))


def _ist(t: float) -> str:
    return datetime.fromtimestamp(t, IST).strftime("%d %b %Y, %H:%M IST")


def geojson(s: dict) -> str:
    feats = []
    for c in s["cells"]:
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                      "properties": {"kind": "storm_cell", **{k: v for k, v in c.items() if k not in ("track", "past", "lat", "lon")},
                                     "threat": LEVELS[c["level"]]}})
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [[p[1], p[0]] for p in c["track"]]},
                      "properties": {"kind": "forecast_track", "cell_id": c["id"], "minutes": [p[2] for p in c["track"]]}})
    for p in s["places"]:
        props = {k: p.get(k) for k in ("id", "name", "state", "type", "status", "eta_min", "duration_min", "level_max")}
        props.update(kind="place", threat=LEVELS[p.get("level_window") or p["level_max"]], **(p.get("hazards") or {}))
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]}, "properties": props})
    for c in s["ci"]:
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                      "properties": {"kind": "convective_initiation", **{k: v for k, v in c.items() if k not in ("lat", "lon")}}})
    return json.dumps({"type": "FeatureCollection", "name": "BUMBLEBLE nowcast",
                       "analysis_time": s["time_iso"], "features": feats}, indent=1)


def places_csv(s: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["place", "state", "type", "status", "eta_min", "arrival_ist", "threat", "hail_prob", "gust_kmh",
                "lightning_fl_km2_h", "cloudburst_prob", "rain_1h_mm", "duration_min", "lat", "lon"])
    for p in s["places"]:
        h = p.get("hazards") or {}
        arr = _ist(s["time"] + p["eta_min"] * 60) if p.get("eta_min") is not None else ""
        w.writerow([p["name"], p["state"], p["type"], p["status"], p.get("eta_min"), arr,
                    LEVELS[p.get("level_window") or p["level_max"]] if p["status"] != "clear" else "None",
                    h.get("hail_prob", ""), round(h["gust_ms"] * 3.6) if "gust_ms" in h else "", h.get("lightning", ""),
                    h.get("cloudburst_prob", ""), h.get("rain1h_mm", ""), p.get("duration_min", ""), p["lat"], p["lon"]])
    return buf.getvalue()


def bulletin_html(s: dict) -> str:
    e = html.escape
    thr = [p for p in s["places"] if p["status"] != "clear"]
    color = ["#94a3b8", "#eab308", "#f97316", "#dc2626", "#c026d3"]
    rows = "".join(
        f"<tr><td><b>{e(p['name'])}</b><br><small>{e(p['state'])} · {e(p['type'])}</small></td>"
        f"<td><span class='lv' style='background:{color[p.get('level_window') or p['level_max']]}'>"
        f"{LEVELS[p.get('level_window') or p['level_max']]}</span></td>"
        f"<td>{'NOW' if p['status'] == 'impact' else _ist(s['time'] + p['eta_min'] * 60)[-9:]}</td>"
        f"<td>{(p.get('hazards') or {}).get('hail_prob', 0):.0%}</td>"
        f"<td>{(p.get('hazards') or {}).get('gust_ms', 0) * 3.6:.0f}</td>"
        f"<td>{(p.get('hazards') or {}).get('lightning', 0)}</td>"
        f"<td>{(p.get('hazards') or {}).get('cloudburst_prob', 0):.0%}</td>"
        f"<td>~{p.get('duration_min', '')} min</td></tr>" for p in thr) or \
        "<tr><td colspan='8' style='text-align:center;padding:20px'>No place is under a Moderate or higher threat in the next 6 hours.</td></tr>"
    ev = "".join(f"<li><b>{datetime.fromtimestamp(x['time'], IST).strftime('%H:%M')}</b> {e(x['text'])}</li>"
                 for x in s["events"][:12] if x["severity"] >= 1) or "<li>No significant events.</li>"
    st = s["stats"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>BUMBLEBLE bulletin — {_ist(s['time'])}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font:14px/1.5 Inter,Segoe UI,system-ui,sans-serif;color:#0f1b2d;max-width:960px;margin:24px auto;padding:0 16px;background:#fff}}
h1{{margin:0;font-size:24px}} .sub{{color:#6b7a90}} table{{width:100%;border-collapse:collapse;margin-top:12px}}
th,td{{padding:8px;border-bottom:1px solid #e3e8f0;text-align:left;vertical-align:top}} th{{font-size:11px;text-transform:uppercase;color:#6b7a90}}
.lv{{color:#fff;border-radius:6px;padding:2px 8px;font-weight:700;font-size:12px}} .kpi{{display:flex;gap:10px;margin:16px 0}}
.kpi div{{flex:1;border:1px solid #e3e8f0;border-radius:10px;padding:10px}} .kpi b{{font-size:20px;display:block}}
.bar{{height:6px;background:linear-gradient(90deg,#2563eb,#7c3aed);border-radius:4px;margin:12px 0}}
@media print{{.noprint{{display:none}} body{{margin:0}}}}</style></head><body>
<button class="noprint" onclick="print()" style="float:right;padding:8px 14px;border-radius:8px;border:1px solid #ccd;cursor:pointer">🖨 Print / Save as PDF</button>
<h1>⚡ BUMBLEBLE — Thunderstorm Nowcast Bulletin</h1>
<div class="sub">Issued {_ist(s['time'])} · valid next 6 hours · mode: {e(s['mode'])}</div><div class="bar"></div>
<div class="kpi"><div>Active storms<b>{st['n_cells']}</b></div><div>Max threat now<b>{LEVELS[st['max_level_now']]}</b></div>
<div>Places at risk<b>{len(thr)}</b></div><div>New storms forming<b>{st['n_ci']}</b></div></div>
<h2>Places under threat</h2><table><tr><th>Place</th><th>Threat</th><th>Arrival</th><th>Hail</th><th>Gust km/h</th><th>Lightning fl/km²/h</th><th>Cloudburst</th><th>Duration</th></tr>{rows}</table>
<h2>Recent alerts</h2><ul>{ev}</ul>
<p class="sub">Automated nowcast from multi-source data fusion. Probabilities are guidance; follow official IMD warnings.</p>
</body></html>"""
