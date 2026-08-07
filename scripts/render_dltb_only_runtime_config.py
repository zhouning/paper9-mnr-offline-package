#!/usr/bin/env python3
"""Render an install-location-independent config for a DLTB-only run."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from paper9_mnr.config import load_config, validate_config


def render_runtime_config(
    template_path: Path,
    output_path: Path,
    data_root: Path,
    run_name: str = "zhongning",
) -> dict[str, object]:
    """Write absolute input, working, and output paths under data_root."""
    config = load_config(template_path)
    validate_config(config)

    root = data_root.expanduser().resolve()
    input_dir = root / "input"
    working_dir = root / "working"
    outputs_dir = root / "outputs"
    for path in (root, input_dir, working_dir, outputs_dir, outputs_dir / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    config["data"].update(
        {
            "dltb": str(input_dir / "DLTB_with_authority_slope.gpkg"),
            "admin_units": str(input_dir / "admin_units.gpkg"),
            "dem": str(input_dir / "DEM_placeholder.tif"),
            "prepared_dir": str(working_dir / f"prepared_paper9v23_{run_name}_dltb_only"),
        }
    )
    plan_dir = outputs_dir / f"plan_paper9v23_{run_name}_dltb_only"
    config["outputs"].update(
        {
            "plan_dir": str(plan_dir),
            "optimized_vector": str(plan_dir / "DLTB_optimized.shp"),
        }
    )
    config.setdefault("runtime", {})["data_root"] = str(root)
    validate_config(config)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--run-name", default="zhongning")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    render_runtime_config(args.template, args.output, args.data_root, args.run_name)
    print(f"Wrote runtime config: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
