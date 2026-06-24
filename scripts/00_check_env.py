from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


LIGHT_IMPORTS = ("yaml", "paper9_mnr")
FULL_IMPORTS = ("typer", "numpy", "pandas", "geopandas", "rasterio", "torch", "onnxruntime")


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
    args = parser.parse_args()

    print(f"package_root={ROOT}")
    print(f"src={SRC}")
    print(f"python={sys.version.split()[0]}")

    for rel in ("src/paper9_mnr", "src/farmland_mpc", "configs", "scripts", "docs", "wheelhouse"):
        path = ROOT / rel
        print(f"{rel}: {'OK' if path.exists() else 'MISSING'}")

    imports = LIGHT_IMPORTS if args.no_heavy else LIGHT_IMPORTS + FULL_IMPORTS
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


