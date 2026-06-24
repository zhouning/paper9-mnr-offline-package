# Paper9 MNR Offline Package

This package is a standalone, ArcGIS-free engineering bundle for reproducing
Paper9 and recalibrating it on Ministry of Natural Resources authoritative
parcel data inside an intranet.

The default workflow assumes the real parcel vector already contains an
authoritative slope attribute, so preparation uses:

```powershell
--slope-method from_field --slope-field slope_mean
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

For validation on a faster macOS workstation, see docs/08_macos_validation.md.

