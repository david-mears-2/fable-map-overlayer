"""Restaurants layer: count of amenity=restaurant|cafe|pub within 500 m of each
cell centroid (spec §5). The circular window overlaps neighbouring cells, which
removes checkerboard noise from point clusters straddling cell boundaries.
"""
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

from ..common import BNG, BOUNDARY_PATH, GRID_PATH, LAYERS_DIR, PBF_PATH, load_config, region_pbf


def main() -> None:
    from ..osm import extract_points

    cfg_all = load_config()
    cfg = cfg_all["layers"]["restaurants"]
    grid = pd.read_parquet(GRID_PATH)
    cell = 250
    centres = shapely.points(grid.easting.values + cell / 2, grid.northing.values + cell / 2)

    # Source venues from London plus bordering extracts so edge cells count venues
    # just across the boundary (the London extract is boundary-clipped). Clip to a
    # radius buffer around London: venues farther out can reach no cell.
    pbfs = [PBF_PATH] + [region_pbf(r) for r in cfg_all["osm"]["buffer_regions"]]
    venues = extract_points(pbfs, {"restaurants": cfg["include_tags"]}, cache_tag="_buffered")["restaurants"]
    region = gpd.read_file(BOUNDARY_PATH).to_crs(BNG).union_all().buffer(cfg["radius_m"])
    venues = venues[venues.geometry.intersects(region)]
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
