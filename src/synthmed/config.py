"""Configuration for synthetic claim generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class GenerationConfig:
    """Parameters controlling a single generation run.

    Path attributes mirror the layout used in the original notebook:

    - ``data_root`` contains per-cohort / per-year subdirectories of FTS
      schema files (e.g. ``<data_root>/1111/2012/medpar_all_file_*.fts``).
    - ``distribution_dir`` holds the reference CSV / JSON distributions
      (demographics, ZIP-to-FIPS, SSA crosswalks, error rates, ...).
    - ``sample_dir`` holds the CMS DE-SynPUF inpatient sample files used to
      seed the joint distribution of diagnostic codes.
    - ``output_dir`` is where generated DAT files (and copied FTS files)
      are written, mirroring ``data_root``'s structure.
    """

    data_root: Path
    distribution_dir: Path
    sample_dir: Path
    output_dir: Path

    total_people: int = 1000
    alive_ratio: float = 0.95
    average_medpar_records: float = 0.267

    new_year_new_patients_mean: float = 0.05
    new_year_new_patients_sd: float = 0.005

    initial_dob_start: int = 1940
    initial_dob_end: int = 1950

    overall_error_rate: float = 0.66 * 0.01
    race_error_rate: float = 0.85
    dob_error_rate: float = 0.11
    no_medpar_error_rate: float = 0.01
    new_enrollment_no_medpar_rate: float = 0.009

    orphan_admission_rate: float = 0.01
    """Fraction of MEDPAR admissions to assign a fresh, never-enrolled
    BENE_ID (instead of one carried over from the cohort). Models the
    small but real population of admissions in CMS data with no matching
    enrollment row, typically caused by enrollment-data lag, retroactive
    enrollment, or upstream admin errors. Set to 0 to disable."""

    max_diag_columns: int = 25
    sampled_diag_columns: int = 10

    seed: int | None = None
    """If set, seeds Python ``random``, ``numpy.random``, and ``Faker`` at
    the start of :func:`synthmed.pipeline.run` for reproducible output.
    Leave ``None`` for fresh randomness each run."""

    def __post_init__(self) -> None:
        self.data_root = Path(self.data_root)
        self.distribution_dir = Path(self.distribution_dir)
        self.sample_dir = Path(self.sample_dir)
        self.output_dir = Path(self.output_dir)
