import importlib.util
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _load_run_full_pipeline_module():
    module_path = PACKAGE_ROOT / "scripts" / "run_full_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_full_pipeline", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_run_metadata_uses_config_algorithm_and_image_ref(monkeypatch):
    module = _load_run_full_pipeline_module()
    monkeypatch.setenv("PAPER9_IMAGE_REF", "paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64")
    config = {"algorithm": {"name": "paper9v2", "version": "2.2.3"}}

    metadata = module._build_run_metadata(config)

    assert metadata["package_version"] == "0.3.3"
    assert metadata["algorithm_name"] == "paper9v2"
    assert metadata["algorithm_version"] == "2.2.3"
    assert metadata["image_ref"] == "paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64"


def test_build_run_metadata_does_not_label_legacy_config_as_paper9v2(monkeypatch):
    module = _load_run_full_pipeline_module()
    monkeypatch.delenv("PAPER9_IMAGE_REF", raising=False)

    metadata = module._build_run_metadata({})

    assert metadata["package_version"] == "0.3.3"
    assert metadata["algorithm_name"] == ""
    assert metadata["algorithm_version"] == ""
    assert metadata["image_ref"] == ""


def test_run_and_audit_scripts_default_to_paper9v2_config():
    run_script = (PACKAGE_ROOT / "scripts/run_full_pipeline.py").read_text(encoding="utf-8")
    audit_script = (PACKAGE_ROOT / "scripts/05_audit.py").read_text(encoding="utf-8")

    assert 'default=str(ROOT / "configs" / "paper9v22_authority_constraints.yml")' in run_script
    assert 'default=str(ROOT / "configs" / "paper9v22_authority_constraints.yml")' in audit_script


def test_build_full_pipeline_commands_append_audit_gate():
    module = _load_run_full_pipeline_module()
    config = {
        "project": {"name": "demo"},
        "data": {
            "dltb": "data/input/DLTB_with_authority_slope.gpkg",
            "dem": "data/input/DEM_placeholder.tif",
            "prepared_dir": "data/working/prepared",
        },
        "fields": {"dlbm": "DLBM", "qsdwdm": "QSDWDM", "bsm": "BSM"},
        "slope": {"source": "field", "field": "slope_mean"},
        "outputs": {"plan_dir": "outputs/plan", "optimized_vector": "outputs/plan/DLTB_optimized.shp"},
        "sampling": {"n_episodes": 1, "n_states": 2, "n_actions": 3, "seed": 0},
        "training": {"n_members": 1, "epochs": 1, "patience": 1, "lambda_rank": 1.0},
        "planning": {
            "horizon": 1,
            "top_k": 1,
            "n_episodes": 1,
            "constraints": {"cultivated_area_floor_delta_ha": 0},
        },
        "workflow": {"force_resample_and_retrain_on_reward_change": True},
    }

    commands = module.build_full_pipeline_commands(
        config,
        config_path="configs/paper9v22_authority_constraints.yml",
        python_executable="/opt/paper9/bin/python",
    )

    assert list(commands) == ["prepare", "sample", "train", "plan", "audit"]
    assert commands["audit"] == [
        "/opt/paper9/bin/python",
        "scripts/05_audit.py",
        "configs/paper9v22_authority_constraints.yml",
        "--write",
    ]
