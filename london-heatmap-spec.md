# Technical Specification: London Housing Heat Map

**Status:** Draft v0.2 · **Audience:** Two users (David + partner); app is public · **Last updated:** 2026-06-13

New or materially changed design decisions since v0.1 are marked **⟨v0.2⟩** inline. The headline changes: travel time moves from TravelTime-API isochrones to an R5-computed travel-time matrix (rationale in §6); one travel layer per (destination, mode); the price layer filters to 3-bed+ houses via the EPC join; parks become a gravity-style accessibility score; crime splits into per-category layers; normalization changes from percentile rank to winsorized linear rescaling; the data artefact becomes columnar with fully-named fields; partial-data cells are marked by border rather than opacity; and the app is explicitly public with no privacy machinery.

## 1. Purpose

A public web app that renders an interactive heat map of Greater London, where each cell's colour encodes a composite "desirability score": a weighted sum of normalized housing desiderata — purchase price, travel time to two fixed destinations by public transport and by bicycle, restaurant density, park access, crime, and school quality. Users adjust per-layer weights with sliders and the map recolours instantly. The goal is exploratory — surfacing areas worth investigating, not producing a definitive ranking.

## 2. Architecture overview

Two parts, no runtime backend.

**Offline data pipeline** — manually triggered **⟨v0.2⟩** (no cron; source data moves slowly and two users don't need automation), runs locally, fetches source data, computes one normalized score per layer per grid cell, and writes a static data artefact (`grid.json` plus an HTML sanity-check report). The pipeline is the only component touching external services.

**Static frontend** — a single-page app on GitHub Pages **⟨v0.2⟩**. It loads `grid.json` once, then performs all weighting and recolouring client-side. No server, no database, no authentication, and no privacy machinery **⟨v0.2⟩**: the app is public and destination coordinates may appear in the shipped artefact.

The contract between the two parts is the artefact schema (§4); either side can be rewritten independently.

## 3. Spatial model

A uniform square grid of **250 m cells** in British National Grid (EPSG:27700), clipped to the Greater London boundary, yielding ~25,000 cells (Greater London ≈ 1,572 km² × 16 cells/km², less boundary clipping). Each cell is identified by its south-west corner easting/northing as a string id (`530250_180500`).

Why compute in BNG when the frontend displays WGS84: "250 m square" is only coherent in a projected CRS with metre units. A uniform lat/lon grid at London's latitude produces rectangles (1° longitude ≈ 0.62 × 1° latitude in ground distance), and Web Mercator's nominal metres are off by a scale factor of ~1.61 at 51.5°N. BNG gives true metric squares and makes all metric geometry — 500 m count radii, kernel bandwidths, park distance decay — natural. Reprojection to WGS84 for display is a one-time, lossless pipeline step. This is the standard pattern: compute projected, display geographic.

Cells with no housing stock (parks, reservoirs, industrial estates) are flagged non-residential using OSM land-use data and rendered hollow/grey rather than scored, so the colour ramp isn't spent on uninhabitable land.

## 4. Data artefact schema

**⟨v0.2⟩ Columnar layout with fully-named fields**, replacing v0.1's per-cell objects with terse keys. Each field is a parallel array indexed by cell position — cell *i* is row *i* of every array. Keys appear once instead of 25,000 times, so the file is smaller than the per-cell layout even before transfer compression, every name is self-describing, and the frontend's scoring loop becomes a tight pass over flat arrays (the fastest access pattern available to JS).

```json
{
  "meta": {
    "generated": "2026-06-13T10:00:00Z",
    "cellSizeM": 250,
    "computeCrs": "EPSG:27700",
    "layers": [
      {
        "id": "price",
        "label": "Price (£/m², 3-bed+ houses)",
        "direction": "lower_better",
        "source": "HM Land Registry Price Paid + EPC register",
        "vintage": "2026-05",
        "cutoffs": {"low": 4000, "high": 12000},
        "rawUnit": "£/m²"
      }
    ]
  },
  "cellIds":     ["530250_180500", "530500_180500", "530750_180500"],
  "centroids":   [[-0.121, 51.512], [-0.117, 51.512], [-0.114, 51.512]],
  "residential": [true, true, false],
  "layers": {
    "price":              {"scores": [0.62, 0.55, null], "raw": [6900, 7400, null]},
    "travel_workA_pt":    {"scores": [0.81, 0.78, null], "raw": [34, 37, null]},
    "travel_workA_cycle": {"scores": [0.70, 0.66, null], "raw": [41, 45, null]},
    "travel_workB_pt":    {"scores": [0.77, 0.74, null], "raw": [38, 40, null]},
    "travel_workB_cycle": {"scores": [0.58, 0.55, null], "raw": [52, 55, null]},
    "restaurants":        {"scores": [0.44, 0.51, null], "raw": [12, 15, null]},
    "parks":              {"scores": [0.66, 0.61, null], "raw": [2.1, 1.8, null]},
    "crime_burglary":     {"scores": [0.71, 0.69, null], "raw": [3.2, 3.5, null]},
    "schools":            {"scores": [0.52, 0.52, null], "raw": [2.6, 2.6, null]}
  }
}
```

Scores live in [0, 1] with **1 always desirable** (direction applied in the pipeline). `raw` carries human-readable values for tooltips — minutes, £/m², counts — because "0.62" means nothing to a user but "£6,900/m², 34 min by tube" is what they want. Cells lacking data for a layer carry `null`; handling in §7. The artefact is committed as plain JSON; GitHub Pages' CDN applies transfer compression, so no pre-gzipping **⟨v0.2⟩**.

## 5. Layers

| Layer | Source | Cell metric | Direction |
|---|---|---|---|
| Price | Land Registry Price Paid + EPC register | Median £/m² of qualifying sales (3-bed+ houses), cell + 500 m neighbourhood, last 24 months | lower better |
| Travel × 4 | R5 travel-time matrix (§6) | Median minutes over 08:00–09:00 departure window, per (destination, mode) | lower better |
| Restaurants | OpenStreetMap | Count of `amenity=restaurant\|cafe\|pub` within 500 m of centroid | higher better |
| Parks | OpenStreetMap | Gravity accessibility score over nearby parks | higher better |
| Crime × N | data.police.uk | Kernel-smoothed incidents per category | lower better |
| Schools | Ofsted + GIAS | Distance-weighted mean rating of primaries within 1.5 km | higher better |

**Price — ⟨v0.2⟩ filtered to 3-bed+ houses.** Raw sold prices conflate size with location, so the metric is £/m², obtained by joining Price Paid transactions to the EPC register on address (the EPC — Energy Performance Certificate, legally required on construction, sale, or letting — is bulk-downloadable open data carrying floor area and habitable-room count; join rates run 80–90%, unjoined sales dropped). Price Paid alone records property type but not bedrooms; the EPC join supplies the filter: property type in {detached, semi, terraced} **and** (habitable rooms ≥ 5 **or** floor area ≥ 90 m²) as a 3-bed+ proxy. This thins observations badly in central London; the resulting null cells are treated as information ("no qualifying housing stock sold here"), not as a defect to be papered over. Sparse cells borrow from a 500 m neighbourhood; below 5 observations even then → null.

**Travel — ⟨v0.2⟩ one layer per (destination, mode)**: with two destinations and two modes (public transport, cycling) that is four independent layers, each with its own weight slider and raw minutes in the tooltip. v0.1's worst-case aggregation is dropped: aggregation choices encode value judgements better left to the user's weights. Computation in §6.

**Restaurants.** Counted within a 500 m radius of each centroid rather than inside hard cell boundaries, to avoid checkerboard noise — the artefact where a point cluster straddling a cell boundary splits arbitrarily, making adjacent cells alternate high/low for no real reason; overlapping circular windows remove it. OSM completeness in London is good for this category.

**Parks — ⟨v0.2⟩ gravity accessibility score** replacing v0.1's nearest-park distance, which ignored park size and accumulation. Per cell: `Σ over parks p of log(1 + area_ha(p)) · exp(−dist(centroid, p) / λ)`, λ = 500 m (walking-scale decay). The log term encodes diminishing returns in size — gaining a first hectare of park matters far more than a tenth — the exponential rewards proximity continuously, and several nearby parks accumulate. A standard accessibility formulation.

**Crime — ⟨v0.2⟩ per-category layers.** data.police.uk street-level data is queried per crime category; a config-selected subset (default: burglary; violence & robbery; vehicle crime; anti-social behaviour) each becomes its own layer rather than one aggregate, since the categories carry different information for a resident. All ~14 categories as sliders would be noise — many are correlated — hence a curated default with config override. Police location-fuzzing (incidents snapped to a fixed set of anonymised map points) makes **kernel smoothing mandatory**: each incident is replaced by a Gaussian bump (~400 m bandwidth) and bumps are summed, so values reflect distance-weighted local intensity rather than spurious spikes at snap points. Denominator is per residential cell area, not per capita, in v1 — simpler, no census join — accepting that high-footfall central cells are somewhat penalised by visitor-generated incidents; per-capita via LSOA population is the documented fix if those layers look distorted.

**Schools.** Distance-weighted mean rating of primary schools within 1.5 km (GIAS locations, most recent graded judgement per school). Ofsted's single-word judgements were abolished in 2024, so this layer is flagged as the most likely to need a methodology revision. Trivially disabled in config.

## 6. Travel-time computation — design and rationale

**⟨v0.2⟩ Decision: R5 (via r5py) computes all travel layers, both public transport and cycling, replacing the v0.1 TravelTime-API isochrone design.** Because this decision moved twice during review, the alternatives and the reasons for rejecting them are recorded here.

**Rejected: TravelTime API isochrones (v0.1 design).** Two independent defects. First, banding: isochrones quantize travel time into discrete contours, so properties just inside and just outside a contour are treated as very different while genuine differences within a band are erased entirely. Granular bands mitigate but never remove this, and cost proportionally more API calls. Second, commercial fragility: the API is paid beyond a two-week trial; building a quarterly-refresh pipeline on a trial is not a foundation.

**Rejected: batched TfL Journey Planner calls.** Superficially attractive — free, returns continuous per-journey minutes (solving the banding problem), and the volume is feasible (~20k residential cells × 2 destinations ≈ 40k calls, a few hours overnight within the 500 req/min registered limit). Rejected because per-journey answers from a trip-planning assistant make a poor dataset:

1. *Option selection, not optimisation.* Each response is a small set of candidate journeys chosen by heuristics balancing speed, number of changes, and walking comfort. The fastest journey shown is not guaranteed to be the fastest that exists, and the heuristic can choose differently for adjacent cells feeding the same corridor — producing speckle between cells whose true times are near-identical.
2. *Timetable-alignment luck.* A single "depart 08:30" query includes the wait for the first service: if one cell's bus leaves at 08:31 and its neighbour's at 08:43, the neighbour looks 12 minutes worse despite identical service frequency — measuring phase, not accessibility. Correcting this requires querying a departure window, multiplying call volume in exactly the wrong direction.
3. *Live-data contamination.* Responses blend in current disruptions and engineering works, so results depend on the day and minute the batch ran — a weekend line closure dents a whole sector of the map, unreproducibly.
4. *Edge behaviour.* Cells far from any stop return "no journey" or odd first legs, where a matrix router simply walks further.
5. A 40k-call batch also sits in fair-use territory rather than the API's intended interactive use.

**Chosen: R5.** R5 (Conveyal's routing engine, used from Python via r5py) builds a multimodal graph from an OSM street-network extract plus GTFS transit feeds and computes one-to-many travel-time matrices: continuous minutes from each destination to all ~25k centroids in one operation. It answers each of the problems above structurally rather than mitigating them: no banding (continuous output); the matrix is computed across a departure window (every minute, 08:00–09:00, taking the **median** per origin–destination pair), which averages away timetable phase; the result is a pure function of the timetable feed — rerun with the same feed, get identical numbers — so refreshes are reproducible and engineering works don't contaminate anything; and it is free and local, with no rate limits or third-party availability risk during runs.

**⟨v0.2⟩ Cycling also runs through R5** (it routes bicycle journeys natively from the OSM network, with configurable speed and traffic-stress tolerance), so the OSRM container floated during review is unnecessary — one engine covers both modes.

**Inputs and their sourcing.** GTFS feeds are published open data we download, not data we author. Buses (including London's): the DfT Bus Open Data Service offers a direct GTFS download. TfL tube/DLR/Overground and national rail are published in UK-specific formats (CIF for rail) requiring one conversion step via UK2GTFS, or a community-maintained pre-converted feed. Feeds contain dated service calendars, so the graph build pins a "typical Tuesday" inside the feed validity window, recorded in `meta` for reproducibility.

**Costs accepted:** a JDK dependency and ~8 GB RAM during graph build (the main reason Docker is recommended, §9), the feed-conversion step, and occasionally stale community feeds. One-time setup pain against recurring correctness — the right trade for a tool whose travel layers carry the most weight.

## 7. Normalization and scoring

**⟨v0.2⟩ Winsorized linear rescaling replaces v0.1's percentile rank.** Percentile rank was rejected during review because it discards magnitude: scores become ordinal, and the map should care about degree. Plain min–max rescaling — `(x − min)/(max − min)` — preserves degree but lets the single most extreme cell define the scale: a handful of £20k+/m² Mayfair sales would compress the rest of London into a narrow band and wash the layer out. The adopted middle course:

**Per layer: clamp raw values to configured cut-offs, rescale linearly between them, flip where lower is better.** Values beyond cut-offs saturate at 0 or 1. Cut-offs are configurable per layer as either percentiles (default p2/p98) or absolute values where domain knowledge exists — "≤ £4,000/m² scores 1, ≥ £12,000/m² scores 0" is more interpretable than a percentile and encodes the *users'* desirable range rather than London's distribution. Cut-offs used are recorded in `meta` per layer. An optional pre-transform (log, sqrt) is available in config but defaults to identity: with sensible cut-offs it is a refinement, not a necessity, and linearity in raw units is the easiest scale to reason about.

The composite score for cell *i* given user weights *w*, over layers where the score is non-null:

```
score(i) = Σ_l  w_l · s_il  /  Σ_l  w_l
```

Renormalizing over non-null layers means a cell missing price data is scored on its remaining layers rather than dropped. **⟨v0.2⟩ Partial-data cells are marked with a cell border** (plus a tooltip note listing missing layers) rather than v0.1's reduced opacity, which would have collided with the user-controllable global layer opacity (§8). Implementation: MapLibre's per-feature `fill-outline-color` hairline first; if too subtle, a companion line layer filtered to partial-data cells.

Weights are sliders in [0, 10]; weight 0 removes a layer from the sum entirely. Known artefact of weighted sums: free trade-off, so enough restaurant density can "compensate" for a terrible commute. Optional per-layer hard floors (client-side mask) remain a v2 candidate; the data model already supports them.

## 8. Frontend

**Stack:** Vite + TypeScript, MapLibre GL JS, no UI framework (Preact if state grows). The grid renders as a MapLibre `fill` layer built in-memory from the columnar artefact; 25k polygons is comfortably within MapLibre's envelope, and recolouring uses `setFeatureState` so weight changes never rebuild geometry. Basemap: a free vector-tile source (OpenFreeMap / Protomaps) in muted greyscale so the heat layer dominates.

**Controls.** One weight slider per layer — with the per-(destination, mode) travel split and per-category crime, the default panel is roughly: price, 4 × travel, restaurants, parks, 4 × crime, schools — each with a "solo" toggle (temporarily zeroes all other weights to inspect one layer). **⟨v0.2⟩ A global heat-layer opacity slider** controls `fill-opacity` so the basemap can be read through the heat map. Recomputation runs on slider input, throttled to animation frames — slider events can fire faster than the screen repaints, so recompute/recolour happens at most once per browser paint (~60 Hz), discarding intermediate values nobody would see; the recompute itself is one pass over flat arrays, well under a frame.

Hover shows a tooltip with composite score and each layer's raw value (and missing-layer notes for partial cells). A perceptually-uniform colour ramp (viridis) maps composite-score percentile for stable visual contrast regardless of weights, with a legend. Weight and opacity state serialize into the URL fragment (`#w=price:7,travel_workA_pt:9,...`) so configurations can be shared as links.

**Out of scope for v1:** address search, drawing custom areas, side-by-side weight-profile comparison, and any mobile-specific layout **⟨v0.2⟩** (basic responsiveness only).

## 9. Pipeline

Python (geopandas, shapely, duckdb for the Price Paid/EPC join, r5py). **⟨v0.2⟩ Docker is recommended, not merely permitted**: r5py requires a JDK ≥ 11 alongside pinned geo-dependencies — the classic "works on one machine" combination. One image (`python:3.12-slim` + OpenJDK 21 via apt + pinned pip requirements), no compose needed since R5 handles both travel modes in-process and there is no second service. Volume mounts: `./cache` (downloaded feeds, OSM extract, the built R5 graph — expensive artefacts survive rebuilds), `config.yaml`, and the output directory. Give the container 8–10 GB RAM for the graph build. A Makefile wraps stage invocations (`make fetch`, `make build`, `make deploy` → `docker run <stage>`); a venv remains viable for anyone who prefers managing the JDK themselves.

Stages, each idempotent and cached so a mid-run failure resumes rather than restarts:

1. `fetch` — Price Paid CSV, EPC bulk extract, police per-category CSVs, Geofabrik London OSM extract, GIAS/Ofsted data, BODS GTFS (buses), rail/tube feed + UK2GTFS conversion.
2. `grid` — build the 250 m BNG grid, clip to boundary, flag residential cells from OSM land use.
3. `layers` — one module per layer emitting `(cell_id, raw_value)`; modules independent and individually re-runnable. The travel module builds the R5 graph (pinned typical-Tuesday date) and computes the four matrices.
4. `score` — apply cut-offs and rescaling, assemble the columnar artefact, validate (score ranges, per-layer null rates under thresholds), and write `grid.json` plus `report.html` with per-layer histograms and mini-maps for eyeballing before deploy.
5. `deploy` — commit the artefact into the frontend repo; GitHub Pages publishes it.

```yaml
destinations:
  - {id: workA, label: "Work A", lat: 51.49, lon: -0.17}
  - {id: workB, label: "Work B", lat: 51.52, lon: -0.10}
travel:
  modes: [public_transport, cycling]
  departure_window: {date: "typical_tuesday", from: "08:00", to: "09:00", statistic: median}
layers:
  price:       {enabled: true, filter: {types: [D, S, T], min_habitable_rooms: 5, min_floor_area_m2: 90},
                cutoffs: {low: 4000, high: 12000}}
  restaurants: {enabled: true, radius_m: 500, cutoffs: {percentile: [2, 98]}}
  parks:       {enabled: true, decay_lambda_m: 500}
  crime:       {enabled: true, categories: [burglary, violence-and-sexual-offences, robbery, vehicle-crime, anti-social-behaviour],
                kernel_bandwidth_m: 400}
  schools:     {enabled: true, radius_m: 1500}
```

No secrets remain in the system **⟨v0.2⟩** — every source is open data and R5 runs locally — so the `.env` machinery from v0.1 is gone.

## 10. Operations

Frontend on GitHub Pages **⟨v0.2⟩**; the artefact is committed as plain JSON and the Pages CDN compresses in transit. The pipeline runs manually on any machine with Docker (a laptop is fine); source-data cadence (Price Paid monthly, police monthly, GTFS feeds rolling, OSM continuous but slow) makes quarterly-to-monthly manual refreshes ample. No monitoring beyond the `score` stage's validation failing loudly. Monorepo: `pipeline/` and `web/`, with the artefact schema documented in `SCHEMA.md` as the interface contract.

## 11. Risks and open questions

The EPC join remains the most fragile data step, now doing double duty (£/m² **and** the 3-bed+ filter); if join rates disappoint, the fallback is median raw price over houses only, with a documented caveat. GTFS sourcing for rail/tube is the main pipeline setup friction, and community feeds can go stale — pin and archive the feeds used per run. The 3-bed+ filter plus 24-month window may leave more null cells than expected outside suburbia; the `report.html` null-rate maps will show whether the observation window needs widening to 36 months. The schools layer's methodology is provisional post-2024 Ofsted reform. Winsorized linear scores are stable across runs only if cut-offs are absolute; percentile cut-offs re-derive each run, so prefer absolute cut-offs once sensible values are known.

Open: final crime-category subset; absolute vs. percentile cut-offs per layer once first-run histograms exist; whether four travel sliders plus four crime sliders make the panel unwieldy (a collapsible group per family is the likely fix).

## 12. v2 candidates (explicitly deferred)

Per-layer hard floors; rent data; noise (DEFRA strategic noise maps, flight paths); council tax band / borough overlays; LSOA census joins (IMD, demographics, per-capita crime denominators); side-by-side weight-profile comparison; address pin + "score this location"; widening to additional destinations.
