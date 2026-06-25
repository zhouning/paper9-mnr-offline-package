from pathlib import Path
import sys

import geopandas as gpd
from shapely.geometry import Polygon


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC))


def test_manifest_stage_table_handles_dry_run_without_log_columns():
    from paper9_mnr.notebook_utils import manifest_stage_table

    manifest = {
        "dry_run": True,
        "status": "dry-run",
        "stages": [
            {
                "stage": "prepare",
                "command": "python -m farmland_mpc.cli prepare",
                "status": "dry-run",
                "returncode": 0,
            }
        ],
    }

    table = manifest_stage_table(manifest)

    assert table.to_dict("records") == [
        {
            "stage": "prepare",
            "status": "dry-run",
            "returncode": 0,
            "command": "python -m farmland_mpc.cli prepare",
        }
    ]


def test_manifest_log_entries_skip_stages_without_log_path_and_resolve_app_paths(tmp_path):
    from paper9_mnr.notebook_utils import manifest_log_entries

    manifest = {
        "stages": [
            {"stage": "prepare", "status": "dry-run"},
            {"stage": "plan", "status": "ok", "log_path": "/app/outputs/logs/run-plan.log"},
        ]
    }

    entries = manifest_log_entries(manifest, root=tmp_path)

    assert entries == [
        {
            "stage": "plan",
            "log_path": tmp_path / "outputs/logs/run-plan.log",
            "exists": False,
        }
    ]


def test_leaflet_map_html_is_self_contained_iframe(tmp_path):
    from paper9_mnr.notebook_utils import leaflet_map_html

    gdf = gpd.GeoDataFrame(
        {"BSM": ["A1"], "DLBM": ["0101"], "CHG_FLAG": [1]},
        geometry=[Polygon([(116.0, 40.0), (116.01, 40.0), (116.01, 40.01), (116.0, 40.01)])],
        crs="EPSG:4326",
    )
    output_path = tmp_path / "map.html"

    iframe = leaflet_map_html(
        [
            {
                "name": "Test parcels",
                "gdf": gdf,
                "popup_fields": ["BSM", "DLBM", "CHG_FLAG"],
                "color_field": "CHG_FLAG",
                "color_map": {1: "#2f6f4e"},
            }
        ],
        title="Offline Paper9 Map",
        output_path=output_path,
    )

    document = output_path.read_text(encoding="utf-8")
    assert "<iframe" in iframe
    assert "srcdoc=" in iframe
    assert "Test parcels" in document
    assert "Offline Paper9 Map" in document
    assert "L.geoJSON" in document
    assert "<script src=" not in document
    assert "<link rel=" not in document
