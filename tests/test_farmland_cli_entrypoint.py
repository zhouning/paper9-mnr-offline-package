from pathlib import Path
import os
import subprocess
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"


def test_farmland_cli_help_builds_all_subcommands():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)

    result = subprocess.run(
        [sys.executable, "-m", "farmland_mpc.cli", "--help"],
        cwd=PACKAGE_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    help_text = result.stdout + result.stderr
    for command in ("prepare", "sample", "train", "plan"):
        assert command in help_text
