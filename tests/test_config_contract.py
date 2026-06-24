from pathlib import Path
import sys

import pytest
import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC))

from paper9_mnr.config import ConfigError, load_config, reward_change_requires_resample_train, validate_config


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _minimal_valid_config() -> dict:
    return {
        "project": {"name": "mnr-paper9-county-demo"},
        "data": {
            "dltb": "data/input/DLTB_with_authority_slope.gpkg",
            "dem": "data/input/DEM_placeholder.tif",
            "prepared_dir": "data/working/prepared",
        },
        "fields": {
            "dlbm": "DLBM",
            "qsdwdm": "QSDWDM",
            "bsm": "BSM",
        },
        "slope": {"source": "field", "field": "slope_mean"},
        "outputs": {
            "plan_dir": "outputs/plan",
            "optimized_vector": "outputs/plan/DLTB_optimized.gpkg",
        },
        "sampling": {"n_episodes": 2, "n_states": 3, "n_actions": 4, "seed": 0},
        "training": {"n_members": 1, "epochs": 2, "patience": 1, "lambda_rank": 5.0},
        "planning": {"horizon": 2, "top_k": 3, "n_episodes": 1},
        "reward": {
            "slope_weight": 4100.0,
            "cont_weight": 600.0,
            "baimu_weight": 2300.0,
            "baimu_bonus": 9.0,
            "baimu_area_penalty": 3100.0,
        },
        "workflow": {"force_resample_and_retrain_on_reward_change": True},
    }


def test_valid_authority_slope_config_loads_and_validates(tmp_path):
    path = _write_yaml(tmp_path / "valid.yml", _minimal_valid_config())

    config = load_config(path)
    validate_config(config)

    assert config["slope"]["source"] == "field"
    assert config["slope"]["field"] == "slope_mean"


def test_authority_slope_field_is_required_for_real_data_configs(tmp_path):
    cfg = _minimal_valid_config()
    cfg["slope"] = {"source": "field"}
    path = _write_yaml(tmp_path / "bad.yml", cfg)

    with pytest.raises(ConfigError, match="slope.field"):
        validate_config(load_config(path))


def test_reward_change_defaults_to_resample_and_retrain(tmp_path):
    cfg = _minimal_valid_config()
    cfg["reward_profiles"] = {
        "business_realism": {
            "description": "Adds three-zone-three-line and soil-quality terms.",
            "requires_resample_train": True,
            "reward": {"slope_weight": 3500.0, "cont_weight": 900.0},
        }
    }
    path = _write_yaml(tmp_path / "calibration.yml", cfg)

    config = load_config(path)
    validate_config(config)

    assert reward_change_requires_resample_train(config, "business_realism") is True


def test_disabling_resample_retrain_for_reward_change_is_rejected(tmp_path):
    cfg = _minimal_valid_config()
    cfg["workflow"]["force_resample_and_retrain_on_reward_change"] = False
    path = _write_yaml(tmp_path / "unsafe.yml", cfg)

    with pytest.raises(ConfigError, match="Reward changes must rerun sample and train"):
        validate_config(load_config(path))

