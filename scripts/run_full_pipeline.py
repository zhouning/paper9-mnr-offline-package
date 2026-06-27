from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from paper9_mnr.config import load_config, validate_config
from paper9_mnr.pipeline import build_stage_commands, format_command
from paper9_mnr.version import ALGORITHM_NAME, ALGORITHM_VERSION, PACKAGE_VERSION


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default_log_dir() -> Path:
    return Path(os.environ.get("PAPER9_LOG_DIR", ROOT / "outputs" / "logs"))


def _build_run_metadata(config: dict[str, object]) -> dict[str, object]:
    algorithm = config.get("algorithm", {})
    if not isinstance(algorithm, dict):
        algorithm = {}
    return {
        "package_version": PACKAGE_VERSION,
        "algorithm_name": algorithm.get("name", ALGORITHM_NAME),
        "algorithm_version": algorithm.get("version", ALGORITHM_VERSION),
        "image_ref": os.environ.get("PAPER9_IMAGE_REF", ""),
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_log_line(log, message: str) -> None:
    print(message)
    log.write(f"{message}\n")
    log.flush()


def _run_and_tee(
    command: list[str],
    env: dict[str, str],
    log_path: Path,
    header_lines: list[str] | None = None,
) -> int:
    with log_path.open("w", encoding="utf-8") as log:
        for line in header_lines or []:
            log.write(f"{line}\n")
        if header_lines:
            log.flush()
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
            log.flush()
        return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full Paper9 offline workflow.")
    parser.add_argument("config", nargs="?", default=str(ROOT / "configs" / "real_data_from_authority_slope.yml"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Directory for run manifests and per-stage logs. Default: $PAPER9_LOG_DIR or outputs/logs.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    validate_config(config)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    log_dir = Path(args.log_dir) if args.log_dir else _default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    run_id = _timestamp()
    run_log = log_dir / f"run_full_pipeline-{run_id}.log"
    manifest_path = log_dir / f"run_full_pipeline-{run_id}.json"
    run_started = time.monotonic()
    manifest: dict[str, object] = {
        "run_id": run_id,
        "started_at": _iso_now(),
        "config": str(args.config),
        "dry_run": args.dry_run,
        "log_dir": str(log_dir),
        "metadata": _build_run_metadata(config),
        "stages": [],
    }

    print(f"run_id={run_id}")
    print(f"log_dir={log_dir}")
    print(f"run_log={run_log}")
    print(f"manifest={manifest_path}")

    with run_log.open("w", encoding="utf-8") as log:
        _write_log_line(
            log,
            (
                f"RUN START run_id={run_id} started_at={manifest['started_at']} "
                f"config={args.config} dry_run={args.dry_run}"
            ),
        )
        _write_log_line(log, f"log_dir={log_dir}")
        _write_log_line(log, f"manifest={manifest_path}")
        for stage, command in build_stage_commands(config, python_executable=sys.executable).items():
            formatted = format_command(command)
            stage_started_at = _iso_now()
            stage_started = time.monotonic()
            stage_record: dict[str, object] = {
                "stage": stage,
                "command": formatted,
                "started_at": stage_started_at,
            }
            _write_log_line(log, f"STAGE START stage={stage} started_at={stage_started_at}")
            _write_log_line(log, f"[{stage}] {formatted}")
            if args.dry_run:
                duration = round(time.monotonic() - stage_started, 3)
                stage_ended_at = _iso_now()
                stage_record.update(
                    {
                        "status": "dry-run",
                        "returncode": 0,
                        "duration_seconds": duration,
                        "ended_at": stage_ended_at,
                    }
                )
                stages = manifest["stages"]
                assert isinstance(stages, list)
                stages.append(stage_record)
                _write_log_line(
                    log,
                    (
                        f"STAGE END stage={stage} status=dry-run returncode=0 "
                        f"ended_at={stage_ended_at} duration_seconds={duration}"
                    ),
                )
                continue

            stage_log = log_dir / f"{run_id}-{stage}.log"
            stage_record["log_path"] = str(stage_log)
            _write_log_line(log, f"stage_log={stage_log}")
            returncode = _run_and_tee(
                command,
                env,
                stage_log,
                header_lines=[
                    f"STAGE START stage={stage} started_at={stage_started_at}",
                    f"[{stage}] {formatted}",
                ],
            )
            duration = round(time.monotonic() - stage_started, 3)
            stage_ended_at = _iso_now()
            status = "ok" if returncode == 0 else "failed"
            stage_record.update(
                {
                    "status": status,
                    "returncode": returncode,
                    "duration_seconds": duration,
                    "ended_at": stage_ended_at,
                }
            )
            with stage_log.open("a", encoding="utf-8") as stage_log_file:
                stage_log_file.write(
                    (
                        f"STAGE END stage={stage} status={status} returncode={returncode} "
                        f"ended_at={stage_ended_at} duration_seconds={duration}\n"
                    )
                )
            _write_log_line(
                log,
                (
                    f"STAGE END stage={stage} status={status} returncode={returncode} "
                    f"ended_at={stage_ended_at} duration_seconds={duration}"
                ),
            )
            stages = manifest["stages"]
            assert isinstance(stages, list)
            stages.append(stage_record)
            _write_json(manifest_path, manifest)
            if returncode != 0:
                manifest["status"] = "failed"
                manifest["ended_at"] = _iso_now()
                manifest["duration_seconds"] = round(time.monotonic() - run_started, 3)
                _write_json(manifest_path, manifest)
                _write_log_line(
                    log,
                    (
                        f"RUN END run_id={run_id} status=failed ended_at={manifest['ended_at']} "
                        f"duration_seconds={manifest['duration_seconds']}"
                    ),
                )
                return returncode
    manifest["status"] = "dry-run" if args.dry_run else "ok"
    manifest["ended_at"] = _iso_now()
    manifest["duration_seconds"] = round(time.monotonic() - run_started, 3)
    _write_json(manifest_path, manifest)
    with run_log.open("a", encoding="utf-8") as log:
        _write_log_line(
            log,
            (
                f"RUN END run_id={run_id} status={manifest['status']} ended_at={manifest['ended_at']} "
                f"duration_seconds={manifest['duration_seconds']}"
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
