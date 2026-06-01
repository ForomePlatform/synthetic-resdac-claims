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
    alive_ratio: float = 0.97
    """Mean per-year survival probability for the existing cohort.
    Default ``0.97`` (3 % deaths) is above
    ``new_year_new_patients_mean + 4 × alive_ratio_sd``
    (= 0.05 + 0.02 = 0.07), so deaths < new enrolees with high
    probability and the year-over-year cohort grows monotonically by
    ~2 %/yr — matching the empirical 2011–2016 trajectory of the
    real Medicare 65+ population. Lower to ~0.95 for a roughly-flat
    cohort, or below the 0.07 boundary for monotonic shrinkage."""
    alive_ratio_sd: float = 0.005
    """Per-year jitter (standard deviation) applied to ``alive_ratio``
    when computing each transition's mortality. With the default
    ``0.005`` and ``alive_ratio = 0.95``, yearly death rates fall in
    roughly ``[0.03, 0.07]`` at 4σ, matching real-world < 1pp
    year-to-year mortality variation for the 65+ population. The
    drawn ratio is clipped to ``[0.80, 0.995]`` so an extreme tail
    can never produce > 20 % or < 0.5 % deaths.

    Previously hardcoded at ``0.1 × alive_ratio`` (~0.095), which
    produced bimodal "everyone lives / everyone dies" swings of ±5pp
    or more in yearly enrolment counts. Bump to ~0.01 if you want
    visible-but-controlled year-to-year noise; leave at the default
    for near-flat cohort evolution. To get a *monotonic-growth*
    trajectory like real Medicare, also raise ``alive_ratio`` above
    ``new_year_new_patients_mean + 4 × alive_ratio_sd``."""
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

    duplicate_admission_rate: float = 0.0013
    """Fraction of MEDPAR admissions to clone verbatim (same BENE_ID,
    same admission/discharge dates, same diagnosis codes). Models the
    real Medicare pattern of duplicate claims -- split bills,
    adjustments overlapping originals, crossover claims appearing
    twice -- that downstream QC code is expected to detect and dedupe.

    Independent of and on top of the rare accidental duplicates
    (~1 in 15k) that emerge from independent admission-date draws (see
    TODO.md). The default ≈ 20× that baseline; tune higher to stress
    deduplication logic. Set to 0 to disable explicit duplication."""

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
