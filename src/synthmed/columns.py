"""Per-column value generation protocols.

Each protocol returns ``(values, fmt)`` where ``values`` is array-like and
``fmt`` is a ``printf``-style format string consumed by :func:`numpy.savetxt`.
"""

from __future__ import annotations

import re
import string

import numpy as np
import pandas as pd

from synthmed.generators import random_char_gen, random_date_gen


def number_generation(
    column_width: float,
    column_long: str,
    underlying: pd.DataFrame,
    year: int,
) -> tuple[np.ndarray | pd.Series, str]:
    """Produce values for a NUM column, honoring the documented exceptions."""
    year = int(year)
    max_num = (10 ** int(column_width)) - 1
    min_num = 0
    n = underlying.shape[0]

    if "Months Number" in column_long:
        max_num = 12
        min_num = 1
    if "Year" in column_long and column_width == 4:
        max_num = year + 1
        min_num = year
    if (
        "Age at End of Reference Year" in column_long
        or "Age as of Date of Admission" in column_long
    ):
        return (underlying["age"], f"%0{int(column_width)}d")
    if max_num > 10**5:
        # NOTE: kept verbatim from the original notebook; the documentation
        # describes this as a 0..10^5 cap to avoid SQL int overflow.
        max_num = 10 * 5

    if abs(column_width - int(column_width)) > 0.01:
        values = np.clip(np.random.rand(n) * 10, 0, 9.98)
        fmt = f"%.{int(np.floor(column_width) - 2)}f"
    else:
        values = np.random.randint(min_num, max_num, n)
        fmt = f"%0{int(column_width)}d"
    return values, fmt


def date_generation(
    column_width: int,
    column_long: str,
    underlying: pd.DataFrame,
    is_medpar: bool,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> tuple[pd.Series | np.ndarray, str]:
    """Produce values for a DATE column."""
    values: pd.Series | np.ndarray = pd.Series(dtype="string", index=underlying.index)
    n = underlying.shape[0]

    if "Date of Birth" in column_long:
        values = underlying["birth_date"]
    elif "Date of Death" in column_long or "Date beneficiary died" in column_long:
        if not is_medpar:
            values = underlying["death_date"]
        else:
            values = values.fillna(" ")
            values.loc[underlying["last_record"] == True] = underlying["death_date"]  # noqa: E712
    else:
        values = random_date_gen(start_date, end_date, n)
    return values, "%s"


def char_generation(
    column_name: str,
    column_width: int,
    column_long: str,
    underlying: pd.DataFrame,
    is_medpar: bool,
) -> tuple[pd.Series | list[str], str]:
    """Produce values for a CHAR column, with many documented overrides."""
    values: pd.Series | list[str] = pd.Series(dtype="string", index=underlying.index)
    n = underlying.shape[0]
    long_lower = column_long.lower()

    if column_name == "BENE_ID":
        values = underlying["id"]
    elif "Zip" in column_long:
        values = underlying["zip4"] if column_width == 9 else underlying["zip"]
    elif "state code" in long_lower:
        values = underlying["state_code"]
    elif "county code" in long_lower:
        values = underlying["county_code"]
    elif "sex" in long_lower:
        values = underlying["sex"]
    elif "race" in long_lower:
        values = underlying["race"]
    elif (
        "Death Date Verification" in column_long
        or "Valid Date of Death Switch" in column_long
    ):
        if is_medpar:
            values = (
                (underlying["death_date"] == " ") & underlying["last_record"]
            ).map({True: " ", False: "V"})
        else:
            values = (underlying["death_date"] == " ").map({True: " ", False: "V"})
    elif (
        "ICD-9-CM Diagnosis code" in column_long
        or "Primary ICD-9-CM code" in column_long
    ):
        m = re.search(r"DGNSCD(\d*)", column_name)
        values = underlying[f"diag_{m.group(1)}"]
    elif "Claim Type" in column_long:
        values = random_char_gen(1, n, ["10", "20", "30", "60", "61", "62", "63", "64"])
    elif "Buy-In Indicator" in column_long:
        values = random_char_gen(1, n, ["0", "1", "2", "3", "A", "B", "C"])
    elif "HMO Indicator" in column_long:
        values = random_char_gen(1, n, ["0", "1", "2", "4", "A", "B", "C"])
    else:
        values = random_char_gen(column_width, n, string.digits)
    return values, "%s"
