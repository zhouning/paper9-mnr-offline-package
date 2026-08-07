"""Offline fusion of authoritative county FileGDB layers for Paper9.

The module deliberately uses only the open-source geospatial stack bundled by
the Paper9 package: GDAL/OpenFileGDB through pyogrio, GeoPandas, Shapely and
Rasterio.  It never invokes ArcPy or downloads data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
import shapely
from pyproj import CRS
from rasterio.merge import merge as merge_rasters
from rasterio.transform import from_bounds, rowcol
from rasterio.features import rasterize
from shapely import area as shape_area
from shapely import intersection, make_valid, union_all

from farmland_mpc.landuse import (
    LandUseCodeError,
    analyse_land_use_codes,
    classify_land_use as classify_land_use_code,
)

SLOPE_GRADE_BOUNDS = (2.0, 6.0, 15.0, 25.0)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def runtime_environment() -> dict[str, Any]:
    """Return version and driver details needed for offline troubleshooting."""
    return {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "geopandas": gpd.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "shapely": shapely.__version__,
        "pyogrio": pyogrio.__version__,
        "pyogrio_gdal": getattr(pyogrio, "__gdal_version_string__", "unknown"),
        "rasterio": rasterio.__version__,
        "rasterio_gdal": getattr(rasterio, "__gdal_version__", "unknown"),
        "openfilegdb_driver": pyogrio.list_drivers().get("OpenFileGDB", "unavailable"),
        "image_ref": os.environ.get("PAPER9_IMAGE_REF", ""),
        "network_policy": "offline; no download code path",
        "arcpy_imported": "arcpy" in sys.modules,
    }


class FusionDiagnostics:
    """Incremental human-readable and JSONL diagnostics for one fusion run."""

    def __init__(
        self,
        log_dir: Path,
        run_id: str,
        operation: str = "authority_four_source",
    ):
        self.log_dir = Path(log_dir)
        self.run_id = run_id
        self.operation = operation
        log_prefix = (
            "authoritative_fusion"
            if operation == "authority_four_source"
            else "dltb_dem_fusion"
        )
        self.log_prefix = log_prefix
        self.log_path = self.log_dir / f"{log_prefix}-{run_id}.log"
        self.events_path = self.log_dir / f"{log_prefix}-{run_id}.jsonl"
        self.failure_path = self.log_dir / f"{log_prefix}-{run_id}-failure.json"
        self.timings: dict[str, float] = {}
        self.warnings: list[str] = []
        self.environment = runtime_environment()
        self._human = None
        self._events = None
        self._started = time.monotonic()

    def __enter__(self) -> "FusionDiagnostics":
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._human = self.log_path.open("w", encoding="utf-8")
        self._events = self.events_path.open("w", encoding="utf-8")
        self.emit(
            "INFO",
            "run_start",
            f"Fusion started for profile={self.operation}.",
            profile=self.operation,
            runtime=self.environment,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._human is not None:
            self._human.close()
        if self._events is not None:
            self._events.close()
        if self.log_path.is_file():
            shutil.copyfile(self.log_path, self.log_dir / f"{self.log_prefix}-latest.log")
        if self.events_path.is_file():
            shutil.copyfile(
                self.events_path,
                self.log_dir / f"{self.log_prefix}-latest.jsonl",
            )

    def emit(
        self,
        level: str,
        event: str,
        message: str,
        **details: Any,
    ) -> None:
        payload = {
            "timestamp_utc": _utc_now(),
            "run_id": self.run_id,
            "level": level,
            "event": event,
            "message": message,
            "details": details,
        }
        detail_text = f" details={_safe_json(details)}" if details else ""
        line = (
            f"{payload['timestamp_utc']} level={level} event={event} "
            f"message={message}{detail_text}"
        )
        stream = sys.stderr if level in {"ERROR", "WARNING"} else sys.stdout
        print(line, file=stream, flush=True)
        if self._human is not None:
            self._human.write(f"{line}\n")
            self._human.flush()
        if self._events is not None:
            self._events.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            self._events.flush()

    def warning(self, event: str, message: str, **details: Any) -> None:
        self.warnings.append(message)
        self.emit("WARNING", event, message, **details)

    @contextmanager
    def stage(self, name: str, **details: Any):
        started = time.monotonic()
        self.emit("INFO", "stage_start", f"Stage {name} started.", stage=name, **details)
        try:
            yield
        except Exception as exc:
            duration = round(time.monotonic() - started, 3)
            self.timings[name] = duration
            self.emit(
                "ERROR",
                "stage_failed",
                f"Stage {name} failed: {exc}",
                stage=name,
                duration_seconds=duration,
                exception_type=type(exc).__name__,
                traceback=traceback.format_exc(),
            )
            raise
        duration = round(time.monotonic() - started, 3)
        self.timings[name] = duration
        self.emit(
            "INFO",
            "stage_end",
            f"Stage {name} completed.",
            stage=name,
            duration_seconds=duration,
        )

    def finish(self, status: str, **details: Any) -> None:
        self.emit(
            "INFO" if status == "ok" else "ERROR",
            "run_end",
            f"Fusion profile={self.operation} ended with status={status}.",
            profile=self.operation,
            status=status,
            duration_seconds=round(time.monotonic() - self._started, 3),
            timings=self.timings,
            warning_count=len(self.warnings),
            **details,
        )

    def write_failure(self, exc: Exception, *, arguments: dict[str, Any]) -> None:
        payload = {
            "schema_version": (
                "paper9.authoritative_fusion_failure.v1"
                if self.operation == "authority_four_source"
                else "paper9.dltb_dem_fusion_failure.v1"
            ),
            "run_id": self.run_id,
            "profile": self.operation,
            "timestamp_utc": _utc_now(),
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "arguments": arguments,
            "runtime": self.environment,
            "timings": self.timings,
            "warnings": self.warnings,
            "human_log": str(self.log_path),
            "events_log": str(self.events_path),
        }
        self.failure_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


class NullDiagnostics:
    """No-op diagnostics used by direct library calls and unit tests."""

    run_id = "library-call"
    timings: dict[str, float] = {}
    warnings: list[str] = []
    environment: dict[str, Any] = {}
    log_path: Path | None = None
    events_path: Path | None = None

    def emit(self, level: str, event: str, message: str, **details: Any) -> None:
        return None

    def warning(self, event: str, message: str, **details: Any) -> None:
        return None

    @contextmanager
    def stage(self, name: str, **details: Any):
        yield


class FusionError(RuntimeError):
    """Raised when the source data cannot safely form a Paper9 input."""


@dataclass(frozen=True)
class LayerSelection:
    dltb: str
    pdt: str
    eco_redline: str
    permanent_basic_farmland: str


@dataclass(frozen=True)
class SlopeReport:
    method: str
    parcel_count: int
    pixel_count: int
    representative_count: int
    null_count: int
    minimum: float
    maximum: float
    mean: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "parcel_count": self.parcel_count,
            "pixel_count": self.pixel_count,
            "representative_count": self.representative_count,
            "null_count": self.null_count,
            "minimum_degrees": self.minimum,
            "maximum_degrees": self.maximum,
            "mean_degrees": self.mean,
        }


def _normalise(value: object) -> str:
    return re.sub(r"[\s_\-()（）]", "", str(value).strip()).casefold()


def _normalise_code(value: object, *, width: int | None = None) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (int, np.integer)):
        text = str(int(value))
    elif isinstance(value, (float, np.floating)) and math.isfinite(float(value)):
        text = str(int(value)) if float(value).is_integer() else str(value).strip()
    else:
        text = str(value).strip()
        if re.fullmatch(r"\d+\.0+", text):
            text = text.split(".", 1)[0]
    return text.zfill(width) if width is not None and text.isdigit() and len(text) < width else text


def _field_lookup(columns: Iterable[object]) -> dict[str, str]:
    return {_normalise(name): str(name) for name in columns}


def _find_field(columns: Iterable[object], *candidates: str) -> str | None:
    lookup = _field_lookup(columns)
    for candidate in candidates:
        found = lookup.get(_normalise(candidate))
        if found is not None:
            return found
    return None


def _require_field(columns: Iterable[object], label: str, *candidates: str) -> str:
    found = _find_field(columns, *candidates)
    if found is None:
        raise FusionError(
            f"Missing {label}. Expected one of {list(candidates)}; "
            f"available fields: {list(columns)}"
        )
    return found


def _layer_candidates(path: Path) -> list[tuple[str, str]]:
    try:
        layers = pyogrio.list_layers(path)
    except Exception as exc:  # pragma: no cover - GDAL message varies by platform
        raise FusionError(
            f"Cannot read {path}. The offline GDAL build must include OpenFileGDB. {exc}"
        ) from exc
    return [(str(name), str(geometry_type)) for name, geometry_type in layers]


def list_source_layers(path: Path) -> list[dict[str, Any]]:
    """Return FileGDB/GPKG layer names, geometry types and physical fields."""
    result = []
    for name, geometry_type in _layer_candidates(path):
        info = pyogrio.read_info(path, layer=name)
        result.append(
            {
                "name": name,
                "geometry_type": geometry_type,
                "fields": [str(field) for field in info["fields"]],
            }
        )
    return result


_ROLE_HINTS = {
    "dltb": ("dltb", "地类图斑", "2025地类"),
    "pdt": ("pdt", "坡度"),
    "eco_redline": ("stbhhx", "生态保护红线", "生态红线"),
    "permanent_basic_farmland": (
        "yjjbntbhtb", "yjjbnttb", "yjjbnt", "永久基本农田", "基本农田",
    ),
}


def _score_layer(role: str, name: str, fields: list[str]) -> int:
    normalised_name = _normalise(name)
    score = sum(100 for hint in _ROLE_HINTS[role] if _normalise(hint) in normalised_name)
    lookup = _field_lookup(fields)
    if role == "dltb":
        score += 30 if _find_field(lookup.values(), "DLBM", "地类编码") else 0
        score += 25 if _find_field(lookup.values(), "QSDWDM", "权属单位代码", "ZLDWDM", "坐落单位代码") else 0
        score += 20 if _find_field(lookup.values(), "BSM", "标识码") else 0
    elif role == "pdt":
        score += 40 if _find_field(lookup.values(), "PDJB", "坡度级别") else 0
        score += 20 if _find_field(lookup.values(), "BZPDJB", "标准坡度级别") else 0
    elif role == "eco_redline":
        score += 15 if _find_field(lookup.values(), "LHDM", "红线代码") else 0
        score += 15 if _find_field(lookup.values(), "LHLX", "红线类型") else 0
    return score


def _select_layer(role: str, source: Path, explicit: str | None) -> str:
    inventory = list_source_layers(source)
    names = {item["name"] for item in inventory}
    if explicit:
        if explicit not in names:
            raise FusionError(
                f"Layer {explicit!r} was not found in {source}. Available: {sorted(names)}"
            )
        return explicit
    polygon_layers = [
        item
        for item in inventory
        if "polygon" in item["geometry_type"].casefold()
    ]
    if len(polygon_layers) == 1:
        return polygon_layers[0]["name"]
    if not polygon_layers:
        raise FusionError(f"No polygon layer was found in {source}.")
    ranked = sorted(
        ((
            _score_layer(role, item["name"], item["fields"]),
            item["name"],
        ) for item in polygon_layers),
        reverse=True,
    )
    if not ranked or ranked[0][0] <= 0:
        raise FusionError(
            f"Cannot identify the {role} layer in {source}. "
            f"Pass an explicit --{role.replace('_', '-')} layer name."
        )
    best_score, best_name = ranked[0]
    tied = [name for score, name in ranked if score == best_score]
    if len(tied) > 1:
        raise FusionError(
            f"Multiple possible {role} layers in {source}: {tied}. "
            f"Pass --{role.replace('_', '-')} explicitly."
        )
    return best_name


def select_layers(
    source: Path,
    *,
    dltb: str | None = None,
    pdt: str | None = None,
    eco_redline: str | None = None,
    permanent_basic_farmland: str | None = None,
) -> LayerSelection:
    return LayerSelection(
        dltb=_select_layer("dltb", source, dltb),
        pdt=_select_layer("pdt", source, pdt),
        eco_redline=_select_layer("eco_redline", source, eco_redline),
        permanent_basic_farmland=_select_layer(
            "permanent_basic_farmland", source, permanent_basic_farmland
        ),
    )


def _polygonal(geometry):
    if geometry is None or geometry.is_empty:
        return geometry
    valid = make_valid(geometry) if not geometry.is_valid else geometry
    if valid.geom_type in {"Polygon", "MultiPolygon"}:
        return valid
    if valid.geom_type == "GeometryCollection":
        polygons = [part for part in valid.geoms if part.geom_type in {"Polygon", "MultiPolygon"}]
        return union_all(polygons) if polygons else None
    return None


def read_polygon_layer(
    path: Path,
    layer: str,
    *,
    required: bool,
    where: str | None = None,
) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    try:
        frame = gpd.read_file(path, layer=layer, engine="pyogrio", where=where)
    except Exception as exc:  # pragma: no cover - depends on GDAL error messages
        raise FusionError(f"Cannot read layer {layer!r} from {path}: {exc}") from exc
    if frame.crs is None:
        raise FusionError(f"Layer {layer!r} has no CRS: {path}")
    if frame.empty:
        raise FusionError(f"Layer {layer!r} has no features: {path}")
    raw_count = len(frame)
    null_or_empty = frame.geometry.isna() | frame.geometry.is_empty
    if bool(null_or_empty.any()):
        if required:
            raise FusionError(f"Layer {layer!r} has {int(null_or_empty.sum())} empty geometries.")
        frame = frame.loc[~null_or_empty].copy()
    invalid = ~frame.geometry.is_valid
    if bool(invalid.any()):
        frame.loc[invalid, "geometry"] = frame.loc[invalid, "geometry"].map(_polygonal)
    non_polygon = ~frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if bool(non_polygon.any()):
        frame.loc[non_polygon, "geometry"] = frame.loc[non_polygon, "geometry"].map(_polygonal)
    bad = frame.geometry.isna() | frame.geometry.is_empty
    if bool(bad.any()):
        if required:
            raise FusionError(
                f"Layer {layer!r} has {int(bad.sum())} non-polygon geometries after repair."
            )
        frame = frame.loc[~bad].copy()
    if frame.empty:
        raise FusionError(f"Layer {layer!r} contains no usable polygon features.")
    return frame.reset_index(drop=True), {
        "source_feature_count": raw_count,
        "invalid_geometry_repaired": int(invalid.sum()),
        "empty_or_non_polygon_dropped": int(raw_count - len(frame)),
    }


def _path_diagnostics(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved.is_file():
        stat = resolved.stat()
        return {
            "path": str(resolved),
            "kind": "file",
            "size_bytes": int(stat.st_size),
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }
    files = sorted(item for item in resolved.rglob("*") if item.is_file())
    total_bytes = sum(item.stat().st_size for item in files)
    return {
        "path": str(resolved),
        "kind": "directory",
        "file_count": len(files),
        "size_bytes": int(total_bytes),
        "sample_files": [str(item.relative_to(resolved)) for item in files[:20]],
    }


def _frame_diagnostics(
    frame: gpd.GeoDataFrame, qc: dict[str, int]
) -> dict[str, Any]:
    geometry_types = {
        str(name): int(count)
        for name, count in frame.geometry.geom_type.value_counts(dropna=False).items()
    }
    return {
        "feature_count": int(len(frame)),
        "field_count": int(len(frame.columns) - 1),
        "fields": [str(column) for column in frame.columns if column != frame.geometry.name],
        "crs": CRS.from_user_input(frame.crs).to_string(),
        "bounds": [float(value) for value in frame.total_bounds],
        "geometry_types": geometry_types,
        "geometry_qc": qc,
    }


def standardise_dltb(dltb: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add exact Paper9 field names while preserving all authority fields."""
    out = dltb.copy()
    bsm = _require_field(out.columns, "DLTB identifier", "BSM", "标识码")
    dlbm = _require_field(out.columns, "DLTB land-use code", "DLBM", "地类编码")
    dlmc = _require_field(out.columns, "DLTB land-use name", "DLMC", "地类名称")
    qsdwdm = _require_field(
        out.columns, "DLTB ownership/admin code", "QSDWDM", "权属单位代码", "ZLDWDM", "坐落单位代码"
    )
    qsdwmc = _find_field(out.columns, "QSDWMC", "权属单位名称", "ZLDWMC", "坐落单位名称")

    def set_standard(name: str, source: str, normaliser) -> None:
        existing = _find_field(out.columns, name)
        if existing is not None and _normalise(existing) == _normalise(name):
            out[name] = out[existing].map(normaliser)
        else:
            out[name] = out[source].map(normaliser)

    set_standard("BSM", bsm, _normalise_code)
    set_standard("DLBM", dlbm, _normalise_code)
    set_standard("DLMC", dlmc, lambda value: "" if pd.isna(value) else str(value).strip())
    set_standard("QSDWDM", qsdwdm, _normalise_code)
    if qsdwmc is not None:
        set_standard("QSDWMC", qsdwmc, lambda value: "" if pd.isna(value) else str(value).strip())
    else:
        out["QSDWMC"] = out["QSDWDM"]

    missing = {
        field: int(out[field].eq("").sum())
        for field in ("BSM", "DLBM", "QSDWDM")
    }
    if any(missing.values()):
        raise FusionError(f"DLTB contains blank required values: {missing}")
    duplicates = int(out["BSM"].duplicated().sum())
    if duplicates:
        raise FusionError(f"DLTB BSM is not unique: {duplicates} duplicate identifiers.")
    if not out["QSDWDM"].str.len().ge(9).all():
        raise FusionError("DLTB QSDWDM must contain at least nine digits for Paper9 township grouping.")
    try:
        code_report = analyse_land_use_codes(
            out["DLBM"], require_farmland=True, require_forest=True
        )
    except LandUseCodeError as exc:
        raise FusionError(str(exc)) from exc
    out["category"] = out["DLBM"].map(classify_land_use)
    out.attrs["land_use_codes"] = code_report.as_dict()
    return out


def classify_land_use(dlbm: object) -> str:
    category = classify_land_use_code(dlbm)
    return category.title() if category in {"farmland", "forest", "orchard"} else "Other"


def choose_metric_crs(dltb: gpd.GeoDataFrame, metric_crs: str | None) -> CRS:
    if metric_crs:
        crs = CRS.from_user_input(metric_crs)
    else:
        source = CRS.from_user_input(dltb.crs)
        if not source.is_geographic and any(
            (axis.unit_conversion_factor or 0.0) > 0 for axis in source.axis_info
        ):
            crs = source
        else:
            estimated = dltb.estimate_utm_crs()
            if estimated is None:
                raise FusionError("Cannot infer a metre-based CRS; pass --metric-crs explicitly.")
            crs = CRS.from_user_input(estimated)
    if crs.is_geographic:
        raise FusionError("--metric-crs must be a projected CRS with metre-like linear units.")
    factors = [axis.unit_conversion_factor for axis in crs.axis_info if axis.unit_conversion_factor]
    if factors and not all(math.isclose(float(factor), 1.0, rel_tol=0.0, abs_tol=1e-9) for factor in factors):
        raise FusionError(
            f"Metric CRS {crs.to_string()} does not use metres. Pass a metre-based --metric-crs."
        )
    return crs


def _load_dem(
    dem_paths: list[Path], coverage: gpd.GeoDataFrame
) -> tuple[np.ndarray, Any, CRS, dict[str, Any]]:
    if not dem_paths:
        raise FusionError("At least one local DEM is required. Public-network download is intentionally unsupported.")
    missing = [str(path) for path in dem_paths if not path.is_file()]
    if missing:
        raise FusionError(f"DEM file(s) not found: {missing}")
    sources = [rasterio.open(path) for path in dem_paths]
    try:
        if any(source.count != 1 for source in sources):
            raise FusionError("Each DEM must have exactly one elevation band.")
        if any(source.crs is None for source in sources):
            raise FusionError("Each DEM must have a CRS.")
        crs = CRS.from_user_input(sources[0].crs)
        if any(CRS.from_user_input(source.crs) != crs for source in sources[1:]):
            raise FusionError("All DEM tiles must share a CRS. Build a local VRT or reproject before fusion.")
        coverage_in_dem_crs = (
            coverage
            if CRS.from_user_input(coverage.crs) == crs
            else coverage.to_crs(crs)
        )
        left, bottom, right, top = map(float, coverage_in_dem_crs.total_bounds)
        x_res = abs(float(sources[0].transform.a))
        y_res = abs(float(sources[0].transform.e))
        padding = 3
        crop_bounds = (
            left - padding * x_res,
            bottom - padding * y_res,
            right + padding * x_res,
            top + padding * y_res,
        )
        source_left = min(float(item.bounds.left) for item in sources)
        source_bottom = min(float(item.bounds.bottom) for item in sources)
        source_right = max(float(item.bounds.right) for item in sources)
        source_top = max(float(item.bounds.top) for item in sources)
        if (
            crop_bounds[2] <= source_left
            or crop_bounds[0] >= source_right
            or crop_bounds[3] <= source_bottom
            or crop_bounds[1] >= source_top
        ):
            raise FusionError(
                "The supplied DEM tiles do not overlap the DLTB extent. "
                f"DLTB bounds in {crs.to_string()}: {[left, bottom, right, top]}"
            )
        merged, transform = merge_rasters(
            sources,
            bounds=crop_bounds,
            nodata=np.nan,
            dtype="float64",
        )
        elevation = np.asarray(merged[0], dtype=np.float64)
        return elevation, transform, crs, {
            "paths": [str(path) for path in dem_paths],
            "shape": [int(elevation.shape[0]), int(elevation.shape[1])],
            "crs": crs.to_string(),
            "pixel_size_native": [abs(float(transform.a)), abs(float(transform.e))],
            "cropped_to_dltb_bounds": True,
            "crop_bounds": [float(value) for value in crop_bounds],
        }
    finally:
        for source in sources:
            source.close()


def _horn_slope_degrees(elevation: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    padded = np.pad(elevation, 1, mode="edge")
    a = padded[:-2, :-2]
    b = padded[:-2, 1:-1]
    c = padded[:-2, 2:]
    d = padded[1:-1, :-2]
    f = padded[1:-1, 2:]
    g = padded[2:, :-2]
    h = padded[2:, 1:-1]
    i = padded[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * dx_m)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8.0 * dy_m)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    no_data = np.isnan(a) | np.isnan(b) | np.isnan(c) | np.isnan(d) | np.isnan(f) | np.isnan(g) | np.isnan(h) | np.isnan(i)
    return np.where(no_data, np.nan, slope)


def _dem_pixel_size_metres(transform, crs: CRS, height: int) -> tuple[float, float, str]:
    if abs(float(transform.b)) > 1e-12 or abs(float(transform.d)) > 1e-12:
        raise FusionError("Rotated DEM grids are unsupported; rectify the raster before fusion.")
    if crs.is_geographic:
        geod = crs.get_geod()
        latitude = float(transform.f - height * abs(float(transform.e)) / 2.0)
        longitude = float(transform.c)
        dx_deg, dy_deg = abs(float(transform.a)), abs(float(transform.e))
        _, _, dx_m = geod.inv(longitude - dx_deg / 2, latitude, longitude + dx_deg / 2, latitude)
        _, _, dy_m = geod.inv(longitude, latitude - dy_deg / 2, longitude, latitude + dy_deg / 2)
        return float(dx_m), float(dy_m), "horn_geographic_centre_latitude"
    factors = [axis.unit_conversion_factor for axis in crs.axis_info if axis.unit_conversion_factor]
    factor = float(factors[0]) if factors else 1.0
    return abs(float(transform.a)) * factor, abs(float(transform.e)) * factor, "horn_projected"


def _representative_samples(
    polygons: gpd.GeoDataFrame, slope: np.ndarray, transform, slope_crs: CRS, missing: np.ndarray
) -> np.ndarray:
    values = np.full(len(polygons), np.nan, dtype=np.float64)
    subset = polygons.iloc[missing]
    if CRS.from_user_input(subset.crs) != slope_crs:
        subset = subset.to_crs(slope_crs)
    points = subset.geometry.representative_point()
    rows, cols = rowcol(transform, points.x.to_numpy(), points.y.to_numpy())
    height, width = slope.shape
    for output_idx, r, c in zip(missing, rows, cols):
        best: tuple[float, float] | None = None
        for radius in range(0, 3):
            for rr in range(max(0, r - radius), min(height, r + radius + 1)):
                for cc in range(max(0, c - radius), min(width, c + radius + 1)):
                    candidate = slope[rr, cc]
                    if np.isnan(candidate):
                        continue
                    distance = float((rr - r) ** 2 + (cc - c) ** 2)
                    if best is None or distance < best[0]:
                        best = (distance, float(candidate))
        if best is not None:
            values[output_idx] = best[1]
    return values


def add_dem_slope(
    dltb: gpd.GeoDataFrame, dem_paths: list[Path], *, z_factor: float = 1.0
) -> tuple[gpd.GeoDataFrame, SlopeReport, dict[str, Any]]:
    elevation, transform, dem_crs, dem_meta = _load_dem(dem_paths, dltb)
    if z_factor <= 0:
        raise FusionError("--z-factor must be greater than zero.")
    elevation *= z_factor
    dx_m, dy_m, method = _dem_pixel_size_metres(transform, dem_crs, elevation.shape[0])
    if dx_m <= 0 or dy_m <= 0:
        raise FusionError("Invalid DEM pixel size.")
    slope = _horn_slope_degrees(elevation, dx_m, dy_m)
    n = len(dltb)
    polygons = dltb if CRS.from_user_input(dltb.crs) == dem_crs else dltb.to_crs(dem_crs)
    zones = rasterize(
        ((geom, index + 1) for index, geom in enumerate(polygons.geometry)),
        out_shape=slope.shape,
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    valid = (zones > 0) & ~np.isnan(slope)
    zone_values = zones[valid].astype(np.int64)
    slope_values = slope[valid]
    sums = np.bincount(zone_values, weights=slope_values, minlength=n + 1)
    counts = np.bincount(zone_values, minlength=n + 1)
    maximums = np.full(n + 1, np.nan, dtype=np.float64)
    if len(zone_values):
        maximums.fill(-np.inf)
        np.maximum.at(maximums, zone_values, slope_values)
        maximums[maximums == -np.inf] = np.nan
    means = np.divide(sums[1:], counts[1:], out=np.full(n, np.nan), where=counts[1:] > 0)
    maximums = maximums[1:]
    pixel_counts = counts[1:].astype(np.int64)
    assignment = np.full(n, "pixel", dtype=object)
    missing = np.flatnonzero(np.isnan(means))
    if len(missing):
        fallback = _representative_samples(dltb, slope, transform, dem_crs, missing)
        means[missing] = fallback[missing]
        maximums[missing] = fallback[missing]
        assignment[missing] = np.where(np.isnan(fallback[missing]), "null", "representative")
    out = dltb.copy()
    out["slope_mean"] = means
    out["slope_max"] = maximums
    out["slope_pixel_count"] = pixel_counts
    out["slope_assignment"] = assignment
    out["slope_fallback_issue"] = np.where(assignment == "null", "outside_dem_or_nodata", "")
    null_count = int(np.isnan(means).sum())
    report = SlopeReport(
        method=method,
        parcel_count=n,
        pixel_count=int((assignment == "pixel").sum()),
        representative_count=int((assignment == "representative").sum()),
        null_count=null_count,
        minimum=float(np.nanmin(means)) if null_count < n else float("nan"),
        maximum=float(np.nanmax(means)) if null_count < n else float("nan"),
        mean=float(np.nanmean(means)) if null_count < n else float("nan"),
    )
    dem_meta.update({"method": method, "pixel_size_metres": [dx_m, dy_m], "z_factor": z_factor})
    return out, report, dem_meta


def _dominant_overlap(
    parcels: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
    attributes: list[str],
    metric_crs: CRS,
    *,
    chunk_size: int = 25_000,
) -> pd.DataFrame:
    left = parcels[["geometry"]].to_crs(metric_crs).copy()
    right = zones[[*attributes, "geometry"]].to_crs(metric_crs).copy()
    right["_right_id"] = np.arange(len(right), dtype=np.int64)
    best: dict[int, tuple[float, int]] = {}
    for start in range(0, len(left), chunk_size):
        chunk = left.iloc[start : start + chunk_size]
        pairs = gpd.sjoin(chunk, right[["_right_id", "geometry"]], how="inner", predicate="intersects")
        if pairs.empty:
            continue
        right_geometry = right.geometry.iloc[pairs["_right_id"].to_numpy()].array
        overlap = shape_area(intersection(pairs.geometry.array, right_geometry))
        for parcel_id, right_id, overlap_m2 in zip(pairs.index, pairs["_right_id"], overlap):
            value = float(overlap_m2)
            if value <= 0:
                continue
            prior = best.get(int(parcel_id))
            if prior is None or value > prior[0]:
                best[int(parcel_id)] = (value, int(right_id))
    values: dict[str, list[Any]] = {attribute: [None] * len(parcels) for attribute in attributes}
    overlap_m2 = np.zeros(len(parcels), dtype=np.float64)
    for parcel_id, (area_m2, right_id) in best.items():
        overlap_m2[parcel_id] = area_m2
        for attribute in attributes:
            values[attribute][parcel_id] = right.iloc[right_id][attribute]
    result = pd.DataFrame(values)
    result["dominant_overlap_m2"] = overlap_m2
    return result


def _constraint_overlap_m2(
    parcels: gpd.GeoDataFrame, constraints: gpd.GeoDataFrame, metric_crs: CRS, *, chunk_size: int = 25_000
) -> np.ndarray:
    left = parcels[["geometry"]].to_crs(metric_crs)
    right = constraints[["geometry"]].to_crs(metric_crs)
    merged = union_all(right.geometry.array)
    if merged is None or merged.is_empty:
        return np.zeros(len(parcels), dtype=np.float64)
    dissolved = gpd.GeoDataFrame(
        geometry=gpd.GeoSeries([merged], crs=metric_crs).explode(index_parts=False),
        crs=metric_crs,
    ).reset_index(drop=True)
    result = np.zeros(len(parcels), dtype=np.float64)
    for start in range(0, len(left), chunk_size):
        chunk = left.iloc[start : start + chunk_size]
        pairs = gpd.sjoin(chunk, dissolved, how="inner", predicate="intersects")
        if pairs.empty:
            continue
        right_geometry = dissolved.geometry.iloc[pairs["index_right"].to_numpy()].array
        overlaps = shape_area(intersection(pairs.geometry.array, right_geometry))
        np.add.at(result, pairs.index.to_numpy(dtype=np.int64), np.maximum(overlaps, 0.0))
    return result


def _grade_from_value(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, np.integer)) and 1 <= int(value) <= 5:
        return int(value)
    if isinstance(value, (float, np.floating)) and math.isfinite(float(value)) and 1 <= int(value) <= 5:
        return int(value)
    text = str(value).strip().upper().replace(" ", "")
    roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5}
    if text in roman:
        return roman[text]
    for token in sorted(roman, key=len, reverse=True):
        if text.startswith(token):
            return roman[token]
    match = re.search(r"(?<!\d)([1-5])(?!\d)", text)
    return int(match.group(1)) if match else None


def slope_grade(slope_degrees: np.ndarray) -> np.ndarray:
    return np.select(
        [slope_degrees <= 2, slope_degrees <= 6, slope_degrees <= 15, slope_degrees <= 25],
        [1, 2, 3, 4],
        default=5,
    ).astype(np.int8)


def add_constraint_fields(
    dltb: gpd.GeoDataFrame,
    pdt: gpd.GeoDataFrame,
    eco_redline: gpd.GeoDataFrame,
    permanent_basic_farmland: gpd.GeoDataFrame,
    *,
    metric_crs: CRS,
    lock_min_overlap_m2: float,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    if lock_min_overlap_m2 < 0:
        raise FusionError("--lock-min-overlap-m2 cannot be negative.")
    pdjb = _require_field(pdt.columns, "PDT grade", "PDJB", "坡度级别")
    bzpdjb = _find_field(pdt.columns, "BZPDJB", "标准坡度级别")
    pdt_attributes = [pdjb] + ([bzpdjb] if bzpdjb else [])
    dominant = _dominant_overlap(dltb, pdt, pdt_attributes, metric_crs)
    metric_dltb = dltb.to_crs(metric_crs)
    parcel_area_m2 = metric_dltb.geometry.area.to_numpy(dtype=np.float64)
    eco_overlap_m2 = _constraint_overlap_m2(dltb, eco_redline, metric_crs)
    pbf_overlap_m2 = _constraint_overlap_m2(dltb, permanent_basic_farmland, metric_crs)
    eco_hit = eco_overlap_m2 > lock_min_overlap_m2
    pbf_hit = pbf_overlap_m2 > lock_min_overlap_m2
    pdt_grade = dominant[pdjb].map(_grade_from_value)
    if bzpdjb:
        pdt_grade = pdt_grade.fillna(dominant[bzpdjb].map(_grade_from_value))
    dem_grade = slope_grade(dltb["slope_mean"].to_numpy(dtype=np.float64))
    pdt_grade_numeric = pdt_grade.fillna(-1).astype(np.int8).to_numpy()
    grade_match = np.where(pdt_grade_numeric < 1, -1, (pdt_grade_numeric == dem_grade).astype(np.int8))

    out = dltb.copy()
    out["AREA_M2"] = parcel_area_m2
    out["PDT_PDJB"] = dominant[pdjb].astype("string")
    out["PDT_BZPDJB"] = dominant[bzpdjb].astype("string") if bzpdjb else pd.Series(pd.NA, index=out.index, dtype="string")
    out["PDT_OV_PCT"] = np.divide(
        dominant["dominant_overlap_m2"].to_numpy(), parcel_area_m2,
        out=np.zeros(len(out), dtype=np.float64), where=parcel_area_m2 > 0,
    ) * 100.0
    out["PDT_GRADE"] = pdt_grade_numeric
    out["DEM_GRADE"] = dem_grade
    out["GRD_MATCH"] = grade_match
    out["ECO_OV_M2"] = eco_overlap_m2
    out["ECO_PCT"] = np.divide(eco_overlap_m2, parcel_area_m2, out=np.zeros(len(out)), where=parcel_area_m2 > 0) * 100.0
    out["PBF_OV_M2"] = pbf_overlap_m2
    out["PBF_PCT"] = np.divide(pbf_overlap_m2, parcel_area_m2, out=np.zeros(len(out)), where=parcel_area_m2 > 0) * 100.0
    out["LOCK_C2F"] = (eco_hit | pbf_hit).astype(np.int8)
    out["LOCK_F2C"] = (eco_hit | pbf_hit).astype(np.int8)
    out["EXCH_LOCK"] = (eco_hit | pbf_hit).astype(np.int8)
    reasons = np.full(len(out), "", dtype=object)
    reasons[eco_hit] = "ECO_REDLINE"
    reasons[pbf_hit] = np.where(reasons[pbf_hit] == "", "PERMANENT_BASIC_FARMLAND", reasons[pbf_hit] + ";PERMANENT_BASIC_FARMLAND")
    out["LOCK_RSN"] = reasons
    code_categories = out["DLBM"].map(classify_land_use_code)
    is_forest = code_categories.eq("forest").to_numpy()
    is_farmland = code_categories.eq("farmland").to_numpy()
    review = (pbf_hit & is_forest) | (eco_hit & is_farmland)
    out["REVIEW_REQ"] = review.astype(np.int8)
    out["REVIEW_RSN"] = np.where(
        pbf_hit & is_forest,
        "FOREST_OVERLAPS_PERMANENT_BASIC_FARMLAND",
        np.where(eco_hit & is_farmland, "CULTIVATED_LAND_IN_ECO_REDLINE", ""),
    )
    return out, {
        "lock_min_overlap_m2": lock_min_overlap_m2,
        "eco_redline_overlap_parcels": int(eco_hit.sum()),
        "permanent_basic_farmland_overlap_parcels": int(pbf_hit.sum()),
        "exchange_locked_parcels": int((eco_hit | pbf_hit).sum()),
        "forest_in_permanent_basic_farmland_review": int((pbf_hit & is_forest).sum()),
        "cultivated_land_in_eco_redline_review": int((eco_hit & is_farmland).sum()),
        "pdt_grade_matched": int((grade_match == 1).sum()),
        "pdt_grade_mismatched": int((grade_match == 0).sum()),
        "pdt_grade_unavailable": int((grade_match == -1).sum()),
    }


def _build_dltb_admin_proxy(dltb: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Create a DLTB-derived fallback label layer."""
    units = dltb[["QSDWDM", "QSDWMC", "geometry"]].rename(columns={"QSDWDM": "XZQDM", "QSDWMC": "XZQMC"})
    units = units.dissolve(by=["XZQDM", "XZQMC"], as_index=False)
    units["admin_level"] = np.where(units["XZQDM"].str.len() >= 12, "village", "township")
    units["admin_parent_code"] = units["XZQDM"].str.slice(0, 9)
    units["source_level"] = "DLTB_QSDWDM_DISSOLVE"
    units["source_dataset"] = "authoritative_dltb"
    units["not_for_production"] = True
    return units


def build_admin_units(
    dltb: gpd.GeoDataFrame,
    *,
    metric_crs: CRS,
    reference_path: Path | None,
    reference_layer: str,
    reference_county_code: str | None = None,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Build township reference geometry, preferring the bundled 44-feature layer."""
    county_codes = dltb["QSDWDM"].astype(str).str.extract(r"^(\d{6})", expand=False)
    county_codes = county_codes.dropna()
    dltb_county_code = str(county_codes.mode().iloc[0]) if not county_codes.empty else ""
    county_code = reference_county_code or dltb_county_code
    if reference_path is None:
        units = _build_dltb_admin_proxy(dltb)
        return units, {
            "mode": "dltb_dissolve_fallback",
            "county_code": county_code,
            "dltb_county_code": dltb_county_code,
            "feature_count": int(len(units)),
            "warning": "Bundled township reference was not supplied; DLTB dissolve was used.",
        }
    if not reference_path.is_file():
        raise FusionError(f"Administrative reference file not found: {reference_path}")

    reference, reference_qc = read_polygon_layer(
        reference_path, reference_layer, required=False
    )
    name_field = _require_field(reference.columns, "township name", "XZQMC", "乡", "乡镇名称")
    county_field = _require_field(reference.columns, "reference county code", "county_code", "县代码")
    reference["_county_code"] = reference[county_field].map(_normalise_code)
    selected = reference.loc[reference["_county_code"].eq(county_code)].copy()
    if selected.empty:
        available = sorted(reference["_county_code"].dropna().astype(str).unique())
        raise FusionError(
            f"Administrative reference has no features for county code {county_code!r}; "
            f"available county codes: {available}"
        )
    selected = selected.reset_index(drop=True)
    selected["XZQMC"] = selected[name_field].astype(str).str.strip()
    if selected["XZQMC"].eq("").any():
        raise FusionError("Administrative reference contains blank township names.")

    dltb_codes = dltb[["QSDWDM", "geometry"]].copy()
    dltb_codes["_QSDWDM9"] = dltb_codes["QSDWDM"].astype(str).str.slice(0, 9)
    dominant = _dominant_overlap(
        selected,
        dltb_codes,
        ["_QSDWDM9"],
        metric_crs,
    )
    selected["XZQDM"] = dominant["_QSDWDM9"].fillna("").astype(str)
    selected["admin_level"] = "township"
    selected["admin_parent_code"] = county_code
    selected["code_source"] = np.where(
        selected["XZQDM"].eq(""),
        "UNAVAILABLE",
        "DLTB_DOMINANT_OVERLAP",
    )
    selected["source_level"] = "BUNDLED_TOWNSHIP_SPATIAL_REFERENCE"
    selected["not_for_exchange_constraints"] = True
    source_date_field = _find_field(selected.columns, "source_date")
    source_dataset_field = _find_field(selected.columns, "source_dataset")
    keep = [
        "XZQDM",
        "XZQMC",
        "admin_level",
        "admin_parent_code",
        "code_source",
        "source_level",
        "not_for_exchange_constraints",
    ]
    for optional in (
        "province_name",
        "city_name",
        "county_name",
        source_date_field,
        source_dataset_field,
    ):
        if optional and optional in selected.columns and optional not in keep:
            keep.append(optional)
    units = selected[[*keep, "geometry"]].copy()
    unmatched_codes = int(units["XZQDM"].eq("").sum())
    return units, {
        "mode": "bundled_township_spatial_reference",
        "path": str(reference_path),
        "layer": reference_layer,
        "sha256": _sha256(reference_path),
        "county_code": county_code,
        "dltb_county_code": dltb_county_code,
        "source_feature_count": int(len(reference)),
        "selected_feature_count": int(len(units)),
        "township_code_unmatched": unmatched_codes,
        "geometry_qc": reference_qc,
        "source_date": (
            str(selected[source_date_field].dropna().iloc[0])
            if source_date_field and not selected[source_date_field].dropna().empty
            else "unknown"
        ),
        "role": "township name and spatial reference only; never an exchange constraint",
        "warning": (
            "Reference source date is 2021-06-22; validate township changes against "
            "the customer's 2025 administrative records."
        ),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_gpkg(path: Path, frame: gpd.GeoDataFrame, layer: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    frame.to_file(path, layer=layer, driver="GPKG", engine="pyogrio")


_KNOWN_COUNTIES = {
    "500120": "重庆市璧山区",
    "511011": "四川省内江市东兴区",
}


def _infer_county_name(
    dltb: gpd.GeoDataFrame, dltb_source: Path
) -> tuple[str, str]:
    name_field = _find_field(
        dltb.columns,
        "县（区）",
        "县(区)",
        "县区",
        "县名",
        "行政区名称",
    )
    if name_field is not None:
        names = dltb[name_field].dropna().astype(str).str.strip()
        names = names[names.ne("")]
        if not names.empty:
            return str(names.mode().iloc[0]), f"DLTB.{name_field}"

    codes = dltb["QSDWDM"].astype(str).str.extract(r"^(\d{6})", expand=False)
    codes = codes.dropna()
    if not codes.empty:
        county_code = str(codes.mode().iloc[0])
        if county_code in _KNOWN_COUNTIES:
            return _KNOWN_COUNTIES[county_code], "DLTB.QSDWDM"
        return f"县区_{county_code}", "DLTB.QSDWDM"

    source_name = dltb_source.name
    if source_name.casefold().endswith(".gdb"):
        source_name = source_name[:-4]
    return source_name or "未命名县区", "DLTB source path"


def _write_dem_placeholder(path: Path, dltb: gpd.GeoDataFrame) -> None:
    left, bottom, right, top = map(float, dltb.total_bounds)
    if not (right > left and top > bottom):
        raise FusionError("Cannot create DEM_placeholder.tif from an empty DLTB extent.")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=1,
        width=1,
        count=1,
        dtype="float32",
        crs=dltb.crs,
        transform=from_bounds(left, bottom, right, top, 1, 1),
        nodata=-9999.0,
        compress="deflate",
    ) as target:
        target.write(np.zeros((1, 1), dtype=np.float32), 1)


def _resolve_sources(
    *,
    source: Path | None,
    dltb_source: Path | None,
    pdt_source: Path | None,
    eco_redline_source: Path | None,
    permanent_basic_farmland_source: Path | None,
) -> dict[str, Path]:
    resolved = {
        "dltb": dltb_source or source,
        "pdt": pdt_source or source,
        "eco_redline": eco_redline_source or source,
        "permanent_basic_farmland": permanent_basic_farmland_source or source,
    }
    missing_roles = [role for role, path in resolved.items() if path is None]
    if missing_roles:
        raise FusionError(
            "Four authority sources are required. Missing: "
            + ", ".join(missing_roles)
        )
    sources = {role: Path(path) for role, path in resolved.items() if path is not None}
    missing_paths = [str(path) for path in sources.values() if not path.exists()]
    if missing_paths:
        raise FusionError(f"Authority source(s) do not exist: {missing_paths}")
    return sources


def fuse_county(
    *,
    source: Path | None = None,
    dltb_source: Path | None = None,
    pdt_source: Path | None = None,
    eco_redline_source: Path | None = None,
    permanent_basic_farmland_source: Path | None = None,
    county_name: str | None = None,
    output_dir: Path,
    dem_paths: list[Path],
    admin_reference: Path | None = None,
    admin_reference_layer: str = "admin_reference",
    metric_crs: str | None = None,
    dltb_layer: str | None = None,
    pdt_layer: str | None = None,
    eco_redline_layer: str | None = None,
    permanent_basic_farmland_layer: str | None = None,
    lock_min_overlap_m2: float = 1.0,
    z_factor: float = 1.0,
    diagnostics: FusionDiagnostics | NullDiagnostics | None = None,
) -> dict[str, Any]:
    """Fuse one county's four authority layers into Paper9 input artifacts."""
    diag = diagnostics or NullDiagnostics()
    with diag.stage("resolve_sources"):
        sources = _resolve_sources(
            source=source,
            dltb_source=dltb_source,
            pdt_source=pdt_source,
            eco_redline_source=eco_redline_source,
            permanent_basic_farmland_source=permanent_basic_farmland_source,
        )
        diag.emit(
            "INFO",
            "source_filesystem_inventory",
            "Authority source directory statistics collected.",
            sources={role: _path_diagnostics(path) for role, path in sources.items()},
            admin_reference=(
                _path_diagnostics(admin_reference)
                if admin_reference is not None and admin_reference.exists()
                else str(admin_reference) if admin_reference is not None else None
            ),
            dem=[_path_diagnostics(path) if path.exists() else {"path": str(path), "missing": True} for path in dem_paths],
        )

    with diag.stage("select_layers"):
        layers = LayerSelection(
            dltb=_select_layer("dltb", sources["dltb"], dltb_layer),
            pdt=_select_layer("pdt", sources["pdt"], pdt_layer),
            eco_redline=_select_layer(
                "eco_redline", sources["eco_redline"], eco_redline_layer
            ),
            permanent_basic_farmland=_select_layer(
                "permanent_basic_farmland",
                sources["permanent_basic_farmland"],
                permanent_basic_farmland_layer,
            ),
        )
        diag.emit(
            "INFO",
            "layer_selection",
            "Polygon layers were selected automatically or from explicit overrides.",
            selected=layers.__dict__,
            inventories={role: list_source_layers(path) for role, path in sources.items()},
        )

    with diag.stage("read_and_repair_layers"):
        dltb_raw, dltb_qc = read_polygon_layer(
            sources["dltb"], layers.dltb, required=True
        )
        pdt, pdt_qc = read_polygon_layer(sources["pdt"], layers.pdt, required=True)
        eco, eco_qc = read_polygon_layer(
            sources["eco_redline"], layers.eco_redline, required=False
        )
        pbf, pbf_qc = read_polygon_layer(
            sources["permanent_basic_farmland"],
            layers.permanent_basic_farmland,
            required=False,
        )
        diag.emit(
            "INFO",
            "layer_diagnostics",
            "Layer schemas, CRS, bounds, geometry types, and repair counts collected.",
            layers={
                "dltb": _frame_diagnostics(dltb_raw, dltb_qc),
                "pdt": _frame_diagnostics(pdt, pdt_qc),
                "eco_redline": _frame_diagnostics(eco, eco_qc),
                "permanent_basic_farmland": _frame_diagnostics(pbf, pbf_qc),
            },
        )

    with diag.stage("standardise_dltb_and_infer_county"):
        dltb = standardise_dltb(dltb_raw)
        land_use_code_report = dict(dltb.attrs["land_use_codes"])
        inferred_county_name, county_name_source = _infer_county_name(
            dltb, sources["dltb"]
        )
        resolved_county_name = county_name or inferred_county_name
        if county_name:
            county_name_source = "explicit"
        category_counts = {
            str(name): int(count)
            for name, count in dltb["category"].value_counts(dropna=False).items()
        }
        township_prefix_counts = (
            dltb["QSDWDM"].astype(str).str.slice(0, 9).value_counts().sort_index()
        )
        diag.emit(
            "INFO",
            "dltb_standardisation",
            "DLTB required fields were standardised and county identity inferred.",
            county_name=resolved_county_name,
            county_name_source=county_name_source,
            feature_count=int(len(dltb)),
            category_counts=category_counts,
            land_use_codes=land_use_code_report,
            township_prefix_count=int(len(township_prefix_counts)),
            township_prefix_parcel_counts={
                str(code): int(count) for code, count in township_prefix_counts.items()
            },
        )

    with diag.stage("choose_metric_crs"):
        metric = choose_metric_crs(dltb, metric_crs)
        diag.emit(
            "INFO",
            "metric_crs",
            "Metre-based CRS selected for area and overlap calculations.",
            source_crs=CRS.from_user_input(dltb.crs).to_string(),
            metric_crs=metric.to_string(),
        )

    with diag.stage("dem_slope"):
        dltb, slope_report, dem_meta = add_dem_slope(dltb, dem_paths, z_factor=z_factor)
        diag.emit(
            "INFO",
            "dem_slope_summary",
            "Continuous Horn slope was computed from the bundled offline DEM.",
            dem=dem_meta,
            slope=slope_report.as_dict(),
        )
    if slope_report.null_count:
        raise FusionError(
            f"{slope_report.null_count} DLTB parcels have no local DEM slope after representative-point fallback. "
            "Supply DEM coverage for the entire county; no median filling is permitted."
        )

    with diag.stage("authority_constraints_and_pdt_qc"):
        dltb, constraint_report = add_constraint_fields(
            dltb, pdt, eco, pbf, metric_crs=metric, lock_min_overlap_m2=lock_min_overlap_m2
        )
        diag.emit(
            "INFO",
            "pdt_role",
            "PDT was used only to compare authority slope grades with DEM-derived grades.",
            role="quality_control_only",
            affects_continuous_slope=False,
            affects_exchange_lock=False,
            affects_optimizer_objective=False,
            statistics={
                key: value for key, value in constraint_report.items() if key.startswith("pdt_")
            },
        )
        diag.emit(
            "INFO",
            "constraint_summary",
            "Ecological redline and permanent basic farmland overlaps were evaluated.",
            constraints=constraint_report,
        )

    with diag.stage("administrative_reference"):
        admin_units, admin_report = build_admin_units(
            dltb,
            metric_crs=metric,
            reference_path=admin_reference,
            reference_layer=admin_reference_layer,
        )
        if admin_report.get("warning"):
            diag.warning(
                "administrative_reference_warning",
                str(admin_report["warning"]),
                admin_reference=admin_report,
            )
        diag.emit(
            "INFO",
            "administrative_reference_summary",
            "Administrative reference layer was prepared for township labels.",
            admin_reference=admin_report,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    dltb_path = output_dir / "DLTB_with_authority_slope.gpkg"
    admin_path = output_dir / "admin_units.gpkg"
    constraints_path = output_dir / "authority_constraints.gpkg"
    dem_placeholder_path = output_dir / "DEM_placeholder.tif"
    summary_path = output_dir / "fusion_summary.csv"
    with diag.stage("write_outputs"):
        _write_gpkg(dltb_path, dltb, "dltb")
        _write_gpkg(admin_path, admin_units, "admin_units")
        _write_dem_placeholder(dem_placeholder_path, dltb)
        _write_gpkg(constraints_path, pdt, "pdt")
        eco.to_file(
            constraints_path,
            layer="eco_redline",
            driver="GPKG",
            engine="pyogrio",
            mode="a",
        )
        pbf.to_file(
            constraints_path,
            layer="permanent_basic_farmland",
            driver="GPKG",
            engine="pyogrio",
            mode="a",
        )
        locked = dltb[dltb["EXCH_LOCK"].eq(1)].copy()
        if not locked.empty:
            locked.to_file(
                constraints_path,
                layer="locked_dltb_audit",
                driver="GPKG",
                engine="pyogrio",
                mode="a",
            )
        summary = pd.DataFrame([
            {
                "category": category,
                "parcel_count": int(len(group)),
                "area_ha": float(group["AREA_M2"].sum() / 10_000.0),
                "locked_parcel_count": int(group["EXCH_LOCK"].sum()),
            }
            for category, group in dltb.groupby("category", dropna=False)
        ])
        summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
        diag.emit(
            "INFO",
            "output_files",
            "Fusion outputs were written and hashed.",
            outputs={
                "dltb": {"path": str(dltb_path), "size_bytes": dltb_path.stat().st_size, "sha256": _sha256(dltb_path)},
                "admin_units": {"path": str(admin_path), "size_bytes": admin_path.stat().st_size, "sha256": _sha256(admin_path)},
                "constraints": {"path": str(constraints_path), "size_bytes": constraints_path.stat().st_size, "sha256": _sha256(constraints_path)},
                "dem_placeholder": {"path": str(dem_placeholder_path), "size_bytes": dem_placeholder_path.stat().st_size, "sha256": _sha256(dem_placeholder_path)},
                "summary": {"path": str(summary_path), "size_bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)},
            },
        )
    report = {
        "schema_version": "paper9.authoritative_fusion.v1",
        "run_id": diag.run_id,
        "run_timestamp_utc": _utc_now(),
        "county_name": resolved_county_name,
        "county_name_source": county_name_source,
        "backend": "open_source_geopandas_pyogrio_rasterio",
        "arcgis_or_arcpy_used": False,
        "network_access_used": False,
        "source": {
            "mode": "single_container" if len(set(sources.values())) == 1 else "four_sources",
            "path": str(source) if source is not None else None,
            "layers": layers.__dict__,
            "datasets": {
                role: {"path": str(sources[role]), "layer": getattr(layers, role)}
                for role in sources
            },
        },
        "metric_crs": metric.to_string(),
        "layer_qc": {"dltb": dltb_qc, "pdt": pdt_qc, "eco_redline": eco_qc, "permanent_basic_farmland": pbf_qc},
        "runtime": diag.environment,
        "timings_seconds": diag.timings,
        "warnings": diag.warnings,
        "dem": dem_meta,
        "slope": slope_report.as_dict(),
        "administrative_reference": admin_report,
        "pdt": {
            "role": "quality_control_only",
            "affects_continuous_slope": False,
            "affects_exchange_lock": False,
            "affects_optimizer_objective": False,
            "purpose": "Compare customer authority slope grade with the DEM-derived grade and expose mismatches for review.",
        },
        "constraints": constraint_report,
        "land_use_codes": land_use_code_report,
        "policy": {
            "eco_redline": "Any material overlap is locked against both automated conversion directions.",
            "permanent_basic_farmland": "Any material overlap is locked against both automated conversion directions by default; forest overlap requires manual data/approval review.",
            "automatic_forest_to_cultivated_land_in_permanent_basic_farmland": False,
            "automatic_cultivated_land_to_forest_in_eco_redline": False,
        },
        "outputs": {
            "dltb": {"path": str(dltb_path), "layer": "dltb", "sha256": _sha256(dltb_path), "feature_count": int(len(dltb))},
            "admin_units": {
                "path": str(admin_path),
                "layer": "admin_units",
                "sha256": _sha256(admin_path),
                "feature_count": int(len(admin_units)),
                "source_mode": admin_report["mode"],
                "warning": admin_report.get("warning"),
            },
            "constraints": {"path": str(constraints_path), "sha256": _sha256(constraints_path)},
            "summary": {"path": str(summary_path), "sha256": _sha256(summary_path)},
            "dem_placeholder": {
                "path": str(dem_placeholder_path),
                "sha256": _sha256(dem_placeholder_path),
                "purpose": "Paper9 from_field interface placeholder; slope values come from slope_mean.",
            },
        },
        "logs": {
            "human": str(diag.log_path) if diag.log_path else None,
            "events_jsonl": str(diag.events_path) if diag.events_path else None,
            "latest_human": str(diag.log_path.parent / "authoritative_fusion-latest.log") if diag.log_path else None,
            "latest_events_jsonl": str(diag.events_path.parent / "authoritative_fusion-latest.jsonl") if diag.events_path else None,
        },
    }
    report_path = output_dir / "fusion_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    diag.emit(
        "INFO",
        "fusion_report",
        "Fusion report was written.",
        path=str(report_path),
        sha256=_sha256(report_path),
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fuse one county's authoritative FileGDB layers into ArcGIS-free Paper9 inputs."
    )
    parser.add_argument("--source", type=Path, help="Legacy single container holding all four layers.")
    parser.add_argument("--dltb-source", "--dltb-gdb", dest="dltb_source", type=Path)
    parser.add_argument("--pdt-source", "--pdt-gdb", dest="pdt_source", type=Path)
    parser.add_argument(
        "--eco-redline-source",
        "--eco-redline-gdb",
        dest="eco_redline_source",
        type=Path,
    )
    parser.add_argument(
        "--permanent-basic-farmland-source",
        "--permanent-basic-farmland-gdb",
        dest="permanent_basic_farmland_source",
        type=Path,
    )
    parser.add_argument("--county-name")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dem", type=Path, nargs="+", help="One or more local DEM GeoTIFF tiles. No network download occurs.")
    parser.add_argument(
        "--admin-reference",
        type=Path,
        help="Bundled township reference GeoPackage. Used for labels only, never exchange constraints.",
    )
    parser.add_argument("--admin-reference-layer", default="admin_reference")
    parser.add_argument(
        "--log-dir",
        type=Path,
        help="Detailed fusion logs. Default: $PAPER9_LOG_DIR or OUTPUT_DIR/logs.",
    )
    parser.add_argument("--run-id", help="Optional externally assigned diagnostic run identifier.")
    parser.add_argument("--metric-crs", help="Projected CRS for overlay areas, e.g. EPSG:2359. Defaults to projected DLTB CRS or inferred local UTM.")
    parser.add_argument("--dltb-layer")
    parser.add_argument("--pdt-layer")
    parser.add_argument("--eco-redline-layer")
    parser.add_argument("--permanent-basic-farmland-layer")
    parser.add_argument("--lock-min-overlap-m2", type=float, default=1.0)
    parser.add_argument("--z-factor", type=float, default=1.0)
    parser.add_argument("--list-layers", action="store_true", help="Print source layers and fields, then exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_layers:
        paths = {
            "source": args.source,
            "dltb": args.dltb_source,
            "pdt": args.pdt_source,
            "eco_redline": args.eco_redline_source,
            "permanent_basic_farmland": args.permanent_basic_farmland_source,
        }
        inventory = {
            role: list_source_layers(path)
            for role, path in paths.items()
            if path is not None
        }
        if not inventory:
            print("ERROR: pass --source or one or more --*-gdb paths", file=sys.stderr)
            return 2
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return 0
    missing = [
        flag
        for flag, value in (
            ("--output-dir", args.output_dir),
            ("--dem", args.dem),
        )
        if not value
    ]
    if missing:
        print(f"ERROR: required for fusion: {', '.join(missing)}", file=sys.stderr)
        return 2
    log_dir = args.log_dir or Path(
        os.environ.get("PAPER9_LOG_DIR", str(args.output_dir / "logs"))
    )
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    arguments = {
        "source": args.source,
        "dltb_source": args.dltb_source,
        "pdt_source": args.pdt_source,
        "eco_redline_source": args.eco_redline_source,
        "permanent_basic_farmland_source": args.permanent_basic_farmland_source,
        "county_name": args.county_name,
        "output_dir": args.output_dir,
        "dem": args.dem,
        "admin_reference": args.admin_reference,
        "admin_reference_layer": args.admin_reference_layer,
        "metric_crs": args.metric_crs,
        "selected_layers": {
            "dltb": args.dltb_layer,
            "pdt": args.pdt_layer,
            "eco_redline": args.eco_redline_layer,
            "permanent_basic_farmland": args.permanent_basic_farmland_layer,
        },
        "lock_min_overlap_m2": args.lock_min_overlap_m2,
        "z_factor": args.z_factor,
        "offline_required": True,
    }
    with FusionDiagnostics(log_dir, run_id) as diagnostics:
        diagnostics.emit(
            "INFO",
            "arguments",
            "Fusion arguments recorded for reproducibility.",
            arguments=arguments,
        )
        try:
            report = fuse_county(
                source=args.source,
                dltb_source=args.dltb_source,
                pdt_source=args.pdt_source,
                eco_redline_source=args.eco_redline_source,
                permanent_basic_farmland_source=args.permanent_basic_farmland_source,
                county_name=args.county_name,
                output_dir=args.output_dir,
                dem_paths=args.dem,
                admin_reference=args.admin_reference,
                admin_reference_layer=args.admin_reference_layer,
                metric_crs=args.metric_crs,
                dltb_layer=args.dltb_layer,
                pdt_layer=args.pdt_layer,
                eco_redline_layer=args.eco_redline_layer,
                permanent_basic_farmland_layer=args.permanent_basic_farmland_layer,
                lock_min_overlap_m2=args.lock_min_overlap_m2,
                z_factor=args.z_factor,
                diagnostics=diagnostics,
            )
        except Exception as exc:
            diagnostics.write_failure(exc, arguments=arguments)
            diagnostics.finish(
                "failed",
                failure_report=str(diagnostics.failure_path),
                exception_type=type(exc).__name__,
                error_message=str(exc),
            )
            print(
                f"ERROR: {exc}\nDetailed diagnostics: {diagnostics.failure_path}",
                file=sys.stderr,
            )
            return 2 if isinstance(exc, FusionError) else 1
        diagnostics.finish(
            "ok",
            county_name=report["county_name"],
            report_path=str(args.output_dir / "fusion_report.json"),
        )
    print(
        json.dumps(
            {
                "county_name": report["county_name"],
                "outputs": report["outputs"],
                "constraints": report["constraints"],
                "pdt": report["pdt"],
                "administrative_reference": report["administrative_reference"],
                "logs": report["logs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
