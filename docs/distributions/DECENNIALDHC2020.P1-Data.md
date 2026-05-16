# `DECENNIALDHC2020.P1-Data.csv`

> Path: [`inputs/distributions/DECENNIALDHC2020.P1-Data.csv`](../../inputs/distributions/DECENNIALDHC2020.P1-Data.csv)

Per-ZCTA total population from the **2020 US Decennial Census,
Demographic and Housing Characteristics (DHC) file, Table P1, variable
`P1_001N` (Total Population)**. `synthmed` uses it to weight ZIP
sampling so that synthetic beneficiaries land in geographies roughly
proportional to where Americans actually live.

## File format

Comma-separated, UTF-8 **with BOM**, 33,774 data rows. The export from
`data.census.gov` includes two artifacts to ignore on load:

```
"GEO_ID","NAME","P1_001N","Tota",
"860Z200US00601","ZCTA5 00601","17242",
"860Z200US00602","ZCTA5 00602","37548",
...
"860Z200US99929","ZCTA5 99929","2079",
```

| Column     | Meaning                                                                |
|:-----------|:-----------------------------------------------------------------------|
| `GEO_ID`   | Census geographic identifier; for ZCTAs it is `860Z200US<ZCTA5>`. Chars 9+ are the 5-digit ZCTA code. |
| `NAME`     | Human-readable label, e.g. `ZCTA5 00601`.                              |
| `P1_001N`  | Total population in the ZCTA (integer).                                |
| `Tota`     | **Truncated column header**, all values empty. Likely the export of "Total Population" was cut to 4 chars by the data.census.gov form. |
| *(unnamed)*| Trailing comma in the file produces an empty unnamed column. Ignored. |

**Sanity check:** `sum(P1_001N) = 334,726,586`, somewhat above the
2020 US-resident total of 331,449,281 because ZCTA rows include Puerto
Rico and US territories.

## Provenance

Downloaded **verbatim** from
<https://data.census.gov/table/DECENNIALDHC2020.P1?q=population&g=010XX00US$8600000>
[@census-2020-dhc-p1]. The `010XX00US$8600000` query parameter selects
the **ZIP Code Tabulation Area** summary level for all US ZCTAs.

The 2020 Decennial Census DHC file was released in 2023 (DHC supersedes
the earlier Summary File 1/2 products for the 2020 cycle).

License: **U.S. Government public-domain work** — no restrictions on
redistribution.

## How `synthmed` uses it

Loaded once per run by
[`synthmed.distributions._build_zip2fips2pop`](../../src/synthmed/distributions.py)
with two derived columns:

```python
zip2pop = pd.read_csv(distribution_dir / "DECENNIALDHC2020.P1-Data.csv")
zip2pop["ZIP"] = zip2pop["GEO_ID"].str.slice(9)        # '00601'
zip2pop["POP"] = zip2pop["P1_001N"] / zip2pop["P1_001N"].sum()
zip2pop = zip2pop[["ZIP", "POP"]]
```

`POP` is therefore a **per-ZCTA population share** that sums to 1.0
across the file. It is then merged with
[`zip2fips.csv`](zip2fips.md) (a clauswilke/zipcodes ZIP→FIPS
crosswalk) on `ZIP == zipcode`:

- ZCTAs present in `zip2fips.csv` keep their population share.
- ZCTAs missing from `zip2fips.csv` (different vintage / coverage)
  get a flat redistribution of the residual probability mass:
  ```python
  leftover = (1 - zip2fips2pop["POP"].sum()) / missing.sum()
  zip2fips2pop.loc[missing, "POP"] = leftover
  ```

The resulting `zip2fips2pop` is sampled by
[`synthmed.internal_db.generate_location`](../../src/synthmed/internal_db.py)
with `replace=True, weights=POP` to assign each synthetic beneficiary a
ZIP code (whose FIPS / SSA codes are then carried through).

## Caveats and known simplifications

- **ZCTA ≠ ZIP.** ZCTAs are tabulation areas built from census blocks
  to approximate USPS ZIPs. They are not identical:
  - P.O.-box-only ZIPs typically have **no ZCTA** and so contribute
    zero population weight here.
  - Some ZIPs are split across multiple ZCTAs, and vice versa.
  - ZCTA boundaries are decennial; USPS ZIPs change continuously.
  Using ZCTA population as a stand-in for ZIP population is the
  standard practice but is a known approximation.
- **2020 snapshot.** The file reflects April 1, 2020 enumeration.
  By the time `synthmed` generates cohorts (the FTS schemas in this
  repo span 2011–2016), this is *forward-looking* relative to the
  data; for any future cohort year past ~2020 it becomes *backward*-
  looking. Either way it does not match the cohort year exactly.
  Switching to ACS 5-year estimates would let us match a cohort year
  more closely, at the cost of higher uncertainty per ZCTA.
- **Header glitch.** The fourth column header is truncated to `Tota`
  with all values blank, and the file ends each line with a trailing
  comma, adding an empty unnamed column. Loader is robust to both.
- **BOM byte present.** UTF-8 with BOM (`﻿`). `pandas.read_csv`
  handles it transparently; strict readers that don't auto-detect
  may need `encoding="utf-8-sig"`.
- **Loader normalizes across the full file**, not across only the
  ZIPs the rest of the pipeline can use. ZCTAs with no matching FIPS
  in [`zip2fips.csv`](zip2fips.md) contribute to the
  denominator of `POP` but never get sampled, so a small fraction of
  the probability mass is lost. The "flat redistribution" of leftover
  mass over unmatched ZCTAs compensates approximately, not exactly.
- **No urban/rural / age / income conditioning.** Population is the
  only weight; in real Medicare, beneficiary density anti-correlates
  with under-65 share, so this slightly under-weights areas with
  younger populations as a fraction of *Medicare* members. Acceptable
  for synthetic generation.
- **3 of 5 columns loaded but discarded.** `usecols=["GEO_ID",
  "P1_001N"]` would be a tiny optimization.

## References

See [`docs/references.bib`](../references.bib):
`@census-2020-dhc-p1`.

## License

The file content is a verbatim US Census export, public-domain US
Government work. Redistributed here under the repo's
**Apache License, Version 2.0** — see the repo-root
[LICENSE](../../LICENSE).

## Change log

- _Initial version_ — imported from the upstream
  [ChilliPenguin/SynthMed](https://github.com/ChilliPenguin/SynthMed)
  prototype as-is. File content matches the data.census.gov export
  byte-for-byte; not modified.
