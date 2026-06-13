"""Stage 2: build the 250 m BNG grid, clip to the boundary, flag residential cells.

Compute in EPSG:27700 where "250 m square" is coherent; reproject centroids to
WGS84 once for the artefact (spec §3).
"""
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.strtree import STRtree

from .common import BNG, BOUNDARY_PATH, GRID_PATH, PBF_PATH, WGS84, load_config
from .osm import extract_polygons


def build_cells(boundary: shapely.Geometry, cell: int) -> pd.DataFrame:
    minx, miny, maxx, maxy = boundary.bounds
    eastings = np.arange(np.floor(minx / cell) * cell, maxx, cell)
    northings = np.arange(np.floor(miny / cell) * cell, maxy, cell)
    ee, nn = (a.ravel() for a in np.meshgrid(eastings, northings))

    # Clip: a cell belongs to London if its centre is inside the boundary.
    centres = shapely.points(ee + cell / 2, nn + cell / 2)
    shapely.prepare(boundary)
    inside = shapely.contains(boundary, centres)
    ee, nn = ee[inside].astype(int), nn[inside].astype(int)

    to_wgs = Transformer.from_crs(BNG, WGS84, always_xy=True)
    lon, lat = to_wgs.transform(ee + cell / 2, nn + cell / 2)
    return pd.DataFrame(
        {
            "cell_id": [f"{e}_{n}" for e, n in zip(ee, nn)],
            "easting": ee,
            "northing": nn,
            "lon": np.round(lon, 5),
            "lat": np.round(lat, 5),
        }
    )


def coverage(cells: pd.DataFrame, polygons: gpd.GeoDataFrame, cell: int) -> np.ndarray:
    """Fraction of each cell covered by the given polygons."""
    boxes = shapely.box(
        cells.easting.values,
        cells.northing.values,
        cells.easting.values + cell,
        cells.northing.values + cell,
    )
    polys = polygons.geometry.values
    cell_idx, poly_idx = STRtree(polys).query(boxes, predicate="intersects")
    pieces = shapely.intersection(boxes[cell_idx], polys[poly_idx])

    cov = np.zeros(len(cells))
    # Union per cell so overlapping polygons (a park inside a heath) don't double-count.
    grouped = pd.Series(pieces).groupby(cell_idx)
    for ci, group in grouped:
        cov[ci] = shapely.union_all(group.values).area / cell**2
    return cov


def main() -> None:
    cfg = load_config()
    cell = cfg["grid"]["cell_size_m"]

    boundary = gpd.read_file(BOUNDARY_PATH).to_crs(BNG).union_all()
    cells = build_cells(boundary, cell)
    print(f"grid: {len(cells)} cells inside Greater London")

    # Request the parks group too: one OSM parse serves both this stage and the layer.
    groups = extract_polygons(
        PBF_PATH,
        {
            "nonres": cfg["grid"]["non_residential"]["tags"],
            "parks": cfg["layers"]["parks"]["include_tags"],
        },
    )
    # Spec §3: flag cells with no housing stock — only cells completely covered
    # by non-residential land use are excluded.
    threshold = cfg["grid"]["non_residential"]["coverage_threshold"]
    nonres_cov = coverage(cells, groups["nonres"], cell)
    cells["residential"] = nonres_cov < threshold
    cells["nonres_coverage"] = np.round(nonres_cov, 3)  # kept for debugging
    print(
        f"grid: {cells.residential.sum()} residential "
        f"({cells.residential.mean():.0%}) at coverage threshold {threshold}"
    )

    cells.to_parquet(GRID_PATH)
    print(f"grid: wrote {GRID_PATH.name}")


if __name__ == "__main__":
    main()
