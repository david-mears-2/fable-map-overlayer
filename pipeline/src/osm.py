"""Shared OSM polygon extractor.

Parses the .pbf once for any number of named tag groups (parks, non-residential
land use, later restaurants' context) and caches each group as GeoParquet in BNG.
The parse is the expensive step — two passes for multipolygon assembly — so
callers request every group they need in one call; cached groups are never
re-parsed.
"""
import osmium
import osmium.geom
import shapely
import geopandas as gpd

from .common import BNG, CACHE, WGS84

TagGroups = dict[str, dict[str, list[str]]]  # group name -> tag key -> values


class _AreaCollector(osmium.SimpleHandler):
    def __init__(self, groups: TagGroups):
        super().__init__()
        self.matchers = {
            name: {k: set(vs) for k, vs in tags.items()} for name, tags in groups.items()
        }
        self.wkb_factory = osmium.geom.WKBFactory()
        self.collected: dict[str, list[tuple[bytes, str]]] = {n: [] for n in groups}

    def area(self, a: osmium.osm.Area) -> None:
        matched = []
        for name, matcher in self.matchers.items():
            for key, values in matcher.items():
                v = a.tags.get(key)
                if v in values:
                    matched.append((name, f"{key}={v}"))
                    break
        if not matched:
            return
        try:
            wkb = bytes.fromhex(self.wkb_factory.create_multipolygon(a))
        except RuntimeError:
            return  # broken multipolygon in source data — skip
        for name, tag in matched:
            self.collected[name].append((wkb, tag))


def extract_polygons(pbf_path, groups: TagGroups) -> dict[str, gpd.GeoDataFrame]:
    paths = {name: CACHE / f"osm_{name}.parquet" for name in groups}
    missing = {name: tags for name, tags in groups.items() if not paths[name].exists()}

    if missing:
        print(f"osm: parsing {pbf_path.name} for groups: {', '.join(missing)}")
        collector = _AreaCollector(missing)
        collector.apply_file(str(pbf_path), locations=True)
        for name, rows in collector.collected.items():
            geoms = shapely.from_wkb([wkb for wkb, _ in rows])
            gdf = gpd.GeoDataFrame(
                {"tag": [tag for _, tag in rows]}, geometry=geoms, crs=WGS84
            ).to_crs(BNG)
            gdf.to_parquet(paths[name])
            print(f"osm: {name}: {len(gdf)} polygons cached")

    return {name: gpd.read_parquet(path) for name, path in paths.items()}
