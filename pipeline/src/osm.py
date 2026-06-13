"""Shared OSM polygon extractor.

Parses the .pbf once for any number of named tag groups (parks, non-residential
land use, later restaurants' context) and caches each group as GeoParquet in BNG.
The parse is the expensive step — two passes for multipolygon assembly — so
callers request every group they need in one call; cached groups are never
re-parsed.
"""
from pathlib import Path

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
        # group -> list of (osm area id, wkb, tag); the id lets callers dedupe a
        # polygon that appears in more than one extract (see extract_polygons).
        self.collected: dict[str, list[tuple[int, bytes, str]]] = {n: [] for n in groups}

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
            self.collected[name].append((a.id, wkb, tag))


class _PointCollector(osmium.SimpleHandler):
    """Collects matching features as points: tagged nodes directly, tagged areas
    (venues mapped as building outlines) via their centroid."""

    def __init__(self, groups: TagGroups):
        super().__init__()
        self.matchers = {
            name: {k: set(vs) for k, vs in tags.items()} for name, tags in groups.items()
        }
        self.wkb_factory = osmium.geom.WKBFactory()
        self.collected: dict[str, list] = {n: [] for n in groups}

    def _match(self, tags):
        for name, matcher in self.matchers.items():
            for key, values in matcher.items():
                v = tags.get(key)
                if v in values:
                    yield name, f"{key}={v}"
                    break

    def node(self, n: osmium.osm.Node) -> None:
        if not n.tags:
            return
        for name, tag in self._match(n.tags):
            self.collected[name].append((shapely.Point(n.location.lon, n.location.lat), tag))

    def area(self, a: osmium.osm.Area) -> None:
        matched = list(self._match(a.tags))
        if not matched:
            return
        try:
            geom = shapely.from_wkb(bytes.fromhex(self.wkb_factory.create_multipolygon(a)))
        except RuntimeError:
            return
        for name, tag in matched:
            self.collected[name].append((shapely.centroid(geom), tag))


def extract_points(pbf_path, groups: TagGroups) -> dict[str, gpd.GeoDataFrame]:
    paths = {name: CACHE / f"osm_pts_{name}.parquet" for name in groups}
    missing = {name: tags for name, tags in groups.items() if not paths[name].exists()}

    if missing:
        print(f"osm: parsing {pbf_path.name} for point groups: {', '.join(missing)}")
        collector = _PointCollector(missing)
        collector.apply_file(str(pbf_path), locations=True)
        for name, rows in collector.collected.items():
            gdf = gpd.GeoDataFrame(
                {"tag": [tag for _, tag in rows]},
                geometry=[pt for pt, _ in rows],
                crs=WGS84,
            ).to_crs(BNG)
            gdf.to_parquet(paths[name])
            print(f"osm: {name}: {len(gdf)} points cached")

    return {name: gpd.read_parquet(path) for name, path in paths.items()}


def extract_polygons(pbf_paths, groups: TagGroups, cache_tag: str = "") -> dict[str, gpd.GeoDataFrame]:
    """Extract tagged polygons from one or more PBF extracts.

    `pbf_paths` may be a single path or a list. When several extracts are given
    (e.g. London plus bordering counties for the green-space buffer), polygons are
    deduped by OSM id: Geofabrik includes a boundary-straddling polygon whole in
    every region it touches, so the same park can appear in multiple files.
    `cache_tag` distinguishes the cache file when a group is extracted with a
    different set of inputs (the buffered parks vs. a London-only build).
    """
    if isinstance(pbf_paths, (str, Path)):
        pbf_paths = [pbf_paths]

    paths = {name: CACHE / f"osm_{name}{cache_tag}.parquet" for name in groups}
    missing = {name: tags for name, tags in groups.items() if not paths[name].exists()}

    if missing:
        collected: dict[str, dict[int, tuple[bytes, str]]] = {n: {} for n in missing}
        for pbf in pbf_paths:
            print(f"osm: parsing {pbf.name} for groups: {', '.join(missing)}")
            collector = _AreaCollector(missing)
            collector.apply_file(str(pbf), locations=True)
            for name, rows in collector.collected.items():
                for oid, wkb, tag in rows:
                    collected[name].setdefault(oid, (wkb, tag))
        for name, items in collected.items():
            geoms = shapely.from_wkb([wkb for wkb, _ in items.values()])
            gdf = gpd.GeoDataFrame(
                {"tag": [tag for _, tag in items.values()]}, geometry=geoms, crs=WGS84
            ).to_crs(BNG)
            gdf.to_parquet(paths[name])
            print(f"osm: {name}: {len(gdf)} polygons cached")

    return {name: gpd.read_parquet(path) for name, path in paths.items()}
