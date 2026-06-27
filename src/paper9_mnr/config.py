"""Configuration loading and validation for the MNR offline package."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from paper9_mnr.version import ALGORITHM_NAME, ALGORITHM_VERSION


class ConfigError(ValueError):
    """Raised when a package configuration is incomplete or unsafe."""


REQUIRED_TOP_LEVEL = (
    "project",
    "data",
    "fields",
    "slope",
    "outputs",
    "sampling",
    "training",
    "planning",
    "workflow",
)

REQUIRED_FIELDS = ("dlbm", "qsdwdm", "bsm")
REQUIRED_DATA = ("dltb", "dem", "prepared_dir")
REQUIRED_OUTPUTS = ("plan_dir", "optimized_vector")


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file and return its mapping."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {config_path}")
    return data


def validate_config(config: Mapping[str, Any]) -> None:
    """Validate the real-data workflow contract.

    The Ministry real-data default is intentionally conservative:
    authority slope is read from the parcel vector, and reward changes are
    treated as training-data changes that require sample + train reruns.
    """
    _require_mapping(config, REQUIRED_TOP_LEVEL, "config")
    _require_mapping(config["data"], REQUIRED_DATA, "data")
    _require_mapping(config["fields"], REQUIRED_FIELDS, "fields")
    _require_mapping(config["outputs"], REQUIRED_OUTPUTS, "outputs")

    algorithm = config.get("algorithm")
    if algorithm is not None:
        algorithm_map = _as_mapping(algorithm, "algorithm")
        if algorithm_map.get("name") == ALGORITHM_NAME:
            if algorithm_map.get("version") != ALGORITHM_VERSION:
                raise ConfigError(
                    f"algorithm.version must be {ALGORITHM_VERSION!r} "
                    f"when algorithm.name is {ALGORITHM_NAME!r}."
                )
            constraints = _as_mapping(
                _as_mapping(config["planning"], "planning").get("constraints", {}),
                "planning.constraints",
            )
            if "cultivated_area_floor_delta_ha" not in constraints:
                raise ConfigError("planning.constraints.cultivated_area_floor_delta_ha is required for paper9v2.")
            floor_delta = constraints["cultivated_area_floor_delta_ha"]
            if not isinstance(floor_delta, (int, float)) or isinstance(floor_delta, bool):
                raise ConfigError("planning.constraints.cultivated_area_floor_delta_ha must be numeric.")
            if float(floor_delta) < 0:
                raise ConfigError("planning.constraints.cultivated_area_floor_delta_ha must be >= 0.")

    slope = _as_mapping(config["slope"], "slope")
    source = slope.get("source")
    if source != "field":
        raise ConfigError(
            "slope.source must be 'field' for the MNR real-data default. "
            "Use the authority parcel slope attribute instead of recomputing DEM slope."
        )
    if not slope.get("field"):
        raise ConfigError("slope.field is required when slope.source is 'field'.")

    workflow = _as_mapping(config["workflow"], "workflow")
    if workflow.get("force_resample_and_retrain_on_reward_change") is not True:
        raise ConfigError(
            "Reward changes must rerun sample and train; set "
            "workflow.force_resample_and_retrain_on_reward_change: true."
        )

    _require_numeric_options(config["sampling"], "sampling", ("n_episodes", "n_states", "n_actions", "seed"))
    _require_numeric_options(config["training"], "training", ("n_members", "epochs", "patience", "lambda_rank"))
    _require_numeric_options(config["planning"], "planning", ("horizon", "top_k", "n_episodes"))

    reward_profiles = config.get("reward_profiles", {})
    if reward_profiles is not None:
        profiles = _as_mapping(reward_profiles, "reward_profiles")
        for name, profile in profiles.items():
            profile_map = _as_mapping(profile, f"reward_profiles.{name}")
            if profile_map.get("requires_resample_train") is not True:
                raise ConfigError(
                    f"reward_profiles.{name}.requires_resample_train must be true. "
                    "Reward profiles alter labels sampled from the environment."
                )


def reward_change_requires_resample_train(config: Mapping[str, Any], profile_name: str | None = None) -> bool:
    """Return whether the configured reward change requires sample + train."""
    workflow = _as_mapping(config.get("workflow", {}), "workflow")
    if workflow.get("force_resample_and_retrain_on_reward_change") is True:
        return True
    if profile_name:
        profiles = _as_mapping(config.get("reward_profiles", {}), "reward_profiles")
        profile = _as_mapping(profiles.get(profile_name, {}), f"reward_profiles.{profile_name}")
        return profile.get("requires_resample_train") is True
    return False


def _require_mapping(value: object, keys: tuple[str, ...], label: str) -> None:
    mapping = _as_mapping(value, label)
    missing = [key for key in keys if key not in mapping or mapping[key] in (None, "")]
    if missing:
        raise ConfigError(f"{label} missing required keys: {missing}")


def _require_numeric_options(value: object, label: str, keys: tuple[str, ...]) -> None:
    mapping = _as_mapping(value, label)
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ConfigError(f"{label} missing required keys: {missing}")
    for key in keys:
        if not isinstance(mapping[key], (int, float)):
            raise ConfigError(f"{label}.{key} must be numeric; got {mapping[key]!r}")


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{label} must be a mapping.")
    return value
