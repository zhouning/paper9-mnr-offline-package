"""Notebook helpers for Paper9 MNR data review and result visualization."""

from __future__ import annotations

import json
import os
import html
import uuid
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Iterable

import geopandas as gpd
import pandas as pd
from shapely import set_precision

from .config import load_config, validate_config


def project_root() -> Path:
    """Return the repository root inside or outside the container."""
    env_root = os.environ.get("PAPER9_PROJECT_ROOT")
    candidates = []
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend([Path("/app"), Path.cwd(), *Path.cwd().parents])
    for candidate in candidates:
        if (candidate / "configs").exists() and (candidate / "src").exists():
            return candidate
    return Path.cwd()


def repo_path(path: str | Path) -> Path:
    """Resolve a path relative to the Paper9 package root."""
    value = Path(path)
    if value.is_absolute():
        return value
    return project_root() / value


def load_checked_config(config_path: str | Path = "configs/real_data_from_authority_slope.yml") -> dict:
    """Load and validate a workflow config."""
    config = load_config(repo_path(config_path))
    validate_config(config)
    return config


def vector_profile(path: str | Path, expected_fields: Iterable[str] = ()) -> dict[str, object]:
    """Return a compact vector dataset profile for notebook display."""
    if path in ("", None):
        return {"path": "", "exists": False, "missing_fields": list(expected_fields)}
    resolved = repo_path(path)
    profile: dict[str, object] = {
        "path": str(resolved),
        "exists": resolved.exists(),
    }
    if not resolved.exists():
        profile["missing_fields"] = list(expected_fields)
        return profile

    gdf = gpd.read_file(resolved)
    columns = list(gdf.columns)
    missing = [field for field in expected_fields if field not in columns]
    profile.update(
        {
            "rows": int(len(gdf)),
            "crs": str(gdf.crs) if gdf.crs else "",
            "geometry_types": sorted(str(value) for value in gdf.geometry.geom_type.dropna().unique()),
            "columns": columns,
            "missing_fields": missing,
            "bounds": [float(value) for value in gdf.total_bounds] if len(gdf) else [],
        }
    )
    return profile


def configured_input_profiles(config_path: str | Path = "configs/real_data_from_authority_slope.yml") -> pd.DataFrame:
    """Profile the DLTB and administrative-unit inputs declared in a config."""
    config = load_checked_config(config_path)
    fields = config["fields"]
    slope = config["slope"]
    rows = [
        {
            "dataset": "dltb",
            **vector_profile(
                config["data"]["dltb"],
                expected_fields=[fields["dlbm"], fields["qsdwdm"], fields["bsm"], slope["field"]],
            ),
        },
        {
            "dataset": "admin_units",
            **vector_profile(
                config["data"].get("admin_units", ""),
                expected_fields=[fields.get("admin_name", "XZQMC")],
            ),
        },
    ]
    return pd.DataFrame(rows)


def output_inventory(config_path: str | Path = "configs/real_data_from_authority_slope.yml") -> pd.DataFrame:
    """List expected workflow outputs and whether they currently exist."""
    config = load_checked_config(config_path)
    prepared_dir = repo_path(config["data"]["prepared_dir"])
    output_paths = {
        "prepared_dir": prepared_dir,
        "sample_transitions": prepared_dir / "tool2" / "transitions.npz",
        "sample_pairwise": prepared_dir / "tool2" / "pairwise.npz",
        "ensemble_dir": prepared_dir / config["training"].get("out_subdir", "tool3"),
        "plan_dir": repo_path(config["outputs"]["plan_dir"]),
        "optimized_vector": repo_path(config["outputs"]["optimized_vector"]),
        "audit_summary": project_root() / "outputs" / "audit_summary.json",
    }
    rows = []
    for name, path in output_paths.items():
        rows.append(
            {
                "output": name,
                "path": str(path),
                "exists": path.exists(),
                "size_mb": round(path.stat().st_size / 1024 / 1024, 3) if path.is_file() else None,
            }
        )
    return pd.DataFrame(rows)


def read_sample(path: str | Path, max_features: int = 5000, random_state: int = 0) -> gpd.GeoDataFrame:
    """Read a vector layer and down-sample it for plotting."""
    gdf = gpd.read_file(repo_path(path))
    if 0 < max_features < len(gdf):
        return gdf.sample(max_features, random_state=random_state)
    return gdf


def leaflet_map_html(
    layers: list[dict[str, object]],
    title: str = "Paper9 map",
    output_path: str | Path | None = None,
    height: int = 650,
) -> str:
    """Return a self-contained Leaflet iframe for offline notebook GIS maps."""
    layer_payloads = []
    legend_items: list[dict[str, str]] = []
    for layer in layers:
        gdf = layer["gdf"]
        if not isinstance(gdf, gpd.GeoDataFrame) or gdf.empty:
            continue
        popup_fields = [str(field) for field in layer.get("popup_fields", []) if str(field) in gdf.columns]
        tooltip_fields = [str(field) for field in layer.get("tooltip_fields", popup_fields[:2]) if str(field) in gdf.columns]
        color_map = {str(key): str(value) for key, value in dict(layer.get("color_map", {})).items()}
        payload = {
            "name": str(layer.get("name", "Layer")),
            "data": _geojson_payload(
                gdf,
                popup_fields,
                layer.get("color_field"),
                layer.get("simplify_tolerance"),
                layer.get("coordinate_precision", 6),
            ),
            "style": dict(layer.get("style", {})),
            "popupFields": popup_fields,
            "tooltipFields": tooltip_fields,
            "colorField": str(layer.get("color_field", "")) if layer.get("color_field") else "",
            "colorMap": color_map,
            "defaultColor": str(layer.get("default_color", "#4b5563")),
        }
        layer_payloads.append(payload)
        for label, color in dict(layer.get("legend", {})).items():
            legend_items.append({"label": str(label), "color": str(color)})

    document = _leaflet_document(
        map_id=f"paper9-map-{uuid.uuid4().hex}",
        title=title,
        layers=layer_payloads,
        legend_items=legend_items,
        height=height,
    )
    if output_path is not None:
        resolved = repo_path(output_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(document, encoding="utf-8")
    return _iframe_document(document, height)


def input_layers_map_html(
    config_path: str | Path = "configs/real_data_from_authority_slope.yml",
    max_features: int = 1000,
    output_path: str | Path | None = None,
    height: int = 650,
    simplify_tolerance: float = 2.0,
) -> str:
    """Build an offline interactive map for DLTB and village/admin inputs."""
    config = load_checked_config(config_path)
    fields = config["fields"]
    slope = config["slope"]
    dltb = read_sample(config["data"]["dltb"], max_features=max_features)
    admin_path = config["data"].get("admin_units")
    admin = gpd.read_file(repo_path(admin_path)) if admin_path else gpd.GeoDataFrame(geometry=[], crs=dltb.crs)

    return leaflet_map_html(
        [
            {
                "name": "DLTB parcels",
                "gdf": dltb,
                "popup_fields": [fields["bsm"], fields["dlbm"], fields["qsdwdm"], slope["field"]],
                "tooltip_fields": [fields["bsm"], slope["field"]],
                "style": {"color": "#7a8f72", "weight": 0.7, "fillColor": "#d8e6d1", "fillOpacity": 0.45},
                "legend": {"DLTB parcels": "#d8e6d1"},
                "simplify_tolerance": simplify_tolerance,
                "coordinate_precision": 6,
            },
            {
                "name": "Village/admin boundaries",
                "gdf": admin,
                "popup_fields": [fields.get("admin_name", "XZQMC")],
                "tooltip_fields": [fields.get("admin_name", "XZQMC")],
                "style": {"color": "#111827", "weight": 2.0, "fillOpacity": 0.0},
                "legend": {"Village/admin boundaries": "#111827"},
                "simplify_tolerance": simplify_tolerance,
                "coordinate_precision": 5,
            },
        ],
        title="DLTB parcels and administrative boundaries",
        output_path=output_path,
        height=height,
    )


def optimization_changes_map_html(
    config_path: str | Path = "configs/real_data_from_authority_slope.yml",
    max_features: int = 1500,
    output_path: str | Path | None = None,
    height: int = 650,
    simplify_tolerance: float = 2.0,
) -> str:
    """Build an offline interactive map for optimized DLTB change flags."""
    config = load_checked_config(config_path)
    optimized_path = repo_path(config["outputs"]["optimized_vector"])
    if not optimized_path.exists():
        raise FileNotFoundError(f"Optimized vector does not exist: {optimized_path}")

    gdf = read_sample(optimized_path, max_features=max_features)
    if "CHG_FLAG" not in gdf.columns:
        raise ValueError("Optimized vector is missing CHG_FLAG.")

    fields = config["fields"]
    colors = {0: "#d7d7d7", 1: "#2f6f4e", 2: "#c17c2c"}
    labels = {0: "unchanged", 1: "farm->forest", 2: "forest->farm"}
    gdf = gdf.copy()
    gdf["CHG_LABEL"] = gdf["CHG_FLAG"].fillna(0).astype(int).map(labels).fillna("other")

    return leaflet_map_html(
        [
            {
                "name": "Optimized DLTB changes",
                "gdf": gdf,
                "popup_fields": [fields["bsm"], fields["dlbm"], fields["qsdwdm"], "CHG_FLAG", "CHG_LABEL"],
                "tooltip_fields": [fields["bsm"], "CHG_LABEL"],
                "color_field": "CHG_FLAG",
                "color_map": colors,
                "default_color": "#9ca3af",
                "style": {"color": "#f8fafc", "weight": 0.3, "fillOpacity": 0.62},
                "legend": {labels[key]: color for key, color in colors.items()},
                "simplify_tolerance": simplify_tolerance,
                "coordinate_precision": 6,
            }
        ],
        title="Optimized DLTB change map",
        output_path=output_path,
        height=height,
    )


def plot_input_layers(
    config_path: str | Path = "configs/real_data_from_authority_slope.yml",
    max_features: int = 5000,
    output_path: str | Path | None = None,
):
    """Plot DLTB samples with village/admin boundaries."""
    import matplotlib.pyplot as plt

    config = load_checked_config(config_path)
    dltb = read_sample(config["data"]["dltb"], max_features=max_features)
    admin_path = config["data"].get("admin_units")
    admin = gpd.read_file(repo_path(admin_path)) if admin_path else None
    if admin is not None and admin.crs and dltb.crs and admin.crs != dltb.crs:
        admin = admin.to_crs(dltb.crs)

    fig, ax = plt.subplots(figsize=(10, 10))
    dltb.plot(ax=ax, color="#d8e6d1", edgecolor="#7a8f72", linewidth=0.15)
    if admin is not None:
        admin.boundary.plot(ax=ax, color="#1f2937", linewidth=0.8)
    ax.set_title("DLTB parcels and administrative boundaries")
    ax.set_axis_off()
    _save_figure(fig, output_path)
    return fig, ax


def plot_optimization_changes(
    config_path: str | Path = "configs/real_data_from_authority_slope.yml",
    max_features: int = 5000,
    output_path: str | Path | None = None,
):
    """Plot optimized DLTB output by change flag."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    config = load_checked_config(config_path)
    optimized_path = repo_path(config["outputs"]["optimized_vector"])
    if not optimized_path.exists():
        raise FileNotFoundError(f"Optimized vector does not exist: {optimized_path}")

    gdf = read_sample(optimized_path, max_features=max_features)
    if "CHG_FLAG" not in gdf.columns:
        raise ValueError("Optimized vector is missing CHG_FLAG.")

    colors = {0: "#d7d7d7", 1: "#2f6f4e", 2: "#c17c2c"}
    labels = {0: "unchanged", 1: "farm->forest", 2: "forest->farm"}
    plot_colors = gdf["CHG_FLAG"].fillna(0).astype(int).map(colors).fillna("#9ca3af")

    fig, ax = plt.subplots(figsize=(10, 10))
    gdf.assign(_plot_color=plot_colors).plot(ax=ax, color=plot_colors, edgecolor="#f8fafc", linewidth=0.05)
    ax.legend(handles=[Patch(facecolor=colors[key], label=labels[key]) for key in colors], loc="lower left")
    ax.set_title("Optimized DLTB change map")
    ax.set_axis_off()
    _save_figure(fig, output_path)
    return fig, ax


def change_summary(config_path: str | Path = "configs/real_data_from_authority_slope.yml") -> pd.DataFrame:
    """Summarize optimized DLTB change flags."""
    config = load_checked_config(config_path)
    optimized_path = repo_path(config["outputs"]["optimized_vector"])
    if not optimized_path.exists():
        return pd.DataFrame([{"status": "missing", "path": str(optimized_path)}])

    gdf = gpd.read_file(optimized_path)
    if "CHG_FLAG" not in gdf.columns:
        return pd.DataFrame([{"status": "missing CHG_FLAG", "path": str(optimized_path)}])

    label_map = {0: "unchanged", 1: "farm->forest", 2: "forest->farm"}
    summary = (
        gdf["CHG_FLAG"]
        .fillna(0)
        .astype(int)
        .map(label_map)
        .fillna("other")
        .value_counts()
        .rename_axis("change")
        .reset_index(name="count")
    )
    summary["share"] = summary["count"] / summary["count"].sum()
    return summary


def latest_run_manifest(log_dir: str | Path = "outputs/logs") -> dict[str, object]:
    """Load the latest run_full_pipeline JSON manifest."""
    candidates = sorted(repo_path(log_dir).glob("run_full_pipeline-*.json"))
    if not candidates:
        return {}
    return json.loads(candidates[-1].read_text(encoding="utf-8"))


def manifest_stage_table(manifest: dict[str, object]) -> pd.DataFrame:
    """Return a notebook-friendly stage table for dry-run or full-run manifests."""
    stages = pd.DataFrame(manifest.get("stages", []))
    if stages.empty:
        return stages
    desired = ["stage", "status", "returncode", "duration_seconds", "log_path", "command"]
    available = [column for column in desired if column in stages.columns]
    return stages[available]


def manifest_log_entries(manifest: dict[str, object], root: str | Path | None = None) -> list[dict[str, object]]:
    """Return stage log paths that exist in a full-run manifest."""
    root_path = Path(root) if root is not None else project_root()
    entries: list[dict[str, object]] = []
    for stage in manifest.get("stages", []):
        if not isinstance(stage, dict):
            continue
        log_value = stage.get("log_path")
        if not log_value:
            continue
        log_path = _resolve_project_or_container_path(log_value, root_path)
        entries.append({"stage": stage.get("stage", ""), "log_path": log_path, "exists": log_path.exists()})
    return entries


def _resolve_project_or_container_path(value: object, root: Path) -> Path:
    raw_value = str(value)
    container_path = PurePosixPath(raw_value)
    if container_path.is_absolute() and container_path.parts[:2] == ("/", "app"):
        return root.joinpath(*container_path.parts[2:])
    path = Path(raw_value)
    if path.is_absolute():
        return path
    return root / path


def _geojson_payload(
    gdf: gpd.GeoDataFrame,
    popup_fields: list[str],
    color_field: object | None = None,
    simplify_tolerance: object | None = None,
    coordinate_precision: object | None = 6,
) -> dict:
    fields = list(dict.fromkeys([*popup_fields, str(color_field) if color_field else ""]))
    fields = [field for field in fields if field and field in gdf.columns]
    mapped = gdf[[*fields, "geometry"]].copy()
    tolerance = float(simplify_tolerance or 0)
    if tolerance > 0 and mapped.crs and not mapped.crs.is_geographic:
        mapped.geometry = mapped.geometry.simplify(tolerance, preserve_topology=True)
    if mapped.crs and mapped.crs.to_epsg() != 4326:
        mapped = mapped.to_crs("EPSG:4326")
    precision = int(coordinate_precision or 0)
    if precision > 0:
        grid_size = 10 ** (-precision)
        mapped.geometry = mapped.geometry.map(
            lambda geom: set_precision(geom, grid_size) if geom is not None and not geom.is_empty else geom
        )
    for field in fields:
        mapped[field] = mapped[field].map(_json_safe_value)
    return json.loads(mapped.to_json(drop_id=True))


def _json_safe_value(value: object) -> object:
    if pd.isna(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _leaflet_assets() -> tuple[str, str]:
    asset_root = files("paper9_mnr").joinpath("assets/leaflet")
    css = asset_root.joinpath("leaflet.css").read_text(encoding="utf-8")
    js = asset_root.joinpath("leaflet.js").read_text(encoding="utf-8").replace("</script>", "<\\/script>")
    return css, js


def _leaflet_document(
    map_id: str,
    title: str,
    layers: list[dict[str, object]],
    legend_items: list[dict[str, str]],
    height: int,
) -> str:
    css, js = _leaflet_assets()
    layers_json = json.dumps(layers, ensure_ascii=False)
    legend_json = json.dumps(legend_items, ensure_ascii=False)
    title_json = json.dumps(title, ensure_ascii=False)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
{css}
html, body {{ margin: 0; padding: 0; height: 100%; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
#{map_id} {{ width: 100%; height: {height}px; background: #f8fafc; }}
.paper9-title {{
  position: absolute; z-index: 500; top: 10px; left: 52px; padding: 6px 10px;
  background: rgba(255, 255, 255, 0.92); border: 1px solid #cbd5e1; border-radius: 4px;
  color: #111827; font-size: 13px; font-weight: 600;
}}
.paper9-popup-table {{ border-collapse: collapse; font-size: 12px; }}
.paper9-popup-table th {{ color: #475569; font-weight: 600; text-align: left; padding: 2px 8px 2px 0; }}
.paper9-popup-table td {{ color: #111827; padding: 2px 0; }}
.paper9-legend {{ background: rgba(255,255,255,0.94); padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 4px; }}
.paper9-legend div {{ line-height: 18px; color: #111827; font-size: 12px; }}
.paper9-legend span {{ display: inline-block; width: 12px; height: 12px; margin-right: 6px; border: 1px solid #64748b; vertical-align: -2px; }}
</style>
</head>
<body>
<div id="{map_id}"></div>
<div class="paper9-title"></div>
<script>
{js}
</script>
<script>
const mapTitle = {title_json};
const layerDefs = {layers_json};
const legendItems = {legend_json};
const map = L.map("{map_id}", {{ preferCanvas: true, zoomControl: true }});
const layerGroup = L.featureGroup().addTo(map);
const overlays = {{}};
document.querySelector(".paper9-title").textContent = mapTitle;

function escapeHtml(value) {{
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, function(match) {{
    return ({{"&": "&amp;", "<": "&lt;", ">": "&gt;", "\\"": "&quot;", "'": "&#39;"}})[match];
  }});
}}

function popupTable(feature, fields) {{
  const props = feature.properties || {{}};
  const rows = fields.map(function(field) {{
    return "<tr><th>" + escapeHtml(field) + "</th><td>" + escapeHtml(props[field]) + "</td></tr>";
  }}).join("");
  return "<table class='paper9-popup-table'>" + rows + "</table>";
}}

function featureStyle(layerDef, feature) {{
  const style = Object.assign({{}}, layerDef.style || {{}});
  if (layerDef.colorField) {{
    const value = feature.properties ? feature.properties[layerDef.colorField] : null;
    const color = layerDef.colorMap[String(value)] || layerDef.defaultColor || "#4b5563";
    style.fillColor = color;
    if (!style.color) style.color = color;
  }}
  return style;
}}

layerDefs.forEach(function(layerDef) {{
  const geoLayer = L.geoJSON(layerDef.data, {{
    style: function(feature) {{ return featureStyle(layerDef, feature); }},
    onEachFeature: function(feature, layer) {{
      if (layerDef.popupFields && layerDef.popupFields.length) {{
        layer.bindPopup(popupTable(feature, layerDef.popupFields), {{ maxWidth: 420 }});
      }}
      if (layerDef.tooltipFields && layerDef.tooltipFields.length) {{
        const props = feature.properties || {{}};
        const text = layerDef.tooltipFields.map(function(field) {{ return props[field]; }}).filter(Boolean).join(" | ");
        if (text) layer.bindTooltip(escapeHtml(text), {{ sticky: true }});
      }}
    }}
  }});
  overlays[layerDef.name] = geoLayer;
  geoLayer.addTo(map);
  layerGroup.addLayer(geoLayer);
}});

if (Object.keys(overlays).length > 1) {{
  L.control.layers(null, overlays, {{ collapsed: false }}).addTo(map);
}}
L.control.scale({{ metric: true, imperial: false }}).addTo(map);

if (legendItems.length) {{
  const legend = L.control({{ position: "bottomright" }});
  legend.onAdd = function() {{
    const div = L.DomUtil.create("div", "paper9-legend");
    div.innerHTML = legendItems.map(function(item) {{
      return "<div><span style='background:" + escapeHtml(item.color) + "'></span>" + escapeHtml(item.label) + "</div>";
    }}).join("");
    return div;
  }};
  legend.addTo(map);
}}

if (layerGroup.getLayers().length) {{
  map.fitBounds(layerGroup.getBounds(), {{ padding: [20, 20] }});
}} else {{
  map.setView([35, 105], 4);
}}
</script>
</body>
</html>"""


def _iframe_document(document: str, height: int) -> str:
    escaped = html.escape(document, quote=True)
    return (
        f'<iframe srcdoc="{escaped}" width="100%" height="{height}" '
        'style="border:1px solid #cbd5e1; border-radius:4px;"></iframe>'
    )


def _save_figure(fig, output_path: str | Path | None) -> None:
    if output_path is None:
        return
    resolved = repo_path(output_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(resolved, dpi=180, bbox_inches="tight")
