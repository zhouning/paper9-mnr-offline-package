"""Tool 4: Model-Predictive Control planning.

Uses core.blocks_env.make_env(prepared_dir=...) to instantiate a
region-agnostic CountyLevelEnv, then rolls out top-K candidate blocks
under the ONNX ensemble for H steps and commits the block whose
rollout accumulates the highest reward.

Outputs:
    land_use.npy  -- flattened land-use vector per step
    summary.json  -- aggregate slope / baimu / contiguity metrics
    mpc_run.log   -- per-episode / per-step progress

Optionally writes an optimized DLTB feature class with OPT_DLBM /
OPT_DLMC / CHG_FLAG / ORIG_DLBM fields, mapped back via BSM.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MPC_BATCH_SIZE = 1024


# ---------------------------------------------------------------------------
# MPC core: lifted from mpc_planner.py, torch dependency removed.
# ---------------------------------------------------------------------------

def _compute_slope_signal(cur_gf, next_gf):
    # global_features[4] = (initial_slope - cur_slope) / initial_slope
    return next_gf[:, 4] - cur_gf[:, 4]


def _greedy_1step_actions(
    ensemble, cur_bf, cur_gf, valid_actions, n_sample, rng,
    batch_size=DEFAULT_MPC_BATCH_SIZE,
):
    k = cur_bf.shape[0]
    if len(valid_actions) <= n_sample:
        sample_actions = valid_actions
    else:
        sample_actions = rng.choice(valid_actions, n_sample, replace=False)
    n_s = len(sample_actions)

    best_score = np.full(k, -np.inf, dtype=np.float64)
    best_action = np.full(k, int(sample_actions[0]), dtype=np.int64)
    total = k * n_s
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        flat_idx = np.arange(start, end)
        traj_idx = flat_idx // n_s
        action_idx = flat_idx % n_s
        bf = cur_bf[traj_idx]
        gf = cur_gf[traj_idx]
        actions = sample_actions[action_idx]
        if hasattr(ensemble, "batch_predict_rewards"):
            r_exp, _ = ensemble.batch_predict_rewards(bf, gf, actions)
        else:
            _, _, r_exp, _ = ensemble.batch_predict(bf, gf, actions)
        for local_i, traj in enumerate(traj_idx):
            score = float(r_exp[local_i])
            if score > best_score[traj]:
                best_score[traj] = score
                best_action[traj] = int(sample_actions[action_idx[local_i]])
    return best_action


def mpc_select_action(ensemble, block_features, global_features, action_mask,
                      horizon=5, top_k=50, gamma=0.99, n_rollouts=1,
                      continuation="random", greedy_sample=50,
                      scoring="reward", rng=None,
                      batch_size=DEFAULT_MPC_BATCH_SIZE):
    """Pick the next action by simulating top-K candidates H steps forward."""
    rng = rng or np.random.default_rng()
    valid_actions = np.where(action_mask)[0]
    if len(valid_actions) == 0:
        return 0, {}

    batch_size = max(1, int(batch_size or DEFAULT_MPC_BATCH_SIZE))

    # Stage 1: score every valid action 1-step while retaining only per-chunk
    # top-K next states. This is exact for the global top-K because an action
    # outside its chunk's top-K cannot be in the global top-K.
    n_valid = len(valid_actions)
    k = min(top_k, n_valid)
    action_parts = []
    score_parts = []
    bf_parts = []
    gf_parts = []
    for start in range(0, n_valid, batch_size):
        chunk_actions = valid_actions[start:start + batch_size]
        n_chunk = len(chunk_actions)
        bf_batch = np.repeat(block_features[np.newaxis], n_chunk, axis=0)
        gf_batch = np.repeat(global_features[np.newaxis], n_chunk, axis=0)
        next_bf, next_gf, r1, _ = ensemble.batch_predict(
            bf_batch, gf_batch, chunk_actions)
        score1 = (_compute_slope_signal(gf_batch, next_gf)
                  if scoring == "slope" else r1)
        local_k = min(k, n_chunk)
        local_top = np.argsort(score1)[-local_k:]
        action_parts.append(chunk_actions[local_top])
        score_parts.append(score1[local_top])
        bf_parts.append(next_bf[local_top])
        gf_parts.append(next_gf[local_top])

    chunk_candidates = np.concatenate(action_parts)
    chunk_scores = np.concatenate(score_parts)
    chunk_bf = np.concatenate(bf_parts, axis=0)
    chunk_gf = np.concatenate(gf_parts, axis=0)
    top_idx = np.argsort(chunk_scores)[-k:]
    candidates = chunk_candidates[top_idx]
    cand_cumrew = chunk_scores[top_idx].copy().astype(np.float64)
    init_bf = chunk_bf[top_idx]
    init_gf = chunk_gf[top_idx]

    # Stage 2: H-1 step rollout(s), mean over n_rollouts
    rollout_rewards = np.zeros(k, dtype=np.float64)
    for _ in range(n_rollouts):
        cur_bf = init_bf.copy()
        cur_gf = init_gf.copy()
        prev_gf = init_gf.copy()
        discount = gamma
        for _step in range(1, horizon):
            if continuation == "greedy":
                actions = _greedy_1step_actions(
                    ensemble, cur_bf, cur_gf, valid_actions, greedy_sample,
                    rng, batch_size=batch_size)
            else:
                actions = rng.choice(valid_actions, size=k)
            nb, ng, r_step, _ = ensemble.batch_predict(cur_bf, cur_gf, actions)
            step_score = _compute_slope_signal(prev_gf, ng) if scoring == "slope" else r_step
            rollout_rewards += discount * step_score
            discount *= gamma
            prev_gf = cur_gf.copy()
            cur_bf = nb
            cur_gf = ng
    cand_cumrew += rollout_rewards / n_rollouts

    best = int(np.argmax(cand_cumrew))
    chosen = int(candidates[best])
    info = {
        "n_valid": int(n_valid), "n_candidates": int(k),
        "best_cumrew": float(cand_cumrew[best]),
        "mean_cumrew": float(cand_cumrew.mean()),
        "horizon": horizon, "continuation": continuation, "scoring": scoring,
    }
    return chosen, info


# ---------------------------------------------------------------------------
# Episode runner (talks to the Gymnasium env)
# ---------------------------------------------------------------------------

def _run_episode(env, ensemble, horizon, top_k, gamma, continuation,
                 scoring, seed, progress_cb=None,
                 batch_size=DEFAULT_MPC_BATCH_SIZE):
    env.reset(seed=seed)
    rng = np.random.default_rng(seed)
    total_reward = 0.0
    step_times = []
    last_info = {}

    for step in range(env.max_steps):
        bf = env._get_block_features()
        gf = env._get_global_features()
        mask = env.action_masks()

        t0 = time.time()
        action, mpc_info = mpc_select_action(
            ensemble, bf, gf, mask,
            horizon=horizon, top_k=top_k, gamma=gamma,
            n_rollouts=1, continuation=continuation,
            scoring=scoring, rng=rng, batch_size=batch_size,
        )
        step_times.append(time.time() - t0)

        _, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        last_info = info

        if progress_cb is not None:
            progress_cb(step + 1, env.max_steps, info, step_times[-1])

        if terminated or truncated:
            break

    last_info["total_reward"] = total_reward
    last_info["mean_step_time"] = float(np.mean(step_times)) if step_times else 0.0
    last_info["total_time"] = float(np.sum(step_times))
    last_info["steps_run"] = len(step_times)
    return last_info


# ---------------------------------------------------------------------------
# Entry point called by the .pyt
# ---------------------------------------------------------------------------

def run(ensemble_dir, out_dir, horizon=5, top_k=50, gamma=0.99,
        threads=0, n_episodes=1, continuation="random", scoring="reward",
        mpc_batch_size=DEFAULT_MPC_BATCH_SIZE,
        max_steps=None, seed_offset=0,
        prepared_dir=None, proj_crs=None,
        output_fc=None, input_dltb_fc=None,
        farm_dlbm=None, forest_dlbm=None,
        slope_weight=None, cont_weight=None,
        baimu_weight=None, baimu_bonus=None,
        baimu_area_penalty=None,
        cultivated_area_floor_delta_ha=None,
        baimu_area_floor_delta_ha=None,
        gamma_conn=None, delta_conn=None,
        env_kind="county",
        messages=None):
    """MPC planning loop (v0.3).

    v0.3 adds optional reward-weight overrides. When any of slope_weight /
    cont_weight / baimu_weight / baimu_bonus is non-None, the env is built
    with that weight (overriding the Paper 9 v6 default). **Important**:
    env reward is what Tool 3's ensemble was trained to predict. Changing
    weights at Tool 4 time means the ensemble's reward head is slightly
    mis-calibrated for the new objective. The MPC still runs -- because
    Paper 9 picks actions by integrating reward over H steps, and the
    ensemble's reward scale is approximately preserved under linear re-
    weighting -- but the result is strictly "in-distribution for Tool 3"
    only at the defaults. For the cleanest results, retrain Tool 3 after
    changing weights.

    Parameters (new vs v0.2)
    ------------------------
    slope_weight : float or None
        Override env.slope_weight (Paper 9 default 4000.0).
    cont_weight : float or None
        Override env.cont_weight (default 500.0).
    baimu_weight : float or None
        Override env.baimu_weight (default 1500.0).
    baimu_bonus : float or None
        Override env.baimu_bonus (default 5.0).
    baimu_area_penalty : float or None
        Override env.baimu_area_penalty (default 2000.0; an asymmetric penalty
        the env applies whenever baimu_fang area decreases between steps,
        NOT documented in the Paper 9 v7 reward equation Eq.1). Note: this
        runtime override only affects the env.step() reward used by
        episode_return reporting; it has NO effect on stage-1/stage-2
        candidate ranking because those use the ONNX ensemble's reward head,
        which was frozen at training time under whatever value of
        baimu_area_penalty was in effect when Tool 2 sampled and Tool 3
        trained. To actually steer planning by a different penalty, re-run
        Tools 2 and 3 with the desired value.
    cultivated_area_floor_delta_ha : float or None
        Optional hard execution constraint. When set, real env.step() may only
        commit farm->forest / forest->farm pairs that keep cumulative cultivated
        area >= initial_farm_area + this delta. Use 0.0 for exact no-net-loss,
        or a negative value for an explicit hectare tolerance.
    baimu_area_floor_delta_ha : float or None
        Optional hard execution constraint on cumulative qualifying baimu-fang
        area. Use 0.0 for no net loss in qualifying large-patch area. This
        floor is checked during real pair execution and can be slower because it
        recomputes connected components for candidate pairs.
    gamma_conn, delta_conn : float or None
        Optional local pair-selection heuristic overrides. Higher gamma_conn
        favours forest parcels with more farmland neighbours; higher delta_conn
        protects farmland parcels with more farmland neighbours from retirement.

    See v0.2 docstring for the rest.
    """

    def _say(msg, level="info"):
        if messages is not None:
            getattr(messages, "addMessage" if level == "info"
                    else "addWarningMessage")(msg)
        logger.info(msg)
        print(msg, flush=True)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log_path = out_dir / "mpc_run.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)
    logging.getLogger().setLevel(logging.INFO)

    try:
        # Ensure the toolbox dir (so 'core/...' is importable) is on
        # sys.path. The .pyt also does this; we repeat here in case
        # core.mpc_plan is invoked from another script.
        toolbox_dir = str(Path(__file__).resolve().parent.parent)
        if toolbox_dir not in sys.path:
            sys.path.insert(0, toolbox_dir)
        core_dir = str(Path(__file__).resolve().parent)
        if core_dir not in sys.path:
            sys.path.insert(0, core_dir)

        _say(f"[MPC] horizon={horizon} top_k={top_k} gamma={gamma} "
             f"continuation={continuation} scoring={scoring} "
             f"episodes={n_episodes} threads={threads} "
             f"mpc_batch_size={mpc_batch_size}")
        _say(f"[MPC] ensemble_dir = {ensemble_dir}")
        _say(f"[MPC] prepared_dir = {prepared_dir}")
        if output_fc:
            _say(f"[MPC] output_fc   = {output_fc}")
            if not input_dltb_fc:
                raise ValueError("output_fc requires input_dltb_fc")
        if cultivated_area_floor_delta_ha is not None:
            _say("[MPC] cultivated-area floor active: "
                 f"delta >= {float(cultivated_area_floor_delta_ha):+.3f} ha")
        if baimu_area_floor_delta_ha is not None:
            _say("[MPC] baimu-area floor active: "
                 f"delta >= {float(baimu_area_floor_delta_ha):+.3f} ha")

        # Load ensemble
        try:
            from farmland_mpc.ensemble_runner import EnsembleOrtRunner
        except ImportError:
            from core.ensemble_runner import EnsembleOrtRunner
        ensemble = EnsembleOrtRunner(ensemble_dir, n_threads=threads)
        _say(f"[MPC] Loaded {ensemble.n_members} ONNX members: "
             + ", ".join(os.path.basename(p) for p in ensemble.paths))

        # Build env (v0.2: region-agnostic; v0.3: optional reward weights;
        # v0.4: --env-kind selects between county-level (CountyLevelEnv) and
        # restoration-priority (RestorationEnv) environments).
        if env_kind == "restoration":
            _say("[MPC] Building RestorationEnv via "
                 "restoration_env.make_restoration_env (~1s data load)...")
        else:
            _say("[MPC] Building CountyLevelEnv via blocks_env.make_env "
                 "(~30-70s data load)...")
        t_env = time.time()
        if env_kind == "restoration":
            try:
                from farmland_mpc.restoration_env import make_restoration_env as make_env
            except ImportError:
                from core.restoration_env import make_restoration_env as make_env
        else:
            try:
                from farmland_mpc.blocks_env import make_env
            except ImportError:
                from core.blocks_env import make_env

        env_kwargs = {}
        reward_overrides = {}
        for name, val in (
            ("slope_weight", slope_weight),
            ("cont_weight", cont_weight),
            ("baimu_weight", baimu_weight),
            ("baimu_bonus", baimu_bonus),
            ("baimu_area_penalty", baimu_area_penalty),
            ("cultivated_area_floor_delta_ha", cultivated_area_floor_delta_ha),
            ("baimu_area_floor_delta_ha", baimu_area_floor_delta_ha),
            ("gamma_conn", gamma_conn),
            ("delta_conn", delta_conn),
        ):
            if val is not None:
                env_kwargs[name] = float(val)
                if name in {
                    "slope_weight", "cont_weight", "baimu_weight",
                    "baimu_bonus", "baimu_area_penalty",
                }:
                    reward_overrides[name] = float(val)
        if reward_overrides:
            _say(
                "[MPC] WARNING: overriding env reward weights "
                + ", ".join(f"{k}={v}" for k, v in reward_overrides.items())
                + ". "
                "Effect: Tool 3's ensemble.reward_head predicts reward "
                "under the ORIGINAL training weights, not the overridden "
                "ones. When scoring='reward', MPC ranks candidates by the "
                "ensemble prediction, so the override has no effect on "
                "block selection -- it only changes the env.step() reward "
                "that episode_return etc. report. For the override to "
                "actually steer planning, retrain Tool 3 with these "
                "weights first. (When scoring='slope', MPC uses the env's "
                "slope delta directly, so the weight has no effect at "
                "all.)",
                level="warn",
            )

        if env_kind == "restoration":
            # RestorationEnv reads weights/budget/cost_col from
            # scenario_config.json in prepared/, so it ignores reward kwargs.
            if reward_overrides:
                _say("[MPC] (restoration env) reward overrides are ignored; "
                     "edit scenario_config.json before training.", level="warn")
            env = make_env(prepared_dir=prepared_dir)
        else:
            env = make_env(prepared_dir=prepared_dir, proj_crs=proj_crs,
                           **env_kwargs)
        if max_steps is not None and max_steps > 0:
            env.max_steps = int(max_steps)
            _say(f"[MPC] env.max_steps capped to {env.max_steps} for smoke test")
        _say(f"[MPC] env built in {time.time() - t_env:.1f}s; "
             f"n_blocks={env.n_blocks}, max_steps={env.max_steps}, "
             f"n_parcels={env.n_parcels}")

        # Verify ensemble was trained for the same n_blocks
        ensemble.assert_compatible(env.n_blocks)

        progress_total = {"done": 0}

        def _progress(step_idx, total, info, step_time):
            progress_total["done"] += 1
            if step_idx % 10 == 0 or step_idx == total:
                _say(f"    step {step_idx:3d}/{total} "
                     f"slope={info.get('slope_change_pct', 0):+.4f}% "
                     f"cont={info.get('cont_change', 0):+.4f} "
                     f"baimu_ha={info.get('baimu_area_change_ha', 0):+.1f} "
                     f"mpc_step={step_time:.2f}s")

        # Run episodes
        results = []
        for ep in range(n_episodes):
            seed = seed_offset + ep
            _say(f"\n[MPC] === Episode {ep + 1}/{n_episodes} (seed={seed}) ===")
            t0 = time.time()
            info = _run_episode(env, ensemble, horizon, top_k, gamma,
                                continuation, scoring, seed, _progress,
                                batch_size=mpc_batch_size)
            ep_time = time.time() - t0
            record = {
                "episode": ep, "seed": seed,
                "slope_change_pct": float(info.get("slope_change_pct", 0.0)),
                "cont_change": float(info.get("cont_change", 0.0)),
                "baimu_count_change": int(info.get("baimu_count_change", 0)),
                "baimu_area_change_ha": float(info.get("baimu_area_change_ha", 0.0)),
                "total_reward": float(info.get("total_reward", 0.0)),
                "steps_run": int(info.get("steps_run", 0)),
                "swaps_completed": int(info.get("budget_used", 0)),
                "mean_step_time_s": float(info.get("mean_step_time", 0.0)),
                "total_time_s": float(ep_time),
            }
            for key in (
                "cultivated_area_ha",
                "cultivated_area_change_ha",
                "cultivated_area_change_pct",
                "cultivated_area_floor_delta_ha",
                "cultivated_area_floor_ha",
                "baimu_area_floor_delta_ha",
                "baimu_area_floor_ha",
            ):
                if key in info:
                    record[key] = info[key]
            # For RestorationEnv add the natural-resources-specific summary
            # (n_selected, budget_used, per-component cumulative rewards).
            if env_kind == "restoration":
                record["n_selected"] = int(env.selected.sum())
                record["budget_used"] = float(env.budget_used)
                record["budget_fraction_used"] = float(env.budget_used / max(env.budget, 1e-6))
                # Per-component cumulative reward (first 8 reward terms)
                for j, term_name in enumerate(list(env.reward_terms.keys())[:8]):
                    record[f"cum_{term_name}"] = float(env._cum_reward_components[j])
            results.append(record)
            if env_kind == "restoration":
                _say(f"[MPC] ep {ep}: total_reward={record['total_reward']:+.2f} "
                     f"n_selected={record['n_selected']} "
                     f"budget_used={record['budget_used']:.1f}/{env.budget:.1f} "
                     f"({100*record['budget_fraction_used']:.1f}%) "
                     f"time={ep_time:.1f}s")
            else:
                _say(f"[MPC] ep {ep}: slope={record['slope_change_pct']:+.4f}% "
                     f"cont={record['cont_change']:+.4f} "
                     f"baimu_ha={record['baimu_area_change_ha']:+.2f} "
                     f"time={ep_time:.1f}s")

            np.save(out_dir / "mpc_land_use.npy", env.land_use.astype(np.int8))

        # Aggregate
        slopes = [r["slope_change_pct"] for r in results]
        conts  = [r["cont_change"] for r in results]
        baimu  = [r["baimu_area_change_ha"] for r in results]
        summary = {
            "config": {
                "horizon": horizon, "top_k": top_k, "gamma": gamma,
                "continuation": continuation, "scoring": scoring,
                "mpc_batch_size": int(mpc_batch_size),
                "n_episodes": n_episodes, "threads": threads,
                "max_steps": env.max_steps, "n_blocks": int(env.n_blocks),
                "n_parcels": int(env.n_parcels),
                "prepared_dir": getattr(env, "_prepared_dir", None),
                "proj_crs": proj_crs,
                "reward_overrides": reward_overrides,
                "cultivated_area_floor_delta_ha": cultivated_area_floor_delta_ha,
                "baimu_area_floor_delta_ha": baimu_area_floor_delta_ha,
                "pair_selection_overrides": {
                    "gamma_conn": gamma_conn,
                    "delta_conn": delta_conn,
                },
            },
            "ensemble": {
                "n_members": ensemble.n_members,
                "paths": [os.path.basename(p) for p in ensemble.paths],
            },
            "results": results,
            "aggregate": {
                "slope_pct_mean": float(np.mean(slopes)),
                "slope_pct_std":  float(np.std(slopes, ddof=1)) if len(slopes) > 1 else 0.0,
                "cont_mean":      float(np.mean(conts)),
                "baimu_ha_mean":  float(np.mean(baimu)),
            },
        }

        # Optional: write optimized DLTB feature class
        if output_fc:
            _say(f"\n[MPC] Writing optimized DLTB to {output_fc} ...")
            try:
                from farmland_mpc.shapefile_io import infer_swap_codes, write_optimized_dltb
            except ImportError:
                from core.shapefile_io import infer_swap_codes, write_optimized_dltb
            if farm_dlbm is None or forest_dlbm is None:
                import geopandas as gpd

                input_codes = gpd.read_file(input_dltb_fc, columns=["DLBM"])["DLBM"]
                inferred_farm, inferred_forest = infer_swap_codes(input_codes)
                farm_dlbm = farm_dlbm or inferred_farm
                forest_dlbm = forest_dlbm or inferred_forest
                _say(
                    f"[MPC] inferred output DLBM codes: farm={farm_dlbm}, "
                    f"forest={forest_dlbm}"
                )
            shp_stats = write_optimized_dltb(
                input_fc=input_dltb_fc, output_fc=output_fc, env=env,
                farm_dlbm=farm_dlbm, forest_dlbm=forest_dlbm,
                messages=messages,
            )
            summary["shapefile_output"] = shp_stats

        with open(out_dir / "mpc_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        _say("")
        _say("[MPC] ==== Summary ====")
        _say(f"  slope: {summary['aggregate']['slope_pct_mean']:+.4f}% "
             f"+- {summary['aggregate']['slope_pct_std']:.4f}")
        _say(f"  cont : {summary['aggregate']['cont_mean']:+.4f}")
        _say(f"  baimu: {summary['aggregate']['baimu_ha_mean']:+.2f} ha")
        _say(f"  outputs written to {out_dir}")
        if output_fc:
            _say(f"  optimized feature class: {output_fc}")

        return summary
    finally:
        logging.getLogger().removeHandler(fh)
        fh.close()
