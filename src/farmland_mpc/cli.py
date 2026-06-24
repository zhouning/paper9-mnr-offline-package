"""Command-line interface for farmland_mpc.

Subcommands:
    prepare   Phase A: DEM + DLTB -> per-parcel slope_mean.shp
    sample    Phase B: pairwise transition sampling (TODO: lift from core)
    train     Phase C: contrastive ensemble training (TODO: lift from core)
    plan      Phase D: MPC planning (TODO: lift from core)

Run ``farmland-mpc --help`` to see the current subcommand surface.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from farmland_mpc import __version__

app = typer.Typer(
    name="farmland-mpc",
    help=(
        "County-scale farmland consolidation via contrastive world-model + MPC. "
        "Pure-Python; no proprietary GIS dependencies required."
    ),
    no_args_is_help=True,
)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def version() -> None:
    """Print the installed farmland-mpc version."""
    typer.echo(f"farmland-mpc {__version__}")


@app.command()
def prepare(
    dltb: Path = typer.Option(..., "--dltb", help="Polygon vector file (shapefile / .gpkg / .geojson)"),
    dem: Path = typer.Option(..., "--dem", help="DEM raster (.tif / .vrt etc.)"),
    out: Path = typer.Option(..., "--out", help="Output prepared_dir"),
    proj_crs: str = typer.Option("EPSG:32648", "--crs", help="Target projected CRS for slope/area metrics"),
    dlbm_field: str = typer.Option("DLBM", "--dlbm-field"),
    qsdwdm_field: str = typer.Option("QSDWDM", "--qsdwdm-field"),
    bsm_field: str = typer.Option("BSM", "--bsm-field"),
    skip_blocks: bool = typer.Option(False, "--skip-blocks",
        help="Only run Phase A (slope). Skip block definition + sanity check."),
    min_parcels: int = typer.Option(3, "--min-parcels",
        help="Block min parcels (Paper 3 default 3)"),
    min_area_ha: float = typer.Option(0.5, "--min-area-ha",
        help="Block min area in hectares (Paper 3 default 0.5)"),
    max_parcels: int = typer.Option(30, "--max-parcels",
        help="Block max parcels before subdivision (Paper 3 default 30)"),
    min_parcels_per_township: int = typer.Option(50, "--min-parcels-per-township",
        help="Drop townships with fewer parcels (border artifacts). Lower for small test data."),
    slope_method: str = typer.Option("auto", "--slope-method",
        help="auto | gradient_geographic | horn_projected | from_field. "
             "'auto' picks gradient_geographic for geographic DEMs (e.g. EPSG:4326 Copernicus tiles), "
             "horn_projected otherwise. 'from_field' reads slope from the DLTB attribute table "
             "(use --slope-field to pick the column)."),
    slope_field: str = typer.Option("slope_mean", "--slope-field",
        help="Column name for --slope-method=from_field. Default 'slope_mean'."),
    treat_zero_as_nodata: bool = typer.Option(True, "--treat-zero-as-nodata/--no-treat-zero-as-nodata",
        help="Treat DEM elevation <=0 as nodata (defends against rasters whose nodata is "
             "stored as 0 with no nodata flag). Default True."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase A+B+C: build full prepared_dir from a DLTB polygon file and a DEM raster."""
    _setup_logging(verbose)
    from farmland_mpc.prepare import run

    out_path = run(
        dltb_path=dltb,
        dem_path=dem,
        prepared_dir=out,
        proj_crs=proj_crs,
        dlbm_field=dlbm_field,
        qsdwdm_field=qsdwdm_field,
        bsm_field=bsm_field,
        slope_method=slope_method,
        slope_field=slope_field,
        treat_zero_as_nodata=treat_zero_as_nodata,
        run_phase_bc=not skip_blocks,
        min_parcels=min_parcels,
        min_area_ha=min_area_ha,
        max_parcels=max_parcels,
        min_parcels_per_township=min_parcels_per_township,
    )
    if skip_blocks:
        typer.echo(f"Phase A done -> {out_path}")
    else:
        typer.echo(f"Phase A+B+C done -> {out_path}")


@app.command()
def sample(
    prepared_dir: Path = typer.Option(..., "--prepared-dir", help="Phase A output directory"),
    n_transition_episodes: int = typer.Option(60, "--n-episodes",
        help="Random-policy episodes for the MSE transitions dataset."),
    n_pairwise_states: int = typer.Option(1000, "--n-states",
        help="State snapshots for the pairwise ranking dataset."),
    n_pairwise_actions: int = typer.Option(50, "--n-actions",
        help="Actions to evaluate per state (capped to env.n_blocks)."),
    seed: int = typer.Option(0, "--seed"),
    proj_crs: Optional[str] = typer.Option(None, "--crs",
        help="Forwarded to make_env. Defaults to whatever the env factory picks."),
    slope_weight: Optional[float] = typer.Option(None, "--slope-weight",
        help="Override CountyLevelEnv slope reward weight before Tool 2 sampling."),
    cont_weight: Optional[float] = typer.Option(None, "--cont-weight",
        help="Override CountyLevelEnv contiguity reward weight before Tool 2 sampling."),
    baimu_weight: Optional[float] = typer.Option(None, "--baimu-weight",
        help="Override CountyLevelEnv baimu-fang area reward weight before Tool 2 sampling."),
    baimu_bonus: Optional[float] = typer.Option(None, "--baimu-bonus",
        help="Override CountyLevelEnv new baimu-fang patch bonus before Tool 2 sampling."),
    baimu_area_penalty: Optional[float] = typer.Option(None, "--baimu-area-penalty",
        help="Override CountyLevelEnv asymmetric baimu area-loss penalty before Tool 2 sampling."),
    env_kind: str = typer.Option("county", "--env",
        help="county (default; CountyLevelEnv on cadastral DLTB) | "
             "restoration (RestorationEnv on planning-unit attributes)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase B: sample transitions + pairwise data from the prepared environment."""
    _setup_logging(verbose)
    from farmland_mpc.sample import run

    summary = run(
        prepared_dir=prepared_dir,
        n_transition_episodes=n_transition_episodes,
        n_pairwise_states=n_pairwise_states,
        n_pairwise_actions=n_pairwise_actions,
        seed=seed,
        proj_crs=proj_crs,
        env_kind=env_kind,
        slope_weight=slope_weight,
        cont_weight=cont_weight,
        baimu_weight=baimu_weight,
        baimu_bonus=baimu_bonus,
        baimu_area_penalty=baimu_area_penalty,
    )
    typer.echo(
        f"Phase B done -> {summary['transitions']['n_transitions']} transitions, "
        f"{summary['pairwise']['n_states']} pairwise states"
    )


@app.command()
def train(
    prepared_dir: Path = typer.Option(..., "--prepared-dir",
        help="Output of Phase A + B (containing tool2/transitions.npz + tool2/pairwise.npz)"),
    n_members: int = typer.Option(3, "--n-members"),
    epochs: int = typer.Option(30, "--epochs"),
    patience: int = typer.Option(8, "--patience"),
    lambda_rank: float = typer.Option(5.0, "--lambda-rank",
        help="Pairwise margin loss weight; 0 = pure MSE, 5.0 = Paper 9 v6 default."),
    margin: float = typer.Option(0.1, "--margin"),
    batch_size: int = typer.Option(256, "--batch-size"),
    seed_base: int = typer.Option(0, "--seed-base"),
    torch_threads: int = typer.Option(0, "--torch-threads"),
    out_subdir: str = typer.Option("tool3", "--out-subdir",
        help="Output subdir under prepared_dir (default 'tool3'). Use distinct values "
             "to train multiple independent ensembles in parallel on the same prepared/."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase C: train the contrastive transition-model ensemble + export ONNX."""
    _setup_logging(verbose)
    from farmland_mpc.train_ensemble import run

    summary = run(
        prepared_dir=str(prepared_dir),
        n_members=n_members,
        epochs=epochs,
        patience=patience,
        lambda_rank=lambda_rank,
        margin=margin,
        batch_size=batch_size,
        seed_base=seed_base,
        torch_threads=torch_threads,
        out_subdir=out_subdir,
    )
    typer.echo(f"Phase C done -> {n_members} members trained")


@app.command()
def plan(
    ensemble_dir: Path = typer.Option(..., "--ensemble-dir",
        help="Directory containing the trained ONNX ensemble members"),
    prepared_dir: Path = typer.Option(..., "--prepared-dir",
        help="Output of Phase A (contains DLTB_with_slope.shp etc.)"),
    out_dir: Path = typer.Option(..., "--out-dir",
        help="Where to write per-step traces and the optimised shapefile"),
    horizon: int = typer.Option(5, "--horizon", "-H"),
    top_k: int = typer.Option(50, "--top-k", "-K"),
    mpc_batch_size: int = typer.Option(1024, "--mpc-batch-size",
        help="Internal ONNX inference batch size. Does not change top-k or the objective."),
    n_episodes: int = typer.Option(1, "--n-episodes"),
    continuation: str = typer.Option("random", "--continuation",
        help="random | greedy"),
    scoring: str = typer.Option("reward", "--scoring",
        help="reward | slope_only"),
    threads: int = typer.Option(0, "--threads"),
    seed_offset: int = typer.Option(0, "--seed-offset"),
    proj_crs: Optional[str] = typer.Option(None, "--crs"),
    output_fc: Optional[Path] = typer.Option(None, "--output-shp",
        help="Where to write the optimised DLTB shapefile (with OPT_DLBM, CHG_FLAG, ORIG_DLBM)."),
    farm_dlbm: str = typer.Option("011", "--farm-dlbm"),
    forest_dlbm: str = typer.Option("031", "--forest-dlbm"),
    baimu_area_penalty: Optional[float] = typer.Option(None, "--baimu-area-penalty",
        help="Override env baimu_area_penalty (default 2000.0; paper Eq.1 implies 0)."),
    cultivated_area_floor_delta_ha: Optional[float] = typer.Option(
        None, "--cultivated-area-floor-delta-ha",
        help="Hard cumulative cultivated-area floor relative to initial area in ha. "
             "Use 0 for no net loss; negative values allow an explicit tolerance."),
    baimu_area_floor_delta_ha: Optional[float] = typer.Option(
        None, "--baimu-area-floor-delta-ha",
        help="Hard cumulative baimu-fang area floor relative to initial qualifying "
             "area in ha. Use 0 for no net loss; negative values allow a tolerance."),
    gamma_conn: Optional[float] = typer.Option(
        None, "--gamma-conn",
        help="Override local forest-entry connectivity weight for pair selection."),
    delta_conn: Optional[float] = typer.Option(
        None, "--delta-conn",
        help="Override local farmland-retirement connectivity protection weight."),
    env_kind: str = typer.Option("county", "--env",
        help="county (default; CountyLevelEnv) | "
             "restoration (RestorationEnv on planning-unit attributes)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Phase D: MPC planning. Writes per-step traces and (optionally) an optimised DLTB shapefile."""
    _setup_logging(verbose)
    from farmland_mpc.mpc_plan import run

    # Tool 4 was originally written to read the prepared DLTB through arcpy.
    # We pass the prepared_dir + let blocks_env.make_env discover the .shp.
    summary = run(
        ensemble_dir=str(ensemble_dir),
        out_dir=str(out_dir),
        horizon=horizon,
        top_k=top_k,
        mpc_batch_size=mpc_batch_size,
        n_episodes=n_episodes,
        continuation=continuation,
        scoring=scoring,
        threads=threads,
        seed_offset=seed_offset,
        env_kind=env_kind,
        prepared_dir=str(prepared_dir),
        proj_crs=proj_crs,
        output_fc=str(output_fc) if output_fc else None,
        input_dltb_fc=str(prepared_dir / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp"),
        farm_dlbm=farm_dlbm,
        forest_dlbm=forest_dlbm,
        baimu_area_penalty=baimu_area_penalty,
        cultivated_area_floor_delta_ha=cultivated_area_floor_delta_ha,
        baimu_area_floor_delta_ha=baimu_area_floor_delta_ha,
        gamma_conn=gamma_conn,
        delta_conn=delta_conn,
    )
    typer.echo(f"Phase D done -> see {out_dir}")


def main() -> None:
    """Entry point used by the ``farmland-mpc`` script registered in pyproject.toml."""
    app()


if __name__ == "__main__":
    main()
