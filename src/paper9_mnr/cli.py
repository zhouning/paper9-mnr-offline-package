"""CLI helpers for the MNR offline Paper9 package."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from .config import ConfigError, load_config, validate_config
from .pipeline import build_stage_commands, format_command

app = typer.Typer(
    name="paper9-mnr",
    help="Offline MNR wrapper for Paper9 farmland spatial-layout optimization.",
    no_args_is_help=True,
)


@app.command("check-config")
def check_config(config_path: Path) -> None:
    """Validate a YAML workflow config."""
    try:
        config = load_config(config_path)
        validate_config(config)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"OK: {config_path}")


@app.command("print-plan")
def print_plan(config_path: Path) -> None:
    """Print the exact offline commands for the four Paper9 stages."""
    config = load_config(config_path)
    validate_config(config)
    for stage, command in build_stage_commands(config).items():
        typer.echo(f"[{stage}] {format_command(command)}")


@app.command("run-stage")
def run_stage(
    config_path: Path,
    stage: str = typer.Argument(..., help="prepare | sample | train | plan"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the command without executing it."),
) -> None:
    """Run one workflow stage."""
    config = load_config(config_path)
    commands = build_stage_commands(config)
    if stage not in commands:
        raise typer.BadParameter(f"Unknown stage {stage!r}; expected one of {list(commands)}")
    command = commands[stage]
    typer.echo(format_command(command))
    if not dry_run:
        subprocess.run(command, check=True)


@app.command("run-full")
def run_full(
    config_path: Path,
    dry_run: bool = typer.Option(False, "--dry-run", help="Print commands without executing them."),
) -> None:
    """Run prepare, sample, train, and plan in order."""
    config = load_config(config_path)
    for stage, command in build_stage_commands(config).items():
        typer.echo(f"[{stage}] {format_command(command)}")
        if not dry_run:
            subprocess.run(command, check=True)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

