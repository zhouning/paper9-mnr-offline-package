"""Audit helpers for Paper9 MNR workflow outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def expected_outputs(config: Mapping[str, Any]) -> dict[str, Path]:
    """Return required output paths for a configured workflow run."""
    prepared_dir = Path(config["data"]["prepared_dir"])
    plan_dir = Path(config["outputs"]["plan_dir"])
    return {
        "prepared_dir": prepared_dir,
        "sample_transitions": prepared_dir / "tool2" / "transitions.npz",
        "sample_pairwise": prepared_dir / "tool2" / "pairwise.npz",
        "ensemble_dir": prepared_dir / config["training"].get("out_subdir", "tool3"),
        "plan_dir": plan_dir,
        "optimized_vector": Path(config["outputs"]["optimized_vector"]),
        "mpc_summary": plan_dir / "mpc_summary.json",
    }


def evaluate_hard_constraints(config: Mapping[str, Any], mpc_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate per-episode hard gates from an MPC summary."""
    constraints = config.get("planning", {}).get("constraints", {})
    required_area = float(constraints.get("cultivated_area_floor_delta_ha", 0.0))
    results = list(mpc_summary.get("results", []))
    failure_reasons: list[str] = []
    records: list[dict[str, Any]] = []

    for idx, result in enumerate(results):
        area_delta = float(result.get("cultivated_area_change_ha", 0.0))
        slope_delta = float(result.get("slope_change_pct", 0.0))
        cont_delta = float(result.get("cont_change", 0.0))
        record = {
            "episode": idx,
            "cultivated_area_change_ha": area_delta,
            "slope_change_pct": slope_delta,
            "cont_change": cont_delta,
            "baimu_count_change": int(result.get("baimu_count_change", 0)),
            "baimu_area_change_ha": float(result.get("baimu_area_change_ha", 0.0)),
        }
        records.append(record)
        if area_delta < required_area:
            failure_reasons.append(
                f"episode {idx} cultivated_area_change_ha={area_delta:.6f} < required {required_area:.6f}"
            )
        if slope_delta >= 0:
            failure_reasons.append(
                f"episode {idx} slope_change_pct={slope_delta:.6f} does not satisfy slope_change_pct < 0"
            )
        if cont_delta <= 0:
            failure_reasons.append(
                f"episode {idx} cont_change={cont_delta:.6f} does not satisfy cont_change > 0"
            )

    if not results:
        failure_reasons.append("mpc_summary.results is empty")

    return {
        "hard_constraint_passed": not failure_reasons,
        "failure_reasons": failure_reasons,
        "required_cultivated_area_delta_ha": required_area,
        "baimu_is_hard_constraint": False,
        "records": records,
    }


def build_audit_summary(config: Mapping[str, Any]) -> dict[str, Any]:
    """Build the file and hard-constraint audit summary."""
    expected = expected_outputs(config)
    files = {name: {"path": str(path), "exists": path.exists()} for name, path in expected.items()}
    mpc_path = expected["mpc_summary"]
    constraint_status = {
        "hard_constraint_passed": False,
        "failure_reasons": ["mpc_summary.json is missing"],
        "baimu_is_hard_constraint": False,
        "records": [],
    }
    if mpc_path.exists():
        mpc_summary = json.loads(mpc_path.read_text(encoding="utf-8"))
        constraint_status = evaluate_hard_constraints(config, mpc_summary)

    return {
        "files": files,
        "all_expected_outputs_exist": all(item["exists"] for item in files.values()),
        "constraint_status": constraint_status,
    }
