from __future__ import annotations

import argparse
import ast
import importlib
import json
import platform
import sys
from collections.abc import Iterable
from typing import Any


RUNTIME_IMPORTS = (
    "numpy",
    "pandas",
    "geopandas",
    "rasterio",
    "scipy",
    "sklearn",
    "torch",
    "onnxruntime",
)

FORBIDDEN_BASELINE_FEATURES = {
    "X86_V2",
    "X86_V3",
    "X86_V4",
    "SSE41",
    "SSE4_1",
    "POPCNT",
    "AVX",
    "AVX2",
}


def normalize_baseline(value: object) -> set[str]:
    """Normalize NumPy CPU baseline metadata to uppercase feature tokens."""
    if value is None:
        return set()
    if isinstance(value, str):
        parsed: object
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = value.replace(",", " ").split()
        return normalize_baseline(parsed)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return {str(item).strip().upper() for item in value if str(item).strip()}
    return {str(value).strip().upper()} if str(value).strip() else set()


def baseline_is_legacy_safe(features: set[str]) -> bool:
    """Return True when baseline does not require x86-64-v2-only features."""
    normalized = normalize_baseline(features)
    if normalized & FORBIDDEN_BASELINE_FEATURES:
        return False
    return not any(feature.startswith("AVX512") for feature in normalized)


def numpy_cpu_baseline(numpy_module: Any) -> set[str]:
    """Read NumPy's compiled CPU baseline from public and private metadata."""
    candidates = []
    config = getattr(numpy_module, "__config__", None)
    if config is not None:
        candidates.append(getattr(config, "__cpu_baseline__", None))
    try:
        multiarray = importlib.import_module("numpy._core._multiarray_umath")
    except Exception:
        try:
            multiarray = importlib.import_module("numpy.core._multiarray_umath")
        except Exception:
            multiarray = None
    if multiarray is not None:
        candidates.append(getattr(multiarray, "__cpu_baseline__", None))

    baseline: set[str] = set()
    for candidate in candidates:
        baseline |= normalize_baseline(candidate)
    return baseline


def collect_runtime_report() -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": {},
        "numpy_cpu_baseline": [],
    }
    failures: dict[str, str] = {}

    for name in RUNTIME_IMPORTS:
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            failures[name] = str(exc)
            continue
        report["packages"][name] = getattr(module, "__version__", "installed")
        if name == "numpy":
            report["numpy_cpu_baseline"] = sorted(numpy_cpu_baseline(module))

    if failures:
        report["import_failures"] = failures
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Paper9 legacy x86_64 CPU runtime compatibility.")
    parser.add_argument(
        "--require-legacy-amd64",
        action="store_true",
        help="Fail if NumPy baseline requires x86-64-v2, AVX, or target-missing features.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = collect_runtime_report()
    baseline = set(report.get("numpy_cpu_baseline", []))
    legacy_safe = baseline_is_legacy_safe(baseline)
    report["legacy_amd64_safe"] = legacy_safe

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"python={report['python']}")
        print(f"platform={report['platform']}")
        print(f"machine={report['machine']}")
        for name, version in report["packages"].items():
            print(f"import {name}: OK {version}")
        for name, error in report.get("import_failures", {}).items():
            print(f"import {name}: FAIL {error}")
        print("numpy_cpu_baseline=" + ",".join(report["numpy_cpu_baseline"]))
        print(f"legacy_amd64_safe={legacy_safe}")

    if report.get("import_failures"):
        return 1
    if args.require_legacy_amd64 and not legacy_safe:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
