"""Build Paper9 inputs when DLTB is the only customer authority dataset."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio

from .fusion import (
    FusionDiagnostics,
    FusionError,
    _find_field,
    _frame_diagnostics,
    _infer_county_name,
    _path_diagnostics,
    _select_layer,
    _sha256,
    _write_dem_placeholder,
    _write_gpkg,
    add_dem_slope,
    build_admin_units,
    choose_metric_crs,
    read_polygon_layer,
    slope_grade,
    standardise_dltb,
)

PROFILE_NAME = "dltb_dem_only"
EVIDENCE_TIER = "exploratory_data_limited"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _county_where(path: Path, layer: str, county_code: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{6}", county_code):
        raise FusionError("--county-code must contain exactly six digits.")
    info = pyogrio.read_info(path, layer=layer)
    field = _find_field(
        info["fields"],
        "QSDWDM",
        "权属单位代码",
        "ZLDWDM",
        "坐落单位代码",
        "行政区划代码",
        "行政区代码",
    )
    if field is None:
        raise FusionError(
            "Cannot filter the province-wide DLTB by county. Expected QSDWDM, "
            "ZLDWDM, or an administrative-code field."
        )
    quoted_field = field.replace('"', '""')
    return field, f'"{quoted_field}" LIKE \'{county_code}%\''


def _add_unavailable_constraint_fields(dltb, metric_crs):
    """Keep the optimizer contract while making unavailable evidence explicit."""
    out = dltb.copy()
    area_m2 = out.to_crs(metric_crs).geometry.area.to_numpy(dtype=np.float64)
    dem_grade = slope_grade(out["slope_mean"].to_numpy(dtype=np.float64))
    out["AREA_M2"] = area_m2
    out["PDT_PDJB"] = ""
    out["PDT_BZPDJB"] = ""
    out["PDT_OV_PCT"] = 0.0
    out["PDT_GRADE"] = np.int8(-1)
    out["DEM_GRADE"] = dem_grade
    out["GRD_MATCH"] = np.int8(-1)
    out["ECO_OV_M2"] = 0.0
    out["ECO_PCT"] = 0.0
    out["PBF_OV_M2"] = 0.0
    out["PBF_PCT"] = 0.0
    out["LOCK_C2F"] = np.int8(0)
    out["LOCK_F2C"] = np.int8(0)
    out["EXCH_LOCK"] = np.int8(0)
    out["LOCK_RSN"] = ""
    out["REVIEW_REQ"] = np.int8(0)
    out["REVIEW_RSN"] = ""
    out["CONSTR_STA"] = "NOT_EVALUATED"
    return out


def fuse_dltb_dem_county(
    *,
    dltb_source: Path,
    output_dir: Path,
    dem_paths: list[Path],
    admin_reference: Path,
    county_code: str,
    county_name: str | None = None,
    reference_county_code: str | None = None,
    dltb_layer: str | None = None,
    admin_reference_layer: str = "admin_reference",
    metric_crs: str | None = None,
    z_factor: float = 1.0,
    diagnostics=None,
) -> dict[str, Any]:
    """Fuse a county DLTB with bundled DEM and administrative reference data.

    This profile intentionally does not fabricate PDT, ecological-redline, or
    permanent-basic-farmland evidence. Exchange locks remain zero and every
    output is labelled as regulatory constraints not evaluated.
    """
    diag = diagnostics
    if diag is None:
        from .fusion import NullDiagnostics

        diag = NullDiagnostics()

    dltb_source = Path(dltb_source)
    output_dir = Path(output_dir)
    admin_reference = Path(admin_reference)
    dem_paths = [Path(path) for path in dem_paths]
    if not dltb_source.exists():
        raise FusionError(f"DLTB source does not exist: {dltb_source}")
    if not admin_reference.is_file():
        raise FusionError(f"Administrative reference does not exist: {admin_reference}")

    with diag.stage("select_and_filter_dltb"):
        selected_layer = _select_layer("dltb", dltb_source, dltb_layer)
        code_field, where = _county_where(dltb_source, selected_layer, county_code)
        dltb_raw, dltb_qc = read_polygon_layer(
            dltb_source,
            selected_layer,
            required=True,
            where=where,
        )
        dltb = standardise_dltb(dltb_raw)
        actual_codes = dltb["QSDWDM"].astype(str).str.slice(0, 6)
        if not actual_codes.eq(county_code).all():
            raise FusionError("The filtered DLTB still contains records outside the requested county.")
        diag.emit(
            "INFO",
            "dltb_county_selection",
            "Province-wide DLTB was filtered to one county.",
            county_code=county_code,
            filter_field=code_field,
            where=where,
            selected_feature_count=int(len(dltb)),
        )

    with diag.stage("choose_metric_crs"):
        metric = choose_metric_crs(dltb, metric_crs)

    with diag.stage("dem_slope"):
        dltb, slope_report, dem_meta = add_dem_slope(
            dltb,
            dem_paths,
            z_factor=z_factor,
        )
        if slope_report.null_count:
            raise FusionError(
                f"{slope_report.null_count} DLTB parcels have no local DEM slope. "
                "The bundled DEM must cover the complete county."
            )

    with diag.stage("mark_unavailable_constraints"):
        dltb = _add_unavailable_constraint_fields(dltb, metric)
        constraint_status = {
            "pdt": "not_provided_not_evaluated",
            "eco_redline": "not_provided_not_evaluated",
            "permanent_basic_farmland": "not_provided_not_evaluated",
            "exchange_locked_parcels": 0,
            "regulatory_compliance_evaluated": False,
        }
        diag.warning(
            "regulatory_constraints_unavailable",
            "PDT, ecological redline, and permanent basic farmland were not provided; "
            "outputs are exploratory and cannot establish regulatory compliance.",
            constraints=constraint_status,
        )

    with diag.stage("administrative_reference"):
        admin_units, admin_report = build_admin_units(
            dltb,
            metric_crs=metric,
            reference_path=admin_reference,
            reference_layer=admin_reference_layer,
            reference_county_code=reference_county_code,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    dltb_path = output_dir / "DLTB_with_authority_slope.gpkg"
    admin_path = output_dir / "admin_units.gpkg"
    dem_placeholder_path = output_dir / "DEM_placeholder.tif"
    summary_path = output_dir / "fusion_summary.csv"
    availability_path = output_dir / "input_availability.json"
    with diag.stage("write_outputs"):
        _write_gpkg(dltb_path, dltb, "dltb")
        _write_gpkg(admin_path, admin_units, "admin_units")
        _write_dem_placeholder(dem_placeholder_path, dltb)
        summary = pd.DataFrame(
            [
                {
                    "category": category,
                    "parcel_count": int(len(group)),
                    "area_ha": float(group["AREA_M2"].sum() / 10_000.0),
                    "locked_parcel_count": 0,
                    "constraint_status": "NOT_EVALUATED",
                }
                for category, group in dltb.groupby("category", dropna=False)
            ]
        )
        summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
        availability = {
            "schema_version": "paper9.input_availability.v1",
            "profile": PROFILE_NAME,
            "evidence_tier": EVIDENCE_TIER,
            "county_code": county_code,
            "dltb": "provided",
            "dem": "bundled",
            "administrative_reference": "bundled",
            **constraint_status,
            "decision_use": "exploratory_technical_validation_only",
        }
        availability_path.write_text(
            json.dumps(availability, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    inferred_name, inferred_source = _infer_county_name(dltb, dltb_source)
    resolved_name = county_name or inferred_name
    report = {
        "schema_version": "paper9.dltb_dem_fusion.v1",
        "run_id": diag.run_id,
        "run_timestamp_utc": _utc_now(),
        "county_code": county_code,
        "reference_county_code": reference_county_code or county_code,
        "county_name": resolved_name,
        "county_name_source": "explicit" if county_name else inferred_source,
        "profile": PROFILE_NAME,
        "evidence_tier": EVIDENCE_TIER,
        "backend": "open_source_geopandas_pyogrio_rasterio",
        "arcgis_or_arcpy_used": False,
        "network_access_used": False,
        "source": {
            "mode": PROFILE_NAME,
            "dltb": {
                "path": str(dltb_source),
                "layer": selected_layer,
                "county_filter_field": code_field,
                "county_filter": where,
            },
        },
        "layer_qc": {"dltb": dltb_qc},
        "dltb": _frame_diagnostics(dltb, dltb_qc),
        "metric_crs": metric.to_string(),
        "dem": dem_meta,
        "slope": slope_report.as_dict(),
        "administrative_reference": admin_report,
        "constraints": constraint_status,
        "policy": {
            "decision_use": "exploratory_technical_validation_only",
            "regulatory_compliance_claim_allowed": False,
            "reason": "Ecological redline and permanent basic farmland were not provided.",
        },
        "runtime": diag.environment,
        "timings_seconds": diag.timings,
        "warnings": diag.warnings,
        "inputs": {
            "dltb": _path_diagnostics(dltb_source),
            "dem": [_path_diagnostics(path) for path in dem_paths],
            "administrative_reference": _path_diagnostics(admin_reference),
        },
        "outputs": {
            "dltb": {"path": str(dltb_path), "layer": "dltb", "sha256": _sha256(dltb_path)},
            "admin_units": {"path": str(admin_path), "layer": "admin_units", "sha256": _sha256(admin_path)},
            "dem_placeholder": {"path": str(dem_placeholder_path), "sha256": _sha256(dem_placeholder_path)},
            "summary": {"path": str(summary_path), "sha256": _sha256(summary_path)},
            "input_availability": {"path": str(availability_path), "sha256": _sha256(availability_path)},
        },
    }
    report_path = output_dir / "fusion_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    diag.emit(
        "INFO",
        "dltb_dem_fusion_complete",
        "DLTB+DEM exploratory inputs were written.",
        report=str(report_path),
        parcel_count=int(len(dltb)),
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build exploratory Paper9 inputs from DLTB plus bundled DEM/admin data."
    )
    parser.add_argument("--dltb-gdb", "--dltb-source", dest="dltb_source", type=Path, required=True)
    parser.add_argument("--dltb-layer")
    parser.add_argument("--county-code", required=True)
    parser.add_argument("--county-name")
    parser.add_argument(
        "--reference-county-code",
        help="Override the county code used to select a current administrative reference. ",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dem", type=Path, nargs="+", required=True)
    parser.add_argument("--admin-reference", type=Path, required=True)
    parser.add_argument("--admin-reference-layer", default="admin_reference")
    parser.add_argument("--metric-crs")
    parser.add_argument("--z-factor", type=float, default=1.0)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    log_dir = args.log_dir or args.output_dir.parent / "outputs" / "logs"
    arguments = {
        "dltb_source": args.dltb_source,
        "dltb_layer": args.dltb_layer,
        "county_code": args.county_code,
        "county_name": args.county_name,
        "reference_county_code": args.reference_county_code,
        "output_dir": args.output_dir,
        "dem": args.dem,
        "admin_reference": args.admin_reference,
        "metric_crs": args.metric_crs,
        "profile": PROFILE_NAME,
    }
    with FusionDiagnostics(log_dir, run_id, operation=PROFILE_NAME) as diagnostics:
        diagnostics.emit("INFO", "arguments", "Fusion arguments recorded.", arguments=arguments)
        try:
            report = fuse_dltb_dem_county(
                dltb_source=args.dltb_source,
                dltb_layer=args.dltb_layer,
                county_code=args.county_code,
                county_name=args.county_name,
                reference_county_code=args.reference_county_code,
                output_dir=args.output_dir,
                dem_paths=args.dem,
                admin_reference=args.admin_reference,
                admin_reference_layer=args.admin_reference_layer,
                metric_crs=args.metric_crs,
                z_factor=args.z_factor,
                diagnostics=diagnostics,
            )
        except Exception as exc:
            diagnostics.write_failure(exc, arguments=arguments)
            diagnostics.finish("failed", exception_type=type(exc).__name__, message=str(exc))
            print(f"ERROR: {exc}")
            return 2
        diagnostics.finish("ok", report=report["outputs"])
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
