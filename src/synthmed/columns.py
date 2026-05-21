"""Per-column value generation for FTS-described fixed-width DAT files.

Each FTS column has a declared ``type`` (``NUM`` / ``CHAR`` / ``DATE``)
and a free-text long description. The generators here dispatch on those
plus a small set of name- and description-based overrides so that cohort
attributes (BENE_ID, ZIP, race, …) survive verbatim into the emitted
DAT row instead of being clobbered with a random value of the right
type and width.

Each generator returns ``(values, fmt)`` where ``values`` is an
array-like (one element per cohort row) and ``fmt`` is a printf-style
format string consumed by :func:`numpy.savetxt` in
:mod:`synthmed.year`.
"""

from __future__ import annotations

import re
import string

import numpy as np
import pandas as pd

from synthmed.generators import random_char_gen, random_date_gen


# ---------------------------------------------------------------------------
# NUM
# ---------------------------------------------------------------------------


def number_generation(
    column_width: float,
    column_label: str,
    underlying: pd.DataFrame,
    year: int,
) -> tuple[np.ndarray | pd.Series, str]:
    """Generate a ``NUM`` column.

    Overrides (highest priority first):

    1. ``"Age at End of Reference Year"`` / ``"Age as of Date of Admission"``
       → cohort ``age``.
    2. ``"Months Number"`` → uniform integer in ``[1, 12]``.
    3. ``"Year"`` (width 4) → uniform in ``{year, year + 1}``.
    4. Default: uniform integer in ``[0, 10**width - 1]``.

    Fractional widths (e.g. ``5.2`` meaning "5 chars, 2 decimal places")
    yield a float in ``[0, 10)`` formatted to ``floor(width) - 2``
    decimal places.
    """
    year = int(year)
    n = underlying.shape[0]

    if (
        "Age at End of Reference Year" in column_label
        or "Age as of Date of Admission" in column_label
    ):
        return underlying["age"], f"%0{int(column_width)}d"

    min_num, max_num = _num_range(column_label, column_width, year)

    if abs(column_width - int(column_width)) > 0.01:
        # Fractional width => fixed-point float (e.g. width 5.2 => XX.XX format).
        values = np.clip(np.random.rand(n) * 10, 0, 9.98)
        fmt = f"%.{int(np.floor(column_width) - 2)}f"
    else:
        values = np.random.randint(min_num, max_num, n)
        fmt = f"%0{int(column_width)}d"
    return values, fmt


def _num_range(column_label: str, column_width: float, year: int) -> tuple[int, int]:
    """Resolve ``(min_num, max_num)`` for a NUM column given its label/width."""
    if "Months Number" in column_label:
        return 1, 12
    if "Year" in column_label and column_width == 4:
        return year, year + 1

    max_num = (10 ** int(column_width)) - 1
    if max_num > 10**5:
        # TODO: kept verbatim from the upstream notebook -- documented intent
        # is `10 ** 5` (== 100000) but the literal here is `10 * 5` (== 50).
        # Tracked in TODO.md ("Column generation"); needs a regression test
        # before changing because it ships in v0.1.0.
        max_num = 10 * 5
    return 0, max_num


# ---------------------------------------------------------------------------
# DATE
# ---------------------------------------------------------------------------


def date_generation(
    column_width: int,
    column_label: str,
    underlying: pd.DataFrame,
    is_medpar: bool,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> tuple[pd.Series | np.ndarray, str]:
    """Generate a ``DATE`` column.

    Overrides:

    - ``"Date of Birth"`` → cohort ``birth_date``.
    - ``"Date of Death"`` / ``"Date beneficiary died"`` → cohort
      ``death_date`` (MEDPAR: only on the last admission row per
      beneficiary, so the death date is reported once).
    - Default: uniform random date in ``[start_date, end_date)`` (the
      cohort year).
    """
    n = underlying.shape[0]

    if "Date of Birth" in column_label:
        return underlying["birth_date"], "%s"

    if "Date of Death" in column_label or "Date beneficiary died" in column_label:
        if is_medpar:
            values: pd.Series = pd.Series(" ", dtype="string", index=underlying.index)
            values.loc[underlying["last_record"] == True] = underlying["death_date"]  # noqa: E712
            return values, "%s"
        return underlying["death_date"], "%s"

    return random_date_gen(start_date, end_date, n), "%s"


# ---------------------------------------------------------------------------
# CHAR
# ---------------------------------------------------------------------------


# Small enumerations whose support is fixed by the ResDAC documentation
# but whose individual draws are not cohort-derived. The ``in column_label``
# trigger is matched on the raw (case-sensitive) FTS description.
_ENUMERATED_CHAR_OVERRIDES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Claim Type",       ("10", "20", "30", "60", "61", "62", "63", "64")),
    ("Buy-In Indicator", ("0", "1", "2", "3", "A", "B", "C")),
    ("HMO Indicator",    ("0", "1", "2", "4", "A", "B", "C")),
)

_DGNSCD_RE = re.compile(r"DGNSCD(\d*)")


def char_generation(
    column_name: str,
    column_width: int,
    column_label: str,
    underlying: pd.DataFrame,
    is_medpar: bool,
) -> tuple[pd.Series | list[str], str]:
    """Generate a ``CHAR`` column.

    Override priority (first match wins):

    1. Cohort-derived columns (exact name or substring of the label):
       ``BENE_ID``, ZIP (5 or 9), state code, county code, sex, race,
       ``DGNSCD_k`` diagnosis codes, death-date verification switch.
    2. Enumerated value sets from the ResDAC docs: claim type, buy-in
       indicator, HMO indicator.
    3. Default: random digit string of the declared width.
    """
    n = underlying.shape[0]
    label_lower = column_label.lower()

    if column_name == "BENE_ID":
        return underlying["id"], "%s"

    if "Zip" in column_label:
        return (underlying["zip4"] if column_width == 9 else underlying["zip"]), "%s"

    if "state code" in label_lower:
        return underlying["state_code"], "%s"
    if "county code" in label_lower:
        return underlying["county_code"], "%s"
    if "sex" in label_lower:
        return underlying["sex"], "%s"
    if "race" in label_lower:
        return underlying["race"], "%s"

    if (
        "Death Date Verification" in column_label
        or "Valid Date of Death Switch" in column_label
    ):
        return _death_date_switch(underlying, is_medpar), "%s"

    if (
        "ICD-9-CM Diagnosis code" in column_label
        or "Primary ICD-9-CM code" in column_label
    ):
        m = _DGNSCD_RE.search(column_name)
        if m is not None:
            return underlying[f"diag_{m.group(1)}"], "%s"

    for trigger, tokens in _ENUMERATED_CHAR_OVERRIDES:
        if trigger in column_label:
            return random_char_gen(1, n, list(tokens)), "%s"

    return random_char_gen(column_width, n, string.digits), "%s"


def _death_date_switch(underlying: pd.DataFrame, is_medpar: bool) -> pd.Series:
    """ResDAC "Death Date Verification" / "Valid Date of Death Switch" column.

    MBSF: blank if alive, ``"V"`` if a death date is recorded.

    MEDPAR: blank on the last admission row of every alive beneficiary,
    ``"V"`` on every other row. This is the literal behaviour inherited
    from the upstream prototype; the inversion vs. the MBSF case is
    suspicious and is tracked in TODO.md but preserved here to keep the
    refactor a no-op on DAT contents.
    """
    is_alive = underlying["death_date"] == " "
    if is_medpar:
        return (is_alive & underlying["last_record"]).map({True: " ", False: "V"})
    return is_alive.map({True: " ", False: "V"})
