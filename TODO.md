# TODO

A running list of known **simplifications, approximations, and bugs**
in `synthmed`. Anything documented as a caveat in a sidecar should also
be reflected here, with a one-line summary and a link back to the
detailed write-up.

Entries are grouped by area, then ordered by severity (highest first).
Use `[x]` to mark resolved items; keep them in place for a release or
two as a change record, then prune.

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

- [x] ~~`number_of_diagnoses` value is not enforced on `diag_k` columns
  and the count column is itself dead.~~ **Resolved 2026-05-19** by
  dropping `number_of_diagnoses.csv` end-to-end. Investigation showed
  the loaded distribution populated a `number_of_diagnoses` column on
  the in-memory cohort that no downstream code path ever read, and the
  FTS slots that should have carried the count (`DGNS_CD_CNT`,
  `POA_DGNS_CD_CNT`, `DGNS_E_CD_CNT`, `POA_DGNS_E_CD_CNT`) fell through
  to the default uniform-random `NUM` generator. A future fix is to
  add a `DGNSCNT`/`DGNS_CD_CNT` override in
  [`synthmed.columns.number_generation`](src/synthmed/columns.py) that
  emits `min(k, n_filled_diags)` so the count matches the actual
  populated `diag_k` slots.
- [ ] **No joint distribution across admissions.** `diag_1..diag_25` for
  one admission are drawn jointly from a single CMS DE-SynPUF row, but
  a patient's subsequent admissions are independent of their prior
  ones. Real claims data show strong sequential / chronic-condition
  patterns. Implementation sketch: tag each beneficiary in the internal
  cohort with a latent chronic-condition state, then condition each
  admission's diag draw on that state. Extension to **multi-year**
  trajectories (state persists across `increment_internal_database`
  calls) is the natural next step. **Privacy constraint:** deriving the
  joint table from a real confidential CMS extract carries
  re-identification risk (rare pairs of specific illnesses can be
  near-identifying); any data-derived table must go through
  documented anti-leakage noise before being shipped, matching the
  pattern already used for [[state_error_medpar_rates.csv]].
- [ ] **ICD-9 only; only 10 codes used per admission.** DE-SynPUF only
  exposes ICD-9 and only `ICD9_DGNS_CD_1..10`; columns `diag_11..diag_25`
  in the internal cohort are left as blank space. Modern Medicare uses
  ICD-10 and ~56% of admissions exceed 10 diagnoses.
- [ ] **No conditioning on demographics or region.** Diagnosis draws
  ignore age, sex, race, and geography of the synthetic beneficiary.
  **Privacy constraint:** the same re-identification risk as for the
  joint-across-admissions item applies — any data-derived
  age/sex/region × diagnosis table must be passed through documented
  anti-leakage noise before publication.
- [x] ~~`diag1.csv` consumer decision is open.~~ **Resolved 2026-05-19**
  by dropping the file: diagnosis sampling uses CMS DE-SynPUF rows
  exclusively (`diag_1..diag_10` with within-admission joint structure).
  The 4076-row primary-dx marginal frequency table and its loader call
  have been removed from `synthmed.distributions`.

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

- [x] ~~Latent loader bug — typo in `dtype` argument (`ssac_ode` →
  `ssa_code`).~~ Fixed 2026-05-16. The 9 CT-planning-region rows with
  empty `ssa_code` (introduced in NBER's 2025 vintage) were forcing
  `float64` inference and losing leading zeros, which would break
  `ssa_code.str.slice(0, 2)` in `generate_location`. Sidecar updated.
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

- [x] ~~No "orphan" admissions — cross-table consistency too tight.~~
  **Fixed 2026-05-17** by adding `GenerationConfig.orphan_admission_rate`
  (default `0.01`) and a new helper
  [`synthmed.medpar._inject_orphan_ids`](src/synthmed/medpar.py) that
  replaces BENE_ID on a small fraction of MEDPAR rows with fresh,
  unseen IDs (same 12+3-char format as cohort IDs). Those admissions
  no longer match any MBSF row, producing exactly the orphan pattern
  dorieh's `medicare.qc_admissions` materialized view expects.
  *Surfaced by the 5 M-run dashboard verification: the
  "Medicare QC (Clean)" Superset dashboard broke on zero orphans;
  with the fix in place the count is small-but-positive as expected.*
  Follow-ups:
  - [ ] Calibrate the 1% default against an empirical real-data
    measurement (same authorization caveat as for
    `state_error_medpar_rates.csv`).
  - [ ] Optional: extend to per-state orphan rates, mirroring the
    state-correlated structure of the existing MEDPAR error
    table.
- [ ] **DOB discrepancy distribution drift.** *Minor finding 2026-05-17
  from the dashboard comparison; specifics TBD.* The injected DOB
  errors render in the dashboard but the shape or magnitude appears
  slightly off vs. real-data patterns. M.~Bouzinier to expand with the
  concrete delta when convenient.
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

## Data quality / provenance

- [x] ~~DE-SynPUF sample is ~320 MB.~~ Now lazy-downloaded by
  [`synthmed.samples.ensure_samples`](src/synthmed/samples.py) into
  `inputs/samples/` (gitignored). SHA-256 manifest pinned; CMS URLs
  are the source. Sidecar:
  [`docs/distributions/medicare_sample_data.md`](docs/distributions/medicare_sample_data.md).
  Follow-ups under "Sample data downloader" below.
- [x] All seven distribution-file sidecars complete (2026-05-16).

## Sample data downloader

See [`docs/distributions/medicare_sample_data.md`](docs/distributions/medicare_sample_data.md)
and [`src/synthmed/samples.py`](src/synthmed/samples.py).

- [ ] **CMS URL stability.** The `/research-statistics-data-and-systems/.../synpufs/downloads/`
  path has moved at least twice historically. When it rots, update
  `_URL_PATTERN` in `samples.py` and add an optional mirror field per
  sample.
- [ ] **No resumable downloads.** Stdlib `urllib.request` is used; a
  partial download is dropped and retried from scratch. Acceptable for
  one-time-per-machine work; if it becomes annoying, swap to
  `requests` + `Range` headers.
- [ ] **No parallel downloads.** All 20 ZIPs are pulled sequentially.
  Trivial to parallelize with `concurrent.futures.ThreadPoolExecutor`
  if first-run latency becomes a complaint.
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

- [x] ~~No tests yet.~~ Two smoke tests under `tests/test_smoke.py`
  cover pipeline completion (100 patients, fixed seed, asserts FTS↔DAT
  pairing + non-empty outputs + row counts in plausible bands) and
  bit-for-bit reproducibility across two seeded runs.
- [ ] **Broader regression coverage.** Snapshot SHA-256 of each output
  `.dat` from a known-good run into a checked-in fixture; assert
  equality on subsequent runs. Catches accidental sampling-order
  changes that the existing reproducibility test would miss across
  refactors.
- [ ] `dorieh` is listed as a PyPI dependency in `pyproject.toml`; if
  the published package name differs, the spec needs to switch to a
  direct VCS reference.
