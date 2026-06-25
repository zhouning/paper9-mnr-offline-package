from pathlib import Path
import sys

import geopandas as gpd
from shapely.geometry import Polygon

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC))

from farmland_mpc.prepare import _labels_from_reference_layer


def test_reference_layer_labels_survive_groupby_sampling(tmp_path):
    dltb = gpd.GeoDataFrame(
        {
            "QSDWDM": ["123456789001", "123456789002"],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
            ],
        },
        crs="EPSG:3857",
    )
    reference = gpd.GeoDataFrame(
        {
            "XZQMC": ["测试村"],
            "geometry": [Polygon([(-1, -1), (4, -1), (4, 2), (-1, 2)])],
        },
        crs="EPSG:3857",
    )
    reference_path = tmp_path / "admin.gpkg"
    reference.to_file(reference_path, driver="GPKG", layer="admin_units")

    labels = _labels_from_reference_layer(
        dltb=dltb,
        qsdwdm_field="QSDWDM",
        reference_layer=reference_path,
        reference_name_field="XZQMC",
        proj_crs="EPSG:3857",
        existing_label_map={"123456789": "123456789"},
    )

    assert labels["123456789"] == "测试村"
