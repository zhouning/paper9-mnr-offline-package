# Paper9v2.1 Legacy AMD64 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and package a Paper9v2.1 `legacy-amd64` offline container release that avoids the NumPy `X86_V2` baseline failure on older or restricted x86_64 CPUs.

**Architecture:** Keep the existing Paper9v2 algorithm and workflow intact. Add a legacy dependency constraints path to Docker builds, a CPU compatibility probe, v2.1 version metadata, legacy image defaults, and lightweight bundle assembly metadata. Verify with heavy imports and in-container tests before exporting the offline package.

**Tech Stack:** Python 3.11, pytest, pip constraints, Docker buildx, Bash packaging scripts, JSON manifests, SHA256 checksums.

---

## File Structure

- Modify `src/paper9_mnr/version.py`: bump package and algorithm versions.
- Modify `pyproject.toml`: bump package version and tighten upper bounds where needed.
- Create `constraints/legacy-x86_64.txt`: pinned legacy dependency set.
- Create `scripts/check_legacy_cpu_compat.py`: import-time compatibility probe.
- Modify `Dockerfile`: add `LEGACY_X86_64` build path, copy constraints, run heavy checks.
- Modify `deploy/container-runtime/run-paper9-container.sh`: default amd64 image tag to v2.1 legacy.
- Create `deploy/container-runtime/package-lightweight-container-bundle.sh`: assemble the customer-facing image bundle.
- Modify docs `README.md`, `docs/11_container_deployment.md`, `docs/12_container_runtime_airgap.md`, `docs/14_dual_mode_image_usage.md`, and `docs/15_current_handoff.md`: document v2.1 legacy usage.
- Modify tests under `tests/`: version, config, Dockerfile, container scripts, CPU probe, and bundle metadata.

## Task 1: Version And Config Metadata

**Files:**
- Modify: `src/paper9_mnr/version.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_version_and_config.py`

- [ ] **Step 1: Write failing version tests**

Change `tests/test_version_and_config.py` so `test_version_constants_define_paper9v2_release` expects:

```python
assert PACKAGE_VERSION == "0.2.1"
assert paper9_mnr.__version__ == PACKAGE_VERSION
assert ALGORITHM_NAME == "paper9v2"
assert ALGORITHM_VERSION == "2.1.0"
```

Also keep `test_paper9v2_no_net_loss_config_validates_with_cultivated_area_floor_only` asserting:

```python
assert config["algorithm"] == {"name": ALGORITHM_NAME, "version": ALGORITHM_VERSION}
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_version_and_config.py -q
```

Expected: fail because current metadata is `0.2.0` / `2.0.0`.

- [ ] **Step 3: Implement version bump**

Update `src/paper9_mnr/version.py`:

```python
PACKAGE_VERSION = "0.2.1"
ALGORITHM_NAME = "paper9v2"
ALGORITHM_VERSION = "2.1.0"
```

Update `pyproject.toml`:

```toml
version = "0.2.1"
```

Update `configs/paper9v2_no_net_loss_authority_slope.yml`:

```yaml
algorithm:
  name: paper9v2
  version: 2.1.0
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_version_and_config.py -q
```

Expected: pass.

## Task 2: Legacy CPU Probe

**Files:**
- Create: `scripts/check_legacy_cpu_compat.py`
- Create: `tests/test_legacy_cpu_compat.py`

- [ ] **Step 1: Write failing tests**

Create tests that call pure helper functions:

```python
from scripts.check_legacy_cpu_compat import baseline_is_legacy_safe, normalize_baseline


def test_normalize_baseline_accepts_numpy_list_string():
    assert normalize_baseline("['SSE', 'SSE2', 'SSE3']") == {"SSE", "SSE2", "SSE3"}


def test_baseline_rejects_x86_v2():
    assert baseline_is_legacy_safe({"SSE", "SSE2", "X86_V2"}) is False


def test_baseline_accepts_pre_v2_features():
    assert baseline_is_legacy_safe({"SSE", "SSE2", "SSE3", "SSSE3"}) is True
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_legacy_cpu_compat.py -q
```

Expected: fail because `scripts/check_legacy_cpu_compat.py` does not exist.

- [ ] **Step 3: Implement probe**

Implement:

- `normalize_baseline(value: object) -> set[str]`
- `baseline_is_legacy_safe(features: set[str]) -> bool`
- CLI flags `--require-legacy-amd64` and `--json`
- imports for `numpy`, `pandas`, `geopandas`, `rasterio`, `torch`, `onnxruntime`, `sklearn`, `scipy`
- non-zero exit when NumPy baseline contains `X86_V2`, `X86_V3`, `X86_V4`, `AVX`, `AVX2`, or `AVX512*`

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_legacy_cpu_compat.py -q
```

Expected: pass.

## Task 3: Docker Legacy Build Path

**Files:**
- Create: `constraints/legacy-x86_64.txt`
- Modify: `Dockerfile`
- Modify: `tests/test_package_integrity.py`

- [ ] **Step 1: Write failing Dockerfile tests**

Add assertions that:

- Dockerfile copies `constraints/legacy-x86_64.txt`.
- Dockerfile defines `ARG LEGACY_X86_64=0`.
- Dockerfile installs with `-c constraints/legacy-x86_64.txt` when legacy mode is enabled.
- Dockerfile runs `python scripts/00_check_env.py --include-notebook`.
- Dockerfile runs `python scripts/check_legacy_cpu_compat.py --require-legacy-amd64`.

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_package_integrity.py -q
```

Expected: fail on missing Dockerfile legacy strings.

- [ ] **Step 3: Implement Dockerfile and constraints**

Create `constraints/legacy-x86_64.txt` with pinned runtime dependencies. Use broad pre-2026 stable wheel versions and include `--extra-index-url https://download.pytorch.org/whl/cpu` only in Docker command, not in the constraints file.

Update Dockerfile to:

- copy `constraints/`
- install legacy dependencies first when `LEGACY_X86_64=1`
- install local package with `--no-deps`
- run full heavy checks and the legacy CPU probe
- keep normal build path for non-legacy builds

- [ ] **Step 4: Run test**

Run:

```bash
python -m pytest tests/test_package_integrity.py -q
```

Expected: pass.

## Task 4: Runtime Wrapper And Bundle Packaging

**Files:**
- Modify: `deploy/container-runtime/run-paper9-container.sh`
- Create: `deploy/container-runtime/package-lightweight-container-bundle.sh`
- Modify: `tests/test_container_runtime_scripts.py`

- [ ] **Step 1: Write failing tests**

Add tests requiring:

- default amd64 tag `paper9v2-2.1.0-legacy-amd64`
- examples use `paper9v2-2.1.0-legacy-amd64`
- lightweight bundle script is bash-parseable
- lightweight bundle manifest includes `cpu_compatibility`
- lightweight bundle README uses the legacy image tar name

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/test_container_runtime_scripts.py -q
```

Expected: fail because scripts still reference `2.0.0`.

- [ ] **Step 3: Implement scripts**

Update `run-paper9-container.sh` default tag selection so amd64 uses:

```bash
paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64
```

Create `package-lightweight-container-bundle.sh` that stages:

- `images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar`
- `bin/run-paper9-container.sh`
- `configs/`
- `docs/`
- `notebooks/`
- `README.md`
- `README_CONTAINER_IMAGE_BUNDLE.md`
- `PACKAGE_STATUS.md`
- `MANIFEST.json`
- `SHA256SUMS.txt`

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_container_runtime_scripts.py -q
```

Expected: pass.

## Task 5: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/11_container_deployment.md`
- Modify: `docs/12_container_runtime_airgap.md`
- Modify: `docs/14_dual_mode_image_usage.md`
- Modify: `docs/15_current_handoff.md`

- [ ] **Step 1: Write failing doc assertions**

Extend existing tests to assert docs contain:

```text
paper9v2-2.1.0-legacy-amd64
legacy-amd64
sse4_1
popcnt
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_container_runtime_scripts.py tests/test_package_integrity.py -q
```

Expected: fail on missing doc text.

- [ ] **Step 3: Update docs**

Update docs to identify v2.1 legacy as the default for the MNR x86_64 customer host and keep v2.0 references only as historical report references.

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_container_runtime_scripts.py tests/test_package_integrity.py -q
```

Expected: pass.

## Task 6: Build, Verify, And Package

**Files:**
- Generated: `dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar`
- Generated: `dist/SHA256SUMS-paper9v2-2.1.0-legacy-amd64.txt`
- Generated: `dist/MANIFEST-paper9v2-2.1.0-legacy-amd64.json`
- Generated: `dist/paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz`

- [ ] **Step 1: Run local tests**

Run:

```bash
python -m pytest tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Build legacy image**

Run:

```bash
docker buildx build --platform linux/amd64 --load \
  --build-arg LEGACY_X86_64=1 \
  --build-arg PACKAGE_VERSION=0.2.1 \
  --build-arg ALGORITHM_NAME=paper9v2 \
  --build-arg ALGORITHM_VERSION=2.1.0 \
  -t paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 .
```

Expected: build exits 0 after heavy import and CPU compatibility checks.

- [ ] **Step 3: Verify image**

Run:

```bash
docker run --rm --platform linux/amd64 paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  python scripts/00_check_env.py --include-notebook
docker run --rm --platform linux/amd64 paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  python scripts/check_legacy_cpu_compat.py --require-legacy-amd64
docker run --rm --platform linux/amd64 paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  python -m pytest tests -q
```

Expected: all commands exit 0.

- [ ] **Step 4: Export image and assemble bundle**

Run:

```bash
docker save paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  -o dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar
shasum -a 256 dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar \
  > dist/SHA256SUMS-paper9v2-2.1.0-legacy-amd64.txt
./deploy/container-runtime/package-lightweight-container-bundle.sh \
  --arch amd64 \
  --image-tar dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --package-version 0.2.1 \
  --algorithm-name paper9v2 \
  --algorithm-version 2.1.0 \
  --cpu-compatibility legacy-x86_64-without-x86-64-v2 \
  --out dist/paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz
```

Expected: exported tar, checksum, manifest, and bundle exist.

- [ ] **Step 5: Verify package**

Run:

```bash
tar -tzf dist/paper9-mnr-offline-container-legacy-amd64-20260701.tar.gz | head -40
shasum -a 256 -c dist/SHA256SUMS-paper9v2-2.1.0-legacy-amd64.txt
```

Expected: package has expected structure and checksum verifies.
