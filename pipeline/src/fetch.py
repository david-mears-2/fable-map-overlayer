"""Stage 1: download source data (spec §9). Parks slice: OSM extract + boundary."""
import json

from .common import BOUNDARY_PATH, CACHE, PBF_PATH, download

PBF_URL = "https://download.geofabrik.de/europe/united-kingdom/england/greater-london-latest.osm.pbf"

# ONS Open Geography Portal: Regions (December 2024), full-resolution clipped (BFC).
BOUNDARY_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Regions_December_2024_Boundaries_EN_BFC/FeatureServer/0/query"
    "?where=RGN24NM%3D%27London%27&outFields=RGN24NM&f=geojson&outSR=4326"
)


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    print("fetch: Greater London OSM extract (Geofabrik)")
    download(PBF_URL, PBF_PATH)
    print("fetch: Greater London boundary (ONS Open Geography)")
    download(BOUNDARY_URL, BOUNDARY_PATH)

    boundary = json.loads(BOUNDARY_PATH.read_text())
    if not boundary.get("features"):
        BOUNDARY_PATH.unlink()
        raise SystemExit("boundary download returned no features — endpoint changed?")
    print(f"fetch: boundary ok ({len(boundary['features'])} feature)")


if __name__ == "__main__":
    main()
