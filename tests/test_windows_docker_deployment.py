import subprocess
from pathlib import Path

import yaml

from paper9_mnr.config import validate_config

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DOCKER = PACKAGE_ROOT / "deploy/windows-docker/run-paper9v23-docker.ps1"


def test_dockerfile_defaults_to_paper9v23_metadata():
    dockerfile = (PACKAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG PACKAGE_VERSION=0.4.0" in dockerfile
    assert "ARG ALGORITHM_VERSION=2.3.0" in dockerfile
    assert 'io.paper9.input.profile="${ALGORITHM_VERSION}"' not in dockerfile
    assert 'io.paper9.input.profile="dltb_dem_only"' in dockerfile
    assert "PYTHONUTF8=1" in dockerfile
    assert "PAPER9_OFFLINE=1" in dockerfile


def test_windows_docker_wrapper_exposes_v23_datasets_and_contracts():
    script = WINDOWS_DOCKER.read_text(encoding="utf-8-sig")

    assert 'ValidateSet("fuse", "all", "check", "check-config", "dry-run", "run", "audit")' in script
    assert 'ValidateSet("zhongning", "dongxing", "bishan")' in script
    assert 'paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64' in script
    assert 'Platform = "linux/amd64"' in script
    assert 'PAPER9_OFFLINE=1' in script
    assert '"--network", "none"' in script
    assert '"--platform", $Platform' in script
    assert 'county_code = "511011"' in script
    assert 'county_code = "500227"' in script
    assert 'reference_county_code = "500120"' in script
    assert 'DltbSource.EndsWith(".gdb"' in script
    assert "fuse_dltb_dem_county.py" in script
    assert "cmd.exe" not in script.lower()


def test_container_smoke_config_is_valid():
    config_path = PACKAGE_ROOT / "configs/paper9v23_dongxing_container_smoke.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    validate_config(config)
    assert config["sampling"] == {
        "n_episodes": 1,
        "n_states": 2,
        "n_actions": 5,
        "seed": 0,
    }
    assert config["training"]["n_members"] == 1
    assert config["training"]["epochs"] == 1
    assert config["planning"]["horizon"] == 1


def test_container_smoke_script_is_bash_parseable():
    script = PACKAGE_ROOT / "scripts/smoke_paper9v23_container.sh"
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_v23_bundle_script_contains_image_and_asset_manifest():
    script = (
        PACKAGE_ROOT / "deploy/container-runtime/package-paper9v23-image-bundle.sh"
    ).read_text(encoding="utf-8")

    assert "paper9-mnr-offline-paper9v2-2.3.0-legacy-linux-amd64.tar" in script
    assert "datasets/dongxing" in script
    assert "datasets/bishan" in script
    assert "copernicus_glo30_zhongning" in script
    assert "xiangzhen_zhongning.gpkg" in script
    assert '"schema_version": "paper9.container_bundle.v2"' in script
    assert "SHA256SUMS.txt" in script
