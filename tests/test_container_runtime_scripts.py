import json
import subprocess
import tarfile
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    PACKAGE_ROOT / "deploy/container-runtime/install-container-runtime.sh",
    PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh",
    PACKAGE_ROOT / "deploy/container-runtime/package-container-runtime-bundle.sh",
    PACKAGE_ROOT / "deploy/container-runtime/package-lightweight-container-bundle.sh",
]


def test_container_runtime_scripts_are_bash_parseable():
    for script in SCRIPTS:
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_container_runtime_doc_states_runtime_packages_are_os_specific():
    doc = (PACKAGE_ROOT / "docs/12_container_runtime_airgap.md").read_text(encoding="utf-8")

    assert "Linux 发行版" in doc
    assert "CPU 架构" in doc
    assert "不能把 Rocky/CentOS 的 RPM 直接拿到 Ubuntu 上用" in doc


def test_docs_describe_paper9v22_legacy_amd64_release():
    paths = [
        PACKAGE_ROOT / "README.md",
        PACKAGE_ROOT / "docs/11_container_deployment.md",
        PACKAGE_ROOT / "docs/12_container_runtime_airgap.md",
        PACKAGE_ROOT / "docs/14_dual_mode_image_usage.md",
        PACKAGE_ROOT / "docs/15_current_handoff.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "paper9v2-2.2.3-legacy-amd64" in text
    assert "legacy-amd64" in text
    assert "sse4_1" in text
    assert "popcnt" in text


def test_container_runtime_wrapper_exposes_notebook_action():
    script = (PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh").read_text(encoding="utf-8")

    assert "notebook     Start JupyterLab" in script
    assert "--notebook-port" in script
    assert 'PAPER9_CONFIG="${config}"' in script
    assert "jupyter lab" in script


def test_container_runtime_wrapper_supports_full_image_ref():
    script = (PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh").read_text(encoding="utf-8")

    assert "--image-ref REF" in script
    assert 'image_ref="${2:-}"' in script
    assert 'default_image_ref "$image" "$arch"' in script
    assert 'PAPER9_IMAGE_REF="$tag"' in script
    assert "paper9-mnr-offline:paper9v2-2.2.3-legacy-amd64" in script


def test_container_runtime_wrapper_defaults_amd64_to_legacy_release():
    script = (PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh").read_text(encoding="utf-8")

    assert 'paper9v2-2.2.3-legacy-amd64' in script
    assert 'paper9v2-2.2.3-arm64' in script
    assert 'paper9v2-2.0.0-$arch' not in script


def test_container_runtime_wrapper_defaults_to_paper9v2_config():
    script = (PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh").read_text(encoding="utf-8")

    assert (
        "--config PATH                 Config path inside container. "
        "Default: configs/paper9v22_authority_constraints.yml"
    ) in script
    assert 'config="configs/paper9v22_authority_constraints.yml"' in script
    assert "configs/real_data_from_authority_slope.yml" not in script


def test_container_runtime_bundle_writes_manifest_and_checksums():
    script = (PACKAGE_ROOT / "deploy/container-runtime/package-container-runtime-bundle.sh").read_text(
        encoding="utf-8"
    )

    assert "--image-ref REF" in script
    assert "--package-version VERSION" in script
    assert "--algorithm-name NAME" in script
    assert "--algorithm-version VERSION" in script
    assert "--git-commit COMMIT" in script
    assert 'package_version="0.3.3"' in script
    assert 'algorithm_name="paper9v2"' in script
    assert 'algorithm_version="2.2.3"' in script
    assert 'git_commit="unknown"' in script
    assert 'amd64) image_ref="paper9-mnr-offline:${algorithm_name}-${algorithm_version}-legacy-amd64"' in script
    assert 'arm64) image_ref="paper9-mnr-offline:${algorithm_name}-${algorithm_version}-arm64"' in script
    assert (
        'amd64) default_bundle_name="paper9-mnr-container-runtime-${algorithm_name}-${algorithm_version}-legacy-amd64"'
        in script
    )
    assert 'arm64) default_bundle_name="paper9-mnr-container-runtime-${algorithm_name}-${algorithm_version}-arm64"' in script
    assert 'bundle_name="$(basename "${out%.tar.gz}")"' in script
    assert '"algorithm_version": "${algorithm_version}"' in script
    assert '"default_config": "configs/paper9v22_authority_constraints.yml"' in script
    assert "SHA256SUMS.txt" in script
    assert "sha256sum" in script
    assert "shasum -a 256" in script
    assert "--dem-dir DIR" in script
    assert '"manifest": "dem/copernicus_glo30/DEM_MANIFEST.json"' in script
    assert 'cp -R "$dem_dir"/. "$staging/dem/copernicus_glo30/"' in script


def test_container_runtime_bundle_readme_uses_minimum_customer_fuse_command():
    script = (PACKAGE_ROOT / "deploy/container-runtime/package-container-runtime-bundle.sh").read_text(
        encoding="utf-8"
    )

    readme = script.split('cat > "$staging/README.txt" <<README', 1)[1].split("\nREADME", 1)[0]
    fuse_line = next(line for line in readme.splitlines() if "run-paper9-container.sh fuse" in line)
    assert "./bin/run-paper9-container.sh fuse --dltb-gdb" in fuse_line
    assert "--pdt-gdb" in fuse_line
    assert "--eco-redline-gdb" in fuse_line
    assert "--permanent-basic-farmland-gdb" in fuse_line
    assert "--runtime docker" not in fuse_line
    assert "--arch ${arch}" not in fuse_line
    assert "--image-ref ${image_ref}" not in fuse_line
    assert "--data-root /data/paper9/COUNTY" not in fuse_line
    assert "Copy the four exact check/dry-run/run/audit commands printed after fusion" in readme


def test_lightweight_container_bundle_writes_legacy_manifest_and_readme():
    script = (PACKAGE_ROOT / "deploy/container-runtime/package-lightweight-container-bundle.sh").read_text(
        encoding="utf-8"
    )

    assert "--cpu-compatibility VALUE" in script
    assert 'cpu_compatibility="legacy-x86_64-without-x86-64-v2"' in script
    assert '"cpu_compatibility": "${cpu_compatibility}"' in script
    assert 'image_tar_name="paper9-mnr-offline-${algorithm_name}-${algorithm_version}-legacy-linux-amd64.tar"' in script
    assert 'image_ref="${image_ref:-paper9-mnr-offline:${algorithm_name}-${algorithm_version}-legacy-amd64}"' in script
    assert "SHA256SUMS.txt" in script
    assert "--dem-dir DIR" in script
    assert '"required_for_fusion": true' in script
    assert 'cp -R "$dem_dir"/. "$staging/dem/copernicus_glo30/"' in script


def test_container_runtime_wrapper_fuses_four_read_only_gdbs_with_bundled_dem():
    script = (PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh").read_text(
        encoding="utf-8"
    )

    assert "fuse          Fuse four county FileGDB inputs" in script
    assert "--dltb-gdb DIR" in script
    assert "--pdt-gdb DIR" in script
    assert "--eco-redline-gdb DIR" in script
    assert "--permanent-basic-farmland-gdb DIR" in script
    assert 'dem_dir="${dem_dir:-$script_dir/../dem/copernicus_glo30}"' in script
    assert 'DEM_MANIFEST.json' in script
    assert 'Copernicus_DSM_COG_10_N29_00_E104_00_DEM.tif' in script
    assert 'Copernicus_DSM_COG_10_N29_00_E105_00_DEM.tif' in script
    assert 'Copernicus_DSM_COG_10_N29_00_E106_00_DEM.tif' in script
    assert 'dltb_path_key="$(printf \'%s\' "$dltb_gdb" | cksum' in script
    assert 'county_code="$(printf \'%s/%s\' "$dltb_parent" "$dltb_label"' in script
    assert 'data_root="$PWD/paper9-data/${county_code}-${dltb_path_key}"' in script
    assert 'FUSION_OUTPUTS.txt' in script
    assert 'fusion_output_files=(' in script
    assert 'Fusion output directory: $input_dir' in script
    assert 'sha256=' in script
    assert 'size_bytes=' in script
    assert '${dltb_gdb}:/app/authority/dltb.gdb:ro${volume_suffix}' in script
    assert '${pdt_gdb}:/app/authority/pdt.gdb:ro${volume_suffix}' in script
    assert '${eco_redline_gdb}:/app/authority/eco_redline.gdb:ro${volume_suffix}' in script
    assert '${permanent_basic_farmland_gdb}:/app/authority/permanent_basic_farmland.gdb:ro${volume_suffix}' in script
    assert '${dem_dir}:/app/data/dem:ro${volume_suffix}' in script
    assert '${admin_reference}:/app/reference/xiangzhen_dongxing_bishan.gpkg:ro${volume_suffix}' in script
    assert 'input_mode="rw"' in script
    assert "--network none" in script
    assert "scripts/fuse_authoritative_county_inputs.py" in script
    assert "--admin-reference /app/reference/xiangzhen_dongxing_bishan.gpkg" in script
    assert "--log-dir /app/outputs/logs" in script
    assert 'container-wrapper-${host_run_id}.log' in script
    assert "HOST RUN START" in script
    assert "HOST RUN END" in script
    assert 'echo "$0 check --data-root' in script
    assert 'echo "$0 dry-run --data-root' in script
    assert 'echo "$0 run --data-root' in script
    assert 'echo "$0 audit --data-root' in script


def test_customer_runbook_minimum_fuse_command_only_requires_four_gdb_paths():
    doc = (PACKAGE_ROOT / "docs/09_mnr_customer_runbook.md").read_text(encoding="utf-8")
    minimum_section = doc.split("## 3. 一条命令融合一个县", 1)[1].split("脚本会自动完成", 1)[0]

    assert minimum_section.count("--dltb-gdb") == 1
    assert minimum_section.count("--pdt-gdb") == 1
    assert minimum_section.count("--eco-redline-gdb") == 1
    assert minimum_section.count("--permanent-basic-farmland-gdb") == 1
    assert "--runtime" not in minimum_section
    assert "--arch" not in minimum_section
    assert "--image-ref" not in minimum_section
    assert "--data-root" not in minimum_section
    assert "--dem-dir" not in minimum_section
    assert "--admin-reference" not in minimum_section


def test_lightweight_bundle_contains_offline_dem_and_manifest(tmp_path):
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"test-image")
    dem_dir = tmp_path / "dem"
    dem_dir.mkdir()
    dem_tile_names = [
        "Copernicus_DSM_COG_10_N29_00_E104_00_DEM.tif",
        "Copernicus_DSM_COG_10_N29_00_E105_00_DEM.tif",
        "Copernicus_DSM_COG_10_N29_00_E106_00_DEM.tif",
    ]
    for tile_name in dem_tile_names:
        (dem_dir / tile_name).write_bytes(b"test-dem")
    (dem_dir / "DEM_MANIFEST.json").write_text(
        json.dumps({"product": "test-dem"}), encoding="utf-8"
    )
    output = tmp_path / "paper9-test-bundle.tar.gz"

    result = subprocess.run(
        [
            "bash",
            str(
                PACKAGE_ROOT
                / "deploy/container-runtime/package-lightweight-container-bundle.sh"
            ),
            "--arch",
            "amd64",
            "--image-tar",
            str(image_tar),
            "--dem-dir",
            str(dem_dir),
            "--out",
            str(output),
        ],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    root = "paper9-test-bundle"
    with tarfile.open(output, "r:gz") as archive:
        names = set(archive.getnames())
        for tile_name in dem_tile_names:
            assert f"{root}/dem/copernicus_glo30/{tile_name}" in names
        assert not any("research_proposal" in name for name in names)
        assert not any("publication_validation_plan" in name for name in names)
        assert f"{root}/dem/copernicus_glo30/DEM_MANIFEST.json" in names
        assert f"{root}/reference/admin/xiangzhen_dongxing_bishan.gpkg" in names
        assert f"{root}/reference/admin/MANIFEST.json" in names
        manifest_file = archive.extractfile(f"{root}/MANIFEST.json")
        assert manifest_file is not None
        manifest = json.load(manifest_file)
    assert manifest["package_version"] == "0.3.3"
    assert manifest["algorithm_version"] == "2.2.3"
    assert manifest["offline_dem"] == {
        "directory": "dem/copernicus_glo30",
        "manifest": "dem/copernicus_glo30/DEM_MANIFEST.json",
        "required_for_fusion": True,
    }
    assert manifest["offline_admin_reference"] == {
        "path": "reference/admin/xiangzhen_dongxing_bishan.gpkg",
        "layer": "admin_reference",
        "feature_count": 44,
        "source_date": "2021-06-22",
        "role": "township name and spatial reference only",
    }
