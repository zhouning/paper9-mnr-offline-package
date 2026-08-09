import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pyogrio
import yaml

from paper9_mnr.config import validate_config

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DEPLOY = PACKAGE_ROOT / "deploy/windows-native"


def test_runtime_config_renderer_uses_absolute_data_root(tmp_path):
    data_root = tmp_path / "paper9 data" / "640521"
    runtime_config = tmp_path / "runtime.yml"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            str(PACKAGE_ROOT / "scripts/render_dltb_only_runtime_config.py"),
            "--template",
            str(PACKAGE_ROOT / "configs/paper9v23_zhongning_dltb_only.yml"),
            "--output",
            str(runtime_config),
            "--data-root",
            str(data_root),
        ],
        cwd=PACKAGE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    config = yaml.safe_load(runtime_config.read_text(encoding="utf-8"))
    validate_config(config)
    assert config["runtime"]["data_root"] == str(data_root.resolve())
    assert config["data"]["dltb"] == str(
        data_root.resolve() / "input/DLTB_with_authority_slope.gpkg"
    )
    assert config["data"]["prepared_dir"].startswith(str(data_root.resolve()))
    assert config["outputs"]["plan_dir"].startswith(str(data_root.resolve()))


def test_zhongning_dem_manifest_matches_bundled_tiles():
    dem_dir = PACKAGE_ROOT / "dist/dem/copernicus_glo30_zhongning"
    if not (dem_dir / "DEM_MANIFEST.json").is_file():
        pytest.skip("Offline DEM delivery assets are not present in this source checkout.")
    manifest = json.loads((dem_dir / "DEM_MANIFEST.json").read_text(encoding="utf-8"))

    assert manifest["target_coverage_check"]["county_code"] == "640521"
    assert manifest["target_coverage_check"]["all_target_bounds_covered"] is True
    assert len(manifest["files"]) == 4
    for record in manifest["files"]:
        path = dem_dir / record["file"]
        assert path.stat().st_size == record["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_zhongning_admin_manifest_matches_reference():
    reference_dir = PACKAGE_ROOT / "reference/admin"
    manifest = json.loads(
        (reference_dir / "MANIFEST_ZHONGNING.json").read_text(encoding="utf-8")
    )
    path = reference_dir / "xiangzhen_zhongning.gpkg"

    assert manifest["selection"] == {
        "county_name": "中宁县",
        "county_code": "640521",
    }
    assert path.stat().st_size == manifest["output"]["bytes"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["output"]["sha256"]


def test_built_in_sample_dataset_manifest_matches_files():
    dataset_dir = PACKAGE_ROOT / "dist/datasets"
    manifest_path = dataset_dir / "MANIFEST.json"
    if not manifest_path.is_file():
        pytest.skip("Built-in sample dataset assets are not present in this source checkout.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert [dataset["id"] for dataset in manifest["datasets"]] == ["dongxing", "bishan"]
    for dataset in manifest["datasets"]:
        dltb = PACKAGE_ROOT / dataset["dltb"]["path"]
        if not dltb.is_file():
            dltb = PACKAGE_ROOT / "dist" / dataset["dltb"]["path"]
        assert dltb.stat().st_size > 0
        assert hashlib.sha256(dltb.read_bytes()).hexdigest() == dataset["dltb"]["sha256"]
        info = pyogrio.read_info(dltb, layer=dataset["dltb"]["layer"])
        assert info["features"] == dataset["dltb"]["feature_count"]


def test_windows_wrapper_exposes_portable_dltb_only_workflow():
    script = (WINDOWS_DEPLOY / "run-paper9-windows.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("fuse", "all", "check", "check-config", "dry-run", "run", "audit")' in script
    assert 'ValidateSet("zhongning", "dongxing", "bishan")' in script
    assert 'county_code = "511011"' in script
    assert 'county_code = "500227"' in script
    assert 'reference_county_code = "500120"' in script
    assert '"--dltb-source", $ResolvedDltb' in script
    assert '$ExternalDltbSource = -not [string]::IsNullOrWhiteSpace($DltbSource)' in script
    assert 'Test-Path -LiteralPath $DltbSource -PathType Container' in script
    assert '$DltbSource.EndsWith(".gdb", [StringComparison]::OrdinalIgnoreCase)' in script
    assert "fuse_dltb_dem_county.py" in script
    assert "paper9v23_zhongning_dltb_only.yml" in script
    assert "conda-unpack.exe" in script
    assert '$env:PYTHONIOENCODING = "utf-8"' in script
    assert '$env:PYTHONUTF8 = "1"' in script
    assert "cmd.exe" not in script.lower()
    assert "--reference-county-code" in script
    assert "-Dataset dongxing" in script
    assert "docker" not in script.lower()
    assert "exploratory technical validation only" in script


def test_windows_wrapper_enables_utf8_inside_runtime_initialization():
    script = (WINDOWS_DEPLOY / "run-paper9-windows.ps1").read_text(encoding="utf-8")
    initialization = script.split("function Initialize-Paper9Runtime", 1)[1].split(
        "function Initialize-DataDirectories", 1
    )[0]

    assert '$env:PYTHONIOENCODING = "utf-8"' in initialization
    assert '$env:PYTHONUTF8 = "1"' in initialization
    assert '$env:PAPER9_APP_ROOT = $AppRoot' in initialization
    assert '$env:PAPER9_PACKAGE_ROOT = $BundleRoot' in initialization


def test_environment_check_supports_split_native_bundle_layout(tmp_path):
    bundle_root = tmp_path / "bundle"
    app_root = bundle_root / "app"
    for path in (
        app_root / "src/paper9_mnr",
        app_root / "src/farmland_mpc",
        app_root / "configs",
        app_root / "scripts",
        bundle_root / "docs",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (app_root / "src/paper9_mnr/__init__.py").write_text(
        '__version__ = "test"\n', encoding="utf-8"
    )
    check_script = app_root / "scripts/00_check_env.py"
    check_script.write_text(
        (PACKAGE_ROOT / "scripts/00_check_env.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PAPER9_APP_ROOT"] = str(app_root)
    env["PAPER9_PACKAGE_ROOT"] = str(bundle_root)
    result = subprocess.run(
        [sys.executable, str(check_script), "--no-heavy"],
        cwd=bundle_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert f"package_root={bundle_root}" in result.stdout
    assert f"app_root={app_root}" in result.stdout
    assert "docs: OK" in result.stdout
    assert "MISSING" not in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell parser required")
def test_windows_wrapper_is_parseable_by_windows_powershell():
    script = WINDOWS_DEPLOY / "run-paper9-windows.ps1"
    env = os.environ.copy()
    env["PAPER9_SCRIPT_TO_PARSE"] = str(script)
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$tokens = $null; $errors = $null; "
                "[System.Management.Automation.Language.Parser]::ParseFile("
                "$env:PAPER9_SCRIPT_TO_PARSE, [ref]$tokens, [ref]$errors) | Out-Null; "
                "if ($errors.Count -gt 0) { "
                "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
            ),
        ],
        cwd=PACKAGE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_windows_build_and_bundle_scripts_require_native_x64_runtime():
    build_script = (WINDOWS_DEPLOY / "build-windows-runtime.ps1").read_text(encoding="utf-8")
    package_script = (WINDOWS_DEPLOY / "package-windows-bundle.ps1").read_text(
        encoding="utf-8"
    )
    environment = yaml.safe_load(
        (WINDOWS_DEPLOY / "environment-windows-x86_64.yml").read_text(encoding="utf-8")
    )

    assert "64-bit Windows" in build_script
    assert "conda-pack" in build_script
    assert "pytest -q" in build_script
    assert "paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64.zip" in build_script
    assert 'platform = "windows/x86_64"' in package_script
    assert "$env:GDAL_DATA" in build_script
    assert "$env:PROJ_LIB" in build_script
    assert 'container_required = $false' in package_script
    assert "SHA256SUMS.txt" in package_script
    assert "MANIFEST_ZHONGNING.json" in package_script
    assert "dist\\datasets" in package_script
    assert "dem\\copernicus_glo30" in package_script
    assert 'Compress-Archive -Path (Join-Path $Staging "*")' in package_script
    assert "pytorch" in environment["dependencies"]
    assert "gdal" in environment["dependencies"]
    assert "conda-pack" in environment["dependencies"]
