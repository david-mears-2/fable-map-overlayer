# `grid.json` — data artefact schema

The interface contract between `pipeline/` (producer) and `web/` (consumer), per
spec §4. Either side may be rewritten independently as long as this holds.
`web/scripts/generate-dummy-grid.mjs` produces the same shape with synthetic values.

Columnar layout: every per-cell field is a parallel array indexed by cell position —
cell *i* is row *i* of every array.

```jsonc
{
  "meta": {
    "generated": "2026-06-13T01:15:01+00:00", // ISO 8601, UTC
    "cellSizeM": 250,
    "computeCrs": "EPSG:27700",
    "layers": [
      // one entry per layer, order = control-panel order
      {
        "id": "parks",                          // key into top-level "layers"
        "label": "Park access (gravity score)", // shown in panel and tooltip
        "direction": "higher_better",           // or "lower_better"; applied by the
                                                // pipeline — scores are ALWAYS 1=desirable
        "source": "OpenStreetMap (Geofabrik Greater London extract)",
        "vintage": "2026-06",                   // source-data date, YYYY-MM
        "cutoffs": { "low": 2.02, "high": 12.8 }, // winsorization bounds used (raw units)
        "rawUnit": ""                           // tooltip suffix; "" for unitless
      }
    ]
  },
  "cellIds": ["503500_155750", "..."],   // "<easting>_<northing>" of the cell's
                                         // south-west corner in EPSG:27700
  "centroids": [[-0.456, 51.29], "..."], // WGS84 [lon, lat], 5 dp (~1 m)
  "residential": [true, "..."],          // false = no housing stock; rendered grey,
                                         // all its layer values are null
  "layers": {
    "parks": {
      "scores": [0.14, null, "..."],     // [0,1], 1 desirable; null = no data
      "raw": [3.49, null, "..."]         // human-readable value for tooltips
    }
  }
}
```

Invariants the frontend relies on:

- `cellIds`, `centroids`, `residential`, and every `scores`/`raw` array have equal length.
- Every `meta.layers[].id` exists as a key in `layers`, and vice versa.
- Non-residential cells carry `null` in every layer.
- `scores` are already direction-corrected and winsorized to [0, 1]; the frontend
  never inspects `direction` or `cutoffs` for computation (display only).
- Cell geometry is reconstructed client-side by reprojecting the EPSG:27700 cell
  corners derived from `cellIds` + `cellSizeM`; no polygons are shipped.
  `centroids` are display conveniences (initial view fitting, future features),
  not geometry sources.
