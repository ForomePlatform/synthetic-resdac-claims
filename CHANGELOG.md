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

### Changed
- **Coverage-chain parameters extracted to `GenerationConfig`.**
  `MarkovConfig` moved to `synthmed.config` (gaining a
  `self_transition_prob` field, default 0.995, replacing the hardcoded
  transition matrix), and `GenerationConfig` gained a `markov_chains`
  mapping (default: `default_markov_chains()`, the ResDAC-coded Buy-In
  and HMO chains). The mapping is threaded through
  `generate_year_files` and `_generate_column` into `char_generation`,
  whose `markov_chains` parameter falls back to the module defaults, so
  existing imports and call sites are unchanged. Locked in by
  `tests/test_markov.py::test_generation_config_defaults_match_module_chains`
  and `::test_char_generation_honors_markov_chains_argument`.

### Fixed
- **Width-9 ZIP fields now carry a full 9-digit ZIP+4.** The cohort
  `zip4` column held only the 5-digit ZIP, so width-9 FTS fields
  (MBSF `BENE_ZIP_CD`) were emitted as `zip5` + 4 trailing blanks
  after the left-justification fix, and dorieh's ingestion crashed
  casting the blank +4 subfield to integer (`invalid input syntax for
  type integer: "    "`, 2026-09-11). `zip4` is now `zip + "0000"`
  so the +4 subfield stays castable (layout-contract call by Michael).
  Follow-up the same day: dorieh's own docs (medicare.yaml:77,
  doc/Medicare.md:453) record that real MBSF carries the +4 only when
  provided — a blank tail is the faithful emulation, and dorieh's
  length guard existed for exactly that case until fixed-width padding
  defeated it. dorieh has since staged a blank-tolerant
  `NULLIF(TRIM(...))` cast, so reverting to a blank tail is viable;
  the direction decision is tracked in TODO.md ("Model a full 9-digit
  ZIP+4").
- **CHAR fields are now left-justified in emitted DAT files.** CMS
  fixed-width extracts left-justify CHAR columns (trailing blanks);
  the emitter right-justified them instead, so any CHAR value shorter
  than its declared width — most visibly the 5-digit ZIP inside the
  9-wide `BENE_ZIP_CD` — carried leading spaces. Consumers reading the
  leading bytes of the field saw blanks: the dorieh QC dashboard
  flagged ~100% of MBSF ZIPs as invalid and ~99.9% as inconsistent
  with the county code, although the underlying zip/county pairs are
  coherent (95.6% exact SSA-county match on the 2011 sample, 100%
  state-level, residual = multi-county ZIPs). Surfaced by the QC
  dashboard audit of 2026-09-10; datasets generated before this fix
  right-justify every under-width CHAR value.
- **2016 ABCD layout: Age and ZIP overrides never fired.** The combined
  `mbsf_abcd_summary` FTS spells the labels "Age at the End of the
  Reference Year" and "5-digit ZIP Code"; the exact-substring test
  ("Age at End of Reference Year") and the case-sensitive `"Zip"` test
  both missed them, so the 2016 file carried uniform random ages
  (0..998, inconsistent with DOB) and random-digit ZIPs (unrelated to
  the cohort ZIP that MEDPAR 2016 carries correctly). Age labels now
  match case- and article-insensitively (`_AGE_LABEL_RE`); the ZIP
  trigger is case-insensitive. Surfaced by a full-dataset audit of the
  regenerated 5M set on 2026-09-10; datasets generated before this fix
  have both defects in every 2016 ABCD row.
- **Off-by-one upper bounds: all-nines NUM values and Dec 31 were
  unreachable.** `_num_range` passed `10**w - 1` to `np.random.randint`,
  whose high end is exclusive, so e.g. 999 never occurred in a width-3
  NUM column (audit: 0 occurrences of 999 in 10.4M x 11 draws, while
  998 appeared at the uniform rate). `random_date_gen` similarly drew
  in `[start, end)` with callers passing Dec 31 as `end`, so Dec 31
  never occurred in any generated date column (~13.5k expected
  occurrences per column per year). NUM defaults now draw in
  `[0, 10**w)`; `random_date_gen` includes the whole end day. The
  "Months Number" (values 1..11) and "Year" (always base year)
  override bounds are NOT changed in this entry; they remain tracked
  in TODO.md.
- **HMO indicator dominant code corrected from `"3"` to `"0"`.** ResDAC
  defines no code 3 for the HMO indicator (the value set is 0, 1, 2, 4,
  A, B, C; see resdac.org/cms-data/variables/hmo-indicator); `"3"` was
  a copy-paste of the buy-in chain's dominant code, so ~69 % of every
  `HMOIND01..12` column in the v0.2.0 release carries an out-of-domain
  value. The dominant steady state is now `"0"` ("Not a member of
  HMO"), matching the real-world modal category. Surfaced by a
  code-vs-paper audit on 2026-09-08 and confirmed against the shipped
  v0.2.0 DAT files (68.8 % `"3"`, `"0"` absent). Tests are
  config-driven and pass unchanged; datasets regenerated after this fix
  will differ in the HMO columns.

## [0.2.0] - 2026-09-07

### Fixed
- **CLI flags no longer silently shadow `GenerationConfig` defaults.**
  [`synthmed.cli`](src/synthmed/cli.py) was hardcoding default values
  for every flag (notably `--alive-ratio = 0.95`), so a `synthmed
  generate` invocation used those CLI defaults regardless of what
  `GenerationConfig` declared. After bumping `alive_ratio` to 0.97 in
  `config.py`, the 5 M run via CLI was still seeing 0.95 and producing
  flat (rather than monotonically growing) yearly cohort sizes. CLI
  flags now default to `None`; unset flags are dropped before
  constructing `GenerationConfig`, so the dataclass defaults stay
  authoritative and future config tweaks propagate automatically.
- **OREC (`ENTLMT_RSN_ORIG`) is now invariant across a beneficiary's years.**
  Previously fell through to the random-digit default in
  [`synthmed.columns.char_generation`](src/synthmed/columns.py) and was
  redrawn independently every year. That silently broke downstream
  natural-joins that treat OREC as a per-beneficiary key — concretely,
  the Dorieh Medicare QC model's `enrollments ⋈ beneficiaries` was
  dropping ~71 % of enrollment-years because the join key kept changing.
  OREC is now sampled once per beneficiary in
  [`generate_demographic`](src/synthmed/internal_db.py) (canonical
  ResDAC codes `0`–`3`) and carried verbatim through
  `increment_internal_database`; only CUREC (`ENTLMT_RSN_CURR`,
  "Current Reason for Entitlement") still varies year-to-year, as it
  should. Locked in by
  `tests/test_statistical.py::test_orec_invariant_across_years`.
- **Year-to-year cohort size now grows monotonically at ~2 %/yr.**
  Two related changes to
  [`synthmed.internal_db.increment_internal_database`](src/synthmed/internal_db.py)
  and the corresponding `GenerationConfig` defaults:
  - The per-transition mortality jitter was hardcoded at
    `N(alive_ratio, alive_ratio × 0.1)` — σ ≈ 0.095 on the survival
    probability — producing bimodal "everyone lives / everyone dies"
    draws that swung enrolment by ±250 K to ±630 K per year on a 5 M
    cohort. The jitter is now σ = 0.005 (configurable via the new
    `GenerationConfig.alive_ratio_sd`) and clipped to `[0.80, 0.995]`.
  - Default `alive_ratio` raised from 0.95 to 0.97 so that
    expected deaths (3 %) sit safely below expected new-65 enrolees
    (5 %) — the cohort now grows monotonically by ~2 %/yr, matching
    the empirical 2011–2016 trajectory of the real Medicare 65+
    population instead of oscillating around a flat mean.
  Locked in by
  `tests/test_statistical.py::test_year_to_year_cohort_size_is_stable`.
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
- **HMO and Part A/B Buy-In monthly coverage indicators**
  (`BUYIN01..12`, `HMOIND01..12`) generated by sticky first-order
  Markov chains: a dominant flat fraction of beneficiaries holds one
  state all year, a secondary flat fraction holds another, and the
  remainder follows a per-month chain with 0.995 self-transition and
  the residual mass spread uniformly. New `MarkovConfig` and
  [`synthmed.columns._build_buyhmo_sequence`](src/synthmed/columns.py),
  dispatched and cached per chain from `char_generation` via
  `_ENUMERATED_MARKOV_CHAINS`. Contributed by Mark Chumack, who joins
  the author list (`CITATION.cff`, `pyproject.toml`, README) with
  this release. Locked in by `tests/test_markov.py`.
- **`GenerationConfig.duplicate_admission_rate`** (default `0.0013`,
  ≈ 20× the previous accidental baseline of ~1 in 15k that emerged
  from independent admission-date draws). New
  [`synthmed.medpar._inject_duplicate_admissions`](src/synthmed/medpar.py)
  clones a configurable fraction of MEDPAR rows verbatim — same
  `BENE_ID`, same admission/discharge dates, same diagnosis codes —
  to model duplicate-claim patterns (split bills, adjustments
  overlapping originals, crossover claims appearing twice) that
  downstream QC code is expected to detect and dedupe. Clones are
  forced to `last_record = False` so the death-date column stays
  single-emit. Locked in by
  `tests/test_medpar.py::test_duplicate_admissions_*`.
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
