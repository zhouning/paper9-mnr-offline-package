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
