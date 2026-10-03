"""Live surface weather from Open-Meteo (free, keyless, cloud API).

Current conditions plus the next hours for any point, and one batched request
for every monitored place. Responses are cached briefly so many viewers share
one upstream call (Open-Meteo updates current conditions every 15 min).
"""
from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.parse
import urllib.request

API = "https://api.open-meteo.com/v1/forecast"
CURRENT = ("temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,rain,weather_code,cloud_cover,"
           "wind_speed_10m,wind_direction_10m,wind_gusts_10m,cape,is_day")
HOURLY = "temperature_2m,precipitation_probability,precipitation,weather_code,wind_gusts_10m,cape,is_day"
TTL_S = 600

# WMO weather interpretation codes -> plain text + icon
WMO = {
    0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"), 48: ("Freezing fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"), 77: ("Snow grains", "🌨️"),
    80: ("Light showers", "🌦️"), 81: ("Showers", "🌧️"), 82: ("Violent showers", "⛈️"),
    85: ("Snow showers", "🌨️"), 86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm with hail", "⛈️"), 99: ("Severe thunderstorm with hail", "⛈️"),
}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _ssl_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class WeatherService:
    def __init__(self, places: list[dict]):
        self.places = places
        self.ctx = _ssl_context()
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def _get(self, params: dict) -> object:
        url = API + "?" + urllib.parse.urlencode(params, safe=",")
        req = urllib.request.Request(url, headers={"User-Agent": "BUMBLEBLE-nowcast/1.0"})
        for attempt in range(3):  # free public API: retry brief connection resets
            try:
                with urllib.request.urlopen(req, timeout=20, context=self.ctx) as r:
                    return json.loads(r.read())
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))

    def _cached(self, key: str, fn):
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
        val = fn()
        with self._lock:
            self._cache[key] = (time.time(), val)
            if len(self._cache) > 500:  # keep the point cache small
                for k, _ in sorted(self._cache.items(), key=lambda kv: kv[1][0])[:250]:
                    self._cache.pop(k, None)
        return val

    @staticmethod
    def _icon(code, is_day) -> str:
        code = int(code or 0)
        return "🌙" if code in (0, 1) and not is_day else WMO.get(code, ("", "🌡️"))[1]

    @classmethod
    def _summarise(cls, c: dict) -> dict:
        code = int(c.get("weather_code") or 0)
        text = WMO.get(code, ("Unknown", ""))[0]
        icon = cls._icon(code, c.get("is_day", 1))
        wd = c.get("wind_direction_10m")
        return {
            "time": c.get("time"), "text": text, "icon": icon, "code": code,
            "temp_c": c.get("temperature_2m"), "feels_c": c.get("apparent_temperature"),
            "humidity": c.get("relative_humidity_2m"), "cloud": c.get("cloud_cover"),
            "rain_mm": c.get("precipitation"), "wind_kmh": c.get("wind_speed_10m"),
            "gust_kmh": c.get("wind_gusts_10m"), "wind_from": None if wd is None else COMPASS[round(wd / 45) % 8],
            "cape": c.get("cape"), "thunder": code >= 95,
        }

    def point(self, lat: float, lon: float) -> dict:
        lat, lon = round(lat, 2), round(lon, 2)  # ~1 km: nearby clicks share a cache entry

        def fetch():
            j = self._get({"latitude": lat, "longitude": lon, "current": CURRENT, "hourly": HOURLY,
                           "forecast_hours": 7, "timezone": "auto"})  # local time of the clicked place
            h = j.get("hourly", {})
            hours = [{"time": t, "temp_c": h["temperature_2m"][i], "rain_prob": h["precipitation_probability"][i],
                      "rain_mm": h["precipitation"][i], "gust_kmh": h["wind_gusts_10m"][i],
                      "icon": self._icon(h["weather_code"][i], h["is_day"][i])}
                     for i, t in enumerate(h.get("time", []))]
            return {"lat": lat, "lon": lon, "now": self._summarise(j.get("current", {})), "hours": hours,
                    "source": "Open-Meteo", "fetched": time.time()}

        return self._cached(f"p:{lat},{lon}", fetch)

    def places_now(self) -> dict:
        def fetch():
            lats = ",".join(f"{p['lat']:.3f}" for p in self.places)
            lons = ",".join(f"{p['lon']:.3f}" for p in self.places)
            j = self._get({"latitude": lats, "longitude": lons, "current": CURRENT, "timezone": "Asia/Kolkata"})
            arr = j if isinstance(j, list) else [j]
            return {"places": {p["id"]: self._summarise(r.get("current", {})) for p, r in zip(self.places, arr)},
                    "source": "Open-Meteo", "fetched": time.time()}

        return self._cached("places", fetch)
