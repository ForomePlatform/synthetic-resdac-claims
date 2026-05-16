# `state_error_medpar_rates.csv`

> Path: [`inputs/distributions/state_error_medpar_rates.csv`](../../inputs/distributions/state_error_medpar_rates.csv)

Per-state probabilities of injecting a missing-field error into a MEDPAR
record. Used by `synthmed` to simulate state-correlated data quality
variation observed in real CMS Medicare data.

## File format

```
SSA Code,Error Rate
1,0.01
2,0.01
...
53,0.01
```

- 53 rows, one per SSA state code (CMS / SSA state numbering, **not**
  FIPS). Includes codes 40 (Puerto Rico) and 48 (Virgin Islands), both
  at baseline.
- `SSA Code` is an integer (`1`..`53`); the loader and matching code in
  `synthmed.errors` cast via `int(state)` so leading-zero forms are not
  required.
- `Error Rate` is a probability in `[0, 1]`. All current values fall in
  `[0.01, 0.045]`.

## Current values

Baseline `0.01` (i.e. 1%) for almost every state. Seven states are
elevated:

| SSA Code | State          | Rate  |
|:--------:|:---------------|------:|
| 6        | Colorado       | 0.045 |
| 16       | Iowa           | 0.030 |
| 22       | Massachusetts  | 0.030 |
| 26       | Missouri       | 0.030 |
| 28       | Nebraska       | 0.025 |
| 35       | North Dakota   | 0.045 |
| 43       | South Dakota   | 0.030 |

(SSA → state name resolved via the NBER SSA-FIPS crosswalk; see
[`ssa_fips_state_county_2025.md`](ssa_fips_state_county_2025.md).)

The 1–5% range matches the description in the upstream
[ChilliPenguin/SynthMed](https://github.com/ChilliPenguin/SynthMed)
documentation.

## Provenance

The values are **approximate** — based on empirical observations made while
building the CMS data preparation pipeline described in:

- Audirac, M., **Bouzinier, M.**, Braun, D., Shad, M. M., & Yockel, S.
  (2023). *Systematic approach to preparing of medical claims data for
  biomedical research.* F1000Research.
  <https://doi.org/10.7490/f1000research.1119612.1>
  [@audirac-2023-cms-prep]
- *Forthcoming, 2026* — Chapter 8 of a SpringerBriefs in Computer
  Science volume (ISBN 978-3-032-21031-9, eBook
  978-3-032-21032-6, ISSN 2191-5768).
  <https://doi.org/10.1007/978-3-032-21032-6_8>
  [@bouzinier-2026-springer-ch8] — expands on the data quality findings
  used to derive these rates. (Cite the F1000Research item until the
  volume ships.)

The numbers in this file (a per-state
aggregate of BENE_ID and
birth_date null rates in MEDPAR records) are distorted and are the only
public form of
that measurement. Computing accurate values requires an authorized CMS
data agreement and rerunning the pipeline above.

## How `synthmed` uses it

Loaded once per run by
[`synthmed.distributions.load_distributions`](../../src/synthmed/distributions.py)
into `DistributionData.state_error_medpar`. Consumed in
[`synthmed.errors.generate_internal_medpar_errors`](../../src/synthmed/errors.py)
roughly as follows for each state:

1. Look up the state's rate `r`.
2. Draw `probs = uniform(0, 1)` for every MEDPAR row in that state.
3. **Split `r` in half** between two fields, `id` and `birth_date`:
   - rows with `probs ∈ [0, r/2)` have their `id` nulled (set to `" "`),
   - rows with `probs ∈ [r/2, r)` have their `birth_date` nulled.

So `Error Rate = 0.01` means **0.5% null `id` + 0.5% null `birth_date`**
in that state (not 1% of either field). The 50/50 split is hard-coded
in `errors.py` via `n_fields = len(["id", "birth_date"])`; the rate in
this file is the *combined* probability.

## Caveats and known simplifications

- **Only two fields are modeled.** Real CMS data quality issues touch
  many more columns (sex, race, dates of service, claim type, etc.).
  The error-field set is hard-coded in `errors.py`, not configurable
  via this file.
- **Constant across years.** A single static rate is applied to every
  cohort/year, although real-world data quality has improved over the
  2011–2016 window.
- **No claim-volume weighting.** A small-population state with 50 MEDPAR
  rows gets the same probability as a large state with 50k rows. For
  generation that's fine; for any future *calibration*, expect that real
  rates probably anti-correlate with state claim volume.
- **Cross-field independence.** A row's `id` and `birth_date` cannot
  both be nulled by this mechanism — the two error categories use
  disjoint probability bands. Real missingness can co-occur.
- **Hard-coded 50/50 split.** Moving the split into a per-field column
  in this CSV would make the file fully self-describing instead of
  half-implicit in code.

## References

See [`docs/references.bib`](../references.bib):
`@audirac-2023-cms-prep`, `@bouzinier-2026-springer-ch8`,
`@nber-ssa-fips-crosswalk-2025`.

## License

This file is part of `synthetic-resdac-claims` and is released under the
**Apache License, Version 2.0** — see the repo-root
[LICENSE](../../LICENSE).

## Change log

- **2026-05-16 — Provenance corrected.** Values were originally read as
  "hand-crafted placeholders"; in fact they are empirical, computed
  from a real (confidential) Medicare extract by M. Bouzinier in the
  course of the pipeline work cited above. Numbers themselves are
  unchanged.
- _Initial version_ — imported from the upstream
  [ChilliPenguin/SynthMed](https://github.com/ChilliPenguin/SynthMed)
  prototype as-is.
