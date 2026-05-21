# `medicare_sample_data/` (lazy-downloaded)

> Path: [`inputs/samples/`](../../inputs/samples/) (gitignored)

The 20 CMS DE-SynPUF inpatient claim sample CSVs used by `synthmed`
as the source of the joint within-admission distribution of ICD-9
diagnosis codes. ~16 MB per file, ~320 MB total — too large to commit,
so they are **fetched on demand**.

## File set

| Filename                                              | Sample # | Approx. CSV size |
|:------------------------------------------------------|:--------:|:----------------:|
| `DE1_0_2008_to_2010_Inpatient_Claims_Sample_1.csv`    | 1        | ~16 MB           |
| `DE1_0_2008_to_2010_Inpatient_Claims_Sample_2.csv`    | 2        | ~16 MB           |
| …                                                     | …        | …                |
| `DE1_0_2008_to_2010_Inpatient_Claims_Sample_20.csv`   | 20       | ~16 MB           |

SHA-256 hashes for all 20 files are pinned in
[`src/synthmed/samples.py`](../../src/synthmed/samples.py)
(`INPATIENT_SAMPLES`). The downloader refuses to use a file whose
hash does not match the pinned value.

> **Line-ending normalization.** CMS has been observed to re-emit the
> ZIPs with CRLF line endings without changing the actual record
> content. The verifier in
> [`synthmed.samples._sha256_of`](../../src/synthmed/samples.py)
> normalizes CRLF → LF before hashing, so the pinned hashes survive
> that cosmetic churn while still detecting any real data change.

## Provenance

CMS Data Entrepreneurs' Synthetic Public Use File (DE-SynPUF),
2008–2010 Inpatient Claims, Samples 1–20.

- Landing page: <https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf>
- User manual: <https://www.cms.gov/Research-Statistics-Data-and-Systems/Downloadable-Public-Use-Files/SynPUFs/Downloads/SynPUF_DUG.pdf>
- Codebook: <https://www.cms.gov/files/document/de-10-codebook.pdf-0>
- ZIP download URL pattern:
  `https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_inpatient_claims_sample_{N}.zip`

License: **U.S. Government public-domain work** — no restrictions on
redistribution.

The DE-SynPUF was created by CMS to give researchers a realistic
analogue of Medicare claims without disclosing any actual beneficiary.
Each "sample" is an independent 1% draw with its own randomization
seed; the 20 samples together approximate a 20% sample of the
2008–2010 Medicare fee-for-service population
[@cms-desynpuf].

## How `synthmed` uses it

Loaded once per run by
[`synthmed.distributions._load_de_sample`](../../src/synthmed/distributions.py),
which calls
[`synthmed.samples.ensure_samples`](../../src/synthmed/samples.py)
first to make sure every file is present (and hash-correct). The 20
CSVs are then concatenated into a single `DataFrame`
(`DistributionData.de_sample`), and sampled row-wise in
[`synthmed.internal_db.generate_diagnosis`](../../src/synthmed/internal_db.py)
to populate `diag_1..diag_10` for each MEDPAR record.

## Auto-download mechanism

First run will fetch all 20 ZIPs from CMS (~10 MB each compressed,
~3 minutes on a typical broadband connection) and unzip them into
`config.sample_dir` (defaults to `inputs/samples/`). Subsequent runs
no-op once hashes verify.

### Explicit download

```bash
synthmed download-samples                  # default: inputs/samples/
synthmed download-samples --target-dir X   # custom location
synthmed download-samples --force          # re-download even if present
```

### Offline mode

Set `SYNTHMED_OFFLINE=1` (or pass `--offline` to the CLI) to refuse
network access. With offline mode and a missing file, the loader
raises :class:`synthmed.samples.OfflineError` rather than calling out.

## Caveats and known simplifications

- **CMS URLs are historically brittle.** The path
  `/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/...`
  has moved at least twice in the program's history. If the pinned URL
  rots, update `_URL_PATTERN` in
  [`src/synthmed/samples.py`](../../src/synthmed/samples.py) and add an
  optional mirror to the manifest.
- **No resumable downloads.** Stdlib `urllib.request` is used; a
  partial download is dropped and retried from scratch. Acceptable for
  one-time-per-machine work; if it becomes annoying, swap to `requests`
  + `Range` headers.
- **ICD-9 only / capped at 10 codes.** DE-SynPUF exposes
  `ICD9_DGNS_CD_1..10`; that's the structural reason
  `synthmed.internal_db.generate_diagnosis` only populates
  `diag_1..diag_10` and leaves `diag_11..diag_25` blank.
- **2008–2010 vintage.** Predates ICD-10 transition (Oct 2015) and
  recent Medicare population shifts.
- **Synthetic, not real.** DE-SynPUF preserves marginal and some joint
  distributions but is not statistically equivalent to real Medicare
  claims; outputs based on it carry the same caveat.

## References

See [`docs/references.bib`](../references.bib): `@cms-desynpuf`.

## License

The downloaded file content is U.S. Government public-domain work.
Redistributed locally (after download) under the repo's
**Apache License, Version 2.0** — see the repo-root
[LICENSE](../../LICENSE).

## Change log

- **2026-05-16 — Verifier made line-ending-agnostic.** First real
  download from CMS produced files with CRLF endings vs. Pavel's
  LF-format local copy; content was byte-identical otherwise.
  `_sha256_of` now normalizes CRLF→LF before hashing so the manifest
  survives that. Pinned hashes unchanged.
- _Initial version_ — moved out of `pavel/SynthMed/medicare_sample_data/`
  on 2026-05-16. Files are no longer committed; lazy-downloaded into
  `inputs/samples/` by
  [`synthmed.samples.ensure_samples`](../../src/synthmed/samples.py).
  SHA-256 manifest pinned from the verified local copy on that date.
