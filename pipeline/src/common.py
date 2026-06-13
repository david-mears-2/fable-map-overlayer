from pathlib import Path

import requests
import yaml

PIPELINE_DIR = Path(__file__).resolve().parent.parent
CACHE = PIPELINE_DIR / "cache"
OUTPUT = PIPELINE_DIR / "output"

BNG = "EPSG:27700"
WGS84 = "EPSG:4326"

GEOFABRIK = "https://download.geofabrik.de/europe/united-kingdom/england/{}-latest.osm.pbf"

PBF_PATH = CACHE / "greater-london-latest.osm.pbf"
BOUNDARY_PATH = CACHE / "boundary.geojson"
GRID_PATH = CACHE / "grid.parquet"
LAYERS_DIR = CACHE / "layers"


def region_pbf(region: str) -> Path:
    """Local cache path for a Geofabrik England sub-region extract."""
    return CACHE / f"{region}-latest.osm.pbf"


def load_config() -> dict:
    return yaml.safe_load((PIPELINE_DIR / "config.yaml").read_text())


def download(url: str, dest: Path) -> Path:
    """Idempotent download: an existing non-empty file is trusted (spec §9)."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached: {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    print(f"  done: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest
