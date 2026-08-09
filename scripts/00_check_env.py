from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path


DEFAULT_APP_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(os.environ.get("PAPER9_APP_ROOT", DEFAULT_APP_ROOT)).resolve()
PACKAGE_ROOT = Path(os.environ.get("PAPER9_PACKAGE_ROOT", APP_ROOT)).resolve()
SRC = APP_ROOT / "src"
sys.path.insert(0, str(SRC))


LIGHT_IMPORTS = ("yaml", "paper9_mnr")
FULL_IMPORTS = ("typer", "numpy", "pandas", "geopandas", "rasterio", "torch", "onnxruntime")
NOTEBOOK_IMPORTS = ("jupyterlab", "matplotlib")


def _check_import(name: str) -> tuple[str, bool, str]:
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        return name, False, str(exc)
    version = getattr(module, "__version__", "installed")
    return name, True, str(version)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Paper9 MNR offline package environment.")
    parser.add_argument("--no-heavy", action="store_true", help="Skip GIS, torch, and ONNX imports.")
    parser.add_argument("--include-notebook", action="store_true", help="Check optional notebook dependencies.")
    args = parser.parse_args()

    print(f"package_root={PACKAGE_ROOT}")
    print(f"app_root={APP_ROOT}")
    print(f"src={SRC}")
    print(f"python={sys.version.split()[0]}")

    layout_paths = [
        ("src/paper9_mnr", APP_ROOT / "src/paper9_mnr"),
        ("src/farmland_mpc", APP_ROOT / "src/farmland_mpc"),
        ("configs", APP_ROOT / "configs"),
        ("scripts", APP_ROOT / "scripts"),
        ("docs", PACKAGE_ROOT / "docs"),
    ]
    if APP_ROOT == PACKAGE_ROOT:
        layout_paths.extend((name, PACKAGE_ROOT / name) for name in ("notebooks", "wheelhouse"))
    for label, path in layout_paths:
        print(f"{label}: {'OK' if path.exists() else 'MISSING'}")

    imports = LIGHT_IMPORTS if args.no_heavy else LIGHT_IMPORTS + FULL_IMPORTS
    if args.include_notebook:
        imports = imports + NOTEBOOK_IMPORTS
    failed = []
    for name in imports:
        pkg, ok, detail = _check_import(name)
        print(f"import {pkg}: {'OK' if ok else 'FAIL'} {detail}")
        if not ok:
            failed.append(pkg)

    if failed:
        print("missing_imports=" + ",".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

