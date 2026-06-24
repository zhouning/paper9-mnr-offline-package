from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from paper9_mnr.config import load_config, validate_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit expected Paper9 workflow outputs.")
    parser.add_argument("config", nargs="?", default=str(ROOT / "configs" / "real_data_from_authority_slope.yml"))
    parser.add_argument("--write", action="store_true", help="Write outputs/audit_summary.json.")
    args = parser.parse_args()

    config = load_config(args.config)
    validate_config(config)
    expected = {
        "prepared_dir": Path(config["data"]["prepared_dir"]),
        "sample_transitions": Path(config["data"]["prepared_dir"]) / "tool2" / "transitions.npz",
        "sample_pairwise": Path(config["data"]["prepared_dir"]) / "tool2" / "pairwise.npz",
        "ensemble_dir": Path(config["data"]["prepared_dir"]) / config["training"].get("out_subdir", "tool3"),
        "plan_dir": Path(config["outputs"]["plan_dir"]),
        "optimized_vector": Path(config["outputs"]["optimized_vector"]),
    }
    summary = {name: {"path": str(path), "exists": path.exists()} for name, path in expected.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.write:
        out = ROOT / "outputs" / "audit_summary.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

