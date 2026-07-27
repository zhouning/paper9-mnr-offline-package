from pathlib import Path
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC))

from farmland_mpc.block_definition import classify_parcel  # noqa: E402
from farmland_mpc.county_env import FARMLAND, FOREST, _classify_type  # noqa: E402
from farmland_mpc.landuse import (  # noqa: E402
    CURRENT_LAND_USE_SCHEME,
    LEGACY_LAND_USE_SCHEME,
    LandUseCodeError,
    analyse_land_use_codes,
    classify_land_use,
)
from farmland_mpc.shapefile_io import (  # noqa: E402
    DEFAULT_FARM_DLBM,
    DEFAULT_FOREST_DLBM,
)


@pytest.mark.parametrize("code", ["0101", "0102", "0103", "0103A"])
def test_current_third_survey_farmland_codes(code):
    assert classify_land_use(code) == "farmland"
    assert classify_parcel(code) == "farmland"
    assert _classify_type(code) == FARMLAND


@pytest.mark.parametrize(
    "code", ["0301", "0302", "0303", "0304", "0305", "0306", "0307", "0301A"]
)
def test_current_third_survey_forest_codes(code):
    assert classify_land_use(code) == "forest"
    assert classify_parcel(code) == "forest"
    assert _classify_type(code) == FOREST


@pytest.mark.parametrize("code", ["0201", "0202", "0203", "0204"])
def test_current_third_survey_orchard_codes(code):
    assert classify_land_use(code) == "orchard"


def test_current_water_code_is_a_barrier_not_swappable():
    assert classify_land_use("1104") == "barrier"
    assert classify_parcel("1104") == "barrier"
    assert _classify_type("1104") == 0


def test_current_code_report_records_scheme_counts_and_categories():
    report = analyse_land_use_codes(
        ["0103", "0103", "0301", "1104", "0201"],
        require_farmland=True,
        require_forest=True,
    )

    assert report.scheme == CURRENT_LAND_USE_SCHEME
    assert report.code_counts == {
        "0103": 2,
        "0201": 1,
        "0301": 1,
        "1104": 1,
    }
    assert report.category_counts == {
        "barrier": 1,
        "farmland": 2,
        "forest": 1,
        "orchard": 1,
    }


def test_legacy_three_digit_test_data_remains_supported():
    report = analyse_land_use_codes(
        ["011", "013", "031", "203"],
        require_farmland=True,
        require_forest=True,
    )

    assert report.scheme == LEGACY_LAND_USE_SCHEME
    assert classify_land_use("011") == "farmland"
    assert classify_land_use("031") == "forest"


def test_mixed_current_and_legacy_swappable_codes_are_rejected():
    with pytest.raises(LandUseCodeError, match="mixed"):
        analyse_land_use_codes(
            ["0103", "031"],
            require_farmland=True,
            require_forest=True,
        )


@pytest.mark.parametrize(
    ("codes", "message"),
    [
        (["0301", "1104"], "farmland"),
        (["0103", "1104"], "forest"),
    ],
)
def test_missing_swappable_class_is_rejected(codes, message):
    with pytest.raises(LandUseCodeError, match=message):
        analyse_land_use_codes(
            codes,
            require_farmland=True,
            require_forest=True,
        )


def test_optimized_output_defaults_use_current_standard_codes():
    assert DEFAULT_FARM_DLBM == "0101"
    assert DEFAULT_FOREST_DLBM == "0301"
