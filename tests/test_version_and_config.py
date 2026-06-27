from pathlib import Path

import pytest

import paper9_mnr
from paper9_mnr.config import ConfigError, load_config, validate_config
from paper9_mnr.version import ALGORITHM_NAME, ALGORITHM_VERSION, PACKAGE_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_version_constants_define_paper9v2_release():
    assert PACKAGE_VERSION == "0.2.0"
    assert paper9_mnr.__version__ == PACKAGE_VERSION
    assert ALGORITHM_NAME == "paper9v2"
    assert ALGORITHM_VERSION == "2.0.0"


def test_paper9v2_no_net_loss_config_validates_with_cultivated_area_floor_only():
    config = load_config(PACKAGE_ROOT / "configs/paper9v2_no_net_loss_authority_slope.yml")

    validate_config(config)

    constraints = config["planning"]["constraints"]
    assert config["algorithm"] == {"name": ALGORITHM_NAME, "version": ALGORITHM_VERSION}
    assert constraints["cultivated_area_floor_delta_ha"] == 0
    assert "baimu_area_floor_delta_ha" not in constraints


def test_paper9v2_config_requires_cultivated_area_floor_delta():
    config = load_config(PACKAGE_ROOT / "configs/paper9v2_no_net_loss_authority_slope.yml")
    del config["planning"]["constraints"]["cultivated_area_floor_delta_ha"]

    with pytest.raises(ConfigError, match="planning.constraints.cultivated_area_floor_delta_ha"):
        validate_config(config)


def test_paper9v2_requires_matching_algorithm_version():
    config = load_config(PACKAGE_ROOT / "configs/paper9v2_no_net_loss_authority_slope.yml")
    config["algorithm"]["version"] = "2.0.1"

    with pytest.raises(ConfigError, match="algorithm.version must be"):
        validate_config(config)
