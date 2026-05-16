# `number_of_diagnoses.csv`

> Path: [`inputs/distributions/number_of_diagnoses.csv`](../../inputs/distributions/number_of_diagnoses.csv)

Marginal distribution of the *count* of ICD diagnosis codes attached to
a single MEDPAR record. Used by `synthmed` to populate each synthetic
beneficiary's `number_of_diagnoses` column.

## File format

**Tab-separated** (not comma). Two columns:

```
number of diagnoses	share_of_rows
1	0.01001914033885488788
2	0.01221673479997164394
...
25	0.05300219759446111676
```

- 25 rows, one per integer diagnosis count `k = 1..25`.
- `share_of_rows` is the probability that an admission record carries
  exactly `k` diagnoses. The full column sums to 1.0.
- `25` is the ResDAC maximum for MEDPAR diagnosis columns; the
  last-row share is therefore the **accumulated right tail** (any
  real admission with `≥ 25` diagnoses collapses into this bin).

## Current values

Plotted as a histogram the distribution is **not monotonic** — it has
two visible artifacts worth knowing about:

| `k` | share  | note                          |
|----:|-------:|:------------------------------|
| 1   | 0.010  |                               |
| ... |        | gradual climb                 |
| 9   | 0.0949 | **peak** (DE-SynPUF cap at 10) |
| 10  | 0.0584 | drop after the cap            |
| 11–13 | ~0.057 each | plateau                |
| 18  | 0.0528 | **secondary bump**            |
| 25  | 0.0530 | **right-tail accumulation**   |

The `k=9` peak is consistent with the
[CMS DE-SynPUF Inpatient Claims sample](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf/de10-sample-1)
only exposing `ICD9_DGNS_CD_1..10`; the `k=25` spike is the right-tail
cap. The `k=18` bump has no obvious technical explanation and is
plausibly a distortion artifact (see Provenance).

## Provenance

The values are **approximate** — derived from inspection of a real,
confidential CMS Medicare extract in the course of
earlier pipeline work — and **intentionally distorted** before being
shipped here.

The distribution should be treated as **structurally plausible** — i.e.
it covers `k = 1..25`, sums to 1.0, and produces a non-trivial spread of
diagnosis counts when sampled — rather than as a faithful reproduction
of any real Medicare quantile. Reproducing accurate values requires
an authorized CMS data agreement.

## How `synthmed` uses it

Loaded once per run by
[`synthmed.distributions.load_distributions`](../../src/synthmed/distributions.py)
into `DistributionData.num_diag` and consumed in
[`synthmed.internal_db.generate_diagnosis`](../../src/synthmed/internal_db.py)
via `random.choices(num_diag["number of diagnoses"], weights=num_diag["share_of_rows"])`
to set the `number_of_diagnoses` column on each MEDPAR row.

**Important:** the sampled `number_of_diagnoses` value is *not* used to
truncate the actual `diag_1..diag_25` columns. Those columns are filled
as follows regardless of `number_of_diagnoses`:

- `diag_1..diag_10` — copied from a sampled DE-SynPUF inpatient row
  (`ICD9_DGNS_CD_1..10`).
- `diag_11..diag_25` — left blank (`" "`).

So a synthetic record with `number_of_diagnoses = 3` may still carry
populated `diag_4..diag_10`. This is a known simplification; see
[Caveats](#caveats-and-known-simplifications) below.

> Pavel's original prototype docs list this file as "Currently not in
> use". That note was stale: the package does use it (to set the
> column value), but the disconnect with column-filling means it has
> no effect on which diagnoses appear, only on the integer in the
> `number_of_diagnoses` column.

## Caveats and known simplifications

- **`number_of_diagnoses` value is not enforced on `diag_k` columns.**
  Truncating `diag_(number_of_diagnoses+1)..diag_25` to blank would
  match real claims and is a near-free fix.
- **Bimodal / spike shape is partly artificial.** The `k=18` bump and
  the `k=25` right-tail spike reflect distortion + capping, not a real
  observed mode. Anyone using this file to *study* diagnosis-count
  distributions should look elsewhere (HCUP/AHRQ inpatient stay
  summaries publish real distributions; not cited here because we
  don't fit ours to them).
- **No conditioning on demographics, year, geography, or facility
  type.** Number of diagnoses in reality correlates strongly with
  comorbidity burden and admission type.
- **`k = 0` is not representable.** Every MEDPAR row gets at least one
  diagnosis. In real data, MEDPAR records with no primary diagnosis
  exist but are rare.
- **Tab-separated, with a space in the column header.** Loaders must
  pass `delimiter="\t"` and quote `"number of diagnoses"`. Considered
  fragile; switching to a comma-separated, snake_case header would be
  cheap, but breaks the upstream reader without coordination.

## References

No external references for this specific table. See
[`docs/references.bib`](../references.bib) for repo-wide citations.

## License

This file is part of `synthetic-resdac-claims` and is released under the
**Apache License, Version 2.0** — see the repo-root
[LICENSE](../../LICENSE).

## Change log

- _Initial version_ — imported from the upstream
  [ChilliPenguin/SynthMed](https://github.com/ChilliPenguin/SynthMed)
  prototype as-is. Values not modified.
