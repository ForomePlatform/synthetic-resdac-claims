"""Top-level orchestration: discover years and drive multi-year generation."""

from __future__ import annotations

import shutil
from os import listdir
from pathlib import Path

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData, load_distributions
from synthmed.errors import generate_internal_errors, generate_internal_medpar_errors
from synthmed.internal_db import (
    generate_internal_database,
    increment_internal_database,
)
from synthmed.medpar import generate_medpar_internal_database
from synthmed.year import generate_year_files


def discover_year_directories(
    data_root: Path, output_root: Path
) -> dict[str, dict[str, Path]]:
    """Map ``year`` -> ``{"input": ..., "output": ...}`` for every cohort/year pair.

    Mirrors the directory layout under ``data_root`` into ``output_root``.
    """
    directory_map: dict[str, dict[str, Path]] = {}
    for subdir in listdir(data_root):
        cohort = data_root / subdir
        if not cohort.is_dir():
            continue
        for year_dir in listdir(cohort):
            year_path = cohort / year_dir
            if not year_path.is_dir():
                continue
            output_year = output_root / subdir / year_dir
            directory_map[year_dir] = {
                "input": year_path,
                "output": output_year,
            }
            output_year.mkdir(parents=True, exist_ok=True)
    return directory_map


def copy_fts_files(directory_map: dict[str, dict[str, Path]]) -> None:
    """Copy ``.fts`` schemas alongside the generated ``.dat`` outputs."""
    for entry in directory_map.values():
        input_dir = entry["input"]
        output_dir = entry["output"]
        for file in listdir(input_dir):
            if file.endswith(".fts"):
                shutil.copyfile(input_dir / file, output_dir / file)


def run(
    config: GenerationConfig,
    dist: DistributionData | None = None,
) -> dict[str, dict[str, Path]]:
    """Run the full multi-year generation pipeline.

    Returns the discovered ``directory_map`` to make follow-up inspection easy.
    """
    if dist is None:
        dist = load_distributions(config.distribution_dir, config.sample_dir)

    directory_map = discover_year_directories(config.data_root, config.output_dir)
    years = sorted(directory_map.keys())
    if not years:
        raise RuntimeError(
            f"No year subdirectories discovered under {config.data_root}"
        )

    first_year = int(years[0])
    base = generate_internal_database(
        config.total_people,
        config.initial_dob_start,
        config.initial_dob_end,
        generate_dead=True,
        death_year=first_year - 1,
        dist=dist,
        config=config,
    )
    base, medpar = generate_medpar_internal_database(base, dist, config)

    for i, year in enumerate(years):
        entry = directory_map[year]
        generate_year_files(entry["input"], entry["output"], year, base, medpar)
        if i < len(years) - 1:
            base = increment_internal_database(base, years[i + 1], dist, config)
            base = generate_internal_errors(base, config)
            base, medpar = generate_medpar_internal_database(base, dist, config)
            medpar = generate_internal_medpar_errors(medpar, dist)

    copy_fts_files(directory_map)
    return directory_map
