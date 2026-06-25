# Paper9 MNR Offline Package

This package is a standalone, ArcGIS-free engineering bundle for reproducing
Paper9 and recalibrating it on Ministry of Natural Resources authoritative
parcel data inside an intranet.

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

Quick local checks:

```powershell
python scripts\00_check_env.py --no-heavy
python -m pytest tests -q
```

After offline dependency installation:

```powershell
paper9-mnr check-config configs\real_data_from_authority_slope.yml
paper9-mnr print-plan configs\real_data_from_authority_slope.yml
paper9-mnr run-full configs\real_data_from_authority_slope.yml
```

Read the `docs/` files in order before moving real Ministry data into
`data/input/`.

For the customer-facing runbook that describes required data, operation steps,
and delivered outputs, see docs/09_mnr_customer_runbook.md.

Current MNR Docker target profile:

- Customer hosts reported: `deepin server 16`, `x86_64`.
- Container runtime now allowed by customer policy; use Docker as the default runtime.
- Use the `linux/amd64` image package on these hosts:
  `dist/paper9-mnr-offline-container-amd64-20260625.tar.gz`.
- The `linux/arm64` package is still generated for other ARM servers, but it is not the
  default package for the reported MNR hosts.

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

For validation on a faster macOS workstation, see docs/08_macos_validation.md.
