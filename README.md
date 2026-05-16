# synthetic-resdac-claims

`synthmed` — a Python package that generates **synthetic ResDAC / Medicare
claims data** (MEDPAR, MBSF) as fixed-width DAT files that conform to a
set of ResDAC File Transfer Specification (FTS) schemas.

The generator maintains a single internal cohort of synthetic beneficiaries
and rolls it forward year-by-year so that demographics, IDs, locations and
diagnosis histories stay consistent across files. Realistic data-quality
errors (race miscoding, date-of-birth drift, state-correlated null IDs)
are injected on the way through.

> Originally a notebook prototype by
> [Pavel Belakurski](https://github.com/ChilliPenguin/SynthMed).

## Status

Alpha. The migration from the original notebook is structurally complete:

- All reference inputs live under [`inputs/`](inputs/). The seven
  distribution files in [`inputs/distributions/`](inputs/distributions/)
  each have a sidecar under
  [`docs/distributions/`](docs/distributions/) covering format,
  provenance, license, and how `synthmed` consumes them. Citations are
  consolidated in [`docs/references.bib`](docs/references.bib).
- The ~320 MB CMS DE-SynPUF inpatient samples are
  **lazy-downloaded** from CMS into `inputs/samples/` by
  `synthmed download-samples` (or on first generation run).
- A handful of distribution values are intentionally approximate and
  distorted (the underlying CMS data is confidential); each sidecar's
  *Provenance* section is explicit about what is and isn't backed by
  a public source.

What's still alpha-grade — no regression tests, a few known
simplifications and small bugs are enumerated
in [TODO.md](TODO.md).

## Install

```bash
pip install -e .
```

Requires Python 3.10+. The package depends on
[`dorieh`](https://github.com/forome/dorieh) for FTS parsing.

## Usage

### Python

```python
from pathlib import Path
from synthmed import GenerationConfig, run

run(GenerationConfig(
    data_root=Path("inputs/schemas"),
    distribution_dir=Path("inputs/distributions"),
    sample_dir=Path("inputs/samples"),
    output_dir=Path("output_dat_files"),
    total_people=1000,
))
```

### CLI

```bash
# (Optional) one-shot pre-download of the ~320 MB CMS DE-SynPUF samples
# into inputs/samples/. If you skip this, `synthmed generate` will
# trigger the same download on first run.
synthmed download-samples

synthmed generate \
    --data-root         inputs/schemas \
    --distribution-dir  inputs/distributions \
    --sample-dir        inputs/samples \
    --output-dir        output_dat_files \
    --total-people      1000
```

Set `SYNTHMED_OFFLINE=1` (or pass `--offline` to `download-samples`)
to refuse network access; with offline mode and missing files the
loader raises rather than calling out.

### Notebook

A minimal end-to-end demo lives at [`notebooks/demo.ipynb`](notebooks/demo.ipynb).
It only calls into `synthmed` — there is no business logic in the notebook.

## Layout

```
src/synthmed/
    config.py          # GenerationConfig dataclass
    distributions.py   # Load reference CSV/JSON distributions
    generators.py      # Low-level random char / date generators
    internal_db.py     # Build & roll the internal beneficiary cohort
    medpar.py          # Expand cohort into MEDPAR admission rows
    errors.py          # Inject realistic data-quality errors
    columns.py         # NUM / CHAR / DATE column protocols
    year.py            # Emit one year's DAT files from FTS schemas
    pipeline.py        # Top-level multi-year orchestrator
    cli.py             # `synthmed generate ...`
notebooks/demo.ipynb   # Thin demo notebook
```

## License

See [LICENSE](LICENSE).
