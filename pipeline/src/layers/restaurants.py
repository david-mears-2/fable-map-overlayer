"""Restaurants layer: count of amenity=restaurant|cafe|pub within 500 m of each
cell centroid (spec §5). The circular window overlaps neighbouring cells, which
removes checkerboard noise from point clusters straddling cell boundaries.
"""
import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

from ..common import GRID_PATH, LAYERS_DIR, PBF_PATH, load_config


def main() -> None:
    from ..osm import extract_points

    cfg = load_config()["layers"]["restaurants"]
    grid = pd.read_parquet(GRID_PATH)
    cell = 250
    centres = shapely.points(grid.easting.values + cell / 2, grid.northing.values + cell / 2)

    venues = extract_points(PBF_PATH, {"restaurants": cfg["include_tags"]})["restaurants"]
    print(f"restaurants: {len(venues)} venues ({venues.tag.value_counts().to_dict()})")

    tree = STRtree(venues.geometry.values)
    cell_idx, _ = tree.query(centres, predicate="dwithin", distance=cfg["radius_m"])
    counts = np.bincount(cell_idx, minlength=len(grid))

    LAYERS_DIR.mkdir(parents=True, exist_ok=True)
    out = LAYERS_DIR / "restaurants.parquet"
    pd.DataFrame({"cell_id": grid.cell_id, "raw": counts}).to_parquet(out)
    print(f"restaurants: wrote {out.name} (max {counts.max()} within {cfg['radius_m']} m)")


if __name__ == "__main__":
    main()
