from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from paper9_mnr.config import load_config, validate_config
from paper9_mnr.pipeline import build_stage_commands, format_command


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full Paper9 offline workflow.")
    parser.add_argument("config", nargs="?", default=str(ROOT / "configs" / "real_data_from_authority_slope.yml"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    validate_config(config)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")

    for stage, command in build_stage_commands(config).items():
        print(f"[{stage}] {format_command(command)}")
        if not args.dry_run:
            completed = subprocess.run(command, cwd=str(ROOT), env=env, check=False)
            if completed.returncode != 0:
                return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

