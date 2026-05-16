# `ssa_fips_state_county_2025.csv`

> Path: [`inputs/distributions/ssa_fips_state_county_2025.csv`](../../inputs/distributions/ssa_fips_state_county_2025.csv)

County-level crosswalk between **FIPS** state/county codes and **SSA**
state/county codes, plus CBSA labels and state/county names. Used by
`synthmed` to translate FIPS-coded geographic data into the SSA codes
that MEDPAR and MBSF files use for `state_code` and `county_code`
columns.

## File format

Comma-separated, 8 columns, 3283 data rows.

```
fipscounty,countyname_fips,state,cbsa_code,cbsa_name,ssa_code,state_name,countyname_rate
02013,ALEUTIANS EAST,AK,,,02013,ALASKA,ALEUTIANS EAST
02016,ALEUTIANS WEST,AK,,,02013,ALASKA,ALEUTIANS EAST
...
```

| Column           | Meaning                                                                |
|:-----------------|:-----------------------------------------------------------------------|
| `fipscounty`     | 5-digit FIPS state+county code (leading zeros, e.g. `02013`)           |
| `countyname_fips`| County name as published in the FIPS source                            |
| `state`          | 2-letter state postal code                                             |
| `cbsa_code`      | 5-digit Core-Based Statistical Area code (empty for non-metro counties)|
| `cbsa_name`      | CBSA name (empty for non-metro counties)                               |
| `ssa_code`       | 5-digit SSA state+county code (leading zeros for states 01-09)         |
| `state_name`     | Full state name (uppercase)                                            |
| `countyname_rate`| County name as used in CMS ratebook                                    |

53 distinct `state` codes (50 + DC + PR + a US territories sample). SSA
state prefixes seen: `01..53`, `63` (American Samoa), `64` (Northern
Mariana Islands), `65` (Guam).

**Rows with empty fields:** 34 rows have empty `fipscounty`; 9 rows have
empty `ssa_code`. The empties are not noise — they reflect a real
asymmetry between the two coding systems documented below.

## Provenance

Downloaded **verbatim** from NBER's per-year crosswalk archive:
<https://data.nber.org/ssa-fips-state-county-crosswalk/2025/ssa_fips_state_county_2025.csv>
(landing page:
<https://www.nber.org/research/data/ssa-federal-information-processing-series-fips-state-and-county-crosswalk>)
[@nber-ssa-fips-crosswalk-2025].

NBER's 2025 file is **not a single CMS download** — it's a join. CMS
dropped SSA codes from the IPPS Final Rule's FIPS↔CBSA crosswalk
starting in FY 2022, so NBER builds each post-2022 file by combining:

- the **CMS IPPS Final Rule** FIPS↔CBSA crosswalk
  [@cms-ipps-final-rule], and
- the **CMS Medicare Advantage Ratebook**, which still publishes SSA
  codes and county names.

The 2025 file also reflects the **Connecticut transition** from 8
legacy counties to 9 planning regions as county-equivalents (Federal
Register notice, June 2022; Census implementation by 2024)
[@census-2022-ct-change]. That is why some Connecticut rows have an
SSA code but no FIPS county, and the new CT planning-region FIPS codes
(starting with `09`, e.g. `09110 = Capitol`) have no SSA code yet.

## How `synthmed` uses it

Loaded once per run by
[`synthmed.distributions._build_zip2fips2pop`](../../src/synthmed/distributions.py)
into `DistributionData.fip2ssa`, projected to **only two columns**:
`fipscounty` and `ssa_code`. The other six columns are discarded at
load time.

Consumed in
[`synthmed.internal_db.generate_location`](../../src/synthmed/internal_db.py):

1. The pipeline assigns each synthetic beneficiary a ZIP code (sampled
   from population weights — see
   [`DECENNIALDHC2020.P1-Data.md`](DECENNIALDHC2020.P1-Data.md) once
   written).
2. The ZIP is mapped to a FIPS county via
   [`zip2fips.csv`](zip2fips.md) (sidecar pending).
3. The FIPS county is mapped to an SSA code via **this file**
   (left-join on `fipscounty`).
4. `state_code` and `county_code` are derived by slicing the SSA code:
   `state_code = ssa_code[:2]`, `county_code = ssa_code[2:5]`.

## Caveats and known simplifications

- **(Fixed 2026-05-16) Loader-typo bug that suppressed the `ssa_code`
  dtype hint.** `_build_zip2fips2pop` previously called
  `pd.read_csv(..., dtype={"fipscounty": str, "ssac_ode": str})`. The
  key `ssac_ode` was a typo for `ssa_code`, so pandas silently ignored
  the hint and the SSA column was inferred — yielding `float64` (and
  thus losing leading zeros from codes like `02013`) once the 2025
  NBER vintage introduced empty `ssa_code` rows for Connecticut's new
  planning regions. The downstream `ssa_code.str.slice(0, 2)` in
  [`generate_location`](../../src/synthmed/internal_db.py) would then
  raise. The one-character fix is in place; behavior of the upstream
  prototype was preserved up to that change.
- **CT transition produces structural empties.** Rows for Connecticut's
  9 new planning regions have empty `ssa_code` (no CMS SSA assignment
  yet); rows for the 8 legacy CT counties (plus US Virgin Islands)
  have empty `fipscounty`. The current loader's
  `pd.merge(..., how="left", left_on="FIPS", right_on="fipscounty")`
  will produce NaN `ssa_code` for any beneficiary mapped to a new CT
  FIPS, and the subsequent `base.dropna()` in `generate_location`
  silently drops those rows. Acceptable for synthetic generation, but
  worth flagging.
- **Year is hard-coded into the filename.** Refreshing to a future
  NBER vintage means renaming the file and updating the loader path.
  Switching to a year-agnostic filename (`ssa_fips_state_county.csv`)
  + a `year` field in the file or a separate manifest would be safer.
- **Six of eight columns are loaded but discarded.** Loading the full
  file is cheap (~170 KB), so this is fine, but a future minimization
  could `usecols=["fipscounty", "ssa_code"]` to save a tiny amount.
- **No Connecticut-aware compatibility shim.** Old MEDPAR extracts
  (pre-2024) use CT's 8 legacy county FIPS codes; new ones will use
  the 9 planning regions. The crosswalk handles both directions
  asymmetrically — see structural empties above.

## References

See [`docs/references.bib`](../references.bib):
`@nber-ssa-fips-crosswalk-2025`, `@cms-ipps-final-rule`,
`@census-2022-ct-change`.

## License

The file content is a derivative work over **U.S. public-domain
government data** (CMS IPPS Final Rule + CMS Medicare Advantage
Ratebook). NBER's processed crosswalks are freely distributed without
restriction (see the [NBER data portal terms](https://www.nber.org/research/data)).
Redistributed here under the repo's
**Apache License, Version 2.0** — see the repo-root
[LICENSE](../../LICENSE).

## Change log

- **2026-05-16 — Loader typo fixed.**
  `_build_zip2fips2pop` had `dtype={"fipscounty": str, "ssac_ode": str}`
  with `ssac_ode` typo'd; corrected to `ssa_code`. File content
  unchanged.
- _Initial version_ — imported from the upstream
  [ChilliPenguin/SynthMed](https://github.com/ChilliPenguin/SynthMed)
  prototype as-is. File content matches the NBER 2025 vintage
  byte-for-byte; not modified.
