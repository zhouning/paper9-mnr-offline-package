# Windows Native Offline Validation Handoff (2026-08-08)

This document records the Windows x64 validation completed locally from commit `e89ce36`.

## Handoff conclusion

The native Windows runtime, offline ZIP, package check, and Dongxing end-to-end sample flow have been validated. Source fixes and regression tests should be committed to GitHub. The Windows runtime ZIP is an ignored build artifact and should be transferred as a GitHub Release asset or through internal artifact storage, together with its checksum sidecar.

## Source improvements

The five source/test files in this commit provide:

- GDAL/PROJ/PATH isolation while building the Windows runtime.
- Windows PowerShell 5.1 parsing compatibility and UTF-8 child-process settings.
- Correct Windows resolution of container `/app/...` paths.
- Windows Git Bash handling for container-runtime tests.
- Regression coverage for PowerShell parsing, UTF-8 initialization, and GDAL/PROJ setup.

## Validation evidence

- Native runtime: Windows x64, Python `3.11.15`.
- Full pytest: `117 passed`.
- Ruff core rules `E4,E7,E9,F` for modified files: passed.
- Extracted validation directory: `D:\paper9_zhongning`.
- `bin\run-paper9-windows.ps1 check`: exit code 0; package checksums and core imports passed.
- ZIP entries: `59,977`; no `.paper9-conda-unpacked`; wrapper has UTF-8 BOM.

Formal package:

```text
dist/paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64.zip
size: 1,154,519,074 bytes
sha256: 681b6869b0c5d110a103478ededb3fa4faa97c0c6ec4df3ae567c27dd4e40e8a
sidecar: dist/paper9-mnr-offline-paper9v2-2.3.0-windows-x86_64.zip.sha256
```

Dongxing `prepare -> sample -> train -> plan -> audit` artifacts passed structured validation:

| Item | Result |
|---|---:|
| transitions | 6,000 |
| pairwise states | 1,000 (50 actions/state) |
| ensemble members | 3 (PT/ONNX) |
| MPC steps | 100 |
| farm -> forest | 479 |
| forest -> farm | 479 |
| cultivated area change | +392.60 ha |
| slope change | -0.3457% |
| contiguity change | +0.0487 |
| hard constraint | passed |

## macOS handoff

1. After the source commit is pushed, run `git pull --ff-only` and verify this document and the five Windows fix/test files are present.
2. Do not add the Windows ZIP, `dist/build`, `D:\paper9_zhongning`, logs, or run outputs to the source commit; these are intentionally ignored.
3. The Windows ZIP must run on Windows x64. It cannot be cross-generated or executed as a Windows runtime on macOS, Linux, or WSL.
4. Transfer the ZIP and `.zip.sha256` together to an offline Windows host, then run `verify-paper9-package.ps1` and `run-paper9-windows.ps1 check`.
5. This profile contains DLTB + DEM only. PDT, ecological redline, and permanent basic farmland are `not_provided_not_evaluated`; `regulatory_compliance_claim_allowed` must remain `false`. Results are for exploratory technical validation only.
