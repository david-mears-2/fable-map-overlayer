"""Parks layer: gravity accessibility score (spec §5).

Per cell: sum over parks p of log(1 + area_ha(p)) * exp(-dist(centroid, p) / lambda).
The log encodes diminishing returns in park size, the exponential rewards proximity
continuously, and several nearby parks accumulate. Distance is to the park edge
(zero inside), so large parks are not penalised by their own extent.
"""
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

from ..common import BNG, BOUNDARY_PATH, GRID_PATH, LAYERS_DIR, PBF_PATH, load_config, region_pbf
from ..osm import extract_polygons


def main() -> None:
    cfg_all = load_config()
    cfg = cfg_all["layers"]["parks"]
    lam = cfg["decay_lambda_m"]
    cutoff = cfg["cutoff_distance_m"]

    grid = pd.read_parquet(GRID_PATH)
    cell = 250
    centres = shapely.points(grid.easting.values + cell / 2, grid.northing.values + cell / 2)

    # Source green space from London plus bordering extracts so cells near the
    # boundary see parks just outside London (within the gravity cutoff), not a
    # data-blank edge. Parks beyond cutoff of London can reach no cell, so clip
    # to a boundary buffer to keep the distance loop small.
    pbfs = [PBF_PATH] + [region_pbf(r) for r in cfg_all["osm"]["buffer_regions"]]
    parks = extract_polygons(pbfs, {"parks": cfg["include_tags"]}, cache_tag="_buffered")["parks"]
    region = gpd.read_file(BOUNDARY_PATH).to_crs(BNG).union_all().buffer(cutoff)
    parks = parks[parks.geometry.intersects(region)]

    # Dissolve overlapping and adjacent polygons into discrete contiguous green
    # spaces. OSM often maps the same ground under several tags (a nature reserve
    # also tagged natural=wood); summing both would count that area twice. Dissolving
    # also makes log(1 + area) apply to true contiguous area rather than to each
    # arbitrarily-split piece.
    geoms = shapely.get_parts(shapely.unary_union(parks.geometry.values))
    areas = shapely.area(geoms)
    geoms, areas = geoms[areas >= cfg["min_area_m2"]], areas[areas >= cfg["min_area_m2"]]
    weights = np.log1p(areas / 10_000)  # log(1 + hectares), from true (unsimplified) area
    # ~10 m simplification: invisible against a 500 m decay, much cheaper distances.
    geoms = shapely.simplify(geoms, 10)
    print(f"parks: {len(geoms)} discrete green spaces >= {cfg['min_area_m2']} m²")

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
