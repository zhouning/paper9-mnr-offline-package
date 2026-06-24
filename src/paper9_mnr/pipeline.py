"""Command construction for the offline Paper9 workflow."""

from __future__ import annotations

import shlex
from typing import Any, Mapping

from .config import validate_config


def build_prepare_args(config: Mapping[str, Any]) -> list[str]:
    validate_config(config)
    data = config["data"]
    fields = config["fields"]
    slope = config["slope"]
    prep = config.get("preparation", {})

    args = [
        "prepare",
        "--dltb",
        str(data["dltb"]),
        "--dem",
        str(data["dem"]),
        "--out",
        str(data["prepared_dir"]),
        "--slope-method",
        "from_field",
        "--slope-field",
        str(slope["field"]),
        "--dlbm-field",
        str(fields["dlbm"]),
        "--qsdwdm-field",
        str(fields["qsdwdm"]),
        "--bsm-field",
        str(fields["bsm"]),
    ]
    _append_optional(args, "--crs", config.get("crs"))
    _append_optional(args, "--min-parcels", prep.get("min_parcels"))
    _append_optional(args, "--min-area-ha", prep.get("min_area_ha"))
    _append_optional(args, "--max-parcels", prep.get("max_parcels"))
    _append_optional(args, "--min-parcels-per-township", prep.get("min_parcels_per_township"))
    return args


def build_sample_args(config: Mapping[str, Any]) -> list[str]:
    validate_config(config)
    sampling = config["sampling"]
    reward = config.get("reward", {})

    args = [
        "sample",
        "--prepared-dir",
        str(config["data"]["prepared_dir"]),
        "--n-episodes",
        str(sampling["n_episodes"]),
        "--n-states",
        str(sampling["n_states"]),
        "--n-actions",
        str(sampling["n_actions"]),
        "--seed",
        str(sampling["seed"]),
    ]
    _append_optional(args, "--crs", config.get("crs"))
    _append_optional(args, "--slope-weight", reward.get("slope_weight"))
    _append_optional(args, "--cont-weight", reward.get("cont_weight"))
    _append_optional(args, "--baimu-weight", reward.get("baimu_weight"))
    _append_optional(args, "--baimu-bonus", reward.get("baimu_bonus"))
    _append_optional(args, "--baimu-area-penalty", reward.get("baimu_area_penalty"))
    return args


def build_train_args(config: Mapping[str, Any]) -> list[str]:
    validate_config(config)
    training = config["training"]
    args = [
        "train",
        "--prepared-dir",
        str(config["data"]["prepared_dir"]),
        "--n-members",
        str(training["n_members"]),
        "--epochs",
        str(training["epochs"]),
        "--patience",
        str(training["patience"]),
        "--lambda-rank",
        str(training["lambda_rank"]),
    ]
    _append_optional(args, "--margin", training.get("margin"))
    _append_optional(args, "--batch-size", training.get("batch_size"))
    _append_optional(args, "--seed-base", training.get("seed_base"))
    _append_optional(args, "--torch-threads", training.get("torch_threads"))
    _append_optional(args, "--out-subdir", training.get("out_subdir"))
    return args


def build_plan_args(config: Mapping[str, Any]) -> list[str]:
    validate_config(config)
    planning = config["planning"]
    constraints = planning.get("constraints", {})
    reward = config.get("reward", {})
    out_subdir = config["training"].get("out_subdir", "tool3")
    ensemble_dir = f"{config['data']['prepared_dir']}/{out_subdir}"

    args = [
        "plan",
        "--ensemble-dir",
        ensemble_dir,
        "--prepared-dir",
        str(config["data"]["prepared_dir"]),
        "--out-dir",
        str(config["outputs"]["plan_dir"]),
        "--horizon",
        str(planning["horizon"]),
        "--top-k",
        str(planning["top_k"]),
        "--n-episodes",
        str(planning["n_episodes"]),
        "--output-shp",
        str(config["outputs"]["optimized_vector"]),
    ]
    _append_optional(args, "--crs", config.get("crs"))
    _append_optional(args, "--mpc-batch-size", planning.get("mpc_batch_size"))
    _append_optional(args, "--continuation", planning.get("continuation"))
    _append_optional(args, "--scoring", planning.get("scoring"))
    _append_optional(args, "--threads", planning.get("threads"))
    _append_optional(args, "--seed-offset", planning.get("seed_offset"))
    _append_optional(args, "--baimu-area-penalty", reward.get("baimu_area_penalty"))
    _append_optional(args, "--cultivated-area-floor-delta-ha", constraints.get("cultivated_area_floor_delta_ha"))
    _append_optional(args, "--baimu-area-floor-delta-ha", constraints.get("baimu_area_floor_delta_ha"))
    _append_optional(args, "--gamma-conn", planning.get("gamma_conn"))
    _append_optional(args, "--delta-conn", planning.get("delta_conn"))
    return args


def build_stage_commands(config: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return runnable Python module commands for all stages."""
    return {
        "prepare": _module_command(build_prepare_args(config)),
        "sample": _module_command(build_sample_args(config)),
        "train": _module_command(build_train_args(config)),
        "plan": _module_command(build_plan_args(config)),
    }


def format_command(command: list[str]) -> str:
    """Format a command for logs and docs."""
    return " ".join(shlex.quote(str(part)) for part in command)


def _module_command(stage_args: list[str]) -> list[str]:
    return ["python", "-m", "farmland_mpc.cli", *stage_args]


def _append_optional(args: list[str], flag: str, value: object) -> None:
    if value is not None:
        args.extend([flag, str(value)])

