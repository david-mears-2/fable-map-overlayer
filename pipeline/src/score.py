"""Stage 4: normalize, assemble the columnar artefact, validate, report (spec §7, §9).

Reads every layer present in cache/layers/, applies winsorized linear rescaling
between configured cut-offs (absolute, or percentiles of the residential non-null
distribution), and writes output/grid.json plus report.html for eyeballing.
"""
import base64
import datetime as dt
import io
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .common import GRID_PATH, LAYERS_DIR, OUTPUT, PBF_PATH, load_config

# Per-layer artefact metadata (artefact schema, spec §4). Grows with each new layer.
LAYER_META = {
    "parks": {
        "label": "Park access (gravity score)",
        "direction": "higher_better",
        "source": "OpenStreetMap (Geofabrik Greater London extract)",
        "rawUnit": "",
    },
    "restaurants": {
        "label": "Restaurants within 500 m",
        "direction": "higher_better",
        "source": "OpenStreetMap (Geofabrik Greater London extract)",
        "rawUnit": "venues",
    },
}


def resolve_cutoffs(cfg: dict, values: np.ndarray) -> tuple[float, float]:
    spec = cfg.get("cutoffs", {"percentile": [2, 98]})
    if "percentile" in spec:
        lo, hi = np.percentile(values, spec["percentile"])
    else:
        lo, hi = spec["low"], spec["high"]
    return round(float(lo), 2), round(float(hi), 2)


def winsorized_scores(raw: pd.Series, low: float, high: float, direction: str) -> pd.Series:
    s = ((raw - low) / (high - low)).clip(0, 1)
    if direction == "lower_better":
        s = 1 - s
    return s.round(3)


def validate(cfg: dict, grid: pd.DataFrame, layers: dict) -> None:
    checks = cfg["validation"]
    n = len(grid)
    lo, hi = checks["cell_count"]
    assert lo <= n <= hi, f"cell count {n} outside [{lo}, {hi}]"
    frac = grid.residential.mean()
    lo, hi = checks["residential_fraction"]
    assert lo <= frac <= hi, f"residential fraction {frac:.2f} outside [{lo}, {hi}]"
    res = grid.residential.values
    for layer_id, data in layers.items():
        scores = np.array([s if s is not None else np.nan for s in data["scores"]], dtype=float)
        null_rate = np.isnan(scores[res]).mean()
        assert null_rate <= checks["max_null_rate"], (
            f"{layer_id}: null rate {null_rate:.2f} among residential cells "
            f"exceeds {checks['max_null_rate']}"
        )
        valid = scores[~np.isnan(scores)]
        assert len(valid) and valid.min() >= 0 and valid.max() <= 1, f"{layer_id}: scores outside [0, 1]"
    print(f"score: validation passed ({n} cells, {frac:.0%} residential)")


def fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def report_section(layer_id: str, meta: dict, raw: pd.Series, scores: pd.Series, grid: pd.DataFrame) -> str:
    res = grid.residential.values
    null_rate = raw[res].isna().mean()

    fig, axes = plt.subplots(1, 2, figsize=(9, 3))
    raw.dropna().hist(bins=60, ax=axes[0], color="#31688e")
    axes[0].set_title("raw")
    axes[0].set_xlabel(meta["rawUnit"] or "raw value")
    scores.dropna().hist(bins=60, ax=axes[1], color="#35b779")
    axes[1].set_title("score")
    axes[1].set_xlabel("score (1 = desirable)")
    for ax in axes:
        ax.set_ylabel("cells")
    hist_b64 = fig_to_b64(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(grid.lon, grid.lat, c=scores.fillna(-0.1), cmap="viridis", s=1.2, vmin=0, vmax=1)
    ax.set_aspect(1 / np.cos(np.radians(51.5)))
    ax.set_title(f"{meta['label']} — score")
    ax.axis("off")
    map_b64 = fig_to_b64(fig)

    return f"""
    <section>
      <h2>{meta["label"]} <code>{layer_id}</code></h2>
      <p>cutoffs [{meta["cutoffs"]["low"]}, {meta["cutoffs"]["high"]}] ·
         direction {meta["direction"]} ·
         null rate (residential) {null_rate:.1%}</p>
      <img src="data:image/png;base64,{hist_b64}" />
      <img src="data:image/png;base64,{map_b64}" />
    </section>"""


def main() -> None:
    cfg = load_config()
    grid = pd.read_parquet(GRID_PATH)
    vintage = dt.datetime.fromtimestamp(PBF_PATH.stat().st_mtime).strftime("%Y-%m")

    layer_files = sorted(LAYERS_DIR.glob("*.parquet"))
    if not layer_files:
        raise SystemExit("no layer outputs in cache/layers/ — run `make layers` first")

    layers_out: dict = {}
    meta_out: list = []
    sections: list = []
    for path in layer_files:
        layer_id = path.stem
        meta = dict(LAYER_META[layer_id])
        df = grid[["cell_id", "residential"]].merge(pd.read_parquet(path), on="cell_id", how="left")
        raw = df.raw.where(df.residential, np.nan)  # non-residential cells carry null

        low, high = resolve_cutoffs(cfg["layers"][layer_id], raw.dropna().values)
        scores = winsorized_scores(raw, low, high, meta["direction"])
        meta.update(id=layer_id, vintage=vintage, cutoffs={"low": low, "high": high})

        to_null = lambda s: [None if pd.isna(v) else v for v in s]
        layers_out[layer_id] = {"scores": to_null(scores), "raw": to_null(raw)}
        meta_out.append(meta)
        sections.append(report_section(layer_id, meta, raw, scores, grid))
        print(f"score: {layer_id}: cutoffs [{low}, {high}]")

    validate(cfg, grid, layers_out)

    artefact = {
        "meta": {
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "cellSizeM": cfg["grid"]["cell_size_m"],
            "computeCrs": "EPSG:27700",
            "layers": meta_out,
        },
        "cellIds": grid.cell_id.tolist(),
        "centroids": [[lon, lat] for lon, lat in zip(grid.lon, grid.lat)],
        "residential": grid.residential.tolist(),
        "layers": layers_out,
    }

    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / "grid.json"
    out.write_text(json.dumps(artefact, separators=(",", ":")))
    print(f"score: wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")

    report = OUTPUT / "report.html"
    report.write_text(
        "<!doctype html><meta charset=utf-8><title>pipeline report</title>"
        "<style>body{font-family:monospace;max-width:1000px;margin:2rem auto}"
        "img{max-width:100%}</style>"
        f"<h1>pipeline report — {artefact['meta']['generated']}</h1>"
        f"<p>{len(grid)} cells · {grid.residential.mean():.0%} residential · OSM vintage {vintage}</p>"
        + "".join(sections)
    )
    print(f"score: wrote {report}")


if __name__ == "__main__":
    main()
