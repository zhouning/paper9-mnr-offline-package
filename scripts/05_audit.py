from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from paper9_mnr.config import load_config, validate_config
from paper9_mnr.audit import build_audit_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit expected Paper9 workflow outputs.")
    parser.add_argument("config", nargs="?", default=str(ROOT / "configs" / "paper9v2_no_net_loss_authority_slope.yml"))
    parser.add_argument("--write", action="store_true", help="Write outputs/audit_summary.json.")
    args = parser.parse_args()

    config = load_config(args.config)
    validate_config(config)
    summary = build_audit_summary(config)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.write:
        out = ROOT / "outputs" / "audit_summary.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if not summary["all_expected_outputs_exist"]:
        return 1
    if not summary["constraint_status"]["hard_constraint_passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
