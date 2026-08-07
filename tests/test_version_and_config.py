from pathlib import Path

import pytest

import paper9_mnr
from paper9_mnr.config import ConfigError, load_config, validate_config
from paper9_mnr.version import ALGORITHM_NAME, ALGORITHM_VERSION, PACKAGE_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_version_constants_define_paper9v2_release():
    assert PACKAGE_VERSION == "0.4.0"
    assert paper9_mnr.__version__ == PACKAGE_VERSION
    assert ALGORITHM_NAME == "paper9v2"
    assert ALGORITHM_VERSION == "2.3.0"


def test_paper9v2_no_net_loss_config_validates_with_cultivated_area_floor_only():
    config = load_config(PACKAGE_ROOT / "configs/paper9v22_authority_constraints.yml")

    validate_config(config)

    constraints = config["planning"]["constraints"]
    assert config["algorithm"] == {"name": ALGORITHM_NAME, "version": "2.2.3"}
    assert config["slope"]["field"] == "slope_mean"
    assert config["outputs"]["optimized_vector"].endswith(".shp")
    assert constraints["cultivated_area_floor_delta_ha"] == 0
    assert "baimu_area_floor_delta_ha" not in constraints


def test_paper9v2_config_requires_cultivated_area_floor_delta():
    config = load_config(PACKAGE_ROOT / "configs/paper9v22_authority_constraints.yml")
    del config["planning"]["constraints"]["cultivated_area_floor_delta_ha"]

    with pytest.raises(ConfigError, match="planning.constraints.cultivated_area_floor_delta_ha"):
        validate_config(config)


def test_paper9v2_config_rejects_negative_cultivated_area_floor_delta():
    config = load_config(PACKAGE_ROOT / "configs/paper9v22_authority_constraints.yml")
    config["planning"]["constraints"]["cultivated_area_floor_delta_ha"] = -0.01

    with pytest.raises(ConfigError, match="must be >= 0"):
        validate_config(config)


def test_paper9v2_config_rejects_non_shapefile_optimized_vector():
    config = load_config(PACKAGE_ROOT / "configs/paper9v22_authority_constraints.yml")
    config["outputs"]["optimized_vector"] = "outputs/plan_paper9v2_no_net_loss/DLTB_optimized.gpkg"

    with pytest.raises(ConfigError, match="optimized_vector must end with .shp"):
        validate_config(config)


def test_paper9v2_requires_matching_algorithm_version():
    config = load_config(PACKAGE_ROOT / "configs/paper9v22_authority_constraints.yml")
    config["algorithm"]["version"] = "2.0.1"

    with pytest.raises(ConfigError, match="algorithm.version must be"):
        validate_config(config)


def test_paper9v23_dltb_only_config_records_missing_regulatory_evidence():
    config = load_config(PACKAGE_ROOT / "configs/paper9v23_zhongning_dltb_only.yml")

    validate_config(config)

    assert config["algorithm"] == {"name": "paper9v2", "version": "2.3.0"}
    assert config["input_profile"]["mode"] == "dltb_dem_only"
    assert config["input_profile"]["decision_use"] == "exploratory_technical_validation_only"


def test_paper9v23_dltb_only_rejects_compliance_claim():
    config = load_config(PACKAGE_ROOT / "configs/paper9v23_zhongning_dltb_only.yml")
    config["input_profile"]["decision_use"] = "formal_approval"

    with pytest.raises(ConfigError, match="exploratory_technical_validation_only"):
        validate_config(config)


@pytest.mark.parametrize(
    "config_name",
    ["paper9v23_dongxing_dltb_only.yml", "paper9v23_bishan_dltb_only.yml"],
)
def test_paper9v23_built_in_sample_configs_validate(config_name):
    config = load_config(PACKAGE_ROOT / "configs" / config_name)
    validate_config(config)
    assert config["input_profile"]["mode"] == "dltb_dem_only"
