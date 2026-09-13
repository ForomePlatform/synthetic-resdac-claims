# Zenodo dataset record — canonical metadata (source of truth)

Maintained in-repo so every new version of the dataset record
(concept DOI [10.5281/zenodo.18915557](https://doi.org/10.5281/zenodo.18915557))
is edited from one reviewed text instead of ad-hoc web edits. Update
this file first; then copy into the Zenodo form.

## Related works (carry on EVERY version)

| Relation | Identifier | Resource type |
|---|---|---|
| Is referenced by | 10.5281/zenodo.22728722 | Software |
| Is described by | 10.1007/978-3-032-21032-6 | Book |
| Is referenced by | 10.7490/f1000research.1119612.1 | Conference paper |

The third row already exists on the live record (F1000Research
poster) — keep it when editing; this table is the complete
carry-forward set.

## Corrections to metadata currently live on the record

Found by the dorieh-side citation audit (2026-09-12); apply during
the v4 edit pass:

1. REPLACE the existing related work `{isbn 978-3-032-21031-9,
   relation "describes"}` — it asserts the DATASET describes the
   BOOK, the wrong direction. Correct form is the table row above:
   relation "Is described by", and the book's DOI
   `10.1007/978-3-032-21032-6` instead of the print ISBN (DOI
   relations aggregate in OpenAIRE/Scholix; ISBN ones mostly do not).
   Alternative if citation-event generation for the book is wanted:
   "Is supplement to" (citation-generating; "is described by" is
   not) — Michael's call, default here is "Is described by".
2. SET the record's `version` field — currently empty. It should
   read the generator tag that produced the archived data
   (v3 archive: 0.2.0; the v4 upload: 0.3.1).

Notes: this is the Dorieh software CONCEPT DOI (not a version DOI),
so the relation survives future Dorieh releases. The inverse
("references" the dataset concept DOI) already exists on the Dorieh
software record. Requested by Michael on 2026-09-12; decision the
same day: v3 is NOT edited retroactively — the relation first ships
with the v4 publish, together with the rest of this record text.

## Pending for the next version (v4, generator v0.3.1)

To fill after the seeded regeneration and release audit:

- Zip name: `medicare-synthetic-database-v.0.3.1.zip` (match the
  generator tag that produced it). INCLUDE
  `generation-manifest.json` from the output directory in the
  archive — it carries version, seed, and the reproducibility
  statement.
- Compressed size: MEASURE after zipping (v3 was 9.2 GB for the
  v0.2.0 data; raw total below suggests a similar ratio).
- Raw size: 27,594,546,707 bytes = 25.70 GiB (27.59 decimal GB),
  17 DAT + 17 FTS files; FTS headers carry true per-file name, row
  count and byte size. Version field: 0.3.1.
- Scale (final seeded run, release-audited 2026-09-13, all counts
  byte-exact): MBSF beneficiaries 2011-2016:
  4,945,624 / 5,060,232 / 5,116,430 / 5,218,572 / 5,347,340 /
  5,469,383 (total beneficiary-years 31,157,581). MEDPAR admissions:
  1,322,577 / 1,338,120 / 1,354,439 / 1,378,858 / 1,413,400 /
  1,447,779 (total 8,255,173).
- Reproducibility: generator tag v0.3.1, seed 20260912 (run of
  2026-09-12 with `--seed today`). The run console was lost; the seed
  was confirmed empirically on 2026-09-13 by re-seeding the RNGs and
  reproducing the dataset's first minted beneficiary ID
  (`GZNFFCHBRUTZ000`) exactly — the ID prefix consumes the first 12
  post-seed draws, so a chance match is ~26^-12. The tag + seed pair
  regenerates the archive from the repo's committed inputs.
- Changes-vs-v3 note for existing users: v0.2.0 data right-justified
  every under-width CHAR value (ZIP unreadable from leading bytes),
  carried out-of-domain HMO code "3", had uniform random age and ZIP
  in the 2016 ABCD file, never emitted all-nines NUM values or
  Dec 31 dates, and shipped placeholder FTS header metadata. All are
  fixed in this version; see the synthmed CHANGELOG 0.3.0/0.3.1.
