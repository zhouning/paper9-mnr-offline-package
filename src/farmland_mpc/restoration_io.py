#!/usr/bin/env python3
"""Render a restoration plan to a GIS-readable shapefile + geojson.

The farmland pipeline writes an optimised DLTB shapefile back to disk after
MPC, with per-parcel DLBM swap flags. The restoration plan emits an analogous
artefact: each planning unit (row in the original geometry layer) gets the
following fields appended:

    selected        : 0/1, whether the unit was chosen for restoration
    step_chosen     : 1..max_steps, the planning step at which it was chosen
                      (NaN for units that were not selected)
    reward_at_step  : the per-step reward credited at the moment the unit was chosen
    cum_reward      : cumulative episode reward up to and including that step
    n_selected_so_far : 1..50 cumulative selection count
    budget_used_so_far: cumulative cost-proxy spend at that step

Inputs:

    --plan-dir         output dir of `farmland-mpc plan --env restoration`
                       (must contain mpc_run.log and mpc_summary.json)
    --units-geometry   the upstream geometry file (planning_units_2km.geojson
                       for buchanan, restoration_units.geojson for synthetic)
    --out-shp          where to write the rendered .shp (a .geojson sibling
                       is also written automatically)

Usage:

    python -m farmland_mpc.restoration_io \\
        --plan-dir runs/restoration/buchanan_va/5seed_results/seed0 \\
        --units-geometry runs/restoration/buchanan_va/planning_units_2km.geojson \\
        --out-shp runs/restoration/buchanan_va/5seed_results/seed0/optimized_units.shp
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("restoration_io")


def _parse_run_log(log_path: Path) -> list[dict]:
    """Extract per-step (step, action_id, step_reward, cum_reward, budget_used) tuples.

    Restoration mpc_run.log format (per env.step):
       2026-05-30 19:42:00,123 INFO     step  10/50 ... reward=+1.23 ...
    Falls back to summary-only if log lacks per-step entries.
    """
    rows = []
    if not log_path.exists():
        return rows
    text = log_path.read_text(errors="ignore")
    # Try to find restoration's selected_id / reward markers.
    # The current mpc_plan log format prints "step N/M" but not the action id;
    # we reconstruct the action id sequence from mpc_land_use snapshots if present.
    return rows  # always empty for now; replaced by snapshot reconstruction below


def _reconstruct_step_choice_from_npy(npy_path: Path) -> np.ndarray | None:
    """Final 0/1 selected mask is what mpc_plan saves; without per-step snapshots
    we can only derive ``selected`` (no step_chosen). Return the final mask or None.
    """
    if not npy_path.exists():
        return None
    arr = np.load(npy_path)
    return arr.astype(bool)


def _replay_episode(prepared_dir: Path, ensemble_dir: Path, seed: int = 0,
                    horizon: int = 5, top_k: int = 50,
                    continuation: str = "greedy") -> dict:
    """Replay the deterministic plan to recover per-step choice ordering.

    Restoration env + ensemble + greedy MPC is deterministic given a seed, so
    re-running locally reproduces the exact action sequence and per-step rewards
    that produced the saved mpc_summary.json. We use this to attach
    step_chosen / reward_at_step / cum_reward to each unit.
    """
    from farmland_mpc.restoration_env import make_restoration_env
    from farmland_mpc.ensemble_runner import EnsembleOrtRunner
    from farmland_mpc.mpc_plan import mpc_select_action

    env = make_restoration_env(prepared_dir)
    ensemble = EnsembleOrtRunner(str(ensemble_dir))
    ensemble.assert_compatible(env.n_blocks)

    env.reset(seed=seed)
    rng = np.random.default_rng(seed)
    history = []
    cum_reward = 0.0
    cum_budget = 0.0
    for step in range(env.max_steps):
        bf = env._get_block_features()
        gf = env._get_global_features()
        mask = env.action_masks()
        if not mask.any():
            break
        action, _ = mpc_select_action(
            ensemble, bf, gf, mask,
            horizon=horizon, top_k=top_k, gamma=0.99,
            n_rollouts=1, continuation=continuation,
            scoring="reward", rng=rng,
        )
        _, reward, term, trunc, info = env.step(int(action))
        cum_reward += reward
        cum_budget = env.budget_used
        history.append({
            "step":            step + 1,
            "action_unit_id":  int(action),
            "reward_at_step":  float(reward),
            "cum_reward":      float(cum_reward),
            "n_selected_so_far": int(env.selected.sum()),
            "budget_used_so_far": float(cum_budget),
        })
        if term or trunc:
            break
    return history


def _infer_unit_id_column(gdf: gpd.GeoDataFrame, n_units: int) -> str:
    """Pick which column to join on. Prefer 'unit_id'; fall back to inferred index.

    The geometry GeoJSON files already have unit_id in numerical order by row.
    """
    if "unit_id" in gdf.columns:
        return "unit_id"
    if "FID" in gdf.columns:
        return "FID"
    # Fallback: assume the geojson's row order matches unit_id 0..n-1.
    gdf["unit_id"] = np.arange(len(gdf))
    return "unit_id"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-dir",       type=Path, required=True)
    ap.add_argument("--units-geometry", type=Path, required=True)
    ap.add_argument("--prepared-dir",   type=Path, required=True,
                    help="prepared/ used for replay; must contain "
                         "scenario_config.json + attributes.csv + adjacency.csv "
                         "and a sibling ensemble dir.")
    ap.add_argument("--ensemble-dir",   type=Path, required=True,
                    help="Ensemble dir to replay with (must match plan_dir's run).")
    ap.add_argument("--seed",           type=int, default=0)
    ap.add_argument("--horizon",        type=int, default=5)
    ap.add_argument("--top-k",          type=int, default=50)
    ap.add_argument("--continuation",   type=str, default="greedy")
    ap.add_argument("--candidate-only", action="store_true",
                    help="Filter output to candidate units only (drops units "
                         "that were never selectable -- useful for buchanan "
                         "where 40/562 units have candidate=0).")
    ap.add_argument("--out-shp",        type=Path, required=True)
    args = ap.parse_args()

    plan_dir   = args.plan_dir.resolve()
    geom_path  = args.units_geometry.resolve()
    out_shp    = args.out_shp.resolve()
    out_shp.parent.mkdir(parents=True, exist_ok=True)

    log.info("=== restoration_io: rendering plan to GIS ===")
    log.info("  plan_dir       = %s", plan_dir)
    log.info("  units_geometry = %s", geom_path)
    log.info("  out_shp        = %s", out_shp)

    # Load summary just to confirm we're rendering the right episode
    summary = json.loads((plan_dir / "mpc_summary.json").read_text())
    cfg = summary["config"]
    res = summary["results"][0]
    log.info("  episode: total_reward=%.2f n_selected=%s budget_used=%.1f steps_run=%s",
             res.get("total_reward", 0),
             res.get("n_selected"), res.get("budget_used", 0),
             res.get("steps_run"))

    # Replay to recover per-step ordering
    log.info("  replaying episode to recover step ordering...")
    history = _replay_episode(args.prepared_dir, args.ensemble_dir,
                              seed=args.seed,
                              horizon=args.horizon, top_k=args.top_k,
                              continuation=args.continuation)
    log.info("  replay produced %d steps, final cum_reward=%.2f",
             len(history), history[-1]["cum_reward"] if history else 0)
    if history and "total_reward" in res:
        if abs(history[-1]["cum_reward"] - res["total_reward"]) > 0.5:
            log.warning("  replay total_reward (%.4f) differs from summary (%.4f) "
                        "by %.4f — ensemble or RNG mismatch?",
                        history[-1]["cum_reward"], res["total_reward"],
                        history[-1]["cum_reward"] - res["total_reward"])

    # Load geometry layer
    gdf = gpd.read_file(geom_path)
    uid_col = _infer_unit_id_column(gdf, len(gdf))
    log.info("  geometry layer: %d rows, joining on %s", len(gdf), uid_col)
    if "unit_id" not in gdf.columns:
        gdf["unit_id"] = gdf[uid_col].astype(int)

    # Build per-unit step-history dataframe
    history_df = pd.DataFrame(history)
    if not history_df.empty:
        history_df = history_df.rename(columns={"action_unit_id": "unit_id"})
        # Keep only the FIRST selection per unit (a unit is monotonically selected once)
        history_df = history_df.drop_duplicates(subset=["unit_id"], keep="first")

    # Merge
    out = gdf.merge(history_df, on="unit_id", how="left")
    out["selected"] = out["step"].notna().astype(int)
    # Pretty-print fields
    out["step_chosen"] = out["step"].astype("Int64")
    out = out.drop(columns=["step"])

    if args.candidate_only and "candidate" in out.columns:
        kept = out["candidate"].astype(int) == 1
        log.info("  filtering to candidates: kept %d/%d", kept.sum(), len(out))
        out = out[kept].copy()

    # Write
    n_sel = int(out["selected"].sum())
    log.info("  writing %d selected / %d total units", n_sel, len(out))

    # Shapefile field name limit (10 chars), so abbreviate
    rename = {
        "step_chosen":         "step_chosn",
        "reward_at_step":      "rwd_step",
        "cum_reward":          "cum_rwd",
        "n_selected_so_far":   "n_sel_far",
        "budget_used_so_far":  "bud_so_far",
    }
    out_shp_df = out.rename(columns=rename).copy()
    out_shp_df.to_file(out_shp, driver="ESRI Shapefile", encoding="utf-8")

    # Also write geojson sibling without renaming (geojson has no name limit)
    geojson_path = out_shp.with_suffix(".geojson")
    out.to_file(geojson_path, driver="GeoJSON")
    log.info("  wrote %s", out_shp)
    log.info("  wrote %s", geojson_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
