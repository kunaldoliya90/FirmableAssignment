# Command-line interface: generate, validate, benchmark, config
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer

from orggraph_dataset.config import (
    ConfigError,
    apply_overrides,
    build_config,
    load_raw_config,
    parse_override_pairs,
)
from orggraph_dataset.constants import SPLITS
from orggraph_dataset.utils.jsonl import write_json
from orggraph_dataset.utils.logging import configure_logging

app = typer.Typer(
    name="orggraph-dataset",
    help="Synthetic org-chart dataset generation, validation and benchmarking for OrgGraph.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

ConfigDirOpt = Annotated[
    Path | None, typer.Option("--config-dir", help="Directory with the YAML configuration.")
]
SetOpt = Annotated[
    list[str] | None,
    typer.Option("--set", help="Config override, e.g. --set dataset.workforce.remote_probability=0.1"),
]
LogOpt = Annotated[str | None, typer.Option("--log-level", help="DEBUG, INFO, WARNING or ERROR.")]


def _fail(message: str) -> typer.Exit:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    return typer.Exit(code=2)


def _load(config_dir: Path | None, overrides: list[str] | None) -> tuple[Any, dict[str, Any]]:
    _, raw = load_raw_config(config_dir)
    if overrides:
        raw = apply_overrides(raw, parse_override_pairs(overrides))
    return build_config(raw), raw


@app.command(help="Generate a synthetic dataset (observed data plus hidden ground truth).")
def generate(
    companies: Annotated[int | None, typer.Option(help="Number of companies.")] = None,
    min_employees_per_company: Annotated[
        int | None, typer.Option(help="Minimum employees per company.")
    ] = None,
    target_employees: Annotated[
        int | None,
        typer.Option(help="Minimum total employees (the generator may plan more for size diversity)."),
    ] = None,
    seed: Annotated[int | None, typer.Option(help="Random seed.")] = None,
    noise_profile: Annotated[
        str | None, typer.Option(help="Noise profile for train/validation/test.")
    ] = None,
    challenge_noise_profile: Annotated[
        str | None, typer.Option(help="Noise profile for the challenge split.")
    ] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Output directory.")] = None,
    batch_size: Annotated[int | None, typer.Option(help="Companies per export batch.")] = None,
    overwrite: Annotated[
        bool, typer.Option(help="Replace an existing dataset in the output directory.")
    ] = False,
    validate_after: Annotated[
        bool,
        typer.Option("--validate-after/--no-validate-after", help="Reload and validate after export."),
    ] = True,
    config_dir: ConfigDirOpt = None,
    set_: SetOpt = None,
    log_level: LogOpt = None,
) -> None:
    from orggraph_dataset.pipeline.exporter import OutputDirectoryError
    from orggraph_dataset.pipeline.orchestrator import (
        GenerationSettings,
        GenerationValidationError,
        run_generation,
    )

    configure_logging(log_level)
    try:
        config, raw = _load(config_dir, set_)
        settings = GenerationSettings.from_config(
            config,
            companies=companies,
            min_employees_per_company=min_employees_per_company,
            target_employees=target_employees,
            seed=seed,
            noise_profile=noise_profile,
            challenge_noise_profile=challenge_noise_profile,
            output_dir=output_dir or os.environ.get("ORGGRAPH_OUTPUT_DIR"),
            batch_size=batch_size,
            overwrite=overwrite,
            validate_after_export=validate_after,
        )
        result = run_generation(config, settings, raw_config=raw)
    except (ConfigError, OutputDirectoryError) as exc:
        raise _fail(str(exc)) from None
    except GenerationValidationError as exc:
        raise _fail(str(exc)) from None

    m = result.manifest
    typer.echo(f"\nDataset written to {result.output_dir}")
    typer.echo(f"  companies           {m.company_count:,}")
    typer.echo(f"  employees           {m.employee_count:,}  (requested >= {m.requested_target_employees:,})")
    typer.echo(f"  departed employees  {m.departed_employee_count:,}")
    typer.echo(f"  reporting edges     {m.reporting_edge_count:,}  (+{m.root_count} roots)")
    typer.echo(f"  secondary edges     {m.secondary_edge_count:,}")
    typer.echo(f"  observations        {m.observation_count:,}")
    typer.echo(
        "  splits              " + ", ".join(f"{s}={m.split_distribution[s]['companies']}" for s in SPLITS)
    )
    typer.echo(
        "  sizes               " + ", ".join(f"{k}={v}" for k, v in m.company_size_distribution.items())
    )
    typer.echo("  archetypes          " + ", ".join(f"{k}={v}" for k, v in m.archetype_distribution.items()))
    if result.validation is not None:
        status = "passed" if result.validation.ok else "FAILED"
        typer.echo(f"  validation          {status} ({sum(result.validation.checks.values()):,} checks)")
    typer.echo(f"  elapsed             {result.summary['elapsed_seconds']}s")


@app.command(help="Reload an exported dataset and check every constraint, including leakage.")
def validate(
    dataset_dir: Annotated[Path, typer.Option(help="Dataset directory produced by `generate`.")] = Path(
        "datasets/FirmableAssignmentDataset"
    ),
    min_companies: Annotated[int | None, typer.Option(help="Fail if fewer companies.")] = None,
    min_employees_per_company: Annotated[int | None, typer.Option(help="Per-company minimum.")] = None,
    min_total_employees: Annotated[int | None, typer.Option(help="Fail if fewer employees overall.")] = None,
    report: Annotated[Path | None, typer.Option(help="Write the full JSON report here.")] = None,
    config_dir: ConfigDirOpt = None,
    set_: SetOpt = None,
    log_level: LogOpt = None,
) -> None:
    from orggraph_dataset.validation import validate_dataset_dir

    configure_logging(log_level)
    try:
        config, _ = _load(config_dir, set_)
    except ConfigError as exc:
        raise _fail(str(exc)) from None
    result = validate_dataset_dir(
        dataset_dir,
        config,
        min_companies=min_companies,
        min_employees_per_company=min_employees_per_company,
        min_total_employees=min_total_employees,
    )
    if report:
        write_json(report, result.to_dict())
    stats = result.stats
    typer.echo(f"Validated {dataset_dir}")
    for key in (
        "companies",
        "employees",
        "departed_employees",
        "reporting_edges",
        "secondary_edges",
        "observations",
    ):
        typer.echo(f"  {key:<20}{stats.get(key, 0):,}")
    typer.echo(f"  {'companies_per_split':<20}{stats.get('companies_per_split', {})}")
    leakage_checks = sum(v for k, v in result.checks.items() if k.startswith("leakage."))
    leakage_errors = sum(v for k, v in result.issue_counts.items() if k.startswith("leakage."))
    typer.echo(f"  {'checks run':<20}{sum(result.checks.values()):,}")
    typer.echo(f"  {'leakage checks':<20}{leakage_checks:,} ({leakage_errors} violations)")
    if result.ok:
        typer.secho("  result              PASSED", fg=typer.colors.GREEN)
        return
    typer.secho(f"  result              FAILED ({result.error_count} issues)", fg=typer.colors.RED)
    for line in result.summary_lines():
        typer.echo(f"    {line}")
    raise typer.Exit(code=1)


@app.command(help="Score predicted reporting lines against hidden ground truth.")
def benchmark(
    predictions: Annotated[Path, typer.Option(help="Prediction JSONL produced by an inference engine.")],
    dataset_dir: Annotated[Path, typer.Option(help="Dataset directory.")] = Path(
        "datasets/FirmableAssignmentDataset"
    ),
    split: Annotated[list[str] | None, typer.Option(help="Split(s) to evaluate (default: all).")] = None,
    wrong_edge_penalty: Annotated[
        float | None, typer.Option(help="Correct edges lost per wrong edge.")
    ] = None,
    output: Annotated[Path | None, typer.Option(help="Write the full JSON report here.")] = None,
    config_dir: ConfigDirOpt = None,
    set_: SetOpt = None,
) -> None:
    from orggraph_dataset.evaluation import BenchmarkError, PredictionFileError, run_benchmark

    try:
        config, _ = _load(config_dir, set_)
        evaluation = config.dataset.evaluation
        result = run_benchmark(
            dataset_dir,
            predictions,
            splits=split,
            wrong_edge_penalty=wrong_edge_penalty
            if wrong_edge_penalty is not None
            else evaluation.wrong_edge_penalty,
            calibration_bins=evaluation.calibration_bins,
            confidence_thresholds=evaluation.confidence_thresholds,
        )
    except (ConfigError, BenchmarkError, PredictionFileError) as exc:
        raise _fail(str(exc)) from None
    if output:
        write_json(output, result)
    overall = result["overall"]
    typer.echo(f"Benchmark: {predictions} on splits {result['splits']}")
    for key in (
        "edge_precision",
        "edge_recall",
        "edge_f1",
        "coverage",
        "abstention_rate",
        "wrong_edge_rate",
        "penalized_score",
    ):
        typer.echo(f"  {key:<24}{overall[key]}")
    cal = result["calibration"]
    typer.echo(f"  {'ECE':<24}{cal['expected_calibration_error']}")
    typer.echo(f"  {'Brier score':<24}{cal['brier_score']}")
    counts = overall["counts"]
    typer.echo(
        f"  counts: correct={counts['correct']:,} wrong={counts['wrong']:,} "
        f"abstained={counts['abstained']:,} missing_rows={counts['missing_predictions']:,}"
    )
    unmatched = result["unmatched_predictions"]
    if unmatched["in_evaluated_companies"]:
        typer.secho(
            f"  warning: {unmatched['in_evaluated_companies']:,} predictions reference unknown employees",
            fg=typer.colors.YELLOW,
        )
    typer.echo(
        "  per noise profile: "
        + ", ".join(f"{k}: F1={v['edge_f1']}" for k, v in result["breakdowns"]["noise_profile"].items())
    )
    if output:
        typer.echo(f"  full report: {output}")


@app.command("config", help="Show the resolved configuration after overrides.")
def show_config(
    section: Annotated[
        str | None, typer.Option(help="Only print this section (e.g. noise, dataset).")
    ] = None,
    config_dir: ConfigDirOpt = None,
    set_: SetOpt = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the resolved configuration as JSON.")
    ] = False,
) -> None:
    from orggraph_dataset.config import resolve_config_dir

    try:
        config, _ = _load(config_dir, set_)
    except ConfigError as exc:
        raise _fail(str(exc)) from None
    dumped = config.model_dump(mode="json")
    if section:
        if section not in dumped:
            raise _fail(f"unknown section '{section}' (choose from {', '.join(dumped)})")
        typer.echo(json.dumps(dumped[section], indent=2, ensure_ascii=False))
        return
    if as_json:
        typer.echo(json.dumps(dumped, indent=2, ensure_ascii=False))
        return
    ds = config.dataset
    typer.echo(f"config directory      {resolve_config_dir(config_dir)}")
    typer.echo(f"companies             {ds.companies}")
    typer.echo(f"min employees/company {ds.min_employees_per_company}")
    typer.echo(
        f"target employees      {ds.target_employees:,} (diversity multiplier {ds.size_diversity_multiplier})"
    )
    typer.echo(f"seed                  {ds.seed}")
    typer.echo(f"noise profile         {ds.noise_profile} (challenge: {ds.challenge_noise_profile})")
    typer.echo(f"output dir            {ds.output_dir}")
    typer.echo(f"split fractions       {ds.splits.fractions}")
    typer.echo(
        f"industries ({len(config.industries.industries)})       {', '.join(config.industries.industries)}"
    )
    typer.echo(f"archetypes            {', '.join(config.archetypes.archetypes)}")
    typer.echo(f"noise profiles        {', '.join(config.noise.profiles)}")
    typer.echo(f"sources               {', '.join(config.sources.sources)}")
    typer.echo(f"departments           {len(config.departments.departments)} in catalog")
    typer.echo(f"job families          {len(config.job_families.families)}")
    typer.echo("Use --section <name> or --json for full detail.")


if __name__ == "__main__":
    app()
