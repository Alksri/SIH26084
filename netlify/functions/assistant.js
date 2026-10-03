/**
 * BUMBLEBLE — Netlify serverless function for the Ask AI assistant.
 * Receives { message, history, location? } from the frontend,
 * calls Google Gemini, and returns { reply, actions, provider, model }.
 *
 * Set GEMINI_API_KEY in Netlify → Site configuration → Environment variables.
 */

const GEMINI_API_KEY = process.env.GEMINI_API_KEY || "";
const GEMINI_MODEL   = process.env.GEMINI_MODEL   || "gemini-2.5-flash";
const GEMINI_API_URL = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`;

// ------------------------------------------------------------------ system prompt
const SYSTEM_PROMPT = `You are BUMBLEBLE, the assistant inside a real-time convective-storm nowcasting dashboard for India (0–6 h forecasts of lightning, hail, downburst gusts and cloudbursts at 2 km resolution).

Rules:
1. Answer only from the live nowcast JSON and knowledge passages provided with each question.
2. Keep replies under 90 words — plain and practical for disaster managers, pilots and farmers.
3. Answer in the language the user writes in (English or Hindi).
4. When the user wants to SEE something on the map, include the right UI actions (set_layer, set_lead, fly_to, set_basemap, set_theme, toggle_overlay). Return actions only when they help.
5. Never invent numbers, places or warnings. Remind users that official IMD warnings always take precedence.
6. If the user mentions "me", "here" or "my location" and user_location is provided in the context, answer from user_location.storm_forecast and user_location.weather_now.

Valid layers: level, level_60, level_360, lightning, hail, gust, cloudburst, rain1h, dbz, ir, qpe1h, confidence
Valid basemaps: auto, streets, satellite, hybrid, terrain, topo
Valid overlays: cells, strikes, ci, clocks, motion, radars, rainviewer, gibs
Level names: 0=None, 1=Low, 2=Moderate, 3=High, 4=Extreme

You MUST respond with ONLY valid JSON in this exact schema:
{
  "reply": "<your answer string, max 90 words>",
  "actions": [
    { "type": "set_layer", "layer": "<layer name>" },
    { "type": "set_lead", "lead_min": <integer 0–360, multiple of 10> },
    { "type": "fly_to", "lat": <number>, "lon": <number>, "zoom": <number 6–14>, "place": "<name>" },
    { "type": "set_basemap", "basemap": "<basemap name>" },
    { "type": "set_theme", "theme": "light|dark" },
    { "type": "toggle_overlay", "overlay": "<overlay name>", "on": true|false }
  ]
}
Only include action types that apply. "actions" may be an empty array [].`;

// ------------------------------------------------------------------ demo fallback (no API key)
const DEMO_ANSWERS = [
  { match: /hail/i,      reply: "Hail risk is shown on the Hazards page. The Hail layer on the map shows probability across monitored regions. Stay indoors and away from windows during hail events. Always follow official IMD warnings." },
  { match: /lightning|thunder/i, reply: "Lightning risk is displayed on the Map page. Seek shelter in a strong building immediately if you hear thunder. Avoid open areas, tall trees and bodies of water. Always follow official IMD warnings." },
  { match: /rain|flood/i, reply: "Rainfall forecasts are shown on the Map page (Rain next hour layer). Move to higher ground if flash flooding is possible. Always follow official IMD warnings." },
  { match: /safe|danger|risk|threat/i, reply: "Check the Hazards page for a full risk summary of all monitored locations. The Map page shows the composite threat level across the region. Always follow official IMD warnings." },
  { match: /storm|cell/i, reply: "Active storm cells are tracked on the Map page. Storm outlines and movement arrows can be toggled in the Layers panel. For arrival times, check the Arrivals page. Always follow official IMD warnings." },
  { match: /.*/, reply: "I'm running in demo mode (no AI key configured). Ask about hail, lightning, rain, storm threats, or how to use the map — I'll do my best. Always follow official IMD warnings." },
];

function demoReply(message) {
  const hit = DEMO_ANSWERS.find((d) => d.match.test(message)) || DEMO_ANSWERS[DEMO_ANSWERS.length - 1];
  return { provider: "demo", reply: hit.reply, actions: [], sources: [] };
}

// ------------------------------------------------------------------ action extractor / validator
const VALID_LAYERS   = ["level","level_60","level_360","lightning","hail","gust","cloudburst","rain1h","dbz","ir","qpe1h","confidence"];
const VALID_BASEMAPS = ["auto","streets","satellite","hybrid","terrain","topo"];
const VALID_OVERLAYS = ["cells","strikes","ci","clocks","motion","radars","rainviewer","gibs"];

function validateActions(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const a of raw) {
    const t = a?.type;
    if (t === "set_layer"   && VALID_LAYERS.includes(a.layer))    { out.push({ type: t, layer: a.layer }); }
    else if (t === "set_lead"    && typeof a.lead_min === "number") { out.push({ type: t, lead_min: Math.round(Math.max(0, Math.min(360, a.lead_min / 10)) * 10) }); }
    else if (t === "fly_to"      && isFinite(a.lat) && isFinite(a.lon)) { out.push({ type: t, lat: +a.lat, lon: +a.lon, zoom: +(a.zoom || 9), place: a.place || "" }); }
    else if (t === "set_basemap" && VALID_BASEMAPS.includes(a.basemap)) { out.push({ type: t, basemap: a.basemap }); }
    else if (t === "set_theme"   && (a.theme === "light" || a.theme === "dark")) { out.push({ type: t, theme: a.theme }); }
    else if (t === "toggle_overlay" && VALID_OVERLAYS.includes(a.overlay)) { out.push({ type: t, overlay: a.overlay, on: !!a.on }); }
  }
  return out;
}

// ------------------------------------------------------------------ Gemini call
async function callGemini(message, history) {
  const contents = [];

  // Rebuild conversation history
  for (const h of (history || []).slice(-8)) {
    if (h.role === "user" || h.role === "assistant") {
      contents.push({
        role: h.role === "assistant" ? "model" : "user",
        parts: [{ text: String(h.content || "").slice(0, 2000) }],
      });
    }
  }
  contents.push({ role: "user", parts: [{ text: message }] });

  const body = {
    system_instruction: { parts: [{ text: SYSTEM_PROMPT }] },
    contents,
    generationConfig: {
      temperature: 0.3,
      responseMimeType: "application/json",
    },
  };

  const res = await fetch(GEMINI_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => res.status);
    throw new Error(`Gemini API error ${res.status}: ${errText}`);
  }

  const data = await res.json();
  const text = data?.candidates?.[0]?.content?.parts?.[0]?.text || "";
  const parsed = JSON.parse(text);

  return {
    provider: "gemini",
    model: GEMINI_MODEL,
    reply: parsed.reply || "Done.",
    actions: validateActions(parsed.actions),
    sources: [],
  };
}

// ------------------------------------------------------------------ handler
export default async function handler(req, context) {
  // CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      },
    });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ detail: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ detail: "Invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const { message, history, location: userLoc } = body || {};
  if (!message || typeof message !== "string") {
    return new Response(JSON.stringify({ detail: "message is required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Build the full prompt with location context if provided
  let fullMessage = message;
  if (userLoc) {
    fullMessage = `[User location: ${userLoc.name || `${userLoc.lat?.toFixed(3)}, ${userLoc.lon?.toFixed(3)}`} (accuracy: ${Math.round(userLoc.accuracy_m || 0)} m)]\n\n${message}`;
  }

  let result;
  if (!GEMINI_API_KEY) {
    result = demoReply(message);
  } else {
    try {
      result = await callGemini(fullMessage, history);
    } catch (err) {
      console.error("Gemini call failed:", err.message);
      result = demoReply(message);
      result.reply = `(AI unavailable — demo mode)\n\n${result.reply}`;
    }
  }

  return new Response(JSON.stringify(result), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
