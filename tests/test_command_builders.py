from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC))

from paper9_mnr.config import validate_config
from paper9_mnr.pipeline import (
    build_full_pipeline_commands,
    build_plan_args,
    build_prepare_args,
    build_sample_args,
    build_stage_commands,
    build_train_args,
)


def _config() -> dict:
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
        "slope": {"source": "field", "field": "authority_slope"},
        "outputs": {
            "plan_dir": "outputs/plan",
            "optimized_vector": "outputs/plan/DLTB_optimized.shp",
        },
        "sampling": {"n_episodes": 60, "n_states": 1000, "n_actions": 50, "seed": 7},
        "training": {"n_members": 3, "epochs": 30, "patience": 8, "lambda_rank": 5.0},
        "planning": {
            "horizon": 5,
            "top_k": 50,
            "n_episodes": 1,
            "constraints": {
                "cultivated_area_floor_delta_ha": 0,
                "baimu_area_floor_delta_ha": 0,
            },
        },
        "reward": {
            "slope_weight": 4100.0,
            "cont_weight": 600.0,
            "baimu_weight": 2300.0,
            "baimu_bonus": 9.0,
            "baimu_area_penalty": 3100.0,
        },
        "workflow": {"force_resample_and_retrain_on_reward_change": True},
    }


def _value_after(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_prepare_args_use_authority_slope_field():
    cfg = _config()
    validate_config(cfg)

    args = build_prepare_args(cfg)

    assert _value_after(args, "--slope-method") == "from_field"
    assert _value_after(args, "--slope-field") == "authority_slope"
    assert _value_after(args, "--dlbm-field") == "DLBM"
    assert _value_after(args, "--qsdwdm-field") == "QSDWDM"
    assert _value_after(args, "--bsm-field") == "BSM"


def test_prepare_args_include_admin_reference_layer():
    cfg = _config()
    cfg["data"]["admin_units"] = "data/input/admin_units.gpkg"
    cfg["fields"]["admin_name"] = "XZQMC"

    args = build_prepare_args(cfg)

    assert _value_after(args, "--reference-layer") == "data/input/admin_units.gpkg"
    assert _value_after(args, "--reference-name-field") == "XZQMC"


def test_sample_args_forward_reward_overrides_for_calibration():
    args = build_sample_args(_config())

    assert _value_after(args, "--slope-weight") == "4100.0"
    assert _value_after(args, "--cont-weight") == "600.0"
    assert _value_after(args, "--baimu-weight") == "2300.0"
    assert _value_after(args, "--baimu-bonus") == "9.0"
    assert _value_after(args, "--baimu-area-penalty") == "3100.0"


def test_sample_args_include_paper9v2_cultivated_area_floor_only():
    cfg = _config()
    del cfg["planning"]["constraints"]["baimu_area_floor_delta_ha"]

    args = build_sample_args(cfg)

    assert _value_after(args, "--cultivated-area-floor-delta-ha") == "0"
    assert "--baimu-area-floor-delta-ha" not in args


def test_train_args_use_local_prepared_dir_and_rank_loss():
    args = build_train_args(_config())

    assert _value_after(args, "--prepared-dir") == "data/working/prepared"
    assert _value_after(args, "--lambda-rank") == "5.0"
    assert _value_after(args, "--n-members") == "3"


def test_plan_args_include_no_net_loss_constraints():
    cfg = _config()
    del cfg["planning"]["constraints"]["baimu_area_floor_delta_ha"]

    args = build_plan_args(cfg)

    assert _value_after(args, "--cultivated-area-floor-delta-ha") == "0"
    assert "--baimu-area-floor-delta-ha" not in args
    assert _value_after(args, "--output-shp") == "outputs/plan/DLTB_optimized.shp"


def test_full_stage_commands_keep_sample_and_train_before_plan():
    commands = build_stage_commands(_config())

    assert list(commands) == ["prepare", "sample", "train", "plan"]
    assert commands["sample"][0:2] == ["python", "-m"]
    assert "farmland_mpc.cli" in commands["sample"]
    assert "sample" in commands["sample"]
    assert "train" in commands["train"]
    assert "plan" in commands["plan"]


def test_stage_commands_can_use_current_python_executable():
    commands = build_stage_commands(_config(), python_executable="/opt/conda/envs/paper9/bin/python")

    assert commands["prepare"][0] == "/opt/conda/envs/paper9/bin/python"
    assert commands["sample"][0] == "/opt/conda/envs/paper9/bin/python"
    assert commands["train"][0] == "/opt/conda/envs/paper9/bin/python"
    assert commands["plan"][0] == "/opt/conda/envs/paper9/bin/python"


def test_full_pipeline_commands_append_audit_gate():
    commands = build_full_pipeline_commands(
        _config(),
        config_path="configs/paper9v22_authority_constraints.yml",
        python_executable="/opt/conda/envs/paper9/bin/python",
    )

    assert list(commands) == ["prepare", "sample", "train", "plan", "audit"]
    assert commands["audit"] == [
        "/opt/conda/envs/paper9/bin/python",
        "scripts/05_audit.py",
        "configs/paper9v22_authority_constraints.yml",
        "--write",
    ]
