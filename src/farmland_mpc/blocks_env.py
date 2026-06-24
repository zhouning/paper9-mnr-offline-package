"""Region-agnostic factory for CountyLevelEnv.

county_env.py declares DLTB_PATH, BLOCK_DIR, ALL_TOWNSHIPS, and
TOWNSHIP_CODES as module-level constants (placeholders by default).
Rather than fork the 900-line file per region, this module
monkey-patches those four constants from a user-supplied prepared_dir
before instantiating CountyLevelEnv.

This module also captures the per-parcel BSM (the Third-National-Survey
patch ID) onto the env instance, so that after MPC the caller can map
env-internal parcel indices back to DLTB.shp rows by BSM lookup.

Public surface:
    make_env(prepared_dir, total_budget=500, swaps_per_step=5, proj_crs=None,
             **env_kwargs) -> CountyLevelEnv

`prepared_dir` must contain (output of Tool 1):
    dem_slope_analysis/output/DLTB_with_slope.shp   (one parcel layer)
    results_real/blocks/township_<code>/block_compositions.json
    results_real/blocks/township_<code>/block_features.json (compactness)
    results_real/blocks/township_<code>/parcel_block_mapping.csv (optional)
    townships.json                                   {code: label, ...}
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional


# Default UTM zone 48N (CGCS2000 / WGS84) -- works for most of central
# and western China. Users in other zones (NE / NW / SE coast) MUST
# override via the proj_crs argument.
DEFAULT_PROJ_CRS = "EPSG:32648"


def _ensure_townships_json(prepared_dir: Path):
    """Load townships.json under prepared_dir, raising if missing.

    Returns the loaded dict (code -> label).
    """
    p = prepared_dir / "townships.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. Tool 1 should produce townships.json "
            "alongside results_real/blocks/."
        )
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def make_env(prepared_dir, total_budget=500, swaps_per_step=5,
             proj_crs=None, **env_kwargs):
    """Build a region-agnostic CountyLevelEnv via monkey-patching.

    Parameters
    ----------
    prepared_dir : str or Path
        Output directory of Tool 1. Required.
    total_budget, swaps_per_step : int
        Forwarded to CountyLevelEnv.
    proj_crs : str or None
        Override the projection used for area calculations. None =
        EPSG:32648 (UTM 48N). Set to EPSG:32649/47/etc. for other zones.
    **env_kwargs : dict
        Forwarded to CountyLevelEnv (slope_weight, baimu_weight, ...).
    """
    # core/ is on sys.path because the ArcGIS toolbox's .pyt inserts it.
    # In the standalone package, county_env is a sibling module of
    # blocks_env inside farmland_mpc; either import path works because
    # both use module-level constants that we patch in place.
    try:
        from farmland_mpc import county_env  # type: ignore[import-not-found]
    except ImportError:
        import county_env  # type: ignore[import-not-found]

    if prepared_dir is None:
        raise ValueError("make_env requires prepared_dir (output of Tool 1).")
    prepared_dir = Path(prepared_dir)

    # Resolve dltb path under prepared_dir. Tool 1 writes .shp; legacy
    # layouts may carry a .gpkg. Prefer .shp when both exist.
    out_dir = prepared_dir / "dem_slope_analysis" / "output"
    shp_candidate = out_dir / "DLTB_with_slope.shp"
    gpkg_candidate = out_dir / "DLTB_with_slope.gpkg"
    if shp_candidate.exists():
        dltb_path = shp_candidate
    elif gpkg_candidate.exists():
        dltb_path = gpkg_candidate
    else:
        raise FileNotFoundError(
            f"DLTB layer not found under {out_dir} (looked for "
            f"DLTB_with_slope.shp and DLTB_with_slope.gpkg)"
        )
    block_dir = prepared_dir / "results_real" / "blocks"

    if not block_dir.exists():
        raise FileNotFoundError(f"Block dir not found: {block_dir}")

    townships = _ensure_townships_json(prepared_dir)

    # Apply patches. DLTB_PATH and BLOCK_DIR must be string paths,
    # not Path objects (county_env uses os.path.join with them).
    county_env.DLTB_PATH = str(dltb_path)
    county_env.BLOCK_DIR = str(block_dir)
    county_env.ALL_TOWNSHIPS = dict(townships)
    county_env.TOWNSHIP_CODES = sorted(townships.keys())
    if proj_crs:
        county_env.PROJ_CRS = proj_crs

    # CountyLevelEnv must be re-imported from the same module object we
    # just patched, not from a fresh import path.
    CountyLevelEnv = county_env.CountyLevelEnv

    env = CountyLevelEnv(total_budget=total_budget,
                         swaps_per_step=swaps_per_step, **env_kwargs)

    # Attach BSM array for shapefile write-back. CountyLevelEnv discards
    # the BSM column inside _load_data; recover it from the same DLTB
    # using the same WHERE filter so the row order matches.
    _attach_bsm(env, dltb_path, county_env.TOWNSHIP_CODES)

    # Record provenance for debugging
    env._prepared_dir = str(prepared_dir)
    env._dltb_path = str(dltb_path)
    env._block_dir = str(block_dir)
    env._townships = dict(townships)
    return env


def _attach_bsm(env, dltb_path, township_codes):
    """Read BSM column from the same DLTB gpkg using the same row order
    as CountyLevelEnv._load_data, and attach as env._parcel_bsm.

    CountyLevelEnv builds gdf_swap = gdf[type_code in {FARMLAND, FOREST}]
    then reset_index(drop=True). We replicate exactly that filter so the
    BSM array aligns with env's parcel indices 0..n_parcels-1.
    """
    import geopandas as gpd
    import numpy as np

    where = " OR ".join([f"QSDWDM LIKE '{c}%'" for c in township_codes])
    gdf = gpd.read_file(dltb_path, where=where)
    # CountyLevelEnv's _classify_type uses these same prefixes
    farm = gdf['DLBM'].astype(str).str.startswith(('011', '012', '013'))
    forest = gdf['DLBM'].astype(str).str.startswith(('031', '032', '033'))
    keep = farm | forest
    gdf_swap = gdf[keep].reset_index(drop=True)
    if len(gdf_swap) != env.n_parcels:
        raise RuntimeError(
            f"BSM alignment mismatch: gdf_swap has {len(gdf_swap)} rows but "
            f"env.n_parcels = {env.n_parcels}. Did the DLTB change between "
            "env build and BSM attach?"
        )
    if 'BSM' not in gdf_swap.columns:
        raise RuntimeError(
            f"DLTB gpkg missing required field 'BSM': {dltb_path}. "
            "Tool 1 must preserve BSM from the source shapefile."
        )
    env._parcel_bsm = gdf_swap['BSM'].values
