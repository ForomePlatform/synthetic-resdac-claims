# TODO

A running list of known **simplifications, approximations, and bugs**
in `synthmed`. Anything documented as a caveat in a sidecar should also
be reflected here, with a one-line summary and a link back to the
detailed write-up.

Entries are grouped by area, then ordered by severity (highest first).
**Resolved changes live in [CHANGELOG.md](CHANGELOG.md)**, not here —
when an item ships, remove it from this file and add the
corresponding entry to the `[Unreleased]` section of the changelog.

---

## Demographic distribution

See [`docs/distributions/demographic_distributions.md`](docs/distributions/demographic_distributions.md).

- [ ] **No year conditioning.** A single static `race` / `sex` distribution
  is sampled for every cohort/year, even though Medicare composition
  shifts measurably across the 2011–2016 cohort window. Fix path: per-year
  weights or a script that interpolates CMS Medicare Enrollment Dashboard
  tabulations [@cms-medicare-enrollment-dashboard].
- [ ] **No age conditioning.** New 65-year-olds added by
  `synthmed.internal_db.increment_internal_database` are drawn from the
  same weights as the prevalent cohort, although new-enrollee race/ethnic
  mix differs from prevalent mix.
- [ ] **No race × sex joint distribution.** Sex is sampled independently
  of race; real Medicare shows a slightly higher female share among Black
  beneficiaries and a lower one among Asian beneficiaries.
- [ ] **RTI `Other` vs. `North American Native` split is an estimate.**
  KFF doesn't report AI/AN separately due to CPS sample size; the
  `0.008 / 0.005` split is best-effort. Pin against CMS Office of
  Minority Health tabulations if this becomes load-bearing.
- [ ] **`Unknown` rates are floor values, not measured.** `0.001` (sex)
  and `0.002` (race) preserve a non-zero stratum without overstating
  it. Real RTI-coded extracts could pin these tighter.
- [ ] **JSON is hand-maintained.** When a real source is wired up,
  derivation should move into a checked-in
  `scripts/derive_demographic_distributions.py` so the JSON is generated,
  not hand-edited.

## Diagnosis codes

- [ ] **Admission-count column is uniform-random, not derived.** The
  FTS slots `DGNS_CD_CNT`, `POA_DGNS_CD_CNT`, `DGNS_E_CD_CNT`, and
  `POA_DGNS_E_CD_CNT` fall through to the default uniform-random
  `NUM` generator instead of reflecting how many `diag_k` slots are
  actually populated. Add a `DGNSCNT` / `DGNS_CD_CNT` override in
  [`synthmed.columns.number_generation`](src/synthmed/columns.py)
  that emits `min(k, n_filled_diags)`.
- [ ] **Trajectory replay is single-year only.** Each cohort year
  re-samples a fresh DE-SynPUF beneficiary for each synthetic
  beneficiary, so the across-admission joint is preserved within a
  year but a synthetic beneficiary's chronic-condition trajectory
  does not persist across `increment_internal_database` calls. Carry
  the DESYNPUF_ID assignment across years so multi-year patterns
  stay coherent.
- [ ] **Sparse-stratum fallback is binary, not smoothed.**
  [`synthmed.internal_db._stratum_pool`](src/synthmed/internal_db.py)
  falls back from `(age, sex, state)` to `(age, sex, *)` to
  `(age, *, *)` to global when the requested cell is empty, but does
  not blend the cell with its parent (Bayesian smoothing). Small-state
  strata that are non-empty but sparse get noisier-than-necessary
  draws.
- [ ] **ICD-9 only; only 10 codes used per admission.** DE-SynPUF only
  exposes ICD-9 and only `ICD9_DGNS_CD_1..10`; columns `diag_11..diag_25`
  in the internal cohort are left as blank space. Modern Medicare uses
  ICD-10 and ~56% of admissions exceed 10 diagnoses.

## Column generation

- [ ] **`number_generation` width-6+ cap is `10*5 = 50`, not `10**5 = 100000`.**
  See [`synthmed.columns._num_range`](src/synthmed/columns.py).
  Behavior preserved from the upstream prototype; the documented intent
  is the larger cap. Fix once we have a regression suite.
- [ ] **MEDPAR death-date-verification switch is inverted vs. MBSF.** In
  [`synthmed.columns._death_date_switch`](src/synthmed/columns.py),
  MBSF emits `"V"` only on dead beneficiaries (intuitive), but MEDPAR
  emits `"V"` on every admission row of every beneficiary *except* the
  last-record row of alive ones — so dead beneficiaries also get `"V"`
  on every record. Suspected typo in the upstream prototype's logical
  expression. Decide between three fixes once we have a real-data
  comparison: (a) match MBSF (death-date-bearing record only), (b)
  invert to mean "this record's death date is valid", (c) leave as-is
  if real MEDPAR actually carries `"V"` on most rows. Preserved during
  the v0.2 refactor to keep DAT output unchanged.
- [ ] **Most `CHAR` columns without explicit overrides are random digit
  strings.** Matches the upstream prototype but yields semantically
  meaningless values (e.g. HMO sub-indicators, payment codes). Each new
  override would tighten realism for specific downstream consumers.
- [ ] **HMO / Buy-In / dual-eligibility coverage columns are
  unconditioned and not internally coherent.** Affects
  `hmo_indicator*`, `buyin*`, `dual_*`, and their matching
  `{hmo|buyin|dual}_mo` month-flag columns. Three layered issues:
  1. *Within-row incoherence:* `*_MO` columns are drawn independently
     of the matching annual yes/no indicator, so a beneficiary can
     show "no HMO" annually but `HMO_MO = 7`.
  2. *Missing column family:* `dual_*` (dual Medicare/Medicaid
     eligibility) is not currently modeled at all — entries fall
     through to the default random-digit `CHAR` path.
  3. *Downstream coupling not modeled:* coverage status is a major
     driver of MEDPAR admission counts in real data (dual-eligible and
     non-HMO beneficiaries admit more often), but
     [`generate_medpar_stats`](src/synthmed/internal_db.py) draws
     `number_of_records` from a single Poisson with no conditioning.
     Treating coverage as a covariate of the Poisson mean is the next
     fidelity step.

## Geographic / crosswalk

See [`docs/distributions/ssa_fips_state_county_2025.md`](docs/distributions/ssa_fips_state_county_2025.md).

- [ ] **Connecticut transition not gracefully handled.** The 2025 NBER
  crosswalk has empty `ssa_code` for CT's 9 new planning regions
  (`09110..09190`) and empty `fipscounty` for the 8 legacy CT counties.
  Beneficiaries mapped to new CT FIPS get NaN SSA codes and are
  silently dropped by `generate_location`'s `dropna`. Decide whether to
  add a CT-aware fallback or accept the drop. See
  [@census-2022-ct-change].
- [ ] **NBER crosswalk vintage is year-pinned in the filename.**
  Refreshing to a future vintage means file rename + loader update.
  Switching to a year-agnostic filename + manifest would be safer.
- [ ] **`zip2fips.csv` uses 1:1 ZIP→FIPS.** Real ZIPs often span
  multiple counties; this file picks one representative per ZIP
  ([`docs/distributions/zip2fips.md`](docs/distributions/zip2fips.md)).
  Upgrading would mean swapping in the HUD 1:N crosswalk and adding a
  weighted draw in `generate_location`.
- [ ] **`zip2fips.csv` upstream is "work in progress".** The
  clauswilke/zipcodes README explicitly states not all ZIPs are
  correctly mapped. No per-row confidence marker.
- [ ] **`zip2fips.csv` has no vintage stamp.** Last refresh date is
  unrecorded. Periodic refresh from upstream would catch new ZIPs and
  the CT planning-region transition.
- [ ] **ZCTA used as a stand-in for ZIP.** The 2020 Decennial Census
  publishes population by ZCTA, not by USPS ZIP. P.O.-box-only ZIPs
  are missing; some ZIPs split across ZCTAs. Standard approximation
  but worth flagging
  ([`docs/distributions/DECENNIALDHC2020.P1-Data.md`](docs/distributions/DECENNIALDHC2020.P1-Data.md)).
- [ ] **DECENNIAL 2020 snapshot is fixed.** Doesn't match any FTS
  cohort year exactly. Swapping in ACS 5-year estimates would allow
  per-cohort-year population weights at the cost of higher per-ZCTA
  variance.
- [ ] **Flat redistribution of unmatched-ZCTA mass.** The leftover
  probability mass from ZCTAs missing from `zip2fips.csv` is spread
  uniformly across those ZCTAs, which is a guess, not a measurement.

## Cohort evolution

- [ ] **All new enrollees are exactly 65.** `increment_internal_database`
  hard-codes the new-enrollee birth year to `next_year - 65`. No <65
  disability-based enrollees, no spread of new-enrollee ages.
- [ ] **No disability-based enrollment.** Generate `ENTLMT_RSN_ORIG` /
  `ENTLMT_RSN_CURR` and add a <65 cohort
  ([ResDAC docs](https://resdac.org/cms-data/variables/original-reason-entitlement-code)).

## Error injection

See [`docs/distributions/state_error_medpar_rates.md`](docs/distributions/state_error_medpar_rates.md).

- [ ] **Orphan-admission rate default is best-guess.** `GenerationConfig.orphan_admission_rate`
  defaults to `0.01`; calibrate against an empirical real-data
  measurement once authorization is available (same caveat as
  `state_error_medpar_rates.csv`).
- [ ] **Orphan-admission rate is global, not per-state.** Optional
  follow-up to mirror the state-correlated structure of the existing
  MEDPAR error table.
- [ ] **DOB error mode weights are not empirically calibrated.** The
  mixture in
  [`synthmed.errors._DOB_ERROR_MODES`](src/synthmed/errors.py) — 55 %
  month-off / 30 % day-off / 5 % year-off / 10 % combined — was
  chosen by domain intuition (month-typos most common; combined
  rarest) after the 2026-05-21 fix to the additive-Poisson shape.
  Pin against real-extract DOB-error frequencies when authorization
  is available; the per-mode Poisson parameters
  (`Poisson(1.0)` for month-count, `Poisson(1.5)` for day-count,
  `Poisson(0.5)` for year-count) likewise need empirical pinning.
- [ ] **Fill in `@bouzinier-2026-springer-ch8` placeholder once the
  volume ships.** Chapter title, author list, book title, and editors
  are tagged `FORTHCOMING` in
  [`docs/references.bib`](docs/references.bib); grep for that string.
  The DOI / ISBNs / series fields are final.
- [ ] **`state_error_medpar_rates.csv` rates are real but stale.** They
  reflect a single Medicare-extract snapshot used by the pipeline in
  [@audirac-2023-cms-prep] / [@bouzinier-2026-springer-ch8]. Data
  quality has shifted over time; future refresh would require an
  authorized rerun against a newer extract.
- [ ] **MEDPAR id/birth_date errors only.** Modeled errors are limited
  to two fields. Sex/race nulling, claim-date misencoding, etc. are not
  injected. The error-field set (`["id", "birth_date"]`) is hard-coded
  in [`synthmed.errors`](src/synthmed/errors.py), not configurable via
  the CSV.
- [ ] **50/50 id/DOB split is hard-coded, not declared.** The CSV's
  `Error Rate` is the *combined* probability and is split evenly inside
  the code (`n_fields = 2`). Self-describing alternative: replace the
  single rate with per-field columns in the CSV.
- [ ] **Static across years.** A single rate is applied to every cohort
  year, although real Medicare data quality has improved over the
  2011–2016 window.
- [ ] **Cross-field independence.** A single row cannot have both `id`
  and `birth_date` nulled by the current mechanism (the bands are
  disjoint). Real missingness can co-occur.
- [ ] **Admission/discharge dates not sequential.** They are drawn
  independently within a year, so admission may post-date discharge.
  Also causes rare duplicate `(BENE_ID, ADM, DIS)` triples (~1 in 15k).

## Sample data downloader

See [`docs/distributions/medicare_sample_data.md`](docs/distributions/medicare_sample_data.md)
and [`src/synthmed/samples.py`](src/synthmed/samples.py).

- [ ] **CMS URL stability.** The `/research-statistics-data-and-systems/.../synpufs/downloads/`
  path has moved at least twice historically. When it rots, update
  `_INPATIENT_URL` / `_BENEFICIARY_URL` in `samples.py` and add an
  optional mirror field per sample.
- [ ] **No resumable downloads.** Stdlib `urllib.request` is used; a
  partial download is dropped and retried from scratch. Acceptable for
  one-time-per-machine work; if it becomes annoying, swap to
  `requests` + `Range` headers.
- [ ] **No parallel downloads.** All 40 sample ZIPs (20 inpatient + 20
  beneficiary summary) are pulled sequentially. Trivial to parallelize
  with `concurrent.futures.ThreadPoolExecutor` if first-run latency
  becomes a complaint.
- [ ] **No progress bar.** Plain `logging.info` is emitted per file.
  `rich.progress` or `tqdm` would be friendlier but adds a dep.

## MIMIC-IV / PhysioNet integration (deferred branch)

A potential second source of distribution data is the MIT Laboratory
for Computational Physiology **MIMIC-IV** database hosted on
PhysioNet (currently
[v2.2](https://physionet.org/content/mimiciv/2.2/)). It would let us
ground several of the currently approximate / distorted tables
(diagnosis frequencies, sequential within-patient patterns,
length-of-stay, hospital-utilization × demographics) against a real
ICU + inpatient cohort, rather than the limited DE-SynPUF subset.
Important constraints that make this a separate branch of work rather
than a quick win:

- [ ] **Access requires a free PhysioNet credentialing course
  (~40 min, MIT-offered).** Anyone contributing to this branch needs
  to complete it; existing contributors who haven't, can't pull the
  data. This is a real onboarding tax for software-engineer
  contributors who don't otherwise need clinical-data training.
- [ ] **License constraint propagates downstream.** Per the
  PhysioNet Credentialed Health Data License, any model or dataset
  *derived from* MIMIC-IV can only be redistributed back through
  PhysioNet — not Zenodo, not GitHub release artifacts, not the open
  Apache-2.0 channel this repo uses. Distributions baked from MIMIC
  cannot be commingled with the open distribution set without
  tainting the whole package.
- [ ] **Implies a two-variant split.** A MIMIC-aware variant (output
  destination: PhysioNet) and a MIMIC-free variant (current behavior,
  open Apache-2.0 publication via Zenodo). Three sensible
  architectural patterns to evaluate when this becomes active:
  1. **Long-lived `mimic` git branch** that diverges only in its
     `inputs/distributions/` content + a few loader paths. Cleanest
     license boundary; ongoing merge cost from `main` to keep parity.
  2. **Extension package** (e.g. `synthmed-mimic`) that depends on
     `synthmed` and overrides specific `DistributionData` fields
     with MIMIC-derived values. Keeps the core repo
     license-uncontaminated; releases happen independently.
  3. **Config-driven single repo** with a
     `GenerationConfig.data_provenance` field gating which
     distributions get loaded; users acknowledge the PhysioNet
     licensing implications at config-construction time.
  None of these solves the *publication-destination* gate by itself —
  the license restriction is about where outputs land, not about how
  the code is organized — so any approach also needs to surface that
  constraint at output-write time.

## Per-year file emission

- [ ] **Fragile MEDPAR-last reordering.** `synthmed.year._reorder_medpar_last`
  reverses the FTS list iff MEDPAR happens to come first in
  `listdir()` order; otherwise it leaves the list alone. This works on
  every supported FTS layout but breaks silently if a future layout
  has MEDPAR neither first nor last (e.g. three MBSF + MEDPAR +
  another MBSF). A robust fix is a sort that pushes MEDPAR to the end
  while preserving MBSF relative order, but that would change reuse
  semantics on existing layouts and needs a comparison run before
  changing.

## Repo / packaging

- [ ] **Broader regression coverage.** Snapshot SHA-256 of each output
  `.dat` from a known-good run into a checked-in fixture; assert
  equality on subsequent runs. Catches accidental sampling-order
  changes that the existing reproducibility test would miss across
  refactors.
