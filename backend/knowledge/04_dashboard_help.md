# Using the BUMBLEBLE dashboard

## Map layers
- Choose a hazard layer in the left panel: Composite threat, Worst in next 1 h / 6 h, Lightning density, Hail probability, Downburst gusts, Cloudburst risk, or Rain next hour.
- Observation layers show the fused radar reflectivity, INSAT infrared, observed rain in the last hour, and fusion confidence.
- The timeline at the bottom moves the forecast from Now to +6 h. Press Play (or Space) to animate, and the arrow keys to step through time.

## Arrival countdowns
The **Arrivals** tab lists every place under a Moderate or higher threat, with a live countdown, expected hazards and duration. Filter by Cities, Airports or Farms. Click a card to fly to the place.

## Map types
The thumbnail in the bottom-left of the map switches between Default, Streets, Satellite, Hybrid, Terrain and Topographic maps.

## Assistant
In the **Ask AI** tab you can ask questions such as "Which cities are at risk?", "Show hail risk near Ranchi in 2 hours", "What should farmers do during a hail warning?" or "Switch to satellite map". The assistant answers from the live forecast and from this knowledge base, and can change the map for you.

## Adding knowledge
Add your own documents (SOPs, district contacts, crop advisories, airport procedures) as Markdown or text files with **📚 Knowledge → Add document** in the Ask AI tab, or by placing them in the server's `backend/knowledge` folder. The assistant then uses them in its answers and cites them.

## Sharing and exporting
- **Share** copies a link to the exact current view.
- **Export** downloads a printable bulletin (save as PDF), a CSV of arrival countdowns, GeoJSON for GIS software, or an image of the current layer.
- **Undo/Redo** (Ctrl+Z / Ctrl+Y) steps back and forward through view changes.

## Alerts and notifications
Turn on the bell icon for browser notifications of High and Extreme threats. The **Alerts** tab logs new storms forming, lightning jumps, severe warnings, cloudburst risks and data-feed problems.
