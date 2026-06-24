#!/usr/bin/env python3
"""Prepare a restoration-case prepared/ directory from raw attributes + adjacency.

Reads the raw planning-unit attribute CSV and adjacency CSV emitted by an
upstream data-prep step (e.g. ``runs/restoration/buchanan_va/`` or
``runs/restoration/synthetic/``), normalises column names, infers a scenario
config from the upstream README, and writes a uniform prepared/ directory that
``RestorationEnv`` (and the rest of the farmland_mpc pipeline) consumes.

Output layout:

    <prepared_dir>/
      attributes.csv          (one row per unit; numeric features only)
      adjacency.csv           (source,target,shared_len_m,...)
      scenario_config.json    (reward_terms, budget, cost_col, max_steps, feature_cols)
      provenance.json         (input paths, normalisation settings)

This is the restoration-case analogue of farmland_mpc.prepare.run, just
much simpler (no DEM, no slope, no block construction) because the upstream
data is already at planning-unit granularity.

Usage:

    python -m farmland_mpc.restoration_prepare \\
        --raw-dir runs/restoration/buchanan_va \\
        --out-dir runs/restoration/buchanan_va/prepared \\
        --case buchanan
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("restoration_prepare")


# Per-case schema mapping. Each case knows where its attributes/adjacency
# files are, what scenario_config to write, and which columns become per-unit
# features vs reward-source columns.
CASES = {
    "buchanan": {
        "attributes_file":  "planning_units_2km_attributes.csv",
        "adjacency_file":   "planning_units_2km_adjacency.csv",
        "raw_scenario":     "scenario_config.json",
        "feature_cols": [
            "row", "col", "area_ha",
            "aml_count", "severity_sum", "severity_mean", "unfunded_cost_sum",
            "dist_water_m", "water_km", "slope_deg_mean",
            "risk_index", "water_priority",
            "restoration_cost_proxy", "benefit_proxy", "priority_score",
            "candidate",
        ],
        "cost_col": "restoration_cost_proxy",
        "default_max_steps": 50,
        # The README's 20,000 cap is binding very early because the highest-
        # priority candidates are also the most expensive (top-5 cost
        # mean ~12,700; median candidate cost only 400). 200,000 is a more
        # meaningful budget that lets a ~50-step episode play out and
        # makes the planning trade-off (skip very-high-cost outliers
        # vs accumulate cheaper unit-by-unit gains) the actual decision
        # the planner faces.
        "default_budget":    200000.0,
        "reward_terms": {
            "risk_index":      0.45,
            "water_priority":  0.25,
            "connectivity":    0.20,
            "cost_penalty":   -0.10,
        },
    },
    "synthetic": {
        "attributes_file":  "restoration_units_attributes.csv",
        "adjacency_file":   "adjacency_edges.csv",
        "raw_scenario":     "scenario_config.json",
        "feature_cols": [
            "row", "col", "area_ha",
            "slope_deg", "disturbance", "erosion_risk", "biodiversity",
            "human_exposure",
            "dist_water_m", "dist_settle_m", "dist_source_m",
            "rest_cost", "risk_reduction", "habitat_gain", "water_gain",
            "priority_score",
        ],
        "cost_col": "rest_cost",
        "default_max_steps": 60,
        "default_budget":    45434.91,
        "reward_terms": {
            "risk_reduction":   0.35,
            "habitat_gain":     0.25,
            "water_gain":       0.20,
            "connectivity":     0.10,
            "cost_penalty":    -0.10,
        },
    },
}


def _coerce_candidate_column(df: pd.DataFrame) -> pd.DataFrame:
    """Synthetic case has no 'candidate' column; treat all units as candidates."""
    if "candidate" not in df.columns:
        df = df.copy()
        df["candidate"] = 1
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--case", choices=list(CASES.keys()), required=True)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--budget",    type=float, default=None)
    args = ap.parse_args()

    spec = CASES[args.case]
    raw_dir = args.raw_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== restoration_prepare: case=%s ===", args.case)
    log.info("  raw_dir = %s", raw_dir)
    log.info("  out_dir = %s", out_dir)

    # Load + normalise attributes
    attrs = pd.read_csv(raw_dir / spec["attributes_file"])
    log.info("  attributes: %d rows, %d cols", len(attrs), len(attrs.columns))
    attrs = _coerce_candidate_column(attrs)
    if "unit_id" not in attrs.columns:
        attrs = attrs.copy()
        attrs.insert(0, "unit_id", range(len(attrs)))

    # Load adjacency
    adj = pd.read_csv(raw_dir / spec["adjacency_file"])
    log.info("  adjacency: %d edges", len(adj))
    if "source" not in adj.columns or "target" not in adj.columns:
        raise ValueError(f"adjacency must have source,target columns; got {list(adj.columns)}")

    # Build scenario config
    scenario_config = {
        "case_name":       args.case,
        "feature_cols":    spec["feature_cols"],
        "reward_terms":    spec["reward_terms"],
        "cost_col":        spec["cost_col"],
        "budget":          float(args.budget) if args.budget is not None else float(spec["default_budget"]),
        "max_steps":       int(args.max_steps) if args.max_steps is not None else int(spec["default_max_steps"]),
        "n_units":         int(len(attrs)),
        "n_candidates":    int(attrs["candidate"].sum()),
        "n_edges":         int(len(adj)),
    }

    # Write outputs
    out_attrs = out_dir / "attributes.csv"
    out_adj   = out_dir / "adjacency.csv"
    attrs.to_csv(out_attrs, index=False)
    adj.to_csv(out_adj, index=False)
    (out_dir / "scenario_config.json").write_text(json.dumps(scenario_config, indent=2))

    # Provenance
    prov = {
        "case":            args.case,
        "raw_dir":         str(raw_dir),
        "raw_attributes":  spec["attributes_file"],
        "raw_adjacency":   spec["adjacency_file"],
        "n_units":         scenario_config["n_units"],
        "n_candidates":    scenario_config["n_candidates"],
        "n_edges":         scenario_config["n_edges"],
        "budget":          scenario_config["budget"],
        "max_steps":       scenario_config["max_steps"],
        "feature_cols":    scenario_config["feature_cols"],
        "reward_terms":    scenario_config["reward_terms"],
    }
    (out_dir / "provenance.json").write_text(json.dumps(prov, indent=2))

    log.info("  wrote %s, %s, scenario_config.json, provenance.json", out_attrs.name, out_adj.name)
    log.info("  n_units=%d, n_candidates=%d, n_edges=%d, max_steps=%d, budget=%.1f",
             scenario_config["n_units"], scenario_config["n_candidates"],
             scenario_config["n_edges"], scenario_config["max_steps"], scenario_config["budget"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
