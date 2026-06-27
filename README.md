# Paper9 MNR Offline Package

This package is a standalone, ArcGIS-free engineering bundle for running
Paper9/Paper9v2 and recalibrating it on Ministry of Natural Resources
authoritative parcel data inside an intranet.

The default workflow assumes two authoritative Ministry inputs:

1. DLTB parcels with an authoritative slope attribute.
2. Administrative boundaries that can be resolved to village/community level.

Preparation reads slope from the parcel attribute and uses the administrative
layer as a reference label layer:

```powershell
--slope-method from_field --slope-field slope_mean
--reference-layer data/input/admin_units.gpkg --reference-name-field XZQMC
```

Reward changes are treated as model-label changes. For business calibration,
rerun `sample` and `train` before `plan`; do not only rerun planning with an old
model.

The current Docker deployment baseline is Paper9v2. Its default configuration is:

```powershell
configs\paper9v2_no_net_loss_authority_slope.yml
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
paper9-mnr check-config configs\paper9v2_no_net_loss_authority_slope.yml
paper9-mnr print-plan configs\paper9v2_no_net_loss_authority_slope.yml
paper9-mnr run-full configs\paper9v2_no_net_loss_authority_slope.yml
```

Read the `docs/` files in order before moving real Ministry data into
`data/input/`.

For the customer-facing runbook that describes required data, operation steps,
and delivered outputs, see docs/09_mnr_customer_runbook.md.

Current MNR Docker target profile:

- Customer hosts reported: `deepin server 16`, `x86_64`.
- Container runtime now allowed by customer policy; use Docker as the default runtime.
- Use the `linux/amd64` image package on these hosts:
  `dist/paper9-mnr-container-runtime-paper9v2-2.0.0-amd64.tar.gz`.
- Use the immutable Paper9v2 image reference:
  `paper9-mnr-offline:paper9v2-2.0.0-amd64`.
- The `linux/arm64` package is still generated for other ARM servers, but it is not the
  default package for the reported MNR hosts.

Latest Paper9v2 Docker E2E evidence is in
`docs/reports/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md`.
Both Dongxing and Bishan completed `prepare -> sample -> train -> plan -> audit`
with the Paper9v2 hard gates passing.

For a brand-new Linux machine with no Python/conda environment and no network,
this repository alone is not copy-and-run. Build and ship a Linux runtime bundle
first; see docs/10_linux_airgap_bundle.md.

For Docker/OCI deployment with separate linux/amd64 and linux/arm64 image tar
files, see docs/11_container_deployment.md.

If the target Linux host does not have Docker/Podman but allows offline
installation of a container runtime, see docs/12_container_runtime_airgap.md.

For the optional JupyterLab mode and formal run logs, see
docs/13_notebook_and_logs.md.

For the current dual-mode container image runbook covering command-line batch
mode and Notebook extension mode, see docs/14_dual_mode_image_usage.md.

For the current handoff notes, reproducibility evidence, and next onsite
deployment actions, see docs/15_current_handoff.md.

For validation on a faster macOS workstation, see docs/08_macos_validation.md.
