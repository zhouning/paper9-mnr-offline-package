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
    monkeypatch.setenv("PAPER9_IMAGE_REF", "paper9-mnr-offline:paper9v2-2.0.0-amd64")
    config = {"algorithm": {"name": "paper9v2", "version": "2.0.0"}}

    metadata = module._build_run_metadata(config)

    assert metadata["package_version"] == "0.2.0"
    assert metadata["algorithm_name"] == "paper9v2"
    assert metadata["algorithm_version"] == "2.0.0"
    assert metadata["image_ref"] == "paper9-mnr-offline:paper9v2-2.0.0-amd64"
