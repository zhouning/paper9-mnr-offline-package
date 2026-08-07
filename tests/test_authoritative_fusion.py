import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pyogrio
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin
from shapely.geometry import box

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
sys.path.insert(0, str(SRC))

from farmland_mpc.county_env import CountyLevelEnv, FARMLAND, FOREST  # noqa: E402
from farmland_mpc.landuse import LandUseCodeError  # noqa: E402
from farmland_mpc.shapefile_io import infer_swap_codes, write_optimized_dltb  # noqa: E402
from paper9_mnr.dltb_dem_fusion import fuse_dltb_dem_county  # noqa: E402
from paper9_mnr.fusion import (  # noqa: E402
    FusionDiagnostics,
    build_admin_units,
    fuse_county,
    list_source_layers,
    main,
    slope_grade,
)


def _write_layer(path, frame, layer, *, append):
    frame.to_file(
        path,
        layer=layer,
        driver="GPKG",
        engine="pyogrio",
        mode="a" if append else "w",
    )


def _build_source(path):
    crs = "EPSG:3857"
    dltb = gpd.GeoDataFrame(
        {
            "标识码": [101, 102, 103, 104],
            "地类编码": ["0101", "0103", "0301", "1104"],
            "地类名称": ["水田", "旱地", "乔木林地", "村庄"],
            "权属单位代码": ["511011001001"] * 4,
            "坐落单位名称": ["测试村"] * 4,
            "geometry": [
                box(2, 2, 10, 10),
                box(12, 2, 20, 10),
                box(22, 2, 30, 10),
                box(32, 2, 40, 10),
            ],
        },
        crs=crs,
    )
    pdt = gpd.GeoDataFrame(
        {"PDJB": [2], "BZPDJB": ["II级"], "geometry": [box(0, 0, 45, 15)]},
        crs=crs,
    )
    eco = gpd.GeoDataFrame(
        {"红线代码": ["E1"], "geometry": [box(1, 1, 8, 9)]}, crs=crs
    )
    pbf = gpd.GeoDataFrame(
        {"行政区代码": ["511011"], "geometry": [box(21, 1, 28, 9)]}, crs=crs
    )
    _write_layer(path, dltb, "2025地类图斑", append=False)
    _write_layer(path, pdt, "PDT", append=True)
    _write_layer(path, eco, "STBHHX", append=True)
    _write_layer(path, pbf, "YJJBNTBHTB", append=True)


def _build_separate_sources(tmp_path):
    combined = tmp_path / "combined.gpkg"
    _build_source(combined)
    source_layers = {
        "dltb": "2025地类图斑",
        "pdt": "PDT",
        "eco_redline": "STBHHX",
        "permanent_basic_farmland": "YJJBNTBHTB",
    }
    sources = {}
    for role, source_layer in source_layers.items():
        path = tmp_path / f"unlabelled_{role}.gpkg"
        frame = gpd.read_file(combined, layer=source_layer, engine="pyogrio")
        _write_layer(path, frame, "唯一面图层", append=False)
        sources[role] = path
    return sources


def _build_separate_filegdb_sources(tmp_path):
    combined = tmp_path / "combined_for_gdb.gpkg"
    _build_source(combined)
    source_layers = {
        "dltb": "2025地类图斑",
        "pdt": "PDT",
        "eco_redline": "STBHHX",
        "permanent_basic_farmland": "YJJBNTBHTB",
    }
    sources = {}
    for role, source_layer in source_layers.items():
        path = tmp_path / f"customer_{role}.gdb"
        frame = gpd.read_file(combined, layer=source_layer, engine="pyogrio")
        frame.to_file(
            path,
            layer="OnlyPolygon",
            driver="OpenFileGDB",
            engine="pyogrio",
        )
        sources[role] = path
    return sources


def _build_dem(path):
    rows, cols = 20, 50
    x = np.arange(cols, dtype=np.float32)
    elevation = np.broadcast_to(x * 0.05 + 100.0, (rows, cols)).copy()
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0, 20, 1, 1),
        nodata=-9999.0,
    ) as target:
        target.write(elevation, 1)


def _build_admin_reference(path):
    reference = gpd.GeoDataFrame(
        {
            "province_name": ["四川省", "四川省"],
            "city_name": ["内江市", "内江市"],
            "county_name": ["东兴区", "东兴区"],
            "XZQMC": ["测试街道", "测试镇"],
            "county_code": ["511011", "511011"],
            "source_date": ["2021-06-22", "2021-06-22"],
            "source_dataset": ["test_reference", "test_reference"],
            "geometry": [box(0, 0, 25, 15), box(25, 0, 45, 15)],
        },
        crs="EPSG:3857",
    )
    reference.to_file(
        path,
        layer="admin_reference",
        driver="GPKG",
        engine="pyogrio",
    )


def test_fuse_county_builds_paper9_inputs_and_authority_locks(tmp_path):
    source = tmp_path / "authority.gpkg"
    dem = tmp_path / "county_dem.tif"
    output_dir = tmp_path / "fused"
    _build_source(source)
    _build_dem(dem)

    report = fuse_county(
        source=source,
        county_name="测试县",
        output_dir=output_dir,
        dem_paths=[dem],
        metric_crs="EPSG:3857",
    )

    result = gpd.read_file(
        output_dir / "DLTB_with_authority_slope.gpkg", layer="dltb"
    )
    assert result["BSM"].tolist() == ["101", "102", "103", "104"]
    assert result["DLBM"].tolist() == ["0101", "0103", "0301", "1104"]
    assert result["EXCH_LOCK"].tolist() == [1, 0, 1, 0]
    assert result["LOCK_C2F"].tolist() == [1, 0, 1, 0]
    assert result["LOCK_F2C"].tolist() == [1, 0, 1, 0]
    assert result["slope_mean"].notna().all()
    assert result["PDT_GRADE"].eq(2).all()
    assert result.loc[0, "REVIEW_RSN"] == "CULTIVATED_LAND_IN_ECO_REDLINE"
    assert result.loc[2, "REVIEW_RSN"] == "FOREST_OVERLAPS_PERMANENT_BASIC_FARMLAND"
    assert report["arcgis_or_arcpy_used"] is False
    assert report["network_access_used"] is False
    assert report["constraints"]["exchange_locked_parcels"] == 2
    assert report["land_use_codes"]["scheme"] == "gbt21010_2017_third_survey"
    assert report["land_use_codes"]["category_counts"] == {
        "barrier": 1,
        "farmland": 2,
        "forest": 1,
    }
    assert (output_dir / "admin_units.gpkg").is_file()
    assert (output_dir / "DEM_placeholder.tif").is_file()
    assert set(pyogrio.list_layers(output_dir / "authority_constraints.gpkg")[:, 0]) == {
        "pdt",
        "eco_redline",
        "permanent_basic_farmland",
        "locked_dltb_audit",
    }


def test_fuse_dltb_dem_county_marks_unavailable_constraints_without_fake_locks(tmp_path):
    source = tmp_path / "province_authority.gpkg"
    dem = tmp_path / "county_dem.tif"
    admin_reference = tmp_path / "admin_reference.gpkg"
    output_dir = tmp_path / "dltb_only"
    _build_source(source)
    _build_dem(dem)
    _build_admin_reference(admin_reference)

    report = fuse_dltb_dem_county(
        dltb_source=source,
        output_dir=output_dir,
        dem_paths=[dem],
        admin_reference=admin_reference,
        county_code="511011",
        county_name="测试县",
        metric_crs="EPSG:3857",
    )

    result = gpd.read_file(output_dir / "DLTB_with_authority_slope.gpkg", layer="dltb")
    availability = json.loads((output_dir / "input_availability.json").read_text(encoding="utf-8"))
    assert result["EXCH_LOCK"].eq(0).all()
    assert result["CONSTR_STA"].eq("NOT_EVALUATED").all()
    assert result["PDT_GRADE"].eq(-1).all()
    assert result["slope_mean"].notna().all()
    assert report["profile"] == "dltb_dem_only"
    assert report["constraints"]["regulatory_compliance_evaluated"] is False
    assert report["policy"]["regulatory_compliance_claim_allowed"] is False
    assert availability["decision_use"] == "exploratory_technical_validation_only"
    assert not (output_dir / "authority_constraints.gpkg").exists()


def test_infer_swap_codes_preserves_legacy_three_digit_scheme():
    assert infer_swap_codes(["011", "031", "1104"]) == ("011", "031")


def test_packaged_zhongning_admin_reference_has_expected_county_and_townships():
    path = PACKAGE_ROOT / "reference/admin/xiangzhen_zhongning.gpkg"
    reference = gpd.read_file(path, layer="admin_reference", engine="pyogrio")

    assert len(reference) == 13
    assert reference["county_code"].unique().tolist() == ["640521"]
    assert reference["county_name"].unique().tolist() == ["中宁县"]
    assert reference.geometry.is_valid.all()
    assert reference.crs.to_epsg() == 4326


def test_dltb_only_diagnostics_do_not_claim_four_source_fusion(tmp_path):
    with FusionDiagnostics(tmp_path, "test-run", operation="dltb_dem_only") as diagnostics:
        diagnostics.finish("ok")

    events = [
        json.loads(line)
        for line in (tmp_path / "dltb_dem_fusion-test-run.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["details"]["profile"] for event in events] == [
        "dltb_dem_only",
        "dltb_dem_only",
    ]
    assert all("four-source" not in event["message"] for event in events)


def test_admin_reference_can_map_a_legacy_dltb_county_code(tmp_path):
    dltb = gpd.GeoDataFrame(
        {"QSDWDM": ["500227001001"], "QSDWMC": ["旧码村"], "geometry": [box(0, 0, 10, 10)]},
        crs="EPSG:3857",
    )
    reference = gpd.GeoDataFrame(
        {
            "XZQMC": ["璧山镇"],
            "county_code": ["500120"],
            "source_date": ["2021-06-22"],
            "geometry": [box(0, 0, 10, 10)],
        },
        crs="EPSG:3857",
    )
    reference_path = tmp_path / "current_admin.gpkg"
    reference.to_file(reference_path, layer="admin_reference", driver="GPKG", engine="pyogrio")

    units, report = build_admin_units(
        dltb,
        metric_crs=CRS.from_user_input("EPSG:3857"),
        reference_path=reference_path,
        reference_layer="admin_reference",
        reference_county_code="500120",
    )

    assert len(units) == 1
    assert units.loc[0, "admin_parent_code"] == "500120"
    assert report["dltb_county_code"] == "500227"
    assert report["county_code"] == "500120"


def test_fuse_county_accepts_four_independent_sources_without_layer_or_county_input(
    tmp_path,
):
    sources = _build_separate_sources(tmp_path)
    dem = tmp_path / "county_dem.tif"
    output_dir = tmp_path / "fused"
    _build_dem(dem)

    report = fuse_county(
        dltb_source=sources["dltb"],
        pdt_source=sources["pdt"],
        eco_redline_source=sources["eco_redline"],
        permanent_basic_farmland_source=sources["permanent_basic_farmland"],
        output_dir=output_dir,
        dem_paths=[dem],
    )

    assert report["county_name"] == "四川省内江市东兴区"
    assert report["county_name_source"] == "DLTB.QSDWDM"
    assert report["source"]["mode"] == "four_sources"
    for role, path in sources.items():
        assert report["source"]["datasets"][role] == {
            "path": str(path),
            "layer": "唯一面图层",
        }

    placeholder = output_dir / "DEM_placeholder.tif"
    with rasterio.open(placeholder) as dataset:
        assert dataset.count == 1
        assert dataset.width == 1
        assert dataset.height == 1
        assert dataset.crs.to_string() == "EPSG:3857"
    assert report["outputs"]["dem_placeholder"]["sha256"]


def test_slope_grade_boundaries_are_degree_classes():
    values = np.array([0.0, 2.0, 2.01, 6.0, 6.01, 15.0, 15.01, 25.0, 25.01])
    assert slope_grade(values).tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5]


def test_packaged_admin_reference_has_valid_nonempty_geometry_and_manifest():
    path = PACKAGE_ROOT / "reference/admin/xiangzhen_dongxing_bishan.gpkg"
    manifest = json.loads(
        (PACKAGE_ROOT / "reference/admin/MANIFEST.json").read_text(encoding="utf-8")
    )
    reference = gpd.read_file(path, layer="admin_reference", engine="pyogrio")

    assert len(reference) == 44
    assert not reference.geometry.isna().any()
    assert not reference.geometry.is_empty.any()
    assert reference.geometry.is_valid.all()
    assert reference.crs.to_epsg() == 4326
    assert reference.groupby("county_code").size().to_dict() == {
        "500120": 15,
        "511011": 29,
    }
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["output"]["sha256"]


def test_openfilegdb_driver_can_be_enumerated(tmp_path):
    driver = pyogrio.list_drivers().get("OpenFileGDB", "")
    if "w" not in driver:
        pytest.skip("GDAL OpenFileGDB driver is read-only in this environment")
    source = tmp_path / "authority.gdb"
    frame = gpd.GeoDataFrame(
        {"BSM": [1], "DLBM": ["0101"], "geometry": [box(0, 0, 1, 1)]},
        crs="EPSG:3857",
    )
    frame.to_file(source, layer="DLTB", driver="OpenFileGDB", engine="pyogrio")

    inventory = list_source_layers(source)

    assert len(inventory) == 1
    assert inventory[0]["name"] == "DLTB"
    assert inventory[0]["geometry_type"] in {"Polygon", "MultiPolygon"}
    assert inventory[0]["fields"] == ["BSM", "DLBM"]


def test_four_independent_filegdb_directories_complete_fusion(tmp_path):
    driver = pyogrio.list_drivers().get("OpenFileGDB", "")
    if "w" not in driver:
        pytest.skip("GDAL OpenFileGDB driver is read-only in this environment")
    sources = _build_separate_filegdb_sources(tmp_path)
    dem = tmp_path / "county_dem.tif"
    _build_dem(dem)

    report = fuse_county(
        dltb_source=sources["dltb"],
        pdt_source=sources["pdt"],
        eco_redline_source=sources["eco_redline"],
        permanent_basic_farmland_source=sources["permanent_basic_farmland"],
        output_dir=tmp_path / "fused_gdb",
        dem_paths=[dem],
    )

    assert report["source"]["mode"] == "four_sources"
    assert all(
        item["layer"] == "OnlyPolygon"
        for item in report["source"]["datasets"].values()
    )
    assert report["slope"]["null_count"] == 0


def test_bundled_admin_reference_and_pdt_are_non_driving_inputs(tmp_path):
    source = tmp_path / "authority.gpkg"
    dem = tmp_path / "county_dem.tif"
    admin_reference = tmp_path / "admin_reference.gpkg"
    output_dir = tmp_path / "fused"
    _build_source(source)
    _build_dem(dem)
    _build_admin_reference(admin_reference)

    report = fuse_county(
        source=source,
        output_dir=output_dir,
        dem_paths=[dem],
        admin_reference=admin_reference,
        metric_crs="EPSG:3857",
    )

    admin = gpd.read_file(output_dir / "admin_units.gpkg", layer="admin_units")
    assert sorted(admin["XZQMC"].tolist()) == ["测试街道", "测试镇"]
    assert admin["not_for_exchange_constraints"].all()
    assert report["administrative_reference"]["mode"] == "bundled_township_spatial_reference"
    assert report["administrative_reference"]["selected_feature_count"] == 2
    assert report["pdt"] == {
        "role": "quality_control_only",
        "affects_continuous_slope": False,
        "affects_exchange_lock": False,
        "affects_optimizer_objective": False,
        "purpose": "Compare customer authority slope grade with the DEM-derived grade and expose mismatches for review.",
    }


def test_fusion_cli_writes_detailed_success_and_failure_diagnostics(tmp_path):
    source = tmp_path / "authority.gpkg"
    dem = tmp_path / "county_dem.tif"
    admin_reference = tmp_path / "admin_reference.gpkg"
    output_dir = tmp_path / "fused"
    log_dir = tmp_path / "logs"
    _build_source(source)
    _build_dem(dem)
    _build_admin_reference(admin_reference)

    result = main(
        [
            "--source",
            str(source),
            "--output-dir",
            str(output_dir),
            "--dem",
            str(dem),
            "--admin-reference",
            str(admin_reference),
            "--metric-crs",
            "EPSG:3857",
            "--log-dir",
            str(log_dir),
            "--run-id",
            "success-test",
        ]
    )

    assert result == 0
    assert (log_dir / "authoritative_fusion-success-test.log").is_file()
    assert (log_dir / "authoritative_fusion-latest.log").is_file()
    events = [
        json.loads(line)
        for line in (log_dir / "authoritative_fusion-success-test.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event_names = {event["event"] for event in events}
    assert {
        "run_start",
        "arguments",
        "layer_diagnostics",
        "dem_slope_summary",
        "pdt_role",
        "administrative_reference_summary",
        "output_files",
        "run_end",
    } <= event_names
    report = json.loads((output_dir / "fusion_report.json").read_text(encoding="utf-8"))
    assert report["runtime"]["openfilegdb_driver"]
    assert report["timings_seconds"]["dem_slope"] >= 0

    failure_log_dir = tmp_path / "failure_logs"
    failure = main(
        [
            "--source",
            str(tmp_path / "missing.gpkg"),
            "--output-dir",
            str(tmp_path / "failed_output"),
            "--dem",
            str(dem),
            "--log-dir",
            str(failure_log_dir),
            "--run-id",
            "failure-test",
        ]
    )

    assert failure == 2
    failure_report = json.loads(
        (failure_log_dir / "authoritative_fusion-failure-test-failure.json").read_text(
            encoding="utf-8"
        )
    )
    assert failure_report["exception_type"] == "FusionError"
    assert "missing.gpkg" in failure_report["message"]
    assert "Traceback" in failure_report["traceback"]
    assert failure_report["runtime"]["arcpy_imported"] is False


def test_locked_parcels_are_not_counted_as_available_candidates():
    env = CountyLevelEnv.__new__(CountyLevelEnv)
    env.block_parcels = [np.array([0, 1, 2], dtype=np.intp)]
    env.land_use = np.array([FARMLAND, FARMLAND, FOREST], dtype=np.int8)
    env.swapped = np.zeros(3, dtype=bool)
    env.exchange_locked = np.array([True, False, False])
    env._block_farm_avail = np.zeros(1, dtype=np.int32)
    env._block_forest_avail = np.zeros(1, dtype=np.int32)

    env._init_block_counters()

    assert env._block_farm_avail.tolist() == [1]
    assert env._block_forest_avail.tolist() == [1]


def test_output_writer_rejects_any_locked_land_use_change(tmp_path):
    env = SimpleNamespace(
        _parcel_bsm=np.array(["1"]),
        initial_types=np.array([FARMLAND], dtype=np.int8),
        land_use=np.array([FOREST], dtype=np.int8),
        exchange_locked=np.array([True]),
    )

    with pytest.raises(RuntimeError, match="EXCH_LOCK"):
        write_optimized_dltb(
            tmp_path / "unused.gpkg", tmp_path / "unused.shp", env
        )


def test_output_writer_rejects_current_defaults_for_legacy_input(tmp_path):
    source = tmp_path / "legacy.gpkg"
    gpd.GeoDataFrame(
        {
            "BSM": ["1", "2"],
            "DLBM": ["011", "031"],
            "DLMC": ["水田", "乔木林地"],
            "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)],
        },
        crs="EPSG:3857",
    ).to_file(source, layer="dltb", driver="GPKG", engine="pyogrio")
    env = SimpleNamespace(
        _parcel_bsm=np.array(["1", "2"]),
        initial_types=np.array([FARMLAND, FOREST], dtype=np.int8),
        land_use=np.array([FARMLAND, FOREST], dtype=np.int8),
        exchange_locked=np.array([False, False]),
    )

    with pytest.raises(LandUseCodeError, match="different scheme"):
        write_optimized_dltb(source, tmp_path / "optimized.shp", env)
