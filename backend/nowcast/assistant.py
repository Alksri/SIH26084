"""BUMBLEBLE AI assistant: natural-language control of the dashboard.

The assistant turns a request like "show hail risk near Ranchi in 2 hours"
into (a) a short answer grounded in the latest nowcast and (b) a list of UI
actions the dashboard applies (switch layer, move the timeline, fly to a
place, change map type/theme, toggle overlays).

Provider abstraction:
  AssistantProvider.respond(message, history, context, places, knowledge)
      -> {"reply", "actions", "provider", "model"}
  * GeminiProvider - Google Gemini (default gemini-2.5-flash, with a fallback chain)
                     when GEMINI_API_KEY is set on the server
  * ClaudeProvider - Anthropic Claude when ANTHROPIC_API_KEY is set
  * DemoProvider   - rule-based, no API key, always available (fallback)
Every provider receives RAG passages retrieved from the knowledge base
(backend/knowledge) and the reply cites them. Keys never reach the browser.
"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger("nowcast.assistant")

LAYERS = {
    "level": "Composite threat", "level_60": "Worst threat next 1 h", "level_360": "Worst threat next 6 h",
    "lightning": "Lightning density", "hail": "Hail probability", "gust": "Downburst gusts",
    "cloudburst": "Cloudburst risk", "rain1h": "Rain next hour", "dbz": "Radar reflectivity",
    "ir": "INSAT-3DR infrared", "qpe1h": "Rain last hour", "confidence": "Fusion confidence",
}
BASEMAPS = ("auto", "streets", "satellite", "hybrid", "terrain", "topo")
OVERLAYS = ("cells", "strikes", "ci", "clocks", "motion", "radars", "rainviewer", "gibs")
LEVEL_NAMES = ["None", "Low", "Moderate", "High", "Extreme"]

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "Short answer for the user (max ~80 words)."},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["set_layer", "set_lead", "fly_to", "set_basemap",
                                                        "set_theme", "toggle_overlay"]},
                    "layer": {"type": "string", "enum": list(LAYERS)},
                    "lead_min": {"type": "integer"},
                    "place": {"type": "string"},
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "zoom": {"type": "number"},
                    "basemap": {"type": "string", "enum": list(BASEMAPS)},
                    "theme": {"type": "string", "enum": ["light", "dark"]},
                    "overlay": {"type": "string", "enum": list(OVERLAYS)},
                    "on": {"type": "boolean"},
                },
                "required": ["type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reply", "actions"],
    "additionalProperties": False,
}


def build_context(summary: dict | None, places: list[dict]) -> dict:
    """Compact, model-friendly view of the latest nowcast."""
    if not summary:
        return {"status": "no analysis yet", "places": [p["name"] for p in places]}
    threatened = [
        {"name": p["name"], "status": p["status"], "eta_min": p["eta_min"],
         "level": LEVEL_NAMES[p.get("level_window") or p["level_max"]], "hazards": p.get("hazards"),
         "lat": p["lat"], "lon": p["lon"]}
        for p in summary["places"] if p["status"] != "clear"
    ]
    return {
        "analysis_time_utc": summary["time_iso"], "mode": summary["mode"],
        "stats": summary["stats"], "inputs": summary["inputs"],
        "threatened_places": threatened[:25],
        "storms": [{k: c[k] for k in ("id", "where", "level", "max_dbz", "hail", "gust", "flash_rate",
                                      "lightning_jump", "speed_kmh", "heading_deg", "stage", "lat", "lon")}
                   for c in summary["cells"][:20]],
        "new_storms_forming": [{"where": c["where"], "prob": c["prob"]} for c in summary["ci"] if not c["verified"]][:10],
        "feeds": [{"label": h["label"], "status": h["status"]} for h in summary["health"]],
        "monitored_places": [p["name"] for p in places],
    }


class AssistantProvider:
    name = "base"

    def respond(self, message: str, history: list[dict], context: dict, places: list[dict],
                knowledge: list[dict] | None = None) -> dict:
        raise NotImplementedError


# --------------------------------------------------------------------------- demo
class DemoProvider(AssistantProvider):
    """Keyword/rule-based assistant so the product works with no API key."""

    name = "demo"

    LAYER_WORDS = [
        (r"\bhail", "hail"), (r"lightning|thunder", "lightning"), (r"gust|downburst|wind|squall", "gust"),
        (r"cloud ?burst|flash flood|extreme rain", "cloudburst"), (r"rain (in |over )?(the )?next|rainfall forecast|how much rain", "rain1h"),
        (r"rain (last|past)|observed rain|qpe", "qpe1h"), (r"radar|reflectivity|dbz|echo", "dbz"),
        (r"infra ?red|\bir\b|cloud top|insat", "ir"), (r"confidence", "confidence"),
        (r"worst.*6 ?h|next 6 ?hours", "level_360"), (r"worst.*(1 ?h|hour)", "level_60"),
        (r"threat|danger|risk|hazard|severe|warning", "level"),
    ]
    BASEMAP_WORDS = [(r"hybrid", "hybrid"), (r"satellite (map|view|imagery)|satellite basemap|imagery", "satellite"),
                     (r"terrain|relief|hills", "terrain"), (r"topo", "topo"), (r"street|road map", "streets"),
                     (r"default map|grey map|gray map|plain map", "auto")]

    def respond(self, message, history, context, places, knowledge=None):
        m = message.lower().strip()
        actions: list[dict] = []
        notes: list[str] = []

        if re.search(r"^(help|what can you do|\?)", m):
            return {"provider": self.name, "actions": [], "reply": (
                "Try: “show hail risk in 2 hours”, “zoom to Kolkata”, “which cities are at risk?”, "
                "“switch to satellite map”, “dark mode”, “show lightning”, “summary”, "
                "“turn on live radar”.")}

        # questions about the user's own (shared) location
        loc = context.get("user_location")
        if loc and re.search(r"(me|my|here|i)", m):
            return {"provider": self.name, "reply": self._my_location(loc),
                    "actions": [{"type": "fly_to", "place": loc.get("name") or "your location", "lat": loc["lat"], "lon": loc["lon"], "zoom": 10}]}

        # theme / basemap
        if re.search(r"dark (mode|theme)", m):
            actions.append({"type": "set_theme", "theme": "dark"}); notes.append("switched to dark mode")
        elif re.search(r"light (mode|theme)", m):
            actions.append({"type": "set_theme", "theme": "light"}); notes.append("switched to light mode")
        for pat, key in self.BASEMAP_WORDS:
            if re.search(pat, m) and re.search(r"map|view|basemap|imagery|hybrid|terrain|topo|street", m):
                actions.append({"type": "set_basemap", "basemap": key}); notes.append(f"map type → {key}")
                break

        # external / overlay toggles
        if re.search(r"(live|real|rainviewer) radar", m):
            on = not re.search(r"\b(off|hide|remove|disable)\b", m)
            actions.append({"type": "toggle_overlay", "overlay": "rainviewer", "on": on})
            notes.append(f"RainViewer live radar {'on' if on else 'off'}")
        if re.search(r"imerg|gpm|nasa", m):
            on = not re.search(r"\b(off|hide|remove|disable)\b", m)
            actions.append({"type": "toggle_overlay", "overlay": "gibs", "on": on}); notes.append(f"NASA IMERG {'on' if on else 'off'}")
        if re.search(r"motion|vector|arrow", m):
            actions.append({"type": "toggle_overlay", "overlay": "motion", "on": not re.search(r"\b(off|hide)\b", m)})

        # layer
        layer = None
        for pat, key in self.LAYER_WORDS:
            if re.search(pat, m):
                layer = key
                break
        is_question = bool(re.search(r"\b(which|what|where|how|is|are|any|list)\b.*\?|^(which|what|where|how|is|are|any|list)\b", m))

        # lead time
        lead = None
        mt = re.search(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minutes)\b", m)
        if mt:
            v = float(mt.group(1))
            lead = int(round(v * 60 if mt.group(2).startswith("h") else v))
        elif re.search(r"\b(now|current(ly)?|right now)\b", m):
            lead = 0
        if lead is not None:
            lead = max(0, min(360, int(round(lead / 10.0) * 10)))

        # place
        place = None
        for p in sorted(places, key=lambda p: -len(p["name"])):
            base = p["name"].lower().split(" (")[0]
            if re.search(r"\b" + re.escape(base) + r"\b", m):
                place = p
                break

        if layer and not (is_question and not re.search(r"show|display|map|layer|switch", m)):
            if not (layer == "level" and is_question):
                actions.append({"type": "set_layer", "layer": layer})
                notes.append(f"layer → {LAYERS[layer]}")
        if lead is not None:
            actions.append({"type": "set_lead", "lead_min": lead})
            notes.append("timeline → " + ("now" if lead == 0 else f"+{lead} min"))
        if place:
            actions.append({"type": "fly_to", "place": place["name"], "lat": place["lat"], "lon": place["lon"], "zoom": 9.5})

        reply = self._answer(m, place, context, is_question)
        used_kb = False
        if not reply and knowledge:
            # RAG fallback: answer with the best-matching knowledge passage
            used_kb = True
            top = knowledge[0]
            body = re.sub(r"\s+", " ", top["text"]).strip()
            reply = f"**{top['title']}**\n{body[:600]}{'…' if len(body) > 600 else ''}"
        if notes:
            reply = (reply + "\n\n" if reply else "") + "✓ " + " · ".join(notes)
        if not reply:
            reply = "I didn't catch that. Type “help” for examples."
        return {"provider": self.name, "reply": reply, "actions": actions, "used_kb": used_kb}

    @staticmethod
    def _my_location(loc: dict) -> str:
        where = loc.get("name") or f"{loc['lat']:.3f}, {loc['lon']:.3f}"
        parts = [f"**Your location: {where}.**"]
        f = loc.get("storm_forecast")
        if isinstance(f, dict):
            lv, mins = f["max_level_next_6h"], f["minutes_until_moderate_or_worse"]
            if mins is None:
                parts.append(f"No dangerous storm is expected here in the next 6 hours (highest level: {LEVEL_NAMES[lv]}).")
            else:
                parts.append(f"Storm danger reaches **{LEVEL_NAMES[lv]}** {'now' if mins == 0 else f'in about {mins} min'}"
                             f" — hail chance up to {round(f['max_hail_prob'] * 100)}%, gusts up to {f['max_gust_kmh']} km/h. "
                             "Plan to be indoors before then.")
        elif f:
            parts.append("Storm forecasts only cover East & North-East India, so there is no storm nowcast for your spot.")
        w = loc.get("weather_now")
        if w:
            parts.append(f"Weather now: {w.get('text', '').lower()}, {round(w['temp_c'])}°C (feels {round(w['feels_c'])}°C), "
                         f"humidity {w['humidity']}%, wind {round(w['wind_kmh'])} km/h.")
        parts.append("Always follow official IMD warnings.")
        return " ".join(parts)

    def _answer(self, m, place, ctx, is_question) -> str:
        if ctx.get("status") == "no analysis yet":
            return "The first analysis is still running — try again in a few seconds."
        thr = ctx.get("threatened_places", [])
        if place:
            hit = next((t for t in thr if t["name"] == place["name"]), None)
            if not hit:
                return f"**{place['name']}**: no Moderate-or-higher threat in the next 6 hours."
            h = hit.get("hazards") or {}
            when = "now" if hit["status"] == "impact" else f"in about {hit['eta_min']:.0f} min"
            return (f"**{place['name']}**: {hit['level']} threat {when}. Hail {h.get('hail_prob', 0):.0%}, "
                    f"gusts {h.get('gust_ms', 0) * 3.6:.0f} km/h, lightning {h.get('lightning', 0)} fl/km²/h, "
                    f"cloudburst {h.get('cloudburst_prob', 0):.0%}.")
        if re.search(r"(which|what|list|any).*(cit|place|town|airport|district).*|at risk|affected|threatened", m):
            if not thr:
                return "No monitored place is under a Moderate-or-higher threat in the next 6 hours."
            lines = [f"• {t['name']} — {t['level']}, " + ("NOW" if t["status"] == "impact" else f"ETA {t['eta_min']:.0f} min")
                     for t in thr[:8]]
            return f"{len(thr)} place(s) at risk:\n" + "\n".join(lines)
        if re.search(r"summary|status|overview|situation|brief", m):
            s = ctx["stats"]
            return (f"Analysis {ctx['analysis_time_utc'][11:16]} UTC ({ctx['mode']}): {s['n_cells']} active storm(s), "
                    f"max threat now {LEVEL_NAMES[s['max_level_now']]}, {len(thr)} place(s) at risk, "
                    f"{len(ctx.get('new_storms_forming', []))} new storm(s) forming. "
                    f"Feeds: " + ", ".join(f"{f['label'].split(' (')[0]} {f['status']}" for f in ctx["feeds"][:4]) + ".")
        if re.search(r"storm|cell", m) and is_question:
            st = ctx.get("storms", [])
            if not st:
                return "No storm cells (≥40 dBZ) are being tracked right now."
            top = sorted(st, key=lambda c: -c["level"])[:5]
            return "Strongest storms:\n" + "\n".join(
                f"• #{c['id']} {c['where']} — {LEVEL_NAMES[c['level']]}, {c['max_dbz']} dBZ, "
                f"{c['speed_kmh']:.0f} km/h → {c['heading_deg']:.0f}°" for c in top)
        return ""


# --------------------------------------------------------------------------- shared prompt
SYSTEM_PROMPT = (
    "You are BUMBLEBLE, the assistant inside a real-time convective-storm nowcasting dashboard for India "
    "(0-6 h forecasts of lightning, hail, downburst gusts and cloudbursts at 2 km). Two sources are given with "
    "each question: <live_nowcast> (JSON from the latest analysis) and <knowledge> (retrieved reference passages, "
    "each with a [n] tag). Rules: (1) For current weather, places, ETAs and hazards use ONLY <live_nowcast>. "
    "(2) For definitions, safety advice, procedures and how the system works use ONLY <knowledge>, and cite the "
    "passages you used as [n]. (3) If neither source contains the answer, say you don't have that information - "
    "never invent numbers, places or warnings. (4) Keep replies under 90 words, plain and practical for disaster "
    "managers, pilots and farmers; answer in the language the user writes in (English or Hindi). "
    "(5) When the user wants to see something, add UI actions: set_layer, set_lead (minutes, multiple of 10, "
    "0-360), fly_to (lat/lon of a place from <live_nowcast>), set_basemap, set_theme, toggle_overlay. "
    "Return actions only when they help. Remind users that official IMD warnings take precedence when giving safety advice. "
    "(6) If <live_nowcast> contains user_location, the user shared their own position: when they say 'me', 'here' or "
    "'my location', answer from user_location.storm_forecast and user_location.weather_now, name the place, and you may "
    "fly_to its lat/lon."
)


def _user_turn(message: str, context: dict, knowledge: list[dict] | None) -> str:
    kb = "\n\n".join(f"[{i + 1}] ({k['doc']} — {k['title']})\n{k['text']}" for i, k in enumerate(knowledge or [])) or "(none)"
    return (f"<live_nowcast>{json.dumps(context, separators=(',', ':'))}</live_nowcast>\n"
            f"<knowledge>\n{kb}\n</knowledge>\n\nUser question: {message}")


# --------------------------------------------------------------------------- gemini
class GeminiProvider(AssistantProvider):
    """Google Gemini via the official google-genai SDK.

    The requested model (GEMINI_MODEL, default gemini-2.5-flash) is tried first; if Google
    reports it retired (404) or overloaded (429/503) the next model in GEMINI_FALLBACK_MODELS is used.
    """

    name = "gemini"

    def __init__(self, api_key: str):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=api_key)
        primary = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        fallbacks = os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-3-flash-preview,gemini-flash-latest,gemini-3.5-flash")
        self.models = [primary] + [m.strip() for m in fallbacks.split(",") if m.strip() and m.strip() != primary]
        self.retired: set[str] = set()
        self.last_model: str | None = None

    def embed(self, texts: list[str]):
        r = self.client.models.embed_content(
            model=os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001"), contents=texts,
            config=self.types.EmbedContentConfig(output_dimensionality=768))
        return [e.values for e in r.embeddings]

    def respond(self, message, history, context, places, knowledge=None):
        T = self.types
        contents = []
        for h in history[-8:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                contents.append(T.Content(role="user" if h["role"] == "user" else "model",
                                          parts=[T.Part(text=str(h["content"])[:2000])]))
        contents.append(T.Content(role="user", parts=[T.Part(text=_user_turn(message, context, knowledge))]))
        cfg = T.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.3,
                                      response_mime_type="application/json", response_json_schema=ACTION_SCHEMA)
        last_err = None
        import time as _time

        order = [m for m in self.models if m not in self.retired]
        if self.last_model in order:  # try the model that worked last time first
            order.remove(self.last_model)
            order.insert(0, self.last_model)
        attempts = [(m, r) for r in range(int(os.environ.get("GEMINI_RETRY_ROUNDS", "2"))) for m in order]
        for model, rnd in attempts:
            if model in self.retired:
                continue
            if rnd and model == order[0]:
                _time.sleep(2.0)  # brief back-off before a second round when every model is overloaded
            try:
                r = self.client.models.generate_content(model=model, contents=contents, config=cfg)
                data = json.loads(r.text)
                self.last_model = model
                return {"provider": self.name, "model": model, "reply": data.get("reply", ""), "actions": data.get("actions", [])}
            except Exception as exc:
                code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                last_err = exc
                if code == 404:
                    self.retired.add(model)  # not available for this key - skip from now on
                log.warning("gemini model %s failed (%s): %s", model, code, str(exc)[:160])
                if code not in (404, 429, 500, 503):
                    break
        raise RuntimeError(f"all Gemini models failed: {last_err}")


# --------------------------------------------------------------------------- claude
class ClaudeProvider(AssistantProvider):
    name = "claude"
    MODEL = os.environ.get("NOWCAST_AI_MODEL", "claude-opus-5")
    SYSTEM = (
        "You are BUMBLEBLE, the assistant inside a real-time convective-storm nowcasting dashboard for India "
        "(0-6 h forecasts of lightning, hail, downburst gusts and cloudbursts). Answer only from the JSON "
        "context of the latest analysis that accompanies each question; if the data does not contain the "
        "answer, say so. Keep replies under 80 words, plain and practical, suitable for disaster managers, "
        "pilots and farmers. When the user wants to see something, add UI actions: set_layer, set_lead "
        "(minutes, multiple of 10, 0-360), fly_to (use the lat/lon of a place from the context), set_basemap, "
        "set_theme, toggle_overlay. Return actions only when they help; never invent places or numbers."
    )

    def __init__(self):
        import anthropic

        self.client = anthropic.Anthropic()

    def respond(self, message, history, context, places, knowledge=None):
        msgs = []
        for h in history[-8:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                msgs.append({"role": h["role"], "content": str(h["content"])[:2000]})
        msgs.append({"role": "user", "content": _user_turn(message, context, knowledge)})
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        response = self.client.beta.messages.create(
            model=self.MODEL,
            max_tokens=2000,
            system=self.SYSTEM,
            messages=msgs,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": ACTION_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return {"provider": self.name, "reply": "I can't help with that request.", "actions": []}
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
        return {"provider": self.name, "reply": data.get("reply", ""), "actions": data.get("actions", [])}


def get_provider() -> AssistantProvider:
    if os.environ.get("NOWCAST_AI", "").lower() == "demo":  # force the keyless assistant (offline demos)
        return DemoProvider()
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return GeminiProvider(os.environ["GEMINI_API_KEY"])
        except Exception as exc:
            log.warning("Gemini provider unavailable (%s); trying next provider", exc)
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        try:
            return ClaudeProvider()
        except Exception as exc:  # SDK missing or misconfigured -> demo mode
            log.warning("Claude provider unavailable (%s); using demo assistant", exc)
    return DemoProvider()


DEMO = DemoProvider()


def respond(provider: AssistantProvider, message: str, history: list[dict], context: dict, places: list[dict],
            kb=None) -> dict:
    """Retrieve knowledge (RAG), run the configured provider, fall back to demo mode on any failure."""
    knowledge = []
    if kb is not None:
        try:
            knowledge = kb.search(message, k=4)
        except Exception as exc:
            log.warning("knowledge search failed: %s", exc)
    try:
        out = provider.respond(message, history, context, places, knowledge)
    except Exception as exc:
        log.warning("assistant provider %s failed: %s", provider.name, exc)
        out = DEMO.respond(message, history, context, places, knowledge)
        out["reply"] = "(AI service unavailable — answered in demo mode)\n\n" + out["reply"]
    # cite only what the answer used: demo mode cites its passage only when it answered from it;
    # LLM answers are filtered client-side to the [n] tags that appear in the reply.
    used = knowledge if out.get("used_kb", out.get("provider") != "demo") else []
    out.pop("used_kb", None)
    out["sources"] = [{"n": i + 1, "doc": k["doc"], "title": k["title"], "score": k["score"]} for i, k in enumerate(used)]
    # validate actions defensively (never trust model output blindly)
    clean = []
    for a in out.get("actions") or []:
        t = a.get("type")
        if t == "set_layer" and a.get("layer") in LAYERS:
            clean.append({"type": t, "layer": a["layer"]})
        elif t == "set_lead" and isinstance(a.get("lead_min"), (int, float)):
            clean.append({"type": t, "lead_min": int(max(0, min(360, round(a["lead_min"] / 10) * 10)))})
        elif t == "fly_to" and isinstance(a.get("lat"), (int, float)) and isinstance(a.get("lon"), (int, float)):
            clean.append({"type": t, "lat": float(a["lat"]), "lon": float(a["lon"]),
                          "zoom": float(a.get("zoom") or 9), "place": a.get("place", "")})
        elif t == "set_basemap" and a.get("basemap") in BASEMAPS:
            clean.append({"type": t, "basemap": a["basemap"]})
        elif t == "set_theme" and a.get("theme") in ("light", "dark"):
            clean.append({"type": t, "theme": a["theme"]})
        elif t == "toggle_overlay" and a.get("overlay") in OVERLAYS:
            clean.append({"type": t, "overlay": a["overlay"], "on": bool(a.get("on", True))})
    out["actions"] = clean
    return out
