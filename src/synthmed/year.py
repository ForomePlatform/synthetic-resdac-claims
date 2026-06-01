"""Generate one calendar year's worth of FTS-described DAT files.

For each ``*.fts`` schema in the input directory, emits a same-stem
``*.dat`` fixed-width file in the output directory. Per-year invariants:

* MBSF files are emitted before MEDPAR, so MEDPAR rows can reuse
  beneficiary-level values committed to MBSF files (BENE_ID excepted,
  which is sourced from the cohort directly so orphan IDs stay distinct).

* Values written to one file in a year may be reused by later files in
  the same year via a beneficiary-keyed lookup. This is what keeps
  cross-file consistency (e.g. a beneficiary's race code is identical
  in MBSF-AB-summary, MBSF-D-components, and MEDPAR for the year).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from os import listdir
from os.path import isfile, join
from pathlib import Path

import dorieh.cms.fts2yaml as f2y
import numpy as np
import pandas as pd

from synthmed.columns import (
    GeneratedColumn,
    char_generation,
    date_generation,
    number_generation,
)

log = logging.getLogger(__name__)


# Columns that must always be freshly generated from the cohort even if
# an earlier same-year file already carries them. BENE_ID stays cohort-
# sourced so MEDPAR's orphan-admission IDs survive; BENE_ZIP stays
# cohort-sourced so MEDPAR's per-admission location stays consistent
# with the beneficiary's ZIP.
_NEVER_REUSE = frozenset({"BENE_ID", "BENE_ZIP"})


@dataclass(frozen=True)
class _FTSColumn:
    name: str
    type: str
    width: float
    label: str

    @property
    def is_numeric_like(self) -> bool:
        """True for NUM columns and CHAR/DATE columns whose label is numeric."""
        return self.type == "NUM" or "Number" in self.label or "Year" in self.label


def list_fts_files(input_dir: Path | str) -> list[str]:
    """Return every ``*.fts`` filename in ``input_dir`` (non-recursive)."""
    return [
        f for f in listdir(input_dir)
        if isfile(join(input_dir, f)) and f.endswith(".fts")
    ]


def _reorder_medpar_last(fts_files: list[str]) -> list[str]:
    """Reverse the file list if MEDPAR comes first; otherwise leave it alone.

    MEDPAR must be emitted last so its per-admission rows can reuse
    beneficiary-level values already committed to the MBSF files for the
    same year. The reverse-if-first trick is inherited from the upstream
    prototype and preserves the existing MBSF-vs-MBSF relative order on
    every supported FTS layout; a more robust "MEDPAR always to the end"
    sort would also reorder MBSF files relative to each other, which
    would change reuse semantics between same-year MBSF files. Tracked
    in TODO.md.
    """
    if fts_files and "medpar" in fts_files[0].lower():
        return list(reversed(fts_files))
    return list(fts_files)


def _load_fts_columns(input_dir: Path | str, fts_filename: str) -> list[_FTSColumn]:
    """Parse one FTS file, truncated to its ``Columns in File`` metadata count."""
    mcr_type = f2y.mcr_type(fts_filename)
    fts = f2y.MedicareFTS(mcr_type).init(f"{input_dir}/{fts_filename}")
    n_real = int(fts.metadata["Columns in File"])
    return [
        _FTSColumn(name=c.column, type=c.type, width=c.width, label=c.label)
        for c in fts.columns[:n_real]
    ]


def _reuse_from_prior(
    data: pd.DataFrame,
    column: _FTSColumn,
    prior_frames: list[pd.DataFrame],
) -> GeneratedColumn | None:
    """Try to source ``column`` from a prior same-year file's frame.

    Returns a :class:`GeneratedColumn` if a prior file produced this
    column for the same beneficiaries, ``None`` otherwise. Beneficiaries
    are matched via ``data.actual_bene_id == prior.BENE_ID``.

    BENE_ID and BENE_ZIP are never reused (see :data:`_NEVER_REUSE`).
    """
    if column.name in _NEVER_REUSE:
        return None
    for prior in prior_frames:
        if column.name not in prior.columns:
            continue
        merged = data.merge(
            prior[["BENE_ID", column.name]],
            left_on="actual_bene_id",
            right_on="BENE_ID",
            how="left",
            suffixes=("_x", ""),
        )
        values = merged[column.name]
        if column.is_numeric_like:
            return GeneratedColumn(values, f"%0{int(column.width)}d")
        return GeneratedColumn(values, "%s")
    return None


def _generate_column(
    column: _FTSColumn,
    underlying: pd.DataFrame,
    *,
    is_medpar: bool,
    year: int | str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> GeneratedColumn:
    """Dispatch a single FTS column to the appropriate per-type generator.

    ``"Number"``-labelled and ``"Year"``-labelled CHAR/DATE columns are
    treated as NUM for purposes of generation (some ResDAC FTS files
    declare numeric fields as CHAR).
    """
    if column.is_numeric_like:
        return number_generation(column.width, column.label, underlying, year)
    if column.type == "CHAR":
        return char_generation(column.name, column.width, column.label, underlying, is_medpar)
    if column.type == "DATE":
        return date_generation(
            column.width, column.label, underlying, is_medpar, start_date, end_date,
        )
    raise ValueError(f"Unknown FTS column type {column.type!r} for {column.name!r}")


def _right_justify(series: pd.Series, width: int) -> pd.Series:
    """Right-justify a string column to ``width`` for fixed-width DAT emission."""
    return series.astype("string").str.rjust(int(width), " ")


def _emit_dat(
    data: pd.DataFrame,
    formatters: list[str],
    output_path: Path,
) -> None:
    """Write ``data`` to ``output_path`` in CRLF-terminated fixed-width form."""
    data = data.drop("actual_bene_id", errors="ignore", axis=1)
    np.savetxt(
        str(output_path),
        data.values,
        fmt=formatters,
        delimiter="",
        newline="\r\n",
    )


def generate_year_files(
    input_dir: Path | str,
    output_dir: Path | str,
    year: int | str,
    cohort: pd.DataFrame,
    medpar: pd.DataFrame,
) -> None:
    """For every FTS schema in ``input_dir``, emit the matching DAT file in ``output_dir``.

    This is the single place where the in-memory cohort/MEDPAR frames
    are serialised to disk for a calendar year. The MBSF-vs-MEDPAR
    dispatch is one line (``is_medpar = "medpar" in fts_filename.lower()``):
    every FTS whose name contains ``medpar`` is rendered against the
    ``medpar`` frame and saved as ``<stem>.dat`` (the MEDPAR DAT file);
    every other FTS is rendered against the ``cohort`` frame and saved
    as ``<stem>.dat`` (an MBSF DAT file -- in the current layout, one
    per ``mbsf_ab_summary``, ``mbsf_d_cmpnts``, etc. schema).

    Within a single year, files are processed in order returned by
    :func:`_reorder_medpar_last` (MEDPAR last) so MEDPAR rows can reuse
    beneficiary-level column values already committed to earlier MBSF
    files for the same year (see :func:`_reuse_from_prior`).
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    start_date = pd.to_datetime(f"{year}-01-01")
    end_date = pd.to_datetime(f"{year}-12-31")
    prior_frames: list[pd.DataFrame] = []

    fts_files = _reorder_medpar_last(list_fts_files(input_dir))
    for i, fts_filename in enumerate(fts_files, start=1):
        # MBSF/MEDPAR dispatch: this is where the cohort vs. medpar
        # source frame is chosen for the file we're about to write.
        is_medpar = "medpar" in fts_filename.lower()
        underlying = medpar if is_medpar else cohort
        columns = _load_fts_columns(input_dir, fts_filename)
        n_rows = len(underlying)
        log.info(
            "  year %s file %d/%d: %s (%d rows × %d cols)",
            year, i, len(fts_files), fts_filename, n_rows, len(columns),
        )

        # Small lookup frame used for cross-file reuse merges; stays unchanged.
        lookup = pd.DataFrame(
            {"actual_bene_id": underlying["actual_id"].values},
            index=range(n_rows),
        )
        # Accumulate generated columns in a dict so the final DataFrame
        # is built in a single allocation; appending columns one-at-a-
        # time to a pandas DataFrame triggers an O(n_cols²) fragment
        # warning and is the historical hot path for this loop.
        out: dict[str, object] = {"actual_bene_id": underlying["actual_id"].values}
        formatters: list[str] = []
        for column in columns:
            reused = _reuse_from_prior(lookup, column, prior_frames)
            if reused is not None:
                values, fmt = reused
                if (
                    column.name not in out
                    and column.type in ("CHAR", "DATE")
                    and not column.is_numeric_like
                ):
                    out[column.name] = values.astype("string")
                else:
                    out[column.name] = values
                formatters.append(fmt)
                continue

            values, fmt = _generate_column(
                column, underlying,
                is_medpar=is_medpar, year=year,
                start_date=start_date, end_date=end_date,
            )
            if column.is_numeric_like:
                out[column.name] = values
            else:
                out[column.name] = _right_justify(pd.Series(values), int(column.width))
            formatters.append(fmt)

        data = pd.DataFrame(out, index=range(n_rows))
        prior_frames.append(data)
        # This is where MBSF or MEDPAR for this year lands on disk.
        dat_filename = fts_filename.replace(".fts", ".dat")
        _emit_dat(data, formatters, output_dir / dat_filename)
