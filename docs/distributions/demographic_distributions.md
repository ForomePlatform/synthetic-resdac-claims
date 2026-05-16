# `demographic_distributions.json`

> Path: [`inputs/distributions/demographic_distributions.json`](../../inputs/distributions/demographic_distributions.json)

Sampling weights used to draw a synthetic beneficiary's **race** and
**sex** when building the internal cohort.

## File format

```json
{
  "race": { "values":  [0, 1, 2, 3, 4, 5, 6],
            "weights": [0.002, 0.787, 0.087, 0.008, 0.038, 0.073, 0.005] },
  "sex":  { "values":  [0, 1, 2],
            "weights": [0.001, 0.445, 0.554] }
}
```

For each variable, `values[i]` is sampled with probability `weights[i]`.
Weights sum to 1.0 in both groups.

## Code interpretation

The integer codes are **ResDAC variable codes** (not arbitrary labels);
they are written as-is to the corresponding FTS column.

### `race` — [`RTI_RACE_CD` / `BENE_RACE_CD`](https://resdac.org/cms-data/variables/race-beneficiary) [@resdac-rti-race-cd]

| Code | Label                 | Weight |
|:----:|:----------------------|-------:|
| 0    | Unknown               | 0.002  |
| 1    | White                 | 0.787  |
| 2    | Black                 | 0.087  |
| 3    | Other                 | 0.008  |
| 4    | Asian                 | 0.038  |
| 5    | Hispanic              | 0.073  |
| 6    | North American Native | 0.005  |

### `sex` — [`BENE_SEX_IDENT_CD`](https://resdac.org/cms-data/variables/sex-code) [@resdac-sex-cd]

| Code | Label   | Weight |
|:----:|:--------|-------:|
| 0    | Unknown | 0.001  |
| 1    | Male    | 0.445  |
| 2    | Female  | 0.554  |

## Provenance

The weights target the population represented by the cohort FTS files in
this repo (years 2011–2016, FFS Medicare). A mid-cohort year (2012) was
chosen for the published-table anchor.

### Race (RTI-coded)

Derived from the KFF chartpack
[*Profile of Medicare Beneficiaries by Race and Ethnicity*](https://files.kff.org/attachment/chartpack-profile-of-medicare-beneficiaries-by-race-and-ethnicity-a-chartpack)
[@kff-2016-chartpack] (March 2016, KFF analysis of Current Population
Survey data, 2012).
KFF's published shares for the Medicare population (which sum to >100%
because Hispanic respondents may also report a race):

| KFF category         | KFF % (2012) |
|:---------------------|-------------:|
| White, non-Hispanic  | 79.3%        |
| Black                | 8.8%         |
| Hispanic             | 7.3%         |
| Asian                | 3.8%         |
| Other races          | 1.5%         |

Mapped onto the seven mutually-exclusive RTI codes:

- **Hispanic (code 5)** takes the KFF Hispanic share (7.3% → `0.073`).
- **White / Black / Asian (codes 1, 2, 4)** take the KFF non-Hispanic
  shares (renormalized: `0.787 / 0.087 / 0.038`).
- KFF's `Other races` (1.5%) is split into RTI **Other (code 3)** and
  **North American Native (code 6)**. KFF does not report AI/AN
  separately because of small CPS sample sizes; we use the rough split
  `0.008 / 0.005` (Other / AI/AN) informed by national AI/AN-elder
  share estimates (~0.5–0.7% of the 65+ population).
- **Unknown (code 0)** is set to `0.002`. The RTI algorithm
  ([Eicheldinger & Bonito 2008, *Health Care Financing Review*](https://www.cms.gov/Research-Statistics-Data-and-Systems/Research/HealthCareFinancingReview/downloads/08springpg27.pdf)
  [@eicheldinger-2008-rti-race]) cuts Medicare's `Unknown` race rate to
  well under 1% by re-coding
  beneficiaries based on first/last name, place of birth, and language.
  Picking a small non-zero value preserves an Unknown stratum for
  downstream consumers without overstating it.

Weights renormalized so the total is exactly 1.0.

### Sex

Derived from the
[Chronic Conditions Data Warehouse (CCW) Medicare Enrollment Charts](https://www2.ccwdata.org/web/guest/medicare-charts/medicare-enrollment-charts)
[@ccw-medicare-enrollment-charts] and
[KFF *Distribution of Medicare Beneficiaries by Sex*](https://www.kff.org/medicare/state-indicator/medicare-beneficiaries-by-sex/)
[@kff-medicare-sex-state-indicator], both of which give ~55.4% female /
~44.5% male for the 2012–2015 window
with `Unknown` essentially zero in Medicare enrollment data
(`BENE_SEX_IDENT_CD = 0` is rare because sex is collected during SSA
enrollment).

`0.001` is used for `Unknown` for the same reason as race: keep a small
non-zero stratum without overstating it.

## Caveats and known simplifications

- **No conditioning on year or geography.** A single static distribution
  is sampled for every cohort/year. In reality the Medicare population
  has been growing more diverse year over year (e.g. the Hispanic share
  rose from ~7% in 2012 toward ~9% by 2020). If we ever need year-aware
  weights, switch to a per-year file (or a script that interpolates from
  CMS Medicare Enrollment Dashboard tabulations).
- **No conditioning on age.** Race/ethnicity composition skews younger
  among Medicare *new enrollees* than among the full population. This
  matters most in
  [`synthmed.internal_db.increment_internal_database`](../../src/synthmed/internal_db.py),
  where the new 65-year-olds added each year are drawn from the same
  weights as the prevalent cohort.
- **No race × sex joint distribution.** Sex is sampled independently of
  race; real Medicare data shows a slightly higher female share among
  Black beneficiaries and a lower one among Asian beneficiaries.
- **RTI Other vs. AI/AN split is an estimate.** KFF does not publish
  AI/AN separately, so the `0.008 / 0.005` split is best-effort. CMS
  Office of Minority Health tabulations would give a tighter number if
  this becomes load-bearing.
- **Unknown rates are floor values.** Real RTI-coded extracts have
  near-zero unknown for sex and small but non-zero unknown for race;
  the picked `0.001 / 0.002` are conservative floor values.

If weights need to be regenerated from a different source (e.g. a CMS
Medicare Enrollment Dashboard download for a specific year), prefer
adding a checked-in `scripts/derive_demographic_distributions.py` so
the derivation is reproducible, rather than hand-editing the JSON.

## How `synthmed` uses it

Loaded once per run by
[`synthmed.distributions.load_distributions`](../../src/synthmed/distributions.py)
into `DistributionData.demographic`. Sampled in
[`synthmed.internal_db.generate_demographic`](../../src/synthmed/internal_db.py)
via `random.choices` to fill the `race` and `sex` columns of the
internal cohort. Those columns then populate any FTS column whose long
description contains "race" or "sex" (see
[`synthmed.columns.char_generation`](../../src/synthmed/columns.py)).

## References

Citation keys above resolve against
[`docs/references.bib`](../references.bib):
`@kff-2016-chartpack`, `@eicheldinger-2008-rti-race`,
`@ccw-medicare-enrollment-charts`, `@kff-medicare-sex-state-indicator`,
`@resdac-rti-race-cd`, `@resdac-sex-cd`.

## License

This file is part of `synthetic-resdac-claims` and is released under the
**Apache License, Version 2.0** — see the repo-root
[LICENSE](../../LICENSE).

The Census/CPS data used by the KFF chartpack is public-domain US
Government work. ResDAC variable definitions linked above are
referenced for interpretability only and remain the property of CMS /
ResDAC.

## Change log

- **2026-05-16 — Weights re-derived from cited sources.**
  Sex changed from symmetric `0.45/0.45/0.10` to KFF/CCW-based
  `0.445/0.554/0.001`. Race changed from a US-general approximation
  (Hispanic 19.1%) to a Medicare-population RTI distribution
  (Hispanic 7.3%, White 78.7%, …) anchored on KFF 2012 + RTI 2008
  methodology. The original values are preserved in git history.
- _Initial version_ — imported from the upstream
  [ChilliPenguin/SynthMed](https://github.com/ChilliPenguin/SynthMed)
  prototype as-is.
