"""Per-column value generation for FTS-described fixed-width DAT files.

Each FTS column has a declared ``type`` (``NUM`` / ``CHAR`` / ``DATE``)
and a free-text long description. The generators here dispatch on those
plus a small set of name- and description-based overrides so that cohort
attributes (BENE_ID, ZIP, race, …) survive verbatim into the emitted
DAT row instead of being clobbered with a random value of the right
type and width.

Each ``*_generation`` function returns a :class:`GeneratedColumn` --
a tuple-compatible ``(values, fmt)`` pair where ``values`` is one
element per cohort row and ``fmt`` is a printf-style format string
consumed by :func:`numpy.savetxt` in :mod:`synthmed.year`.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

import numpy as np
import pandas as pd

from synthmed.generators import random_char_gen, random_date_gen

from typing import NamedTuple


class GeneratedColumn(NamedTuple):
    """One generated FTS column: per-row values + printf format string.

    Tuple-compatible so callers may keep writing ``values, fmt = column``;
    the named attributes (:attr:`values`, :attr:`fmt`) are there to make
    the contract explicit at the call site.

    Attributes:
        values: One entry per row in the cohort or MEDPAR frame.
            Typically a :class:`pandas.Series`, :class:`numpy.ndarray`,
            or list of strings.
        fmt: printf-style format string consumed by
            :func:`numpy.savetxt` (e.g. ``"%s"``, ``"%05d"``, ``"%.2f"``).
    """
    values: pd.Series | np.ndarray | list[str]
    fmt: str


# ---------------------------------------------------------------------------
# NUM
# ---------------------------------------------------------------------------


def number_generation(
    column_width: float,
    column_label: str,
    underlying: pd.DataFrame,
    year: int,
) -> GeneratedColumn:
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

    Args:
        column_width: Declared FTS field width in characters. May be
            fractional (``5.2``) to encode "5 chars total, 2 decimal
            places".
        column_label: Free-text FTS long description for the column,
            used to trigger label-based overrides.
        underlying: Per-row source frame for this file (the cohort for
            MBSF; the MEDPAR frame for MEDPAR). One row per output DAT
            row. Used here to read ``age`` for age columns and to size
            the random draws (``n = len(underlying)``).
        year: Calendar year being emitted; bounds the ``"Year"`` override.
    """
    year = int(year)
    n = underlying.shape[0]

    if (
        "Age at End of Reference Year" in column_label
        or "Age as of Date of Admission" in column_label
    ):
        return GeneratedColumn(underlying["age"], f"%0{int(column_width)}d")

    min_num, max_num = _num_range(column_label, column_width, year)

    if abs(column_width - int(column_width)) > 0.01:
        # Fractional width => fixed-point float (e.g. width 5.2 => XX.XX format).
        values = np.clip(np.random.rand(n) * 10, 0, 9.98)
        fmt = f"%.{int(np.floor(column_width) - 2)}f"
    else:
        values = np.random.randint(min_num, max_num, n)
        fmt = f"%0{int(column_width)}d"
    return GeneratedColumn(values, fmt)


def _num_range(column_label: str, column_width: float, year: int) -> tuple[int, int]:
    """Resolve ``(min_num, max_num)`` for a NUM column given its label/width.

    Args:
        column_label: FTS long description; triggers
            ``"Months Number"`` and ``"Year"`` overrides.
        column_width: Declared FTS field width in characters; sets the
            default upper bound to ``10**int(width) - 1``.
        year: Calendar year being emitted; used as the lower bound when
            the ``"Year"`` override fires.
    """
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
) -> GeneratedColumn:
    """Generate a ``DATE`` column.

    Overrides:

    - ``"Date of Birth"`` → cohort ``birth_date``.
    - ``"Date of Death"`` / ``"Date beneficiary died"`` → cohort
      ``death_date`` (MEDPAR: only on the last admission row per
      beneficiary, so the death date is reported once).
    - Default: uniform random date in ``[start_date, end_date)`` (the
      cohort year).

    Args:
        column_width: Declared FTS field width (unused for the date
            overrides since the formatter is always ``%s`` against an
            already-formatted ``CCYYMMDD`` string; carried for signature
            symmetry with the other generators).
        column_label: FTS long description; triggers the DOB/DOD
            overrides.
        underlying: Per-row source frame for this file (cohort for MBSF,
            MEDPAR frame for MEDPAR). Required columns for the
            overrides: ``birth_date``, ``death_date``; plus
            ``last_record`` when ``is_medpar`` is True.
        is_medpar: True when emitting a MEDPAR file. Switches the
            date-of-death override to "report only on the last admission
            row per beneficiary".
        start_date: Inclusive lower bound for the default random-date
            override (typically Jan 1 of ``year``).
        end_date: Exclusive upper bound for the default random-date
            override (typically Dec 31 of ``year``).
    """
    n = underlying.shape[0]

    if "Date of Birth" in column_label:
        return GeneratedColumn(underlying["birth_date"], "%s")

    if "Date of Death" in column_label or "Date beneficiary died" in column_label:
        if is_medpar:
            values: pd.Series = pd.Series(" ", dtype="string", index=underlying.index)
            values.loc[underlying["last_record"] == True] = underlying["death_date"]  # noqa: E712
            return GeneratedColumn(values, "%s")
        return GeneratedColumn(underlying["death_date"], "%s")

    return GeneratedColumn(random_date_gen(start_date, end_date, n), "%s")


# ---------------------------------------------------------------------------
# CHAR
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnumeratedTokens:
    """Override: per-row uniform draw from a fixed token set.

    Matched against ``column_label.lower()`` via substring containment.
    """
    tokens: tuple[str, ...]


@dataclass
class MarkovConfig:
    """Override: per-beneficiary 12-month coverage-indicator sequence.

    ``dominant_prob`` of beneficiaries get a flat 12-month pattern of
    ``dominant_code``; ``secondary_prob`` get a flat pattern of
    ``secondary_code``; the remainder follow a sticky Markov walk over
    ``markov_states``. Matched against ``column_label.lower()`` via
    substring containment.
    """
    dominant_code: str
    dominant_prob: float
    secondary_code: str
    secondary_prob: float
    markov_states: list[str]


# Small enumerations whose support is fixed by the ResDAC documentation
# but whose individual draws are not cohort-derived. Keys are lowercase
# substrings matched against ``column_label.lower()``.
_ENUMERATED_CHAR_OVERRIDES: dict[str, EnumeratedTokens] = {
    "claim type": EnumeratedTokens(
        ("10", "20", "30", "60", "61", "62", "63", "64")
    ),
}

_ENUMERATED_MARKOV_CHAINS: dict[str, MarkovConfig] = {
    "buy-in indicator": MarkovConfig(
        dominant_code="3",
        dominant_prob=0.765,
        secondary_code="C",
        secondary_prob=0.20,
        markov_states=["0", "1", "2", "A", "B"],
    ),
    "hmo indicator": MarkovConfig(
        dominant_code="3",
        dominant_prob=0.69,
        secondary_code="C",
        secondary_prob=0.30,
        markov_states=["1", "2", "4"],
    ),
}

_DGNSCD_RE = re.compile(r"DGNSCD(\d*)")


def _build_buyhmo_sequence(n: int, c: MarkovConfig) -> np.ndarray:
    """Per-beneficiary 12-month coverage-indicator sequences.

    Returns an ``(n, 12)`` array of single-character codes. Intended to
    be called once per chain per frame and cached on
    ``underlying.attrs`` -- see :func:`char_generation`.

    Args:
        n: Number of beneficiaries (rows of the source frame).
        c: Chain parameters (dominant/secondary codes and probabilities,
            plus the Markov state set for the residual population).
    """
    states = np.asarray(c.markov_states)
    seq = np.empty((n, 12), dtype="U1")
    r = np.random.rand(n)

    seq[r < c.dominant_prob] = c.dominant_code
    cutoff = c.dominant_prob + c.secondary_prob
    seq[(r >= c.dominant_prob) & (r < cutoff)] = c.secondary_code

    markov_rows = np.where(r >= cutoff)[0]
    if markov_rows.size:
        k = states.size
        trans = np.full((k, k), 0.005 / (k - 1))
        np.fill_diagonal(trans, 0.995)
        for row in markov_rows:
            current = np.random.randint(k)
            for t in range(12):
                seq[row, t] = states[current]
                current = np.random.choice(k, p=trans[current])
    return seq


def char_generation(
    column_name: str,
    column_width: int,
    column_label: str,
    underlying: pd.DataFrame,
    is_medpar: bool,
) -> GeneratedColumn:
    """Generate a ``CHAR`` column.

    Override priority (first match wins):

    1. Cohort-derived columns (exact name or substring of the label):
       ``BENE_ID``, ZIP (5 or 9), state code, county code, sex, race,
       OREC (Original Reason for Entitlement -- invariant across years),
       ``DGNSCD_k`` diagnosis codes, death-date verification switch.
    2. Per-beneficiary Markov coverage chains (buy-in, HMO indicators).
    3. Enumerated value sets from the ResDAC docs (claim type, …).
    4. Default: random digit string of the declared width.

    Args:
        column_name: FTS short column identifier (e.g. ``BENE_ID``,
            ``DGNSCD05``, ``BUYIN03``). Used for exact-name overrides
            and to parse the trailing month index for Markov chain
            columns and the diagnosis ordinal for ``DGNSCD_k``.
        column_width: Declared FTS field width in characters. Selects
            ZIP 5 vs. ZIP 9 and sets the width of the default random
            digit string.
        column_label: FTS long description. All substring-based
            overrides (state code, sex, ICD-9, buy-in indicator, …)
            dispatch on this -- case-insensitively where the dispatch
            table uses lowercase keys.
        underlying: Per-row source frame for this file (cohort for
            MBSF, MEDPAR frame for MEDPAR). Required columns vary with
            which override fires: ``id``, ``zip``/``zip4``,
            ``state_code``, ``county_code``, ``sex``, ``race``,
            ``death_date``, ``diag_k`` (for ICD-9 columns), and
            ``last_record`` (for MEDPAR death-date). The Markov branch
            also uses ``underlying.attrs`` as a per-frame scratch cache.
        is_medpar: True when emitting a MEDPAR file. Affects only the
            death-date verification switch.
    """
    n = underlying.shape[0]
    label_lower = column_label.lower()

    if column_name == "BENE_ID":
        return GeneratedColumn(underlying["id"], "%s")

    if "Zip" in column_label:
        values = underlying["zip4"] if column_width == 9 else underlying["zip"]
        return GeneratedColumn(values, "%s")

    if "state code" in label_lower:
        return GeneratedColumn(underlying["state_code"], "%s")
    if "county code" in label_lower:
        return GeneratedColumn(underlying["county_code"], "%s")
    if "sex" in label_lower:
        return GeneratedColumn(underlying["sex"], "%s")
    if "race" in label_lower:
        return GeneratedColumn(underlying["race"], "%s")

    # OREC must stay invariant across a beneficiary's years (see cohort
    # ``orec`` column sampled in internal_db.generate_demographic). CUREC
    # ("Current Reason …") is allowed to vary year-to-year and falls
    # through to the default random-digit path below.
    if "Original Reason for Entitlement" in column_label:
        return GeneratedColumn(underlying["orec"], "%s")

    if (
        "Death Date Verification" in column_label
        or "Valid Date of Death Switch" in column_label
    ):
        return GeneratedColumn(_death_date_switch(underlying, is_medpar), "%s")

    if (
        "ICD-9-CM Diagnosis code" in column_label
        or "Primary ICD-9-CM code" in column_label
    ):
        m = _DGNSCD_RE.search(column_name)
        if m is not None:
            return GeneratedColumn(underlying[f"diag_{m.group(1)}"], "%s")

    for chain_name, chain_config in _ENUMERATED_MARKOV_CHAINS.items():
        if chain_name in label_lower:
            # char_generation is called once per monthly column (12 per
            # chain), but the Markov walk has to span all 12 months for
            # a beneficiary's within-year persistence to mean anything.
            # We build the full (n_rows, 12) array on the first month
            # and cache it on ``underlying.attrs`` -- frame-scoped, so
            # the next year's frame gets a fresh draw automatically.
            # Per-chain key keeps buy-in and HMO caches separate; the
            # ``shape[0] != n`` guard invalidates on row-count mismatch.
            month_idx = int(column_name[-2:]) - 1
            cache_key = f"_buyhmo_seq::{chain_name}"
            seq = underlying.attrs.get(cache_key)
            if seq is None or seq.shape[0] != n:
                seq = _build_buyhmo_sequence(n, chain_config)
                underlying.attrs[cache_key] = seq
            values = pd.Series(seq[:, month_idx], index=underlying.index)
            return GeneratedColumn(values, "%s")

    for trigger, override in _ENUMERATED_CHAR_OVERRIDES.items():
        if trigger in label_lower:
            return GeneratedColumn(
                random_char_gen(1, n, list(override.tokens)), "%s"
            )

    return GeneratedColumn(random_char_gen(column_width, n, string.digits), "%s")


def _death_date_switch(underlying: pd.DataFrame, is_medpar: bool) -> pd.Series:
    """ResDAC "Death Date Verification" / "Valid Date of Death Switch" column.

    MBSF: blank if alive, ``"V"`` if a death date is recorded.

    MEDPAR: blank on the last admission row of every alive beneficiary,
    ``"V"`` on every other row. This is the literal behaviour inherited
    from the upstream prototype; the inversion vs. the MBSF case is
    suspicious and is tracked in TODO.md but preserved here to keep the
    refactor a no-op on DAT contents.

    Args:
        underlying: Per-row source frame for this file (cohort for MBSF,
            MEDPAR frame for MEDPAR). Required columns: ``death_date``
            (``" "`` for alive beneficiaries, ``CCYYMMDD`` otherwise);
            ``last_record`` when ``is_medpar`` is True.
        is_medpar: True when emitting a MEDPAR file; flips dispatch to
            the per-admission "blank on last row" semantics.
    """
    is_alive = underlying["death_date"] == " "
    if is_medpar:
        return (is_alive & underlying["last_record"]).map({True: " ", False: "V"})
    return is_alive.map({True: " ", False: "V"})
