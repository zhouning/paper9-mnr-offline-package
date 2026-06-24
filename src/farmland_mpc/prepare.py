"""Pure-Python data-preparation pipeline (no arcpy dependency).

This module replaces the arcpy-based ``_phase_a_arcgis`` and ancillary
helpers from the ArcGIS Pro toolbox with rasterio + geopandas equivalents.

The output schema matches the toolbox version exactly, so downstream
``sample_transitions`` / ``train_ensemble`` / ``mpc_plan`` modules consume
the same files regardless of whether preparation ran through arcpy or
through this open-source path.

Output layout under ``prepared_dir`` (identical to toolbox v1.2):

    dem_slope_analysis/output/DLTB_with_slope.shp     ('slope_mean' field)
    results_real/blocks/township_<code>/
        block_compositions.json
        block_features.json
        parcel_block_mapping.csv
    townships.json                                    (code -> label)
    prepare_data_summary.json                         (provenance)

Phases (all pure Python):
    A. DEM -> Horn 3x3 slope -> per-parcel zonal mean
    B. Extract townships from DLTB.QSDWDM[:9] (+ optional XZQ / reference layer
       label injection), then run block_definition.define_blocks per township
    C. Optional sanity check via blocks_env.make_env

CRS handling: ``proj_crs`` accepts ``"EPSG:nnnn"``, a raw WKT string, or
a PROJ-string. The internal pipeline goes through ``pyproj.CRS.from_user_input``
which handles all three. EPSG lookups depend on the local proj.db being
current; if your PROJ database is stale (e.g. ArcGIS-bundled version 5
where rasterio expects 6+), pass the WKT directly to bypass the database.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.features import rasterize
from rasterio import windows
from pyproj import CRS, Geod

logger = logging.getLogger(__name__)


# =============================================================================
# Public entry point
# =============================================================================
def run(
    dltb_path: str | Path,
    dem_path: str | Path,
    prepared_dir: str | Path,
    *,
    proj_crs: str = "EPSG:32648",
    dlbm_field: str = "DLBM",
    qsdwdm_field: str = "QSDWDM",
    bsm_field: str = "BSM",
    dem_resampling: str = "bilinear",
    slope_method: str = "auto",
    slope_field: str = "slope_mean",
    treat_zero_as_nodata: bool = True,
    run_phase_bc: bool = True,
    min_parcels: int = 3,
    min_area_ha: float = 0.5,
    max_parcels: int = 30,
    min_parcels_per_township: int = 50,
    xzq_path: Optional[str | Path] = None,
    xzq_code_field: str = "XZQDM",
    xzq_name_field: str = "XZQMC",
    reference_layer: Optional[str | Path] = None,
    reference_name_field: str = "乡",
) -> Path:
    """End-to-end Phase A+B+C: full prepared_dir matching the ArcGIS toolbox layout.

    Parameters
    ----------
    dltb_path : str | Path
        Polygon vector file (any format readable by ``geopandas.read_file``:
        shapefile, GeoPackage, FlatGeobuf, GeoJSON).
    dem_path : str | Path
        DEM raster (any format readable by ``rasterio.open``).
    prepared_dir : str | Path
        Output root directory.
    proj_crs : str
        Target projected CRS in ``EPSG:nnnn`` form. Defaults to
        ``EPSG:32648`` (UTM Zone 48N) covering central/western China. For
        deployments outside this zone, override with the correct UTM zone.
    dlbm_field, qsdwdm_field, bsm_field : str
        Column names in the DLTB file. Defaults match the Third National
        Land Survey schema.
    dem_resampling : str
        Resampling method when the DEM has to be reprojected to ``proj_crs``.
        Only relevant when ``slope_method`` actually triggers a DEM reprojection.
    slope_method : str
        How to derive per-parcel slope. One of:

          - ``"auto"`` (default): inspect the DEM CRS. If geographic
            (lat/lon, e.g. EPSG:4326), use ``"gradient_geographic"``;
            otherwise use ``"horn_projected"``.
          - ``"gradient_geographic"``: keep the DEM in its native geographic
            CRS, compute true east-west and north-south pixel sizes in
            metres at the study-area centre via ``pyproj.Geod`` (WGS84
            ellipsoid), then ``np.gradient(dem, dy_m, dx_m)`` for slope.
            This is what the research-side pipeline used to produce the
            paper's Table 1 numbers — it preserves the fact that 1 arc-second
            cells are non-square at non-equatorial latitudes.
          - ``"horn_projected"``: legacy path. Reproject the DEM to
            ``proj_crs`` (typically UTM at 30 m × 30 m), then run Horn 3x3
            slope. This squashes non-square cells into squares and
            systematically under-estimates slope by ~1.25° at mid-latitudes
            in our test counties (see commit 56455bb investigation).
            Retained for backward compatibility with old prepared/ runs.
          - ``"from_field"``: skip DEM-derived slope entirely and read a
            pre-existing column ``slope_field`` from the input vector. Use
            this when feeding a ``DLTB_with_slope.gpkg`` produced by an
            external pipeline (e.g. ArcGIS Slope tool, the research-side
            ``prepare/dem_slope/*.py`` scripts) directly into the package.
    slope_field : str
        Source column for ``slope_method="from_field"``. Default
        ``"slope_mean"``, matching the schema produced by the research-side
        ``prepare/dem_slope/*_dem_slope_zonal.py`` scripts.
    treat_zero_as_nodata : bool
        When True (default), DEM cells with elevation ``<= 0`` are treated
        as nodata in addition to any explicit nodata flag in the raster
        metadata. Defends against rasters whose nodata is recorded as
        ``None`` in the file header but whose actual nodata fill is zero
        (a common pitfall for sea-level / clipped-region tiles).
    run_phase_bc : bool
        When True (default) also run Phase B (block definition) and Phase C
        (sanity make_env). Set False for quick Phase-A-only smoke tests on
        synthetic fixtures too small to form blocks.
    min_parcels, min_area_ha, max_parcels : int, float, int
        Block filtering parameters forwarded to ``block_definition.define_blocks``.
        Paper 3 defaults: 3, 0.5, 30.
    min_parcels_per_township : int
        Filter applied during township extraction: prefixes with fewer parcels
        are dropped (assumed border artifacts). Toolbox default 50; lower to
        ~3 for small synthetic fixtures.
    xzq_path : str | Path | None
        Optional XZQ administrative-boundary file used to inject Chinese
        township labels. When None or label fields missing, labels fall back
        to the 9-digit code itself.
    xzq_code_field, xzq_name_field : str
        Columns in the XZQ file (defaults match Third-Survey ``XZQDM`` / ``XZQMC``).
    reference_layer : str | Path | None
        Optional national/regional township polygon layer (e.g. ``xiangzhen.shp``).
        Used as a fallback label source when XZQ lookup fails.
    reference_name_field : str
        Column in ``reference_layer`` holding the township Chinese name.

    Returns
    -------
    Path to the written ``DLTB_with_slope.shp``.
    """
    t0 = time.time()
    prepared_dir = Path(prepared_dir)
    prepared_dir.mkdir(parents=True, exist_ok=True)
    out_dir = prepared_dir / "dem_slope_analysis" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    shp_out = out_dir / "DLTB_with_slope.shp"

    logger.info("Phase A: pure-Python DEM->slope pipeline")
    logger.info("  DLTB:        %s", dltb_path)
    logger.info("  DEM:         %s", dem_path)
    logger.info("  prepared:    %s", prepared_dir)
    logger.info("  target CRS:  %s",
                str(proj_crs)[:80] + "..." if len(str(proj_crs)) > 80 else proj_crs)

    target_crs = CRS.from_user_input(proj_crs)
    target_epsg = target_crs.to_epsg()  # may be None for WKT-only CRS
    target_crs_label = (
        f"EPSG:{target_epsg}" if target_epsg is not None else "(custom WKT)"
    )

    # Load DLTB
    dltb = gpd.read_file(dltb_path)
    _validate_dltb_columns(dltb, [bsm_field, dlbm_field, qsdwdm_field])
    if dltb.crs is None:
        raise ValueError(f"DLTB has no CRS defined: {dltb_path}")
    if not _crs_equals(dltb.crs, target_crs):
        logger.info("  Projecting DLTB %s -> %s ...", dltb.crs, target_crs_label)
        dltb = dltb.to_crs(target_crs)
    logger.info("  DLTB rows: %d", len(dltb))

    # ---- Phase A: per-parcel slope --------------------------------------
    # Resolve "auto" against the DEM's native CRS (or skip DEM entirely
    # when slope_method == "from_field").
    resolved_slope_method = _resolve_slope_method(slope_method, dem_path)
    logger.info("  slope_method = %s (requested=%s)",
                resolved_slope_method, slope_method)

    if resolved_slope_method == "from_field":
        # Read pre-computed slope from the DLTB attribute table; skip DEM.
        if slope_field not in dltb.columns:
            raise ValueError(
                f"slope_method='from_field' but column {slope_field!r} "
                f"missing from DLTB. Available columns: "
                f"{list(dltb.columns)}"
            )
        slope_means = dltb[slope_field].astype(float).to_numpy()
        # No raster intermediates produced in this mode.
    elif resolved_slope_method == "gradient_geographic":
        # Compute slope in the DEM's native geographic CRS using true
        # lat/lon-derived metres per pixel. Matches the research-side
        # prepare/dem_slope/*.py algorithm and the paper's Table 1 numbers.
        slope_path = out_dir / "_slope_deg.tif"
        _compute_slope_gradient_geographic(
            dem_path, slope_path,
            treat_zero_as_nodata=treat_zero_as_nodata,
        )
        # Zonal mean is done in the DEM's native CRS; project DLTB there.
        slope_means = _zonal_mean_in_raster_crs(dltb, slope_path)
    elif resolved_slope_method == "horn_projected":
        # Legacy path: reproject DEM to proj_crs, then Horn 3x3.
        # Kept for backward compatibility; under-estimates slope by
        # ~1.25° at mid-latitudes vs the geographic gradient method.
        dem_proj_path = out_dir / "_dem_reproj.tif"
        _reproject_dem(dem_path, dem_proj_path, target_crs,
                       resampling=dem_resampling)
        slope_path = out_dir / "_slope_deg.tif"
        _compute_slope_horn(dem_proj_path, slope_path,
                            treat_zero_as_nodata=treat_zero_as_nodata)
        slope_means = _zonal_mean(dltb, slope_path)
    else:
        raise ValueError(
            f"Unknown slope_method={resolved_slope_method!r}. "
            "Expected one of: auto, gradient_geographic, horn_projected, from_field."
        )

    n_unmatched = int(np.isnan(slope_means).sum())
    if n_unmatched:
        # Fill with median so downstream slope_min/max/range stay finite.
        # Dropping would break the gdf_swap row ordering that BSM and the
        # env rely on; zero would bias the reward toward "flat".
        n_total = len(slope_means)
        finite_mask = ~np.isnan(slope_means)
        if finite_mask.sum() == 0:
            raise RuntimeError(
                "All parcel slopes are NaN. The DEM does not cover the AOI. "
                "Check that the DEM tiles span the shapefile bounding box."
            )
        fill_value = float(np.nanmedian(slope_means))
        slope_means = np.where(finite_mask, slope_means, fill_value)
        logger.warning(
            "  %d / %d parcels (%.1f%%) had no slope_mean (outside DEM coverage "
            "or tiny polygons); filled with median=%.3f deg",
            n_unmatched, n_total, 100.0 * n_unmatched / n_total, fill_value,
        )
    dltb["slope_mean"] = slope_means

    # Drop intermediate rasters before exporting (we keep them under
    # _dem_reproj.tif / _slope_deg.tif for debugging; remove if you want
    # a slim prepared_dir)
    # _dem_reproj.tif and _slope_deg.tif are intentionally kept; the
    # toolbox writes equivalents to scratchGDB. They can be deleted by
    # passing keep_intermediate=False at a future API extension.

    # Write DLTB_with_slope.shp; geopandas truncates to <=10 char DBF names
    # so we explicitly check that the schema is shapefile-safe.
    dltb_export = _trim_to_shapefile_schema(dltb)
    if shp_out.exists():
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            try:
                (shp_out.with_suffix(ext)).unlink()
            except FileNotFoundError:
                pass
    dltb_export.to_file(shp_out, driver="ESRI Shapefile", encoding="utf-8")
    logger.info("  Wrote %s (%d rows)", shp_out, len(dltb_export))

    # Provenance summary
    elapsed = time.time() - t0
    summary = {
        "phase_a_backend": "open_source_rasterio_geopandas",
        "slope_method": resolved_slope_method,
        "slope_method_requested": slope_method,
        "dltb_input": str(dltb_path),
        "dem_input": str(dem_path),
        "proj_crs": target_crs_label,
        "treat_zero_as_nodata": bool(treat_zero_as_nodata),
        "n_parcels": int(len(dltb_export)),
        "n_parcels_with_slope": int((~np.isnan(slope_means)).sum()),
        "n_parcels_unmatched": n_unmatched,
        "elapsed_seconds": round(elapsed, 2),
    }
    logger.info("  Phase A done in %.1fs", elapsed)

    # =========================================================================
    # Phase B + C (optional, default on)
    # =========================================================================
    if run_phase_bc:
        # Phase C1: townships.json (must come before Phase B; block_definition
        # iterates TOWNSHIPS keys).
        logger.info("Phase B/C: extracting townships from %s ...", qsdwdm_field)
        townships, township_meta = _extract_townships(
            dltb_export,
            qsdwdm_field=qsdwdm_field,
            xzq_path=xzq_path,
            xzq_code_field=xzq_code_field,
            xzq_name_field=xzq_name_field,
            reference_layer=reference_layer,
            reference_name_field=reference_name_field,
            proj_crs=proj_crs,
            min_parcels_per_township=min_parcels_per_township,
        )
        townships_path = prepared_dir / "townships.json"
        with townships_path.open("w", encoding="utf-8") as fh:
            json.dump(townships, fh, ensure_ascii=False, indent=2)
        logger.info("  %d townships -> %s (labels from: %s)",
                    len(townships), townships_path, township_meta["label_source"])
        summary["townships"] = {
            "n_townships": len(townships),
            "codes": list(townships.keys()),
            "label_source": township_meta["label_source"],
            "file": str(townships_path),
        }

        # Phase B: blocks per township
        t_b = time.time()
        logger.info("Phase B: defining blocks (Paper 3 hybrid) ...")
        blocks_info = _phase_b_blocks(
            prepared_dir=prepared_dir,
            townships=townships,
            proj_crs=proj_crs,
            min_parcels=min_parcels,
            min_area_ha=min_area_ha,
            max_parcels=max_parcels,
        )
        summary["phase_b"] = {
            "elapsed_seconds": round(time.time() - t_b, 1),
            **blocks_info,
        }
        logger.info("  Phase B done in %.1fs: %d blocks across %d townships",
                    summary["phase_b"]["elapsed_seconds"],
                    blocks_info["total_blocks"],
                    blocks_info["n_townships_processed"])

        # Phase C2: sanity make_env
        logger.info("Phase C: sanity make_env(prepared_dir) ...")
        summary["phase_c_sanity"] = _phase_c_sanity(prepared_dir, proj_crs)

    summary_path = prepared_dir / "prepare_data_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    summary["total_elapsed_seconds"] = round(time.time() - t0, 2)
    return shp_out


# =============================================================================
# Helpers
# =============================================================================
def _parse_epsg(proj_crs: str) -> int:
    """Parse 'EPSG:nnnn' into the integer code (legacy helper, kept for tests)."""
    s = str(proj_crs).strip()
    if s.upper().startswith("EPSG:"):
        s = s.split(":", 1)[1]
    try:
        return int(s)
    except ValueError as e:
        raise ValueError(f"Cannot parse proj_crs={proj_crs!r}; expected 'EPSG:nnnn'") from e


def _crs_equals(a: CRS | str, b: CRS | str) -> bool:
    """Robust CRS comparison that tolerates EPSG / WKT / proj-string forms."""
    ca = a if isinstance(a, CRS) else CRS.from_user_input(a)
    cb = b if isinstance(b, CRS) else CRS.from_user_input(b)
    try:
        if ca.to_epsg() is not None and cb.to_epsg() is not None:
            return ca.to_epsg() == cb.to_epsg()
    except Exception:
        pass
    return ca.equals(cb)


def _validate_dltb_columns(dltb: gpd.GeoDataFrame, required: list[str]) -> None:
    missing = [c for c in required if c not in dltb.columns]
    if missing:
        raise ValueError(
            f"DLTB missing required columns: {missing}. "
            f"Available: {list(dltb.columns)}"
        )


def _reproject_dem(
    dem_path: str | Path,
    out_path: str | Path,
    target_crs: CRS | str | int,
    *,
    resampling: str = "bilinear",
) -> None:
    """Project ``dem_path`` to ``target_crs`` and write to ``out_path``.

    If the source DEM is already in the target CRS, this still re-writes
    it (cheap copy) so downstream code can rely on a single output path.
    """
    resampling_map = {
        "bilinear": Resampling.bilinear,
        "nearest": Resampling.nearest,
        "cubic": Resampling.cubic,
    }
    if resampling not in resampling_map:
        raise ValueError(f"Unsupported resampling={resampling!r}")
    rs = resampling_map[resampling]

    target_crs = target_crs if isinstance(target_crs, CRS) else CRS.from_user_input(target_crs)

    with rasterio.open(dem_path) as src:
        if src.crs is None:
            raise ValueError(f"DEM has no CRS defined: {dem_path}")
        src_crs = src.crs
        if _crs_equals(src_crs, target_crs):
            logger.info("  DEM already in target CRS; copying without resampling")
            data = src.read()
            profile = src.profile.copy()
            profile["crs"] = target_crs.to_wkt()
        else:
            logger.info(
                "  Reprojecting DEM %s -> %s (%s) ...",
                src_crs, target_crs, resampling,
            )
            transform, width, height = calculate_default_transform(
                src_crs, target_crs.to_wkt(),
                src.width, src.height, *src.bounds,
            )
            profile = src.profile.copy()
            profile.update({
                "crs": target_crs.to_wkt(),
                "transform": transform,
                "width": width,
                "height": height,
            })
            data = np.empty((src.count, height, width), dtype=src.dtypes[0])
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=data[i - 1],
                    src_transform=src.transform,
                    src_crs=src_crs,
                    dst_transform=transform,
                    dst_crs=target_crs.to_wkt(),
                    resampling=rs,
                )
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data)


def _compute_slope_horn(
    dem_path: str | Path,
    slope_out_path: str | Path,
    treat_zero_as_nodata: bool = True,
) -> None:
    """Compute slope (degrees) using Horn's 3x3 algorithm.

    Equivalent to ``arcpy.sa.Slope(dem, "DEGREE")``.

    References: Horn, B. K. P. (1981). Hill shading and the reflectance map.
    Proceedings of the IEEE, 69(1), 14-47.
    """
    with rasterio.open(dem_path) as src:
        if src.count != 1:
            raise ValueError(f"DEM must be single-band; got {src.count} bands")
        z = src.read(1).astype(np.float64)
        cellsize_x = abs(src.transform.a)
        cellsize_y = abs(src.transform.e)
        nodata = src.nodata

        # Mark NoData as NaN so Horn ignores them via padding logic
        if nodata is not None:
            z = np.where(z == nodata, np.nan, z)
        if treat_zero_as_nodata:
            # Common pitfall: rasters with nodata=None but actual fill = 0
            # (sea-level, clipped-region tiles). Horn would otherwise treat
            # 0 as a real elevation and compute spurious "cliffs" at the
            # boundary, biasing the zonal mean toward 0.
            z = np.where(z <= 0, np.nan, z)

        # Horn's slope algorithm: each cell's slope is computed from a 3x3
        # window with weights [[1,2,1],[0,0,0],[-1,-2,-1]] for dz/dy and
        # the transpose for dz/dx, then slope = atan(sqrt((dz/dx)^2+(dz/dy)^2)).
        # We use np.gradient as a numerically equivalent shortcut for the
        # interior; near edges we rely on np.gradient's edge-mode (forward
        # differences), which differs from arcpy at the very outer ring of
        # cells but agrees everywhere else. For typical county-scale DEMs
        # this is below the precision of zonal averaging.
        # For exact arcpy parity we implement the Horn weights explicitly:
        slope_deg = _horn_slope_deg(z, cellsize_x, cellsize_y)

        profile = src.profile.copy()
        profile.update({"dtype": "float32", "nodata": -9999.0, "count": 1})
        slope_arr = np.where(np.isnan(slope_deg), -9999.0, slope_deg).astype("float32")
        with rasterio.open(slope_out_path, "w", **profile) as dst:
            dst.write(slope_arr, 1)
    logger.info("  Slope raster (degrees) -> %s", slope_out_path)


def _horn_slope_deg(z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Horn 3x3 slope (degrees), matching arcpy.sa.Slope semantics."""
    # Pad with edge values so the convolution doesn't shrink the output
    pad = np.pad(z, 1, mode="edge")
    # 3x3 windows
    a = pad[0:-2, 0:-2]; b = pad[0:-2, 1:-1]; c = pad[0:-2, 2:]
    d = pad[1:-1, 0:-2]; e = pad[1:-1, 1:-1]; f = pad[1:-1, 2:]
    g = pad[2:,   0:-2]; h = pad[2:,   1:-1]; i = pad[2:,   2:]

    # Horn's algorithm: dz/dx, dz/dy with [1,2,1] weights
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * dx)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8.0 * dy)

    rise_run = np.sqrt(dzdx * dzdx + dzdy * dzdy)
    slope_rad = np.arctan(rise_run)
    slope_deg = np.degrees(slope_rad)
    # Where any of the 9 inputs was NaN, the slope is undefined
    nan_mask = (
        np.isnan(a) | np.isnan(b) | np.isnan(c)
        | np.isnan(d) | np.isnan(e) | np.isnan(f)
        | np.isnan(g) | np.isnan(h) | np.isnan(i)
    )
    return np.where(nan_mask, np.nan, slope_deg)


def _resolve_slope_method(method: str, dem_path: str | Path) -> str:
    """Map ``slope_method='auto'`` to a concrete strategy by inspecting the DEM.

    Returns one of: ``"gradient_geographic"`` / ``"horn_projected"`` /
    ``"from_field"``. Raises ``ValueError`` for unknown ``method``.
    """
    if method == "from_field":
        return "from_field"
    if method in ("gradient_geographic", "horn_projected"):
        return method
    if method != "auto":
        raise ValueError(
            f"Unknown slope_method={method!r}. Expected one of: "
            "auto, gradient_geographic, horn_projected, from_field."
        )
    # auto: pick based on DEM CRS
    with rasterio.open(dem_path) as src:
        crs = src.crs
        if crs is None:
            logger.warning("  DEM has no CRS; defaulting to horn_projected.")
            return "horn_projected"
        if crs.is_geographic:
            return "gradient_geographic"
        return "horn_projected"


def _compute_slope_gradient_geographic(
    dem_path: str | Path,
    slope_out_path: str | Path,
    treat_zero_as_nodata: bool = True,
) -> None:
    """Compute slope (degrees) on a geographic-CRS DEM using true metre-scale gradients.

    Pixel size in degrees is converted to metres via ``pyproj.Geod`` at the
    DEM's centre latitude, separately for east-west (varies with cos(lat))
    and north-south (~constant ~30.9 m for 1 arc-second). ``np.gradient``
    is then a numerically equivalent shortcut for the central-difference
    formulation used by the research-side ``prepare/dem_slope/*.py``
    scripts (which produced the paper's Table 1 numbers). Outputs the
    slope as a float32 raster in the SAME geographic CRS as the input DEM.
    """
    with rasterio.open(dem_path) as src:
        if src.count != 1:
            raise ValueError(f"DEM must be single-band; got {src.count} bands")
        if src.crs is None or not src.crs.is_geographic:
            raise ValueError(
                "gradient_geographic requires a DEM in a geographic CRS "
                f"(lat/lon); got {src.crs}."
            )
        z = src.read(1).astype(np.float64)
        nodata = src.nodata
        nan_mask = np.zeros_like(z, dtype=bool)
        if nodata is not None:
            nan_mask |= (z == nodata)
        if treat_zero_as_nodata:
            nan_mask |= (z <= 0)
        if nan_mask.any():
            z = np.where(nan_mask, np.nan, z)

        # Compute true metres-per-pixel at the DEM centre latitude.
        ps = abs(src.transform.a)  # pixel size in degrees (square in degree-space)
        ps_y = abs(src.transform.e)
        origin_lon = src.transform.c
        origin_lat = src.transform.f
        n_rows, n_cols = z.shape
        lat_center = origin_lat - n_rows / 2 * ps_y
        geod = Geod(ellps="WGS84")
        _, _, dy_m = geod.inv(
            origin_lon, lat_center - ps_y / 2,
            origin_lon, lat_center + ps_y / 2,
        )
        _, _, dx_m = geod.inv(
            origin_lon - ps / 2, lat_center,
            origin_lon + ps / 2, lat_center,
        )
        logger.info(
            "  gradient_geographic: lat_center=%.4f, pixel real size %.2f m E-W x %.2f m N-S",
            lat_center, dx_m, dy_m,
        )

        # np.gradient(z, dy_m, dx_m) returns (dz/dy, dz/dx) when called
        # with two scalar spacings on a 2D array; this matches the
        # research-side implementation in prepare/dem_slope/*.py.
        dz_dy, dz_dx = np.gradient(z, dy_m, dx_m)
        slope_rad = np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))
        slope_deg = np.degrees(slope_rad).astype(np.float32)

        profile = src.profile.copy()
        profile.update({"dtype": "float32", "nodata": -9999.0, "count": 1})
        slope_arr = np.where(np.isnan(slope_deg), -9999.0, slope_deg).astype("float32")
        with rasterio.open(slope_out_path, "w", **profile) as dst:
            dst.write(slope_arr, 1)
    logger.info("  Slope raster (degrees, geographic) -> %s", slope_out_path)


def _zonal_mean_in_raster_crs(
    polygons: gpd.GeoDataFrame,
    raster_path: str | Path,
) -> np.ndarray:
    """Per-polygon zonal mean, where polygons may need reprojection to the raster CRS.

    Wraps :func:`_zonal_mean` with an automatic CRS check: if the input
    polygons aren't already in the raster's CRS, they're reprojected
    to it before rasterization. Used for the ``gradient_geographic``
    path where the DEM stays in EPSG:4326 but the DLTB has been
    reprojected to the analysis CRS (e.g. UTM) earlier in ``run()``.
    """
    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
    if raster_crs is None:
        raise ValueError(f"Raster has no CRS: {raster_path}")
    if not _crs_equals(polygons.crs, raster_crs):
        polygons = polygons.to_crs(raster_crs)
    return _zonal_mean(polygons, raster_path)


def _zonal_mean(
    polygons: gpd.GeoDataFrame,
    raster_path: str | Path,
) -> np.ndarray:
    """Per-polygon mean of a raster, equivalent to arcpy.sa.ZonalStatisticsAsTable.

    Returns a length-N float array with NaN where a polygon has no
    valid raster cells (outside coverage, all-nodata, or tiny polygons
    that don't intersect any cell centre).
    """
    n = len(polygons)
    means = np.full(n, np.nan, dtype=np.float64)

    # Precompute polygon FID -> integer zone id (1..n) for rasterize()
    zone_ids = np.arange(1, n + 1, dtype=np.int32)
    geom_iter = ((geom, zid) for geom, zid in zip(polygons.geometry.values, zone_ids))

    with rasterio.open(raster_path) as src:
        slope = src.read(1)
        nodata = src.nodata
        valid = slope != nodata if nodata is not None else np.ones_like(slope, dtype=bool)
        valid &= ~np.isnan(slope)

        # Rasterize all polygons in one pass, using dtype large enough for n
        if n < 2**16 - 1:
            zone_dtype = "uint16"
        else:
            zone_dtype = "int32"

        zone_raster = rasterize(
            shapes=geom_iter,
            out_shape=slope.shape,
            transform=src.transform,
            fill=0,
            dtype=zone_dtype,
            all_touched=False,
        )

        # Aggregate: for each zone id, mean of slope[valid & zone==id]
        # We use np.bincount for O(N) aggregation across all cells
        flat_zones = zone_raster.ravel()
        flat_slope = slope.ravel()
        flat_valid = valid.ravel() & (flat_zones > 0)

        if not np.any(flat_valid):
            logger.warning("  Zonal mean: no valid (zone, slope) pairs found")
            return means

        zone_sel = flat_zones[flat_valid].astype(np.int64)
        slope_sel = flat_slope[flat_valid].astype(np.float64)
        sums = np.bincount(zone_sel, weights=slope_sel, minlength=n + 1)
        counts = np.bincount(zone_sel, minlength=n + 1)
        with np.errstate(invalid="ignore"):
            zone_means = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
        # Map zone_id (1..n) back to polygon index (0..n-1)
        means = zone_means[1 : n + 1]
    return means


def _trim_to_shapefile_schema(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Truncate field names to <=10 chars (DBF limit) and warn on collisions.

    Mirrors the toolbox helper ``_build_shp_safe_field_mappings``.
    """
    rename_map: dict[str, str] = {}
    used_targets: set[str] = set()
    for col in gdf.columns:
        if col == "geometry":
            continue
        target = col[:10]
        if target in used_targets:
            # Resolve collision by appending a digit
            for k in range(1, 10):
                cand = f"{col[: 10 - len(str(k))]}{k}"
                if cand not in used_targets:
                    target = cand
                    break
        if target != col:
            logger.warning("  DBF schema: '%s' truncated to '%s'", col, target)
        used_targets.add(target)
        rename_map[col] = target
    if not rename_map:
        return gdf
    return gdf.rename(columns=rename_map)


# =============================================================================
# Phase B + C helpers (pure Python — no arcpy)
# =============================================================================
def _extract_townships(
    dltb: gpd.GeoDataFrame,
    *,
    qsdwdm_field: str,
    xzq_path: Optional[str | Path],
    xzq_code_field: str,
    xzq_name_field: str,
    reference_layer: Optional[str | Path],
    reference_name_field: str,
    proj_crs: str,
    min_parcels_per_township: int,
) -> tuple[dict, dict]:
    """Build {9-digit-code: label} dict from DLTB.QSDWDM.

    Primary source: unique 9-digit prefixes of dltb[qsdwdm_field].
    Optional: xzq_path supplies Chinese labels via xzq_name_field looked up
    by xzq_code_field prefix. If xzq_path is None or lookup misses, falls
    back to reference_layer (spatial join). Last resort: label = code.

    Returns
    -------
    (townships, meta)
        townships : dict mapping 9-digit code to label string
        meta      : dict with key 'label_source' in {'code','xzq','reference'}
    """
    from collections import Counter

    counts: Counter = Counter()
    for raw in dltb[qsdwdm_field].astype(str):
        s = raw.strip()
        if len(s) >= 9:
            counts[s[:9]] += 1

    codes = sorted(
        prefix for prefix, n in counts.items() if n >= min_parcels_per_township
    )
    dropped = [(p, n) for p, n in counts.items() if n < min_parcels_per_township]
    if dropped:
        logger.warning(
            "  Dropped %d townships with <%d parcels (first 5: %s)",
            len(dropped), min_parcels_per_township, dropped[:5],
        )
    if not codes:
        raise RuntimeError(
            f"No townships with >= {min_parcels_per_township} parcels in DLTB."
            f"{qsdwdm_field}. Found prefixes: {sorted(counts)}. Lower "
            "min_parcels_per_township for small synthetic fixtures."
        )

    label_map = {c: c for c in codes}
    label_source = "code"

    # Optional XZQ injection
    if xzq_path is not None:
        try:
            xzq = gpd.read_file(str(xzq_path))
            if xzq_code_field not in xzq.columns:
                logger.warning(
                    "  XZQ missing code field '%s'; available: %s",
                    xzq_code_field, list(xzq.columns),
                )
            else:
                hits = 0
                name_col = xzq_name_field if xzq_name_field in xzq.columns else None
                for _, row in xzq.iterrows():
                    raw = row.get(xzq_code_field)
                    if raw is None:
                        continue
                    code = str(raw).strip()
                    if len(code) < 9:
                        continue
                    prefix = code[:9]
                    if prefix not in label_map:
                        continue
                    label = row.get(name_col) if name_col else None
                    if label:
                        s = str(label).strip()
                        if label_map[prefix] == prefix or len(s) < len(label_map[prefix]):
                            label_map[prefix] = s
                            hits += 1
                if hits:
                    label_source = "xzq"
                    logger.info("  XZQ resolved %d / %d township labels", hits, len(label_map))
        except Exception as e:
            logger.warning("  XZQ label injection failed: %s", e)

    # Optional reference-layer spatial-join
    if reference_layer is not None and label_source == "code":
        try:
            label_map = _labels_from_reference_layer(
                dltb=dltb,
                qsdwdm_field=qsdwdm_field,
                reference_layer=reference_layer,
                reference_name_field=reference_name_field,
                proj_crs=proj_crs,
                existing_label_map=label_map,
            )
            label_source = "reference"
        except Exception as e:
            logger.warning("  Reference-layer label injection failed: %s", e)

    return dict(sorted(label_map.items())), {"label_source": label_source}


def _labels_from_reference_layer(
    *,
    dltb: gpd.GeoDataFrame,
    qsdwdm_field: str,
    reference_layer: str | Path,
    reference_name_field: str,
    proj_crs: str,
    existing_label_map: dict,
) -> dict:
    """Spatial-join DLTB centroids into a reference polygon layer.

    For each 9-digit QSDWDM prefix, samples up to MAX_SAMPLE_PER_PREFIX parcels,
    takes their centroids, joins into reference_layer, and assigns the dominant
    reference_name_field value as the label.
    """
    MAX_SAMPLE_PER_PREFIX = 5

    ref = gpd.read_file(str(reference_layer))
    if reference_name_field not in ref.columns:
        raise RuntimeError(
            f"Reference layer missing '{reference_name_field}'; "
            f"available: {list(ref.columns)}"
        )
    ref = ref[[reference_name_field, "geometry"]].rename(
        columns={reference_name_field: "_ref_name"}
    )

    dltb_local = dltb[[qsdwdm_field, "geometry"]].copy()
    dltb_local["_prefix9"] = dltb_local[qsdwdm_field].astype(str).str[:9]
    dltb_local = dltb_local[dltb_local["_prefix9"].isin(existing_label_map)]

    sampled = (
        dltb_local.groupby("_prefix9", group_keys=False)
        .apply(lambda g: g.sample(min(len(g), MAX_SAMPLE_PER_PREFIX), random_state=0))
    )
    sampled = sampled.to_crs(proj_crs)
    sampled.geometry = sampled.geometry.centroid
    sampled = sampled.to_crs(ref.crs)

    joined = gpd.sjoin(
        sampled[["_prefix9", "geometry"]],
        ref[["_ref_name", "geometry"]],
        how="left", predicate="within",
    )

    def _dominant(s):
        s = s.dropna()
        return s.mode().iloc[0] if len(s) else None

    dom = joined.groupby("_prefix9")["_ref_name"].apply(_dominant).to_dict()
    out = dict(existing_label_map)
    for prefix, name in dom.items():
        if name:
            out[prefix] = str(name)
    return out


def _phase_b_blocks(
    *,
    prepared_dir: Path,
    townships: dict,
    proj_crs: str,
    min_parcels: int,
    min_area_ha: float,
    max_parcels: int,
) -> dict:
    """Run block_definition.define_blocks + save_results per township."""
    try:
        from farmland_mpc import block_definition as bd  # type: ignore[import-not-found]
    except ImportError:
        import block_definition as bd  # type: ignore[import-not-found]

    shp_path = prepared_dir / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp"
    blocks_root = prepared_dir / "results_real" / "blocks"
    blocks_root.mkdir(parents=True, exist_ok=True)

    # Monkey-patch module constants
    bd.DLTB_PATH = str(shp_path)
    bd.OUTPUT_DIR = str(blocks_root)
    bd.PROJ_CRS = proj_crs
    bd.TOWNSHIPS = dict(townships)

    info = {
        "n_townships_processed": 0,
        "n_townships_skipped": 0,
        "total_blocks": 0,
        "per_township": {},
    }

    for code, label in sorted(townships.items()):
        logger.info("  [Phase B] Township %s (%s) ...", code, label)
        try:
            gdf_sw, block_features, valid_blocks = bd.define_blocks(
                code,
                min_parcels=min_parcels,
                min_area_ha=min_area_ha,
                max_parcels=max_parcels,
            )
        except Exception as e:
            logger.warning("  [Phase B] Township %s FAILED: %s", code, e)
            info["n_townships_skipped"] += 1
            info["per_township"][code] = {"status": "failed", "error": str(e)}
            continue

        if len(valid_blocks) == 0:
            logger.warning("  [Phase B] Township %s -> 0 blocks, skipping save", code)
            info["n_townships_skipped"] += 1
            info["per_township"][code] = {"status": "empty", "n_blocks": 0}
            continue

        bd.save_results(code, gdf_sw, block_features, valid_blocks)
        info["n_townships_processed"] += 1
        info["total_blocks"] += len(valid_blocks)
        info["per_township"][code] = {
            "status": "ok",
            "n_blocks": len(valid_blocks),
            "n_parcels_assigned": int((gdf_sw["block_id"] >= 0).sum()),
        }

    if info["total_blocks"] == 0:
        raise RuntimeError(
            "Phase B produced 0 blocks across all townships. Check that DLBM "
            "values include both farmland (011/012/013) and forest (031/032/033) "
            "codes, and that min_parcels / min_area_ha are not too restrictive."
        )
    return info


def _phase_c_sanity(prepared_dir: Path, proj_crs: str) -> dict:
    """Verify blocks_env.make_env(prepared_dir) returns a usable env."""
    try:
        from farmland_mpc.blocks_env import make_env  # type: ignore[import-not-found]
    except ImportError:
        from blocks_env import make_env  # type: ignore[import-not-found]

    try:
        env = make_env(prepared_dir=str(prepared_dir), proj_crs=proj_crs)
    except Exception as e:
        logger.warning("  [Phase C] make_env FAILED: %s", e)
        return {"status": "failed", "error": str(e)}

    out = {
        "status": "ok",
        "n_blocks": int(env.n_blocks),
        "n_parcels": int(env.n_parcels),
        "initial_slope": float(getattr(env, "avg_farmland_slope", float("nan"))),
        "initial_contiguity": float(getattr(env, "contiguity", float("nan"))),
        "baimu_count": int(getattr(env, "baimu_count", 0)),
    }
    logger.info(
        "  [Phase C] OK n_blocks=%d n_parcels=%d slope=%.4f baimu=%d",
        out["n_blocks"], out["n_parcels"], out["initial_slope"], out["baimu_count"],
    )
    return out
