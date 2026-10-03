/* BUMBLEBLE deployment setting — the only thing you may need to edit when hosting the pages.
 *
 * Leave it empty ("") when the pages are served by the BUMBLEBLE Python server itself
 * (local run, Docker, Hugging Face Spaces, Render).
 *
 * When the pages are on Netlify, Vercel or GitHub Pages, put the address of your running
 * BUMBLEBLE server here, e.g. "https://your-name-bumbleble.hf.space".
 *
 * If it is empty or the server can't be reached, the site still works in "browser mode":
 * storm risk and weather are computed in the visitor's browser from free Open-Meteo data,
 * and the map shows live RainViewer radar.
 */
window.BUMBLEBLE_API = "";
