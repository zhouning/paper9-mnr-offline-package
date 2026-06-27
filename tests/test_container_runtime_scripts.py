import subprocess
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    PACKAGE_ROOT / "deploy/container-runtime/install-container-runtime.sh",
    PACKAGE_ROOT / "deploy/container-runtime/run-paper9-container.sh",
    PACKAGE_ROOT / "deploy/container-runtime/package-container-runtime-bundle.sh",
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
    assert 'tag="${image_ref:-$image:$arch}"' in script
    assert 'PAPER9_IMAGE_REF="$tag"' in script


def test_container_runtime_bundle_writes_manifest_and_checksums():
    script = (PACKAGE_ROOT / "deploy/container-runtime/package-container-runtime-bundle.sh").read_text(
        encoding="utf-8"
    )

    assert "--image-ref REF" in script
    assert "--package-version VERSION" in script
    assert "--algorithm-name NAME" in script
    assert "--algorithm-version VERSION" in script
    assert "--git-commit COMMIT" in script
    assert 'package_version="0.2.0"' in script
    assert 'algorithm_name="paper9v2"' in script
    assert 'algorithm_version="2.0.0"' in script
    assert 'git_commit="unknown"' in script
    assert 'image_ref="${image_ref:-paper9-mnr-offline:${algorithm_name}-${algorithm_version}-${arch}}"' in script
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
        "--image-ref ${image_ref} --image-tar images/paper9-mnr-offline-linux-${arch}.tar"
    ) in script
    assert (
        "./bin/run-paper9-container.sh dry-run --runtime docker --arch ${arch} --image-ref ${image_ref}"
    ) in script
    assert "./bin/run-paper9-container.sh run --runtime docker --arch ${arch} --image-ref ${image_ref}" in script
    assert "./bin/run-paper9-container.sh audit --runtime docker --arch ${arch} --image-ref ${image_ref}" in script
