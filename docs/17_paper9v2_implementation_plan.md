# Paper9v2 Business Constraints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Paper9v2 as the business-constrained Paper9 workflow: county cultivated area must not decrease, average cultivated-land slope must decrease, contiguity must increase, baimu-fang is optimized as a soft target, and container images are versioned explicitly.

**Architecture:** Keep the existing `prepare -> sample -> train -> plan -> audit` workflow. Add a small version metadata module, a v2 config profile, constraint-aware sample/plan command construction, hard audit gates from `mpc_summary.json`, and explicit container image references. Do not change the current region-specific ONNX/action-space model architecture in v2.0.

**Tech Stack:** Python 3.11, Typer CLI, PyYAML, pytest, Docker/Podman shell scripts, OCI image labels.

---

## File Structure

- Create `src/paper9_mnr/version.py`: single source for package version, algorithm name, and algorithm version.
- Modify `pyproject.toml`: bump package version from `0.1.0` to `0.2.0`.
- Modify `src/paper9_mnr/config.py`: validate optional `algorithm` metadata and v2 hard gates.
- Create `configs/paper9v2_no_net_loss_authority_slope.yml`: default Paper9v2 config with cultivated-area floor only.
- Modify `src/paper9_mnr/pipeline.py`: forward cultivated-area floor to sample and plan, preserve absent baimu-area floor.
- Modify `src/farmland_mpc/cli.py`: add Tool 2 `--cultivated-area-floor-delta-ha`.
- Modify `src/farmland_mpc/sample.py`: pass cultivated-area floor into `CountyLevelEnv` during Tool 2 sampling and write it into the Tool 2 summary.
- Create `src/paper9_mnr/audit.py`: reusable file existence and hard-constraint audit logic.
- Modify `scripts/05_audit.py`: call `paper9_mnr.audit`, write hard-constraint status into `outputs/audit_summary.json`, and return non-zero on hard gate failure.
- Modify `scripts/run_full_pipeline.py`: write version metadata and optional image reference into run manifests.
- Modify `Dockerfile`: add version build args and OCI labels.
- Modify `deploy/container-runtime/run-paper9-container.sh`: support `--image-ref` while preserving `--image` + `--arch`.
- Modify `deploy/container-runtime/package-container-runtime-bundle.sh`: accept image metadata and write `MANIFEST.json`.
- Modify `docs/11_container_deployment.md`, `docs/12_container_runtime_airgap.md`, and `docs/14_dual_mode_image_usage.md`: document Paper9v2 image tags and `--image-ref`.
- Update tests in `tests/test_command_builders.py`, `tests/test_container_runtime_scripts.py`, and add focused tests for config, sample constraints, audit constraints, and version metadata.

## Task 1: Version Metadata And Config Validation

**Files:**
- Create: `src/paper9_mnr/version.py`
- Modify: `pyproject.toml`
- Test: `tests/test_version_and_config.py`

- [ ] **Step 1: Write failing test for version constants**

Create `tests/test_version_and_config.py`:

```python
from paper9_mnr.version import ALGORITHM_NAME, ALGORITHM_VERSION, PACKAGE_VERSION


def test_version_constants_define_paper9v2_release():
    assert PACKAGE_VERSION == "0.2.0"
    assert ALGORITHM_NAME == "paper9v2"
    assert ALGORITHM_VERSION == "2.0.0"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_version_and_config.py -q
```

Expected: fail because `paper9_mnr.version` does not exist.

- [ ] **Step 3: Add version metadata**

Create `src/paper9_mnr/version.py`:

```python
"""Package and algorithm version metadata for Paper9 MNR offline runs."""

PACKAGE_VERSION = "0.2.0"
ALGORITHM_NAME = "paper9v2"
ALGORITHM_VERSION = "2.0.0"
```

Modify `pyproject.toml`:

```toml
version = "0.2.0"
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_version_and_config.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/paper9_mnr/version.py pyproject.toml tests/test_version_and_config.py
git commit -m "Add Paper9v2 version metadata"
```

## Task 2: Paper9v2 Config And Command Builders

**Files:**
- Create: `configs/paper9v2_no_net_loss_authority_slope.yml`
- Modify: `src/paper9_mnr/config.py`
- Modify: `src/paper9_mnr/pipeline.py`
- Modify: `tests/test_command_builders.py`
- Test: `tests/test_version_and_config.py`
- Test: `tests/test_command_builders.py`

- [ ] **Step 1: Write failing config and command-builder tests**

Append to `tests/test_version_and_config.py`:

```python
from pathlib import Path

import pytest

from paper9_mnr.config import ConfigError, load_config, validate_config


def test_paper9v2_config_validates():
    config = load_config(Path("configs/paper9v2_no_net_loss_authority_slope.yml"))

    validate_config(config)

    assert config["algorithm"]["name"] == "paper9v2"
    assert config["algorithm"]["version"] == "2.0.0"
    assert config["planning"]["constraints"]["cultivated_area_floor_delta_ha"] == 0
    assert "baimu_area_floor_delta_ha" not in config["planning"]["constraints"]


def test_paper9v2_requires_cultivated_area_floor():
    config = load_config(Path("configs/paper9v2_no_net_loss_authority_slope.yml"))
    config["planning"]["constraints"] = {}

    with pytest.raises(ConfigError, match="paper9v2 requires planning.constraints.cultivated_area_floor_delta_ha"):
        validate_config(config)
```

In `tests/test_command_builders.py`, add this test after `test_sample_args_forward_reward_overrides_for_calibration`:

```python
def test_sample_args_include_paper9v2_cultivated_area_floor_only():
    cfg = _config()
    cfg["algorithm"] = {"name": "paper9v2", "version": "2.0.0"}
    cfg["planning"]["constraints"] = {"cultivated_area_floor_delta_ha": 0}

    args = build_sample_args(cfg)

    assert _value_after(args, "--cultivated-area-floor-delta-ha") == "0"
    assert "--baimu-area-floor-delta-ha" not in args
```

Modify `test_plan_args_include_no_net_loss_constraints` so it asserts that baimu-area floor is not mandatory:

```python
def test_plan_args_include_paper9v2_cultivated_area_floor_only():
    cfg = _config()
    cfg["planning"]["constraints"] = {"cultivated_area_floor_delta_ha": 0}

    args = build_plan_args(cfg)

    assert _value_after(args, "--cultivated-area-floor-delta-ha") == "0"
    assert "--baimu-area-floor-delta-ha" not in args
    assert _value_after(args, "--output-shp") == "outputs/plan/DLTB_optimized.shp"
```

- [ ] **Step 2: Run config and command-builder tests to verify failure**

Run:

```bash
python -m pytest tests/test_version_and_config.py tests/test_command_builders.py::test_sample_args_include_paper9v2_cultivated_area_floor_only tests/test_command_builders.py::test_plan_args_include_paper9v2_cultivated_area_floor_only -q
```

Expected: fail because the v2 config does not exist and `build_sample_args` does not append `--cultivated-area-floor-delta-ha`.

- [ ] **Step 3: Create Paper9v2 config**

Create `configs/paper9v2_no_net_loss_authority_slope.yml`:

```yaml
algorithm:
  name: paper9v2
  version: 2.0.0

project:
  name: paper9-mnr-paper9v2-no-net-loss
  description: Paper9v2 authority-slope workflow with county cultivated-area no-net-loss.

crs: EPSG:32648

data:
  dltb: data/input/DLTB_with_authority_slope.gpkg
  admin_units: data/input/admin_units.gpkg
  dem: data/input/DEM_placeholder.tif
  prepared_dir: data/working/prepared_paper9v2_no_net_loss

fields:
  dlbm: DLBM
  qsdwdm: QSDWDM
  bsm: BSM
  admin_name: XZQMC

slope:
  source: field
  field: slope_mean

preparation:
  min_parcels: 3
  min_area_ha: 0.5
  max_parcels: 30
  min_parcels_per_township: 50

outputs:
  plan_dir: outputs/plan_paper9v2_no_net_loss
  optimized_vector: outputs/plan_paper9v2_no_net_loss/DLTB_optimized.shp

sampling:
  n_episodes: 60
  n_states: 1000
  n_actions: 50
  seed: 0

training:
  n_members: 3
  epochs: 30
  patience: 8
  lambda_rank: 5.0
  margin: 0.1
  batch_size: 256
  seed_base: 0
  torch_threads: 0
  out_subdir: tool3

planning:
  horizon: 5
  top_k: 50
  mpc_batch_size: 1024
  n_episodes: 1
  continuation: random
  scoring: reward
  threads: 0
  seed_offset: 0
  constraints:
    cultivated_area_floor_delta_ha: 0

reward:
  slope_weight: 4100.0
  cont_weight: 600.0
  baimu_weight: 2300.0
  baimu_bonus: 9.0
  baimu_area_penalty: 3100.0

workflow:
  force_resample_and_retrain_on_reward_change: true
```

- [ ] **Step 4: Validate Paper9v2 config metadata**

In `src/paper9_mnr/config.py`, add this import after existing imports:

```python
from .version import ALGORITHM_NAME, ALGORITHM_VERSION
```

Add this block near the end of `validate_config`, after reward profile validation:

```python
    algorithm = config.get("algorithm")
    if algorithm is not None:
        algorithm_map = _as_mapping(algorithm, "algorithm")
        name = algorithm_map.get("name")
        version = algorithm_map.get("version")
        if name == ALGORITHM_NAME:
            if str(version) != ALGORITHM_VERSION:
                raise ConfigError(
                    f"algorithm.version must be {ALGORITHM_VERSION!r} for {ALGORITHM_NAME}."
                )
            planning = _as_mapping(config["planning"], "planning")
            constraints = _as_mapping(planning.get("constraints", {}), "planning.constraints")
            if "cultivated_area_floor_delta_ha" not in constraints:
                raise ConfigError(
                    "paper9v2 requires planning.constraints.cultivated_area_floor_delta_ha."
                )
```

- [ ] **Step 5: Forward cultivated-area floor in command builders**

In `src/paper9_mnr/pipeline.py`, inside `build_sample_args`, add:

```python
    constraints = config.get("planning", {}).get("constraints", {})
```

Then append the constraint after reward options:

```python
    _append_optional(args, "--cultivated-area-floor-delta-ha", constraints.get("cultivated_area_floor_delta_ha"))
```

Do not append `--baimu-area-floor-delta-ha` in `build_sample_args` for v2.0.

Keep `build_plan_args` as-is for cultivated-area floor and baimu-area floor, because plan still supports optional baimu-area hard constraints when explicitly configured.

- [ ] **Step 6: Run tests**

Run:

```bash
python -m pytest tests/test_version_and_config.py tests/test_command_builders.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add configs/paper9v2_no_net_loss_authority_slope.yml src/paper9_mnr/config.py src/paper9_mnr/pipeline.py tests/test_command_builders.py tests/test_version_and_config.py
git commit -m "Add Paper9v2 no-net-loss config"
```

## Task 3: Tool 2 Cultivated-Area Constraint Sampling

**Files:**
- Modify: `src/farmland_mpc/cli.py`
- Modify: `src/farmland_mpc/sample.py`
- Test: `tests/test_sample_constraints.py`

- [ ] **Step 1: Write failing Tool 2 sample test**

Create `tests/test_sample_constraints.py`:

```python
import numpy as np

from farmland_mpc import sample


class _FakeEnv:
    n_blocks = 2
    n_parcels = 4
    max_steps = 1


def test_sample_passes_cultivated_area_floor_to_county_env(tmp_path, monkeypatch):
    captured = {}

    def fake_make_env(**kwargs):
        captured.update(kwargs)
        return _FakeEnv()

    monkeypatch.setattr(sample, "_import_make_env", lambda env_kind: fake_make_env)
    monkeypatch.setattr(
        sample,
        "_collect_transitions",
        lambda env, n_episodes, seed_offset, say: {
            "block_features": np.zeros((1, 2, 17), dtype=np.float32),
            "global_features": np.zeros((1, 12), dtype=np.float32),
            "actions": np.zeros((1,), dtype=np.int64),
            "rewards": np.zeros((1,), dtype=np.float32),
            "next_block_features": np.zeros((1, 2, 17), dtype=np.float32),
            "next_global_features": np.zeros((1, 12), dtype=np.float32),
        },
    )
    monkeypatch.setattr(
        sample,
        "_collect_pairwise",
        lambda env, n_states, n_actions, seed, max_outer_episodes, say: {
            "states_bf": np.zeros((1, 2, 17), dtype=np.float32),
            "states_gf": np.zeros((1, 12), dtype=np.float32),
            "actions": np.zeros((1, 1), dtype=np.int64),
            "rewards": np.zeros((1, 1), dtype=np.float32),
        },
    )

    summary = sample.run(
        prepared_dir=tmp_path,
        n_transition_episodes=1,
        n_pairwise_states=1,
        n_pairwise_actions=1,
        cultivated_area_floor_delta_ha=0,
    )

    assert captured["cultivated_area_floor_delta_ha"] == 0.0
    assert summary["config"]["constraint_overrides"] == {"cultivated_area_floor_delta_ha": 0.0}
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_sample_constraints.py -q
```

Expected: fail because `sample.run` does not accept `cultivated_area_floor_delta_ha`.

- [ ] **Step 3: Add CLI option for Tool 2**

In `src/farmland_mpc/cli.py`, add this option to `sample(...)` after `baimu_area_penalty`:

```python
    cultivated_area_floor_delta_ha: Optional[float] = typer.Option(
        None, "--cultivated-area-floor-delta-ha",
        help="Hard cumulative cultivated-area floor relative to initial area in ha during Tool 2 sampling.",
    ),
```

Pass it to `sample.run`:

```python
        cultivated_area_floor_delta_ha=cultivated_area_floor_delta_ha,
```

- [ ] **Step 4: Pass constraint into sample environment**

In `src/farmland_mpc/sample.py`, add `cultivated_area_floor_delta_ha` to `run(...)`:

```python
        baimu_area_penalty: Optional[float] = None,
        cultivated_area_floor_delta_ha: Optional[float] = None,
        messages=None) -> dict:
```

After `reward_overrides`, add:

```python
        constraint_overrides = {}
        if cultivated_area_floor_delta_ha is not None:
            constraint_overrides["cultivated_area_floor_delta_ha"] = float(cultivated_area_floor_delta_ha)
        if constraint_overrides:
            _say(
                "[Tool 2] constraint overrides: "
                + ", ".join(f"{k}={v}" for k, v in constraint_overrides.items())
            )
```

When building county env, pass both dictionaries:

```python
            env = make_env(
                prepared_dir=str(prepared_dir),
                proj_crs=proj_crs,
                **reward_overrides,
                **constraint_overrides,
            )
```

For restoration env, warn when constraints are supplied:

```python
            if constraint_overrides:
                _say("[Tool 2] constraint overrides ignored for restoration env", level="warn")
```

In the summary config, add:

```python
                "constraint_overrides": constraint_overrides,
```

- [ ] **Step 5: Run tests**

Run:

```bash
python -m pytest tests/test_sample_constraints.py tests/test_command_builders.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/farmland_mpc/cli.py src/farmland_mpc/sample.py tests/test_sample_constraints.py
git commit -m "Make Tool 2 sampling cultivated-area constrained"
```

## Task 4: Hard Audit Gates For Area, Slope, And Contiguity

**Files:**
- Create: `src/paper9_mnr/audit.py`
- Modify: `scripts/05_audit.py`
- Test: `tests/test_audit_constraints.py`

- [ ] **Step 1: Write failing audit tests**

Create `tests/test_audit_constraints.py`:

```python
import json

from paper9_mnr.audit import evaluate_hard_constraints


def _config():
    return {
        "algorithm": {"name": "paper9v2", "version": "2.0.0"},
        "planning": {"constraints": {"cultivated_area_floor_delta_ha": 0}},
    }


def test_hard_constraints_pass_when_area_slope_and_contiguity_pass():
    mpc_summary = {
        "results": [
            {
                "cultivated_area_change_ha": 0.25,
                "slope_change_pct": -0.1,
                "cont_change": 0.02,
                "baimu_count_change": 1,
                "baimu_area_change_ha": -10.0,
            }
        ]
    }

    status = evaluate_hard_constraints(_config(), mpc_summary)

    assert status["hard_constraint_passed"] is True
    assert status["failure_reasons"] == []
    assert status["baimu_is_hard_constraint"] is False


def test_hard_constraints_fail_with_specific_reasons():
    mpc_summary = {
        "results": [
            {
                "cultivated_area_change_ha": -1.5,
                "slope_change_pct": 0.01,
                "cont_change": 0.0,
                "baimu_count_change": 3,
                "baimu_area_change_ha": 12.0,
            }
        ]
    }

    status = evaluate_hard_constraints(_config(), mpc_summary)

    assert status["hard_constraint_passed"] is False
    assert status["failure_reasons"] == [
        "episode 0 cultivated_area_change_ha=-1.500000 < required 0.000000",
        "episode 0 slope_change_pct=0.010000 does not satisfy slope_change_pct < 0",
        "episode 0 cont_change=0.000000 does not satisfy cont_change > 0",
    ]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_audit_constraints.py -q
```

Expected: fail because `paper9_mnr.audit` does not exist.

- [ ] **Step 3: Implement audit helper**

Create `src/paper9_mnr/audit.py`:

```python
"""Audit helpers for Paper9 MNR workflow outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def expected_outputs(config: Mapping[str, Any]) -> dict[str, Path]:
    prepared_dir = Path(config["data"]["prepared_dir"])
    return {
        "prepared_dir": prepared_dir,
        "sample_transitions": prepared_dir / "tool2" / "transitions.npz",
        "sample_pairwise": prepared_dir / "tool2" / "pairwise.npz",
        "ensemble_dir": prepared_dir / config["training"].get("out_subdir", "tool3"),
        "plan_dir": Path(config["outputs"]["plan_dir"]),
        "optimized_vector": Path(config["outputs"]["optimized_vector"]),
        "mpc_summary": Path(config["outputs"]["plan_dir"]) / "mpc_summary.json",
    }


def evaluate_hard_constraints(config: Mapping[str, Any], mpc_summary: Mapping[str, Any]) -> dict[str, Any]:
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
        if area_delta < required_area - 1e-9:
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
```

- [ ] **Step 4: Use audit helper in script**

Replace the body of `scripts/05_audit.py` after config validation with:

```python
    from paper9_mnr.audit import build_audit_summary

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
```

- [ ] **Step 5: Run tests**

Run:

```bash
python -m pytest tests/test_audit_constraints.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/paper9_mnr/audit.py scripts/05_audit.py tests/test_audit_constraints.py
git commit -m "Add Paper9v2 hard audit gates"
```

## Task 5: Run Manifest Metadata

**Files:**
- Modify: `scripts/run_full_pipeline.py`
- Test: `tests/test_run_metadata.py`

- [ ] **Step 1: Write failing metadata test**

Create `tests/test_run_metadata.py`:

```python
import importlib.util
from pathlib import Path


def _load_run_full_pipeline():
    path = Path("scripts/run_full_pipeline.py")
    spec = importlib.util.spec_from_file_location("run_full_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_run_metadata_includes_versions_and_image_ref(monkeypatch):
    module = _load_run_full_pipeline()
    monkeypatch.setenv("PAPER9_IMAGE_REF", "paper9-mnr-offline:paper9v2-2.0.0-amd64")
    config = {"algorithm": {"name": "paper9v2", "version": "2.0.0"}}

    metadata = module._build_run_metadata(config)

    assert metadata["package_version"] == "0.2.0"
    assert metadata["algorithm_name"] == "paper9v2"
    assert metadata["algorithm_version"] == "2.0.0"
    assert metadata["image_ref"] == "paper9-mnr-offline:paper9v2-2.0.0-amd64"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_run_metadata.py -q
```

Expected: fail because `_build_run_metadata` does not exist.

- [ ] **Step 3: Add metadata helper and manifest field**

In `scripts/run_full_pipeline.py`, add imports:

```python
from paper9_mnr.version import ALGORITHM_NAME, ALGORITHM_VERSION, PACKAGE_VERSION
```

Add helper near `_default_log_dir`:

```python
def _build_run_metadata(config: dict[str, object]) -> dict[str, object]:
    algorithm = config.get("algorithm", {})
    if not isinstance(algorithm, dict):
        algorithm = {}
    return {
        "package_version": PACKAGE_VERSION,
        "algorithm_name": str(algorithm.get("name", ALGORITHM_NAME)),
        "algorithm_version": str(algorithm.get("version", ALGORITHM_VERSION)),
        "image_ref": os.environ.get("PAPER9_IMAGE_REF", ""),
    }
```

Add this key when constructing `manifest`:

```python
        "metadata": _build_run_metadata(config),
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_run_metadata.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/run_full_pipeline.py tests/test_run_metadata.py
git commit -m "Write Paper9v2 metadata to run manifests"
```

## Task 6: Container Image Reference And Bundle Metadata

**Files:**
- Modify: `Dockerfile`
- Modify: `deploy/container-runtime/run-paper9-container.sh`
- Modify: `deploy/container-runtime/package-container-runtime-bundle.sh`
- Modify: `tests/test_container_runtime_scripts.py`

- [ ] **Step 1: Write failing tests for image reference support**

Add to `tests/test_container_runtime_scripts.py`:

```python
def test_container_runtime_wrapper_supports_image_ref_and_exports_it():
    script = (PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh").read_text(encoding="utf-8")

    assert "--image-ref" in script
    assert 'image_ref="${2:-}"' in script
    assert 'tag="${image_ref:-$image:$arch}"' in script
    assert 'PAPER9_IMAGE_REF="$tag"' in script


def test_container_bundle_writes_manifest():
    script = (PACKAGE_ROOT / "deploy/container-runtime/package-container-runtime-bundle.sh").read_text(encoding="utf-8")

    assert "--image-ref" in script
    assert "MANIFEST.json" in script
    assert "algorithm_version" in script
    assert "sha256sum" in script or "shasum -a 256" in script
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_container_runtime_scripts.py -q
```

Expected: fail because the scripts do not support `--image-ref` or `MANIFEST.json`.

- [ ] **Step 3: Add OCI labels to Dockerfile**

Add build args after existing args:

```dockerfile
ARG PACKAGE_VERSION=0.2.0
ARG ALGORITHM_NAME=paper9v2
ARG ALGORITHM_VERSION=2.0.0
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
```

Add labels after `FROM ${BASE_IMAGE}` and arg declarations:

```dockerfile
LABEL org.opencontainers.image.title="paper9-mnr-offline" \
      org.opencontainers.image.version="${PACKAGE_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="https://github.com/zhouning/paper9-mnr-offline-package" \
      io.paper9.algorithm.name="${ALGORITHM_NAME}" \
      io.paper9.algorithm.version="${ALGORITHM_VERSION}"
```

- [ ] **Step 4: Add `--image-ref` to runtime wrapper**

In `deploy/container-runtime/run-paper9-container.sh`, add to usage:

```text
  --image-ref REF              Full image reference. Overrides --image + --arch tag construction.
```

Add variable:

```bash
image_ref=""
```

Add parser branch:

```bash
    --image-ref)
      image_ref="${2:-}"
      shift 2
      ;;
```

Replace:

```bash
tag="$image:$arch"
```

with:

```bash
tag="${image_ref:-$image:$arch}"
```

In `run_container`, export image ref:

```bash
  "$runtime" run --rm -e PAPER9_LOG_DIR=/app/outputs/logs -e PAPER9_IMAGE_REF="$tag" "${volume_args[@]}" "$tag" "$@"
```

In notebook mode, add:

```bash
      -e PAPER9_IMAGE_REF="$tag" \
```

- [ ] **Step 5: Add bundle manifest**

In `deploy/container-runtime/package-container-runtime-bundle.sh`, add usage options:

```text
  --image-ref REF              Image ref loaded by the image tar.
  --package-version VERSION    Package version. Default: 0.2.0.
  --algorithm-name NAME        Algorithm name. Default: paper9v2.
  --algorithm-version VERSION  Algorithm version. Default: 2.0.0.
  --git-commit COMMIT          Source commit. Default: unknown.
```

Add defaults:

```bash
image_ref=""
package_version="0.2.0"
algorithm_name="paper9v2"
algorithm_version="2.0.0"
git_commit="unknown"
```

Add parser branches for each option. After copying files, compute build time:

```bash
build_time="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
[ -n "$image_ref" ] || image_ref="paper9-mnr-offline:${algorithm_name}-${algorithm_version}-${arch}"
```

Write manifest:

```bash
cat > "$staging/MANIFEST.json" <<JSON
{
  "package_version": "${package_version}",
  "algorithm_name": "${algorithm_name}",
  "algorithm_version": "${algorithm_version}",
  "image_ref": "${image_ref}",
  "platform": "linux/${arch}",
  "git_commit": "${git_commit}",
  "build_time": "${build_time}",
  "default_config": "configs/paper9v2_no_net_loss_authority_slope.yml"
}
JSON
```

Write checksums:

```bash
(
  cd "$staging"
  if command -v sha256sum >/dev/null 2>&1; then
    find . -type f ! -name SHA256SUMS.txt -print | sort | sed 's#^\./##' | xargs sha256sum > SHA256SUMS.txt
  else
    find . -type f ! -name SHA256SUMS.txt -print | sort | sed 's#^\./##' | xargs shasum -a 256 > SHA256SUMS.txt
  fi
)
```

- [ ] **Step 6: Run tests**

Run:

```bash
python -m pytest tests/test_container_runtime_scripts.py -q
bash -n deploy/container-runtime/run-paper9-container.sh
bash -n deploy/container-runtime/package-container-runtime-bundle.sh
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add Dockerfile deploy/container-runtime/run-paper9-container.sh deploy/container-runtime/package-container-runtime-bundle.sh tests/test_container_runtime_scripts.py
git commit -m "Version Paper9v2 container images"
```

## Task 7: Documentation Updates And Verification

**Files:**
- Modify: `docs/11_container_deployment.md`
- Modify: `docs/12_container_runtime_airgap.md`
- Modify: `docs/14_dual_mode_image_usage.md`
- Test: `tests/test_package_integrity.py`

- [ ] **Step 1: Update container docs**

In all three docs, replace examples that use only `paper9-mnr-offline:amd64` for v2 release instructions with:

```text
paper9-mnr-offline:paper9v2-2.0.0-amd64
paper9-mnr-offline:paper9v2-2.0.0-arm64
```

For runtime wrapper examples, prefer:

```bash
./bin/run-paper9-container.sh check \
  --runtime docker \
  --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.0.0-amd64 \
  --image-tar images/paper9-mnr-offline-paper9v2-2.0.0-linux-amd64.tar \
  --config configs/paper9v2_no_net_loss_authority_slope.yml
```

Explain that `--image-ref` is the formal release reference and `--image paper9-mnr-offline --arch amd64` is retained for v1 compatibility.

- [ ] **Step 2: Add package integrity expectations**

If `tests/test_package_integrity.py` checks documented config names, add:

```python
assert "configs/paper9v2_no_net_loss_authority_slope.yml" in text
assert "paper9v2-2.0.0-amd64" in text
```

Use the local variable names already present in that test file.

- [ ] **Step 3: Run full lightweight verification**

Run:

```bash
python -m pytest tests -q
python scripts/run_full_pipeline.py configs/paper9v2_no_net_loss_authority_slope.yml --dry-run
python -m paper9_mnr.cli check-config configs/paper9v2_no_net_loss_authority_slope.yml
bash -n deploy/container-runtime/run-paper9-container.sh
bash -n deploy/container-runtime/package-container-runtime-bundle.sh
```

Expected:

- pytest exits with code 0.
- dry-run prints prepare, sample, train, and plan commands.
- dry-run sample command includes `--cultivated-area-floor-delta-ha 0`.
- dry-run plan command includes `--cultivated-area-floor-delta-ha 0`.
- check-config prints `OK: configs/paper9v2_no_net_loss_authority_slope.yml`.
- both shell syntax checks exit with code 0.

- [ ] **Step 4: Commit**

Run:

```bash
git add docs/11_container_deployment.md docs/12_container_runtime_airgap.md docs/14_dual_mode_image_usage.md tests/test_package_integrity.py
git commit -m "Document Paper9v2 container release workflow"
```

## Task 8: Final Verification And GitHub Push

**Files:**
- No source files should be edited in this task.

- [ ] **Step 1: Review final diff**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: working tree is clean, and the latest commits are the Paper9v2 implementation commits from Tasks 1-7.

- [ ] **Step 2: Push through local GitHub proxy**

Run:

```bash
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main
```

Expected: push succeeds and updates `main`.

- [ ] **Step 3: Verify remote commit**

Run:

```bash
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ls-remote origin refs/heads/main
```

Expected: remote `refs/heads/main` points at the local `HEAD` commit.

## Scope Deferred From Paper9v2.0

- Cross-county reusable ONNX model with dynamic action space.
- Baimu-fang area no-net-loss as a default hard constraint.
- Full Bishan/Dongxing production E2E after implementation. That is a separate validation run after lightweight tests pass.
- Multi-seed formal report generation. The implementation must support it, but the first code pass only needs to make the v2 single-run workflow correct and auditable.
