# `diag1.csv`

> Path: [`inputs/distributions/diag1.csv`](../../inputs/distributions/diag1.csv)

Marginal frequency table of ICD-9 diagnosis codes appearing in the
primary-diagnosis position (`diag_1`) of Medicare inpatient
(MEDPAR-style) records. Intended as a sampling weight table for
filling individual `diag_k` columns when joint-distribution sampling
from CMS DE-SynPUF is not desired.

## File format

**Tab-separated** (not comma). Two columns:

```
diag1	share_of_total
V5789  	0.05758642690044660791
486    	0.02776530636357191805
0389   	0.02615846310168009641
...
```

- 4076 rows, one per distinct ICD-9 code.
- `diag1` column holds the **ICD-9 code right-padded with spaces to
  width 7**, matching the fixed-width FTS field for MEDPAR diagnosis
  columns (e.g. `486    `, `V5789  `, `0389   `). Loaders that want the
  bare code should `.str.strip()`.
- ICD-9 conventions are preserved: numeric codes (e.g. `486`,
  `0389`), V-codes (79 entries), and E-codes (55 entries).
- `share_of_total` is the probability that a sampled `diag_1` equals
  this code. The full column sums to 1.0.

## Current values

The distribution is heavy-tailed, consistent with Medicare inpatient
data:

| rank | code     | label (ICD-9)                          | share  |
|----:|:---------|:---------------------------------------|-------:|
| 1   | `V5789`  | Other specified aftercare              | 0.0576 |
| 2   | `486`    | Pneumonia, organism unspecified        | 0.0278 |
| 3   | `0389`   | Unspecified septicemia                 | 0.0262 |
| 4   | `5990`   | Urinary tract infection                | 0.0166 |
| 5   | `49121`  | Obstructive chronic bronchitis w/ exacerbation | 0.0157 |
| 6   | `5849`   | Acute kidney failure, unspecified      | 0.0148 |
| 7   | `42731`  | Atrial fibrillation                    | 0.0147 |
| 8   | `71536`  | Osteoarthrosis, lower leg              | 0.0135 |
| 9   | `43491`  | Cerebral artery occlusion w/ infarction | 0.0119 |
| 10  | `41071`  | Subendocardial infarction, initial episode | 0.0117 |

- Top 10 codes cover **~21%** of admissions.
- Top 100 codes cover **~51%** of admissions.
- Long tail of ~thousands of codes at the floor share (`~2.4e-5`,
  i.e. one-occurrence-in-the-source bins).

## Provenance

The values are **approximate** — derived from inspection of a real,
confidential CMS Medicare extract in the course of earlier pipeline
work — and **intentionally distorted** before being shipped here.

The distribution should be treated as **structurally plausible** — i.e.
the set of codes, the heavy-tailed shape, and the broad ranking of the
most-common diagnoses are recognizable as Medicare inpatient data —
rather than as a faithful reproduction of any real Medicare quantile.
Reproducing accurate values requires an authorized CMS data agreement.

## How `synthmed` uses it

**Currently: loaded but not consumed.**
[`synthmed.distributions.load_distributions`](../../src/synthmed/distributions.py)
reads the file into `DistributionData.diag1`, but no active code path
samples from it. The original prototype contained a fallback in
[`synthmed.internal_db.generate_diagnosis`](../../src/synthmed/internal_db.py)
that *would have* used it, of the form:

```python
# (illustrative, currently commented out)
base.loc[base["number_of_diagnoses"] >= j, f"diag_{j}"] = random.choices(
    dist.diag1["diag1"], k=n, weights=dist.diag1["share_of_total"],
)
```

i.e. fill each `diag_j` column by independent draws from this marginal
table. The active path instead samples a full row from the CMS
DE-SynPUF inpatient sample so that `diag_1..diag_10` co-occur with
their original within-admission joint structure (at the cost of being
capped at 10 codes and limited to ICD-9 codes that appear in
DE-SynPUF).

### Two viable consumers — pick one

| consumer | code range | joint structure | ICD coverage | data freshness |
|---|---|---|---|---|
| **Active**: DE-SynPUF row sampling | `diag_1..diag_10` only | ✅ within-admission | DE-SynPUF subset, ICD-9 only | 2008–2010 |
| **Restored fallback**: `diag1.csv` marginal | `diag_1..diag_25` | ❌ independent per slot | Full ICD-9 set, ~4000 codes | distorted snapshot |
| **Hybrid (not implemented)** | `diag_1` from `diag1.csv`, rest from a conditional table | ✅ if conditional table exists | depends | depends |

See [TODO](../../TODO.md) for the open decision on whether to
deprecate this file, restore the fallback, or build a hybrid.

## Caveats and known simplifications

- **Loaded but unused.** Removing the loader call would shave the
  startup cost; doing so locks in the DE-SynPUF-only approach.
- **Marginal, not conditional.** Even when consumed, this table gives
  the *unconditional* primary-diagnosis frequency. It carries no
  information about diag-by-diag co-occurrence, age/sex/region
  dependencies, or the secondary-diagnosis distribution. The column
  name `diag1` is a hint that, conceptually, this is the
  primary-position distribution; using it for `diag_2..diag_25` is a
  blunt approximation.
- **Padding makes the column look like an ID.** Right-padding to width
  7 is necessary for downstream FTS-style fixed-width emission but
  trips up readers that auto-trim or treat the column as semantic.
  Suggested loader convention: store `.str.strip()` for sampling, but
  re-pad to width 7 when writing back into a MEDPAR row.
- **ICD-9 only.** Same constraint as the rest of the diagnosis pipeline
  (see [`number_of_diagnoses.md`](number_of_diagnoses.md) for the
  shared ICD-9 / cap-at-10 caveats).
- **Approximate + distorted** (see Provenance).

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
  prototype as-is. Values not modified. Loaded-but-unused status
  preserved pending an explicit decision (see TODO).
