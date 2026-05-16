# `zip2fips.csv`

> Path: [`inputs/distributions/zip2fips.csv`](../../inputs/distributions/zip2fips.csv)

ZIP → FIPS-county crosswalk for US ZIPs. Used by `synthmed` as the
first hop of the geographic chain that ultimately assigns each
synthetic beneficiary an SSA state/county code via
[`ssa_fips_state_county_2025.csv`](ssa_fips_state_county_2025.md).

## File format

Comma-separated, 5 columns, 41,877 rows (one per ZIP, **no duplicates**).

```
zipcode,county,state,state_code,FIPS
35004,St. Clair County,Alabama,AL,01115
35005,Jefferson County,Alabama,AL,01073
...
83414,Teton County,Wyoming,WY,56039
```

| Column      | Meaning                                                |
|:------------|:-------------------------------------------------------|
| `zipcode`   | 5-digit US ZIP (string with leading zeros preserved)   |
| `county`    | County name, suffixed with "County" / "Parish" / etc.  |
| `state`     | Full state name                                        |
| `state_code`| 2-letter state postal code                             |
| `FIPS`      | 5-digit FIPS state+county code (string, leading zeros) |

52 distinct `state_code` values (50 + DC + PR/territories). 3,217
distinct FIPS counties (~all US counties; the universe is ~3,143
mainland counties plus DC + territories).

## Provenance

Downloaded **verbatim** from
<https://github.com/clauswilke/zipcodes/blob/main/data/zip2fips.csv>
[@wilke-zipcodes-github]. License: **MIT** (compatible with this
repo's Apache-2.0 redistribution).

Upstream chain:

```
US Census Bureau + HUD (public domain)
    ↓
zipcodeR R package (Gavin Rozzi, CRAN) — MIT [@rozzi-zipcoder-cran]
    ↓ ZIP→FIPS join layer
clauswilke/zipcodes (GitHub) — MIT [@wilke-zipcodes-github]
    ↓ verbatim CSV
this file
```

**Two upstream caveats lifted directly from the source README:**

1. *"This is a work in progress, not all zip codes are correctly mapped
   yet."* Some ZIPs may map to the wrong FIPS county.
2. The clauswilke crosswalk is **1:1** (one FIPS per ZIP). Real ZIPs
   frequently span county boundaries; the HUD ZIP–County crosswalk
   handles this with a 1:N table plus weights. This file uses a single
   chosen FIPS per ZIP, which approximates the *modal* mapping.

**Data vintage is not stamped** in either the file or the upstream
README. Last-pull date when this file was imported into the repo is
not recorded; refreshing from upstream is a safe future move.

## How `synthmed` uses it

Loaded once per run by
[`synthmed.distributions._build_zip2fips2pop`](../../src/synthmed/distributions.py)
into `DistributionData.zip2fips`, projected to **only two columns**:
`zipcode` and `FIPS`. The `county`, `state`, `state_code` columns are
discarded at load time.

Consumed in two places:

1. **Inside `load_distributions`** — merged with the ZIP population
   weights derived from
   [`DECENNIALDHC2020.P1-Data.csv`](DECENNIALDHC2020.P1-Data.md)
   (sidecar pending) to produce `DistributionData.zip2fips2pop`, the
   population-weighted ZIP/FIPS sampling table.
2. **In [`synthmed.internal_db.generate_location`](../../src/synthmed/internal_db.py)** —
   `zip2fips2pop` is sampled with `replace=True, weights=POP` to assign
   each synthetic beneficiary a ZIP code. The matched FIPS is then
   left-joined to the SSA-FIPS crosswalk to produce
   `state_code` / `county_code`.

Loader call (uses correct `dtype` hints, unlike the SSA-FIPS loader —
see [TODO](../../TODO.md)):

```python
zip2fips = pd.read_csv(
    distribution_dir / "zip2fips.csv",
    dtype={"zipcode": str, "FIPS": str},
)[["zipcode", "FIPS"]]
```

## Caveats and known simplifications

- **One FIPS per ZIP.** Real ZIPs may overlap multiple counties; this
  file picks a single representative. Fixing this would require either
  the HUD 1:N crosswalk + weighted draws, or a documented choice rule
  (e.g. "FIPS with the largest population share of the ZIP"). The
  current downstream code assumes 1:1.
- **Upstream marked "work in progress".** Some ZIPs may map to the
  wrong FIPS county. No row-level confidence/quality marker is
  attached.
- **No vintage information.** The file content reflects a single pull
  from clauswilke/zipcodes at an unrecorded date. ZIPs are added
  (and rarely removed) by USPS; FIPS county boundaries change too
  (see CT note below). A periodic refresh procedure would help, but
  isn't automated.
- **Connecticut uses legacy FIPS only.** All CT rows here use the 8
  legacy county FIPS (`09001..09015`); none use the 9 new planning
  regions (`09110..09190`). This is *consistent* with the legacy-CT
  rows in
  [`ssa_fips_state_county_2025.csv`](ssa_fips_state_county_2025.md),
  so the ZIP → FIPS → SSA chain works for CT through legacy codes.
  Real MEDPAR extracts from 2024+ may use the new planning regions,
  in which case this file would need refreshing
  ([@census-2022-ct-change]).
- **Three of five columns loaded but discarded.** `usecols=["zipcode",
  "FIPS"]` would shave a tiny amount of load time; current cost is
  small (~1.7 MB file).
- **No US territories beyond what zipcodeR covers.** Guam, American
  Samoa, Northern Mariana Islands etc. ZIPs may be incomplete or
  absent; corresponding SSA codes (`63xxx`, `64xxx`, `65xxx`) in the
  SSA-FIPS crosswalk would therefore be unreachable through this
  chain.

## References

See [`docs/references.bib`](../references.bib):
`@wilke-zipcodes-github`, `@rozzi-zipcoder-cran`,
`@census-2022-ct-change`.

## License

The file content is a derivative work of public-domain US Census +
HUD data, passed through two MIT-licensed open source projects
(`zipcodeR` and `clauswilke/zipcodes`). Redistributed here under the
repo's **Apache License, Version 2.0** — see the repo-root
[LICENSE](../../LICENSE). MIT attribution preserved via the
`@wilke-zipcodes-github` and `@rozzi-zipcoder-cran` BibTeX entries.

## Change log

- _Initial version_ — imported from the upstream
  [ChilliPenguin/SynthMed](https://github.com/ChilliPenguin/SynthMed)
  prototype as-is. File content matches the clauswilke/zipcodes
  snapshot at an unrecorded date; not modified.
