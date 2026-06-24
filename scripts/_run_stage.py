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


def run(stage: str) -> int:
    parser = argparse.ArgumentParser(description=f"Run Paper9 stage: {stage}")
    parser.add_argument("config", nargs="?", default=str(ROOT / "configs" / "real_data_from_authority_slope.yml"))
    parser.add_argument("--dry-run", action="store_true", help="Print the command without executing it.")
    args = parser.parse_args()

    config = load_config(args.config)
    validate_config(config)
    command = build_stage_commands(config)[stage]
    print(format_command(command))
    if args.dry_run:
        return 0
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(command, cwd=str(ROOT), env=env, check=False)
    return completed.returncode

