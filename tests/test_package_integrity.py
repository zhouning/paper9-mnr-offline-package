import ast
import json
from pathlib import Path
import sys
import tomllib

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC))


def test_required_offline_package_directories_exist():
    required = [
        "src/paper9_mnr",
        "src/farmland_mpc",
        "configs",
        "scripts",
        "docs",
        "notebooks",
        "wheelhouse",
    ]

    missing = [rel for rel in required if not (PACKAGE_ROOT / rel).exists()]

    assert missing == []


def test_vendored_core_is_pure_python_not_arcgis_toolbox():
    core = PACKAGE_ROOT / "src" / "farmland_mpc"

    assert (core / "cli.py").exists()
    assert not (PACKAGE_ROOT / "toolbox").exists()
    assert not list(PACKAGE_ROOT.rglob("*.pyt"))



def test_vendored_core_has_no_runtime_arcpy_imports():
    runtime_hits = []
    for path in (PACKAGE_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "arcpy" or alias.name.startswith("arcpy."):
                        runtime_hits.append(f"{path.relative_to(PACKAGE_ROOT)}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "arcpy" or module.startswith("arcpy."):
                    runtime_hits.append(f"{path.relative_to(PACKAGE_ROOT)}: from {module}")

    assert runtime_hits == []

def test_docs_cover_real_data_retraining_and_offline_installation():
    docs = PACKAGE_ROOT / "docs"
    expected = [
        "01_offline_deployment.md",
        "02_data_contract.md",
        "03_full_pipeline.md",
        "04_retrain_and_calibration.md",
        "05_audit_and_interpretation.md",
        "06_troubleshooting.md",
        "07_offline_wheelhouse.md",
        "08_macos_validation.md",
        "13_notebook_and_logs.md",
    ]

    missing = [name for name in expected if not (docs / name).exists()]

    assert missing == []


def test_pyproject_declares_onnx_export_runtime_dependencies():
    pyproject = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    normalized = {dep.split()[0].lower() for dep in dependencies}

    assert "onnxscript" in normalized


def test_notebook_optional_dependencies_are_declared():
    pyproject = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    notebook_deps = pyproject["project"]["optional-dependencies"]["notebook"]
    normalized = {dep.split()[0].lower() for dep in notebook_deps}

    assert {"jupyterlab", "matplotlib"} <= normalized


def test_leaflet_assets_are_packaged_for_offline_notebook_maps():
    assets = PACKAGE_ROOT / "src" / "paper9_mnr" / "assets" / "leaflet"
    pyproject = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["paper9_mnr"]

    assert (assets / "leaflet.js").exists()
    assert (assets / "leaflet.css").exists()
    assert (assets / "LICENSE").exists()
    assert "assets/leaflet/*" in package_data


def test_notebook_files_are_valid_ipynb_json():
    notebooks = sorted((PACKAGE_ROOT / "notebooks").glob("*.ipynb"))

    assert {path.name for path in notebooks} == {
        "00_input_data_check.ipynb",
        "01_pipeline_run_and_logs.ipynb",
        "02_result_visualization.ipynb",
    }
    for path in notebooks:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["nbformat"] == 4
        assert payload["cells"]


def test_notebooks_cover_full_flow_and_inline_visualization():
    payloads = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in (PACKAGE_ROOT / "notebooks").glob("*.ipynb")
    }
    sources = {
        name: "\n".join(
            "".join(cell.get("source", []))
            for cell in payload["cells"]
            if cell.get("cell_type") == "code"
        )
        for name, payload in payloads.items()
    }

    assert 'os.environ.get("PAPER9_CONFIG"' in sources["00_input_data_check.ipynb"]
    assert "input_layers_map_html" in sources["00_input_data_check.ipynb"]
    assert "display(HTML(input_map_html))" in sources["00_input_data_check.ipynb"]
    assert "Image(filename=" not in sources["00_input_data_check.ipynb"]
    assert "scripts/run_full_pipeline.py" in sources["01_pipeline_run_and_logs.ipynb"]
    assert "RUN_PIPELINE = False" in sources["01_pipeline_run_and_logs.ipynb"]
    assert "scripts/05_audit.py" in sources["01_pipeline_run_and_logs.ipynb"]
    assert "latest_run_manifest" in sources["01_pipeline_run_and_logs.ipynb"]
    assert "optimization_changes_map_html" in sources["02_result_visualization.ipynb"]
    assert "display(HTML(changes_map_html))" in sources["02_result_visualization.ipynb"]
    assert "Image(filename=" not in sources["02_result_visualization.ipynb"]


def test_dockerfile_includes_notebook_mode_assets():
    dockerfile = (PACKAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY notebooks ./notebooks" in dockerfile
    assert '".[dev,notebook]"' in dockerfile


def test_dockerfile_supports_legacy_x86_64_build_gate():
    dockerfile = (PACKAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (PACKAGE_ROOT / "constraints" / "legacy-x86_64.txt").exists()
    assert "ARG LEGACY_X86_64=0" in dockerfile
    assert "COPY constraints ./constraints" in dockerfile
    assert "-c constraints/legacy-x86_64.txt" in dockerfile
    assert "--no-deps .[dev,notebook]" in dockerfile
    assert "python scripts/00_check_env.py --include-notebook" in dockerfile
    assert "python scripts/check_legacy_cpu_compat.py --require-legacy-amd64" in dockerfile
