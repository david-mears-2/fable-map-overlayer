# London Housing Heat Map

Interactive heat map of Greater London scored on housing desiderata. Full design in
[london-heatmap-spec.md](london-heatmap-spec.md).

**Status: in progress** — frontend with weight sliders, solo toggles, and global
heat opacity; pipeline produces the first real layer (parks, from OSM). The
artefact schema both sides agree on is documented in [SCHEMA.md](SCHEMA.md).

## Frontend

```sh
cd web
npm install
npm run dev        # http://localhost:5173
```

`npm run build` type-checks and produces `web/dist/` for GitHub Pages.
`npm run generate` writes a deterministic dummy `public/grid.json` (4 synthetic
layers) for frontend work without running the pipeline.

## Pipeline

```sh
cd pipeline
make all   # fetch → grid → layers → score → deploy (copies into web/public/)
```

Stages are idempotent and cached under `pipeline/cache/` (spec §9); rerun any
stage alone with `make fetch|grid|layers|score`. The `score` stage validates the
artefact and writes `output/report.html` with per-layer histograms and mini-maps
for eyeballing before deploy. Needs Python 3.12; `make venv` sets everything up.

## Layout

- `web/` — Vite + TypeScript + MapLibre GL frontend (no framework, spec §8)
- `pipeline/` — Python data pipeline (spec §9): `src/fetch.py`, `src/grid.py`,
  one module per layer under `src/layers/`, `src/score.py`
- `web/scripts/generate-dummy-grid.mjs` — dummy artefact generator
