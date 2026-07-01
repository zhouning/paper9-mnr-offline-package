# Paper9v2.1 Legacy AMD64 Design

Date: 2026-07-01

## Purpose

The current `paper9v2-2.0.0-amd64` offline container fails on the MNR intranet host before reading any data because NumPy was built with an `X86_V2` baseline while the target x86_64 CPU flags do not include `sse4_1` or `popcnt`. The v2.1 release provides a replacement `linux/amd64` deployment package for older or virtualized x86_64 CPUs while preserving Paper9v2 algorithm behavior.

## Scope

Paper9v2.1 is a runtime compatibility release:

- Keep the algorithm name as `paper9v2`.
- Bump package version to `0.2.1`.
- Bump algorithm/release version to `2.1.0`.
- Build a `legacy-amd64` image tagged `paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64`.
- Keep `paper9v2_no_net_loss_authority_slope.yml` as the default profile, with the same cultivated-area no-net-loss constraint semantics.
- Do not change the prepare, sample, train, plan, or audit algorithms.

Out of scope:

- Rebuilding the ARM64 image.
- Native non-container Linux packaging.
- Rewriting PyTorch or ONNX Runtime from source unless the pinned legacy wheel image still fails on the target host.

## Architecture

The release adds a legacy dependency path to the existing Docker build. The Dockerfile will accept `LEGACY_X86_64=1` and install dependencies from a checked-in constraints file before installing the local package without dependency resolution. This makes the image deterministic and prevents pip from selecting newest wheels whose CPU baseline may exceed the target host.

The image build must run a full heavy import check, not the previous `--no-heavy` check. A new CPU compatibility probe records package versions and rejects NumPy builds that report `X86_V2` as their baseline.

The container wrapper defaults to the new immutable legacy image tag for amd64. Users may still pass `--image-ref` explicitly. Documentation and manifests will describe the legacy CPU target so that future failures can be distinguished from data/configuration failures.

## Dependency Strategy

The legacy constraints file pins the GIS, numeric, ML, CLI, and notebook runtime dependencies to stable versions intended for broad manylinux x86_64 compatibility. The first implementation should prefer pre-2026 wheel lines rather than the current unpinned latest packages that produced NumPy `2.4.6` and the `X86_V2` baseline failure.

The image is accepted only after:

- `python scripts/00_check_env.py --include-notebook` succeeds inside the image.
- `python scripts/check_legacy_cpu_compat.py --require-legacy-amd64` succeeds inside the image.
- `python -m pytest tests -q` succeeds inside the image.
- `paper9_mnr.version` and image labels report version `2.1.0`.

## Packaging

The deliverables are:

- `dist/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar`
- `dist/SHA256SUMS-paper9v2-2.1.0-legacy-amd64.txt`
- `dist/MANIFEST-paper9v2-2.1.0-legacy-amd64.json`
- `dist/paper9-mnr-offline-container-legacy-amd64-YYYYMMDD.tar.gz`

The lightweight container bundle contains the image tar, `run-paper9-container.sh`, configs, docs, notebooks, `PACKAGE_STATUS.md`, and `SHA256SUMS.txt`, matching the existing customer-facing package shape.

## Error Handling

If the build cannot obtain compatible wheels, the build should fail during dependency installation rather than silently falling back to unpinned latest dependencies. If a dependency imports successfully on the build host but later fails on the customer host, the customer should run:

```bash
./bin/run-paper9-container.sh check --runtime docker --arch amd64 \
  --image-ref paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64 \
  --image-tar images/paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar \
  --config configs/paper9v2_no_net_loss_authority_slope.yml \
  --data-root /data/paper9
```

That command performs heavy imports before the full pipeline runs.

## Testing

Automated tests cover:

- Version constants and Paper9v2 config metadata.
- Dockerfile legacy build arguments and heavy compatibility gates.
- Container runtime script defaults and docs for `paper9v2-2.1.0-legacy-amd64`.
- The legacy compatibility probe with injected fake NumPy baselines.
- Lightweight bundle assembly metadata and checksum generation.

Manual/build verification covers:

- Building the `linux/amd64` legacy image.
- Running full environment checks and tests inside the image.
- Saving, reloading, and inspecting the image tar.
- Assembling and checksumming the offline deployment bundle.
