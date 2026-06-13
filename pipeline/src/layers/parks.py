"""Parks layer: gravity accessibility score (spec §5).

Per cell: sum over parks p of log(1 + area_ha(p)) * exp(-dist(centroid, p) / lambda).
The log encodes diminishing returns in park size, the exponential rewards proximity
continuously, and several nearby parks accumulate. Distance is to the park edge
(zero inside), so large parks are not penalised by their own extent.
"""
import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

from ..common import GRID_PATH, LAYERS_DIR, PBF_PATH, load_config
from ..osm import extract_polygons


def main() -> None:
    cfg = load_config()["layers"]["parks"]
    lam = cfg["decay_lambda_m"]
    cutoff = cfg["cutoff_distance_m"]

    grid = pd.read_parquet(GRID_PATH)
    cell = 250
    centres = shapely.points(grid.easting.values + cell / 2, grid.northing.values + cell / 2)

    parks = extract_polygons(PBF_PATH, {"parks": cfg["include_tags"]})["parks"]
    parks = parks[parks.geometry.area >= cfg["min_area_m2"]]
    # ~10 m simplification: invisible against a 500 m decay, much cheaper distances.
    geoms = shapely.simplify(parks.geometry.values, 10)
    weights = np.log1p(shapely.area(geoms) / 10_000)  # log(1 + hectares)
    print(f"parks: {len(geoms)} parks >= {cfg['min_area_m2']} m²")

    tree = STRtree(centres)
    score = np.zeros(len(grid))
    for geom, w in zip(geoms, weights):
        minx, miny, maxx, maxy = shapely.bounds(geom)
        candidates = tree.query(shapely.box(minx - cutoff, miny - cutoff, maxx + cutoff, maxy + cutoff))
        if len(candidates) == 0:
            continue
        dist = shapely.distance(centres[candidates], geom)
        near = dist <= cutoff
        score[candidates[near]] += w * np.exp(-dist[near] / lam)

    LAYERS_DIR.mkdir(parents=True, exist_ok=True)
    out = LAYERS_DIR / "parks.parquet"
    pd.DataFrame({"cell_id": grid.cell_id, "raw": np.round(score, 2)}).to_parquet(out)
    print(f"parks: wrote {out.name} (raw range {score.min():.2f}–{score.max():.2f})")


if __name__ == "__main__":
    main()
