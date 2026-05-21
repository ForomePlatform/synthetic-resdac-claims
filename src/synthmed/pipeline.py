"""Top-level orchestration: discover years and drive multi-year generation."""

from __future__ import annotations

import logging
import random
import shutil
import time
from os import listdir
from pathlib import Path

import numpy as np
from faker import Faker

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData, load_distributions
from synthmed.errors import generate_internal_errors, generate_internal_medpar_errors
from synthmed.internal_db import (
    generate_internal_database,
    increment_internal_database,
)
from synthmed.medpar import generate_medpar_internal_database
from synthmed.year import generate_year_files

log = logging.getLogger(__name__)


def _seed_all_rngs(seed: int) -> None:
    """Seed every randomness source the pipeline draws from."""
    random.seed(seed)
    np.random.seed(seed)
    Faker.seed(seed)


def _configure_default_logging() -> None:
    """Attach a console handler at INFO if no logging is configured yet.

    Idempotent and respects host configuration: if the root logger or
    the ``synthmed`` logger already has any handler attached, we leave
    everything alone (the caller -- CLI, framework, notebook setup --
    is presumed to know what they're doing). This makes naive callers
    like ``python -m synthmed`` or a fresh notebook get progress
    messages on stderr for free without overriding more sophisticated
    setups.
    """
    synthmed_log = logging.getLogger("synthmed")
    if synthmed_log.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    synthmed_log.addHandler(handler)
    synthmed_log.setLevel(logging.INFO)


def discover_year_directories(
    data_root: Path, output_root: Path
) -> dict[str, dict[str, Path]]:
    """Return ``{year: {"input": <path>, "output": <path>}}`` for every cohort/year.

    Walks ``data_root/<cohort>/<year>/`` (the layout produced by the
    ResDAC delivery), mirrors that into ``output_root`` (creating output
    directories), and returns one entry per discovered year.
    """
    directory_map: dict[str, dict[str, Path]] = {}
    for cohort_name in listdir(data_root):
        cohort_dir = data_root / cohort_name
        if not cohort_dir.is_dir():
            continue
        for year_name in listdir(cohort_dir):
            input_dir = cohort_dir / year_name
            if not input_dir.is_dir():
                continue
            output_dir = output_root / cohort_name / year_name
            output_dir.mkdir(parents=True, exist_ok=True)
            directory_map[year_name] = {"input": input_dir, "output": output_dir}
    return directory_map


def copy_fts_files(directory_map: dict[str, dict[str, Path]]) -> None:
    """Copy every ``.fts`` schema alongside its generated ``.dat`` output."""
    for entry in directory_map.values():
        for file in listdir(entry["input"]):
            if file.endswith(".fts"):
                shutil.copyfile(entry["input"] / file, entry["output"] / file)


def run(
    config: GenerationConfig,
    dist: DistributionData | None = None,
) -> dict[str, dict[str, Path]]:
    """Run the full multi-year generation pipeline.

    Two in-memory pandas frames carry the generator state across years:

    - ``cohort`` -- the internal beneficiary cohort, one row per synthetic
      beneficiary. Holds persistent identity (BENE_ID, ZIP, FIPS, SSA
      codes, demographics) plus the year's Poisson-drawn
      ``number_of_records`` admission count. **This frame is the source
      for every MBSF DAT file emitted for the year.** There is no
      separate "MBSF generation step" -- the MBSF/MEDPAR dispatch
      happens inside :func:`synthmed.year.generate_year_files`, which
      reads each ``*.fts`` schema in the year's input directory and
      renders it against ``cohort`` or ``medpar`` based on whether the
      filename contains ``"medpar"``.
    - ``medpar`` -- the per-admission frame, derived from ``cohort`` by
      repeating each beneficiary row ``number_of_records`` times so each
      admission inherits the beneficiary's identity while varying its
      diagnosis codes and admission dates independently. **This frame
      is the source for the MEDPAR DAT file emitted for the year.**

    Both ``cohort`` and ``medpar`` are *rebound* rather than mutated in
    place between calendar years: :func:`increment_internal_database`
    returns a fresh ``cohort`` for the next year (drops the dead, ages
    survivors, adds new 65-year-old enrollees), and
    :func:`generate_medpar_internal_database` then derives a fresh
    ``medpar`` from it. The rebind keeps the temporal contract -- "year
    N+1 cohort is a deterministic function of year N" -- visible in the
    code; an in-place mutation would not save memory (every column is
    rewritten anyway) and would obscure that contract. We deliberately
    do *not* retain a year-keyed history of past cohorts, since each
    year's output files are written to disk before the cohort advances.

    Returns the year → input/output directory map for follow-up
    inspection.
    """
    _configure_default_logging()

    if config.seed is not None:
        _seed_all_rngs(config.seed)

    if dist is None:
        log.info("Loading reference distributions and DE-SynPUF samples…")
        dist = load_distributions(config.distribution_dir, config.sample_dir)

    directory_map = discover_year_directories(config.data_root, config.output_dir)
    years = sorted(directory_map.keys())
    if not years:
        raise RuntimeError(
            f"No year subdirectories discovered under {config.data_root}"
        )

    log.info(
        "Run starting: %d cohort year(s) %s → %s, target=%d beneficiaries, output=%s",
        len(years), years[0], years[-1], config.total_people, config.output_dir,
    )

    # Build the initial cohort for the earliest discovered year, then
    # derive its first-year MEDPAR frame. `cohort` and `medpar` are
    # carried (and rebound) across the year loop below; see docstring.
    first_year = int(years[0])
    cohort = generate_internal_database(
        config.total_people,
        config.initial_dob_start,
        config.initial_dob_end,
        generate_dead=True,
        death_year=first_year - 1,
        dist=dist,
        config=config,
    )
    cohort, medpar = generate_medpar_internal_database(cohort, dist, config)

    overall_start = time.perf_counter()
    # Year loop: emit (cohort, medpar) for the current year, then advance
    # the cohort one year forward. The final year has no successor, so
    # the advance block is skipped via the None sentinel.
    for current_year, next_year in zip(years, [*years[1:], None]):
        year_start = time.perf_counter()
        n_dead_in_cohort = int((cohort["death_date"] != " ").sum())
        log.info(
            "Year %s: emitting (cohort=%d beneficiaries, %d marked dead this year; medpar=%d admissions)",
            current_year, len(cohort), n_dead_in_cohort, len(medpar),
        )
        entry = directory_map[current_year]
        # cohort → every MBSF file for current_year; medpar → MEDPAR file.
        # The MBSF/MEDPAR dispatch is FTS-filename-based inside year.py.
        generate_year_files(entry["input"], entry["output"], current_year, cohort, medpar)
        log.info(
            "Year %s: done in %.1fs (MBSF=%d rows, MEDPAR=%d rows)",
            current_year, time.perf_counter() - year_start, len(cohort), len(medpar),
        )
        if next_year is None:
            break
        # Advance cohort: drop dead → age survivors → add new 65s → inject
        # cohort-level errors → re-derive MEDPAR → inject MEDPAR errors.
        cohort = increment_internal_database(cohort, next_year, dist, config)
        cohort = generate_internal_errors(cohort, config)
        cohort, medpar = generate_medpar_internal_database(cohort, dist, config)
        medpar = generate_internal_medpar_errors(medpar, dist)

    copy_fts_files(directory_map)
    log.info(
        "Run done in %.1fs (%d year(s), output under %s)",
        time.perf_counter() - overall_start, len(years), config.output_dir,
    )
    return directory_map
