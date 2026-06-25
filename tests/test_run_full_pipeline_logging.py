import json
import subprocess
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_run_full_pipeline_dry_run_writes_manifest_and_run_log(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_full_pipeline.py",
            "configs/real_data_from_authority_slope.yml",
            "--dry-run",
            "--log-dir",
            str(tmp_path),
        ],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    manifests = sorted(tmp_path.glob("run_full_pipeline-*.json"))
    run_logs = sorted(tmp_path.glob("run_full_pipeline-*.log"))
    assert len(manifests) == 1
    assert len(run_logs) == 1

    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "dry-run"
    assert [stage["stage"] for stage in manifest["stages"]] == ["prepare", "sample", "train", "plan"]
    assert all(stage["returncode"] == 0 for stage in manifest["stages"])
    assert "--reference-layer" in manifest["stages"][0]["command"]

    run_log = run_logs[0].read_text(encoding="utf-8")
    assert "RUN START run_id=" in run_log
    assert "RUN END run_id=" in run_log
    assert "started_at=" in run_log
    assert "ended_at=" in run_log
    assert "STAGE START stage=prepare" in run_log
    assert "STAGE END stage=prepare status=dry-run returncode=0" in run_log
    assert "duration_seconds=" in run_log
    assert "[prepare]" in run_log
