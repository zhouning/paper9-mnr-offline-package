# Paper9v2.3 Windows Docker validation handoff (2026-08-08)

This report records the Windows-side validation of commit `851b7ef`
(`feat: add Paper9v2.3 Windows Docker delivery`). It is the handoff evidence
for the macOS side and for an offline/intranet deployment team.

## Host and image

| Item | Value |
|---|---|
| Host | Windows x64 |
| Docker Desktop | 4.85.0 |
| Docker Engine | 29.6.2 |
| Docker context | `desktop-linux` |
| Container platform | `linux/amd64` |
| Runtime network | `--network none` |
| Image | `paper9-mnr-offline:paper9v2-2.3.0-legacy-amd64` |
| Image digest | `sha256:d00ed3cb905e766876ae1f442d7500c2f024b207bba3bbb3ba4623a36a71ee78` |
| Image revision label | `851b7ef` |
| Input profile | `dltb_dem_only` |

The image was rebuilt on Windows from the GitHub checkout with the legacy
x86-64 CPU compatibility profile. The environment check covered Python 3.11,
GDAL/Rasterio/GeoPandas, PyTorch, ONNX Runtime, Typer, JupyterLab and Matplotlib;
the container test suite passed with three conditional skips. The focused
Windows Docker and runtime-script tests pass with `17 passed`.

## End-to-end Dongxing smoke

The PowerShell launcher was run with a Windows bind-mounted data root:

```powershell
.\deploy\windows-docker\run-paper9v23-docker.ps1 all `
  -Dataset dongxing `
  -Config configs/paper9v23_dongxing_container_smoke.yml `
  -DataRoot D:\tmp\paper9-v23-dongxing-smoke-20260808
```

The run manifest is `outputs/logs/run_full_pipeline-20260808-135621.json` in
that data root. All five stages completed with return code 0:

| Stage | Duration |
|---|---:|
| `prepare` | 1506.648 s |
| `sample` | 357.962 s |
| `train` | 4.895 s |
| `plan` | 1127.279 s |
| `audit` | 0.190 s |
| **Total** | **2997.011 s** |

The smoke used 100 transitions, 2 pairwise states x 5 actions, 1 ensemble
member and 100 MPC steps. It is a container/integration smoke, not a replacement
for the formal default-parameter acceptance run.

Audit evidence:

```text
all_expected_outputs_exist = true
hard_constraint_passed = true
cultivated_area_change_ha = +1.6715866540670394
slope_change_pct = -0.08066593181240474
cont_change = +0.00021865570472723306
regulatory_compliance_claim_allowed = false
```

The data-limited profile deliberately does not evaluate PDT, ecological redline
or permanent basic farmland. The result is exploratory technical validation only.
One Dongxing township had no usable blocks and was recorded as a warning while
the pipeline continued; it did not fail the hard gate.

## PowerShell and FileGDB contract

The Windows runtime path uses `run-paper9v23-docker.ps1` and contains no
`cmd.exe` dependency. Docker Desktop must be in Linux containers mode. Every
container invocation sets `PAPER9_OFFLINE=1`, `--platform linux/amd64` and
`--network none`.

For Zhongning, DLTB is intentionally not bundled. The onsite operator must
provide a complete Esri FileGDB directory, for example:

```powershell
.\bin\run-paper9v23-docker.ps1 all `
  -Dataset zhongning `
  -DltbSource 'E:\Ningxia\2025DLTB.gdb' `
  -DataRoot 'D:\paper9-data\zhongning'
```

`-DltbSource` is rejected unless it is an existing directory whose path ends in
`.gdb`; a single internal FileGDB file, archive or GeoPackage is not accepted.
Zhongning DEM and administrative reference data are included in the bundle.

## Offline artifact handoff

The image export and bundle were produced locally and are ignored build
artifacts, not Git blobs:

```text
dist/paper9-mnr-offline-paper9v2-2.3.0-legacy-linux-amd64.tar
  sha256: bbf025ead53034d72abf1a86aa23578f598152c2667ce5d6aec65a16d5ae2a56

dist/paper9-mnr-offline-container-paper9v2-2.3.0-legacy-amd64.tar.gz
  sha256: ce4c76658415d9b1d42f9d17c4ae0a576b1ca24a9caf4632a0f282264bf60160
```

After extraction, read `README.txt` first. `MANIFEST.json` records the image
digest, package metadata, built-in datasets and the fact that Zhongning DLTB is
external. `SHA256SUMS.txt` was verified successfully on this Windows host.

## macOS handoff

The macOS side can use this report as the Windows evidence baseline. The source
revision, image digest and bundle checksum above must remain unchanged when the
artifact is transferred. macOS should not claim that it executed the Windows
PowerShell workflow; it can independently inspect the manifest/checksums and
use the Linux container scripts where appropriate. Any onsite report must retain
the `dltb_dem_only` profile and the prohibition on regulatory-compliance claims.
