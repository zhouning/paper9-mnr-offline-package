# Paper9 MNR Offline Package

This package is a standalone, ArcGIS-free engineering bundle for running
Paper9/Paper9v2 and recalibrating it on Ministry of Natural Resources
authoritative parcel data inside an intranet.

The current Zhongning delivery profile is Paper9v2.3.0 / package 0.4.0. It
accepts one province-wide DLTB dataset. When Docker is allowed, the preferred
delivery is the `linux/amd64` image
`paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64`; a native Windows runtime remains
available as a fallback. Both deliveries supply four Copernicus GLO-30 DEM
tiles and a 13-feature Zhongning township reference, filters county code
`640521`, and records PDT, ecological redline, and permanent basic farmland as
not provided and not evaluated. This profile is for exploratory technical
validation only and cannot establish regulatory compliance. See
`docs/21_paper9v23_dltb_only_release.md`,
`docs/22_windows_native_airgap.md`, and the Windows validation handoff in
`docs/23_windows_native_validation_20260808.md`. Docker deployment is documented
in `docs/24_paper9v23_windows_docker.md`.

The one-command Windows workflow is:

```powershell
.\bin\run-paper9-windows.ps1 all -DltbSource "E:\authority\DLTB.gdb"
```

The portable Windows runtime must be built and smoke-tested on a networked
Windows x64 build machine before transfer to the intranet. The target machine
does not need Docker, Python, Conda, ArcGIS, administrator rights, or network
access.

The repository stores the built-in DLTB and DEM assets with Git LFS. A Windows
build machine must run `git lfs pull` before building the offline ZIP.

The v2.3 package also carries two reproducible sample datasets for local or
Windows smoke testing: Dongxing (`-Dataset dongxing`) and Bishan (`-Dataset
bishan`). Dongxing is the recommended first validation because its DLTB code
`511011` matches the bundled current administrative reference. Bishan's source
uses legacy code `500227`; the wrapper maps it explicitly to current reference
code `500120` and records that mapping in the dataset manifest.

The Paper9v2.2.3 customer workflow accepts four independent FileGDB directories
for each county:

1. 2025 DLTB parcels.
2. PDT slope classes.
3. Ecological protection redlines.
4. Permanent basic farmland.

The customer does not supply layer names, a county name, CRS parameters, a DEM,
Python, or ArcPy. The offline bundle carries three Copernicus DEM GLO-30 tiles
covering Dongxing and Bishan, plus a 44-feature township spatial reference
derived from the supplied `xiangzhen.shp`. The `fuse` action identifies the four
polygon layers, derives continuous parcel slope, applies protection locks, and
creates the exact Paper9 inputs:

```bash
./bin/run-paper9-container.sh fuse \
  --dltb-gdb /path/to/dltb.gdb \
  --pdt-gdb /path/to/pdt.gdb \
  --eco-redline-gdb /path/to/stbhhx.gdb \
  --permanent-basic-farmland-gdb /path/to/yjjbnt.gdb
```

PDT is retained only as a quality-control comparison against DEM-derived slope
classes. It does not set `slope_mean`, exchange locks, or optimizer behavior.
All container actions run with networking disabled. FileGDB, DEM, and township
reference mounts are read-only; no ArcGIS component is used. Detailed host,
fusion, stage, and failure diagnostics are written to `DATA_ROOT/outputs/logs/`.
After fusion, `DATA_ROOT/FUSION_OUTPUTS.txt` lists every host-side fusion file
with its absolute path, byte size, and SHA-256. Production DLBM classification
uses GB/T 21010-2017 / Third National Land Survey four-digit base codes.

Reward changes are treated as model-label changes. For business calibration,
rerun `sample` and `train` before `plan`; do not only rerun planning with an old
model.

The current Docker deployment baseline is Paper9v2.2. Its default configuration is:

```powershell
configs\paper9v22_authority_constraints.yml
```

Paper9v2 treats the following business checks as hard gates: county-level
cultivated land area must not decrease, average cultivated land slope must
decrease, and contiguity must increase. Hundred-mu field count/area is reported
and optimized where possible, but it is not the default hard-failure condition.

Quick local checks:

```powershell
python scripts\00_check_env.py --no-heavy
python -m pytest tests -q
```

After offline dependency installation:

```powershell
paper9-mnr check-config configs\paper9v22_authority_constraints.yml
paper9-mnr print-plan configs\paper9v22_authority_constraints.yml
paper9-mnr run-full configs\paper9v22_authority_constraints.yml
```

Read the `docs/` files in order before moving real Ministry data into
`data/input/`.

For the customer-facing runbook that describes required data, operation steps,
and delivered outputs, see docs/09_mnr_customer_runbook.md.

Current MNR Docker target profile:

- Customer hosts reported: `deepin server 16`, `x86_64`.
- 2026-07-01 onsite logs show the target x86_64 CPU flags are missing `sse4_1`
  and `popcnt`, so the current amd64 default is the `legacy-amd64` package:
  `dist/paper9-mnr-offline-container-paper9v2-2.2.3-legacy-amd64.tar.gz`.
- Use the immutable Paper9v2.2 legacy image reference:
  `paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64`.
- The standalone legacy amd64 image tar is:
  `dist/paper9-mnr-offline-paper9v2-2.2.3-legacy-linux-amd64.tar`.
- Container runtime now allowed by customer policy; use Docker as the default runtime.
- A separate `linux/arm64` package can be built for other ARM servers, but it is not
  part of the current MNR x86_64 delivery.

Historical Paper9v2.1 legacy-amd64 Docker E2E evidence is in
`docs/reports/paper9v21_legacy_amd64_e2e_20260701/REPORT.md`.
That v2.1 candidate completed `prepare -> sample -> train -> plan -> audit`
on real data with the Paper9v2 hard gates passing, and an Intel Windows workstation
has also rebuilt and tested the same legacy-amd64 image from GitHub source. The older
Paper9v2.0 dual-data report remains available at
`docs/reports/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md` as historical
baseline evidence.

Paper9v2.2.3 adds four-FileGDB ArcPy-free fusion, bundled-DEM parcel slope calculation,
a bundled Dongxing/Bishan township reference, detailed offline diagnostics, and
bidirectional exchange locking for ecological redlines and permanent basic
farmland. The source and container release are verified independently from
the historical v2.1 E2E result. A formal Dongxing/Bishan v2.2 E2E run still
requires the customer FileGDBs; the DEM is already part of the delivery. See
`docs/18_authoritative_filegdb_fusion.md`, `docs/19_paper9v22_release.md`, and
`docs/20_paper9v223_release.md`.

For a brand-new Linux machine with no Python/conda environment and no network,
this repository alone is not copy-and-run. Build and ship a Linux runtime bundle
first; see docs/10_linux_airgap_bundle.md.

For Docker/OCI deployment with separate linux/amd64 and linux/arm64 image tar
files, see docs/11_container_deployment.md.

To rebuild the current Paper9v2.2 legacy amd64 image from source on an Intel
Windows workstation, use Docker Desktop Linux containers and build the image
directly instead of copying the exported image tar:

```powershell
docker buildx build `
  --platform linux/amd64 `
  --build-arg LEGACY_X86_64=1 `
  --build-arg HTTP_PROXY=http://host.docker.internal:7897 `
  --build-arg HTTPS_PROXY=http://host.docker.internal:7897 `
  --build-arg NO_PROXY=localhost,127.0.0.1,host.docker.internal `
  --load `
  -t paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64 .

docker run --rm --platform linux/amd64 `
  paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64 `
  python scripts/check_legacy_cpu_compat.py --require-legacy-amd64
```

If the Windows host does not need a proxy for Docker builds, remove the three
proxy build args. For full pipeline runs and bundle packaging, WSL2 or Git Bash
is recommended because the operational scripts under `deploy/container-runtime/`
are POSIX shell scripts.

If the target Linux host does not have Docker/Podman but allows offline
installation of a container runtime, see docs/12_container_runtime_airgap.md.

For the optional JupyterLab mode and formal run logs, see
docs/13_notebook_and_logs.md.

For the current dual-mode container image runbook covering command-line batch
mode and Notebook extension mode, see docs/14_dual_mode_image_usage.md.

For the current handoff notes, reproducibility evidence, and next onsite
deployment actions, see docs/15_current_handoff.md.

For validation on a faster macOS workstation, see docs/08_macos_validation.md.
