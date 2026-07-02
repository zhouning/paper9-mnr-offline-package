import subprocess
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


def test_docs_describe_paper9v21_legacy_amd64_release():
    paths = [
        PACKAGE_ROOT / "README.md",
        PACKAGE_ROOT / "docs/11_container_deployment.md",
        PACKAGE_ROOT / "docs/12_container_runtime_airgap.md",
        PACKAGE_ROOT / "docs/14_dual_mode_image_usage.md",
        PACKAGE_ROOT / "docs/15_current_handoff.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "paper9v2-2.1.0-legacy-amd64" in text
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
    assert "paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64" in script


def test_container_runtime_wrapper_defaults_amd64_to_legacy_release():
    script = (PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh").read_text(encoding="utf-8")

    assert 'paper9v2-2.1.0-legacy-amd64' in script
    assert 'paper9v2-2.1.0-arm64' in script
    assert 'paper9v2-2.0.0-$arch' not in script


def test_container_runtime_wrapper_defaults_to_paper9v2_config():
    script = (PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh").read_text(encoding="utf-8")

    assert (
        "--config PATH                 Config path inside container. "
        "Default: configs/paper9v2_no_net_loss_authority_slope.yml"
    ) in script
    assert 'config="configs/paper9v2_no_net_loss_authority_slope.yml"' in script
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
    assert 'package_version="0.2.1"' in script
    assert 'algorithm_name="paper9v2"' in script
    assert 'algorithm_version="2.1.0"' in script
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
    assert '"default_config": "configs/paper9v2_no_net_loss_authority_slope.yml"' in script
    assert "SHA256SUMS.txt" in script
    assert "sha256sum" in script
    assert "shasum -a 256" in script


def test_container_runtime_bundle_readme_commands_use_image_ref():
    script = (PACKAGE_ROOT / "deploy/container-runtime/package-container-runtime-bundle.sh").read_text(
        encoding="utf-8"
    )

    assert (
        "./bin/run-paper9-container.sh check --runtime docker --arch ${arch} "
        "--image-ref ${image_ref} --config configs/paper9v2_no_net_loss_authority_slope.yml "
        "--image-tar images/paper9-mnr-offline-linux-${arch}.tar"
    ) in script
    assert (
        "./bin/run-paper9-container.sh dry-run --runtime docker --arch ${arch} "
        "--image-ref ${image_ref} --config configs/paper9v2_no_net_loss_authority_slope.yml"
    ) in script
    assert (
        "./bin/run-paper9-container.sh run --runtime docker --arch ${arch} "
        "--image-ref ${image_ref} --config configs/paper9v2_no_net_loss_authority_slope.yml"
    ) in script
    assert (
        "./bin/run-paper9-container.sh audit --runtime docker --arch ${arch} "
        "--image-ref ${image_ref} --config configs/paper9v2_no_net_loss_authority_slope.yml"
    ) in script


def test_lightweight_container_bundle_writes_legacy_manifest_and_readme():
    script = (PACKAGE_ROOT / "deploy/container-runtime/package-lightweight-container-bundle.sh").read_text(
        encoding="utf-8"
    )

    assert "--cpu-compatibility VALUE" in script
    assert 'cpu_compatibility="legacy-x86_64-without-x86-64-v2"' in script
    assert '"cpu_compatibility": "${cpu_compatibility}"' in script
    assert "paper9-mnr-offline-paper9v2-2.1.0-legacy-linux-amd64.tar" in script
    assert "paper9-mnr-offline:paper9v2-2.1.0-legacy-amd64" in script
    assert "SHA256SUMS.txt" in script
