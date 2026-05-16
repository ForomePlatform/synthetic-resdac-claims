# `inputs/distributions/`

Reference distributions consumed by `synthmed` during generation. Each
file has a sidecar under [`docs/distributions/`](../../docs/distributions/)
with the same stem (e.g. `foo.csv` → `docs/distributions/foo.md`)
covering source, license, retrieval, schema, and how the file is used by
the package.

| File | What it is | Sidecar |
|---|---|---|
| `demographic_distributions.json` | Race + sex sampling weights | [`docs/distributions/demographic_distributions.md`](../../docs/distributions/demographic_distributions.md) |
| `state_error_medpar_rates.csv` | Per-state MEDPAR id/DOB null-injection rates | [`docs/distributions/state_error_medpar_rates.md`](../../docs/distributions/state_error_medpar_rates.md) |
| `number_of_diagnoses.csv` | Marginal distribution of diagnosis-count per MEDPAR row (k = 1..25) | [`docs/distributions/number_of_diagnoses.md`](../../docs/distributions/number_of_diagnoses.md) |
| `diag1.csv` | Marginal frequency table of primary ICD-9 codes (4076 rows, currently loaded-but-unused) | [`docs/distributions/diag1.md`](../../docs/distributions/diag1.md) |
| `ssa_fips_state_county_2025.csv` | NBER FIPS↔SSA county crosswalk (3283 rows, 8 columns) | [`docs/distributions/ssa_fips_state_county_2025.md`](../../docs/distributions/ssa_fips_state_county_2025.md) |
| `zip2fips.csv` | ZIP→FIPS-county crosswalk via clauswilke/zipcodes (41,877 rows, 1:1 ZIP→FIPS) | [`docs/distributions/zip2fips.md`](../../docs/distributions/zip2fips.md) |
| `DECENNIALDHC2020.P1-Data.csv` | 2020 US Census ZCTA total population (table P1, var `P1_001N`); used as ZIP sampling weights | [`docs/distributions/DECENNIALDHC2020.P1-Data.md`](../../docs/distributions/DECENNIALDHC2020.P1-Data.md) |

Sample data lives under [`inputs/samples/`](../samples/) and is **not
committed** — see [`docs/distributions/medicare_sample_data.md`](../../docs/distributions/medicare_sample_data.md)
for the lazy-download mechanism.
