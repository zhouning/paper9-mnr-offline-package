import ast
from pathlib import Path
import sys

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
    ]

    missing = [name for name in expected if not (docs / name).exists()]

    assert missing == []


