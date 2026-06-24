"""DLTB shapefile output helpers (pure-Python / geopandas).

Writes an optimized DLTB feature class with these added fields:

    OPT_DLBM   Text(3)   - optimized 3-digit land-use code
    OPT_DLMC   Text(40)  - optimized land-use Chinese name (looked up via DLMC dict)
    CHG_FLAG   Short     - 0=unchanged, 1=farm->forest, 2=forest->farm
    ORIG_DLBM  Text(3)   - original DLBM (preserved for audit)

The original toolbox implementation used ``arcpy.management.AddField`` +
``arcpy.da.UpdateCursor``; this version uses geopandas dataframe column
assignment + ``GeoDataFrame.to_file``. The semantics are identical and
the output schema matches the toolbox version byte-for-byte (modulo
shapefile's 10-char DBF column-name cap, which both paths respect).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import geopandas as gpd

logger = logging.getLogger(__name__)

# Default representative DLBM codes for the "after" state when a swap happens.
# Users can override via Tool 4 UI parameters.
DEFAULT_FARM_DLBM = "011"    # paddy / cultivated
DEFAULT_FOREST_DLBM = "031"  # forest

# CountyLevelEnv land_use enum (mirrors county_env.FARMLAND/FOREST)
ENV_FARMLAND = 1
ENV_FOREST = 2

# Shapefile DBF text field cap
SHP_TEXT_MAX = 254


def write_optimized_dltb(input_fc, output_fc, env,
                         farm_dlbm: str = DEFAULT_FARM_DLBM,
                         forest_dlbm: str = DEFAULT_FOREST_DLBM,
                         messages=None) -> dict:
    """Copy ``input_fc`` to ``output_fc`` and add OPT_*/CHG_FLAG columns.

    Parameters
    ----------
    input_fc : str | Path
        Source DLTB polygon file (shapefile, GeoPackage, FlatGeobuf, etc.).
        Required fields: BSM, DLBM, DLMC. Other fields pass through.
    output_fc : str | Path
        Output shapefile path. Will be overwritten if it exists.
    env : CountyLevelEnv with attached ``_parcel_bsm``
        Built by ``farmland_mpc.blocks_env.make_env``. Provides:
            env._parcel_bsm     (n_parcels,) BSM values aligned with env indices
            env.initial_types   (n_parcels,) int8: 1=farm 2=forest
            env.land_use        (n_parcels,) int8: post-MPC types
    farm_dlbm, forest_dlbm : str
        DLBM codes written for forest->farm and farm->forest swaps
        respectively.
    messages : optional
        ArcGIS Pro messages object. ``None`` when called from the CLI.

    Returns
    -------
    dict with counts: ``n_input``, ``n_in_env``, ``n_farm_to_forest``,
    ``n_forest_to_farm``, ``n_unchanged``.
    """
    def _say(msg, level="info"):
        if messages is not None:
            getattr(messages, "addMessage" if level == "info"
                    else "addWarningMessage")(msg)
        logger.info(msg)
        print(msg, flush=True)

    input_fc = Path(input_fc)
    output_fc = Path(output_fc)
    output_fc.parent.mkdir(parents=True, exist_ok=True)

    # BSM -> env_idx
    bsm_arr = env._parcel_bsm
    bsm_to_env_idx: dict[str, int] = {}
    for i, bsm in enumerate(bsm_arr):
        bsm_to_env_idx[_norm_bsm(bsm)] = i

    initial_types = env.initial_types
    final_types = env.land_use

    _say(f"[shp_out] Reading {input_fc} ...")
    gdf = gpd.read_file(input_fc)
    _validate_dltb_columns(gdf, ["BSM", "DLBM", "DLMC"])

    # DLBM -> DLMC lookup from the input's own rows (so OPT_DLMC follows
    # the user's Chinese-name conventions; varies subtly across regions).
    dlbm_to_dlmc: dict[str, str] = {}
    for dlbm, dlmc in zip(gdf["DLBM"].astype(str), gdf["DLMC"].astype(str)):
        dlbm = dlbm.strip()
        dlmc = dlmc.strip()
        if dlbm and dlmc and dlbm not in dlbm_to_dlmc:
            dlbm_to_dlmc[dlbm] = dlmc
    dlbm_to_dlmc.setdefault(farm_dlbm, "Farmland")
    dlbm_to_dlmc.setdefault(forest_dlbm, "Forest")

    # Allocate new columns
    n_input = len(gdf)
    orig_dlbm = gdf["DLBM"].astype(str).str.strip().values
    dlmc_orig = gdf["DLMC"].astype(str).str.strip().values
    opt_dlbm = orig_dlbm.copy().astype(object)
    opt_dlmc = dlmc_orig.copy().astype(object)
    chg_flag = np.zeros(n_input, dtype=np.int16)

    n_in_env = 0
    n_farm_to_forest = 0
    n_forest_to_farm = 0
    n_unchanged = 0

    # Decide per-row outcome
    bsms_norm = [_norm_bsm(b) for b in gdf["BSM"].values]
    for i, bsm_key in enumerate(bsms_norm):
        env_idx = bsm_to_env_idx.get(bsm_key)
        if env_idx is None:
            continue  # pass-through; flags already 0 and OPT_* already orig
        n_in_env += 1
        init = int(initial_types[env_idx])
        fin = int(final_types[env_idx])
        if init == ENV_FARMLAND and fin == ENV_FOREST:
            opt_dlbm[i] = forest_dlbm
            opt_dlmc[i] = dlbm_to_dlmc.get(forest_dlbm, "")
            chg_flag[i] = 1
            n_farm_to_forest += 1
        elif init == ENV_FOREST and fin == ENV_FARMLAND:
            opt_dlbm[i] = farm_dlbm
            opt_dlmc[i] = dlbm_to_dlmc.get(farm_dlbm, "")
            chg_flag[i] = 2
            n_forest_to_farm += 1
        else:
            n_unchanged += 1

    gdf["OPT_DLBM"] = opt_dlbm.astype(str)
    gdf["OPT_DLMC"] = opt_dlmc.astype(str)
    gdf["CHG_FLAG"] = chg_flag
    gdf["ORIG_DLBM"] = orig_dlbm

    # Pre-shapefile-export sanitisation: drop columns that cannot survive
    # a DBF write (BigInteger -> Int64; oversize text fields).
    export_gdf = _to_shapefile_safe(gdf)

    # Delete any existing output files to avoid the partial-write footgun
    if output_fc.exists():
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            try:
                output_fc.with_suffix(ext).unlink()
            except FileNotFoundError:
                pass

    _say(f"[shp_out] Writing {output_fc} ({len(export_gdf)} rows) ...")
    export_gdf.to_file(output_fc, driver="ESRI Shapefile", encoding="utf-8")

    _say(f"[shp_out] {n_input} input rows, {n_in_env} matched to env "
         f"({n_input - n_in_env} pass-through)")
    _say(f"[shp_out] swaps: farm->forest={n_farm_to_forest}, "
         f"forest->farm={n_forest_to_farm}, unchanged={n_unchanged}")
    if n_farm_to_forest != n_forest_to_farm:
        _say(f"[shp_out] WARNING: farmland count delta = "
             f"{n_forest_to_farm - n_farm_to_forest} (Paper 9 does NOT "
             "guarantee FC=0; this is expected)", level="warn")
    return {
        "n_input": n_input,
        "n_in_env": n_in_env,
        "n_farm_to_forest": n_farm_to_forest,
        "n_forest_to_farm": n_forest_to_farm,
        "n_unchanged": n_unchanged,
    }


# =============================================================================
# Helpers
# =============================================================================
def _norm_bsm(v) -> str:
    """Normalise BSM to a string key, handling float/int/str variants.

    Mirrors the arcpy-based helper exactly; numeric BSMs may arrive as
    821839.0 (float), 821839 (int), or '821839' (text) depending on
    whether the file is gpkg, shp, or geopandas-roundtripped. We collide
    all three on the same key.
    """
    if v is None:
        return ""
    try:
        import numpy as _np
        if isinstance(v, (_np.floating,)):
            v = float(v)
        elif isinstance(v, (_np.integer,)):
            v = int(v)
    except Exception:
        pass
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return f"{v:.6f}"
    return str(v).strip()


def _validate_dltb_columns(gdf: gpd.GeoDataFrame, required: list[str]) -> None:
    missing = [c for c in required if c not in gdf.columns]
    if missing:
        raise ValueError(
            f"DLTB missing required columns: {missing}. "
            f"Available: {list(gdf.columns)}"
        )


def _to_shapefile_safe(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Drop / coerce columns that cannot survive a DBF write.

    - Pandas Int64 dtype is silently cast to int32 (DBF max).
    - Object columns are coerced to strings, then truncated to 254 chars.
    - Field names > 10 chars are truncated with a collision-avoidance suffix.
    """
    out = gdf.copy()

    for col in list(out.columns):
        if col == "geometry":
            continue
        dtype = out[col].dtype
        # Pandas nullable Int64 -> int32 if values fit; otherwise drop
        if str(dtype) == "Int64":
            try:
                out[col] = out[col].astype("int32")
            except (OverflowError, ValueError):
                logger.warning("dropping column %r (Int64 overflow on shapefile cast)", col)
                out = out.drop(columns=[col])
                continue
        # String-like columns: clamp to DBF text cap
        if dtype == object or str(dtype).startswith("string"):
            ser = out[col].astype(str)
            too_long = (ser.str.len() > SHP_TEXT_MAX).any()
            if too_long:
                logger.warning(
                    "clamping column %r to %d chars (shapefile DBF limit)",
                    col, SHP_TEXT_MAX,
                )
                ser = ser.str.slice(0, SHP_TEXT_MAX)
            out[col] = ser

    return _trim_to_shapefile_schema(out)


def _trim_to_shapefile_schema(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Truncate field names to <=10 chars (DBF limit) and resolve collisions.

    Mirrors the toolbox helper ``_build_shp_safe_field_mappings``.
    """
    rename_map: dict[str, str] = {}
    used_targets: set[str] = set()
    for col in gdf.columns:
        if col == "geometry":
            continue
        target = col[:10]
        if target in used_targets:
            for k in range(1, 10):
                cand = f"{col[: 10 - len(str(k))]}{k}"
                if cand not in used_targets:
                    target = cand
                    break
        if target != col:
            logger.warning("DBF schema: %r truncated to %r", col, target)
        used_targets.add(target)
        rename_map[col] = target
    if not rename_map:
        return gdf
    return gdf.rename(columns=rename_map)
