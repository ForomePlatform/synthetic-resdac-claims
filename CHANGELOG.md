# Changelog

All notable changes to `synthmed` land here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); each entry
is attributed to the release that shipped it. Open items
(simplifications, approximations, known bugs) live in
[TODO.md](TODO.md), not here.

The package version in [`pyproject.toml`](pyproject.toml) tracks the
most recently shipped tag. Work in flight on `dev` accumulates under
`[Unreleased]` and rolls into the next version on tag.

## [Unreleased]

### Fixed
- **DOB error distribution now peaks at month boundaries.** The
  previous additive-Poisson model in
  [`synthmed.errors._sample_dob_offsets`](src/synthmed/errors.py)
  summed five day-scale layers (1 / 3 / 10 / 30 / 365), so a 40-day
  total emerged easily (30 + 10) while a clean 60-day total required
  every off-boundary layer to draw 0. The result was a histogram where
  40d > 60d, opposite of the real-data shape. The new model draws one
  *mutually exclusive* mode per affected beneficiary (month-off /
  day-off / year-off / combined), giving clean spikes at ±30, ±60, ±90
  … days; 40-day or 50-day errors now only emerge from the small
  `combined` weight, restoring the empirical month-boundary clustering.
  Locked in by `tests/test_statistical.py::test_dob_error_shape_peaks_at_month_boundaries`.

### Added
- **Stratified trajectory replay for diagnoses.**
  [`synthmed.internal_db.generate_diagnosis`](src/synthmed/internal_db.py)
  now matches each synthetic beneficiary to a DE-SynPUF beneficiary
  in the same `(age band, sex, state)` stratum and replays *that*
  DE-SynPUF beneficiary's actual inpatient admissions across the
  synthetic beneficiary's `k` MEDPAR rows. Preserves both the
  within-admission and across-admission joint diagnosis structure and
  conditions diagnoses on the synthetic beneficiary's demographics.
- **DE-SynPUF beneficiary summary files added to the sample manifest.**
  `synthmed.samples.BENEFICIARY_SAMPLES` carries 20 new pinned
  SHA-256 hashes; `synthmed download-samples` now fetches both
  inpatient claims and beneficiary summaries (40 files total,
  ~60 MB extra compressed download on first run).
- **Two new statistical tests** assert the trajectory-replay
  contract: every emitted `diag_1..diag_10` row is a verbatim
  DE-SynPUF inpatient row, and every synthetic beneficiary's multiple
  admissions trace to a single DE-SynPUF beneficiary.
- **`CHANGELOG.md`** (this file).

### Changed
- `DistributionData.de_sample` (flat pandas DataFrame) replaced by
  `DistributionData.desynpuf: DesynpufTrajectories`, a compact indexed
  structure: admissions grouped by `DESYNPUF_ID` and an
  age × sex × state stratification index.
- README "How it works" diagram and prose updated to describe
  trajectory replay and the wider DE-SynPUF data dependency.
- TODO.md trimmed: resolved entries moved here (CHANGELOG) instead of
  accumulating in TODO.

## [0.1.1] - 2026-05-21

### Added
- **Statistical test suite** (`tests/test_statistical.py`, opt-out via
  `pytest -m "not statistical"`): race/sex marginal χ², orphan
  admission rate, race/DOB error injection rates, year-to-year cohort
  evolution invariants, state-correlated MEDPAR error rates.
- **Default INFO logging** for generation runs (`pipeline.run`
  configures a console handler iff none is already configured). Per-
  year progress, per-file progress, year transition recap (deaths +
  new enrollees + admissions), and elapsed-time totals all visible on
  stderr by default.
- **2015 calendar-year schemas** under `inputs/schemas/3333/2015/`,
  filling the previously-missing gap year between 2014 and 2016.
- **AI-usage acknowledgement** to the paper covering ChatGPT-4.1
  (FTS generation), Claude Opus 4.7 (codebase refactor), and Claude
  Opus 4.7 + ChatGPT-5.1 (manuscript editing).
- **Mermaid pipeline diagram** at `docs/diagrams/pipeline-flow.mmd`,
  embedded inline in README's "How it works" section so GitHub
  renders it natively.

### Changed
- **Substantial readability refactor** across nine modules:
  extracted helpers (`mint_beneficiary_ids`, `_FTSColumn`,
  `_reuse_from_prior`, `_generate_column`, `_emit_dat`,
  `_sample_dob_offsets`, `_stratum_pool`), regularized the per-column
  override structure in `columns.py`, killed every `print()`
  statement, added docstrings, and renamed the cohort variable from
  `base` → `cohort` repo-wide (114 occurrences) to make the data flow
  legible at every call site.
- `__version__` now derives from package metadata instead of being
  pinned in `synthmed/__init__.py`.
- `pyproject.toml`: `scipy>=1.10` added to the `dev` extra for the
  statistical test suite.
- Pandas `PerformanceWarning` about fragmented DataFrames eliminated
  in `year.generate_year_files` by accumulating generated columns in
  a dict and constructing the DataFrame in a single allocation.

### Removed
- **`number_of_diagnoses.csv`** end-to-end. Investigation showed the
  loaded distribution populated a `number_of_diagnoses` column on the
  in-memory cohort that no downstream code path ever read; the FTS
  slots that should have carried the count (`DGNS_CD_CNT`,
  `POA_DGNS_CD_CNT`, `DGNS_E_CD_CNT`, `POA_DGNS_E_CD_CNT`) fall
  through to the default uniform-random `NUM` generator. Adding a
  `DGNSCNT` override in `columns.number_generation` that emits
  `min(k, n_filled_diags)` is now a TODO.

### Fixed
- Two latent semantic finds discovered during the refactor, preserved
  as-is to keep DAT output byte-stable but logged in TODO:
  MEDPAR death-date-verification switch is inverted vs. MBSF; the
  MEDPAR-last FTS reordering is fragile against future layouts that
  place MEDPAR neither first nor last.

## [0.1.0] - 2026-05-19

### Added
- **Initial release.** Corresponds to Zenodo dataset v1.
  `synthmed` ships as an installable Python package, generating
  fixed-width Medicare DAT files (MBSF + MEDPAR) for 2011–2014, 2016
  cohort years against ResDAC File Transfer Specification schemas
  generated by ChatGPT-4.1. Cohort generation, error injection,
  per-year emission, multi-year evolution, and a CRLF-tolerant
  SHA-256-verified lazy downloader for the CMS DE-SynPUF inpatient
  samples are all in place. Two smoke tests cover end-to-end
  completion and bit-for-bit reproducibility under a fixed seed.

### Removed
- **`diag1.csv`** removed: diagnosis sampling uses CMS DE-SynPUF
  inpatient rows exclusively (preserving the within-admission joint
  structure across `diag_1..diag_10`). The 4076-row primary-dx
  marginal frequency table that the upstream prototype shipped was
  loaded into `DistributionData.diag1` but never consumed by any
  code path.
