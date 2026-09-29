# BUMBLEBLE system guide

## What BUMBLEBLE is
BUMBLEBLE is a real-time convective storm nowcasting system for India. It forecasts thunderstorms, lightning, hail, downburst winds and cloudbursts from 0 to 6 hours ahead, at about 2 km resolution. A new forecast is made about every 5–10 minutes, with lead times in 10-minute steps.

## Data used
BUMBLEBLE fuses three kinds of observations on one common 2 km grid:
- **Doppler Weather Radar (DWR)** reflectivity (rain and hail intensity, in dBZ) and radial velocity (winds, including downburst outflow). In real-time mode it uses the RainViewer radar mosaic, which provides reflectivity only.
- **Geostationary satellite (INSAT-3D/3DR)** infrared cloud-top temperature. Rapidly cooling cloud tops reveal storms forming before radar sees rain. Satellite images are corrected for parallax, the apparent shift of tall clouds seen at an angle.
- **Ground lightning networks**: flash locations and rates. A sudden jump in the flash rate warns of severe weather.
Where radar coverage is missing, a satellite + lightning estimate fills the gap, marked with lower confidence.

## How the forecast works
1. Storm motion is estimated by matching successive radar and satellite images.
2. Storm cells (areas of at least 40 dBZ) are identified and tracked, with their growth or decay trend.
3. The current weather is moved forward along the motion, with growth and decay applied. Small details are smoothed out as lead time grows, because they cannot be predicted far ahead.
4. Newly forming storms detected by satellite are added to the forecast.
5. Hazards are computed for every 10-minute step, and probabilities are spread over a neighbourhood that widens with lead time to reflect growing uncertainty.

## Hazard products
- **Lightning density**: expected flashes per km² per hour.
- **Hail probability**: from vertically integrated liquid (VIL) density, storm-core strength and cloud-top coldness. VIL density above about 3.5 g/m³ strongly suggests large hail.
- **Downburst gust**: expected peak gust (m/s), from the Stewart (1991) VIL/echo-top formula combined with radar-observed outflow.
- **Cloudburst probability**: the chance of 100 mm or more of rain in the next hour.
- **Rain next hour**: expected accumulation in mm.

## Threat levels
The composite threat has five levels:
- **None**: no significant convection.
- **Low (yellow)**: thunderstorm or lightning possible.
- **Moderate (orange)**: an organised storm with some chance of hail, gusts of about 15 m/s (54 km/h) or more, frequent lightning, or a cloudburst chance of 20% or more.
- **High (red)**: hail probability 50% or more, gusts of about 22 m/s (80 km/h) or more, intense lightning, or a cloudburst chance of 40% or more.
- **Extreme (purple)**: hail probability 75% or more, gusts of about 28 m/s (100 km/h) or more, or a cloudburst chance of 65% or more.

## Arrival countdowns
For each city, airport and farming district, the ETA is the first forecast time at which the threat reaches Moderate. It is refined to the minute using the motion of the approaching storm cell. Each countdown card shows the expected hail chance, peak gust, lightning, cloudburst chance and roughly how long the threat lasts.

## Accuracy and limits
Forecast skill is checked live against later radar. CSI (critical success index) compares forecast and observed areas of at least 35 dBZ at 30, 60 and 120 minutes, alongside a "storm doesn't move" persistence baseline. Skill is highest in the first hour and falls with lead time, because storms form and decay faster than extrapolation can follow. Beyond about 2–3 hours, treat forecasts as broad guidance. BUMBLEBLE provides guidance only: always follow official IMD warnings.

## Modes
- **Realtime**: live RainViewer radar. Satellite and lightning feeds are shown as not connected until operational access to IMD/MOSDAC data is arranged.
- **Simulated**: a built-in pre-monsoon storm scenario for demos and training.
- **Live**: operational IMD radar (ODIM_H5), INSAT (HDF5) and lightning feeds.
