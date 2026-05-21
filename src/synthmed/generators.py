"""Low-level random value generators shared by the cohort and column modules."""

from __future__ import annotations

import string
from typing import Iterable

import numpy as np
import pandas as pd


def random_char_gen(
    width: int,
    n_rows: int,
    alphabet: Iterable[str] = string.ascii_uppercase,
) -> list[str]:
    """Return ``n_rows`` strings, each formed by concatenating ``width`` draws from ``alphabet``.

    ``alphabet`` may be single characters (``string.ascii_uppercase``) or
    multi-character tokens (e.g. ``["10", "20", "30"]``); the output strings
    are just ``"".join(...)`` of the draws either way.
    """
    width = int(width)
    n_rows = int(n_rows)
    pool = list(alphabet)
    drawn = np.random.choice(pool, size=(n_rows, width))
    return ["".join(row) for row in drawn]


def random_date_gen(
    start: pd.Timestamp,
    end: pd.Timestamp,
    n: int,
) -> np.ndarray:
    """Return ``n`` random dates in ``[start, end)`` formatted as ``CCYYMMDD`` strings."""
    start_s = start.value // 10**9
    end_s = end.value // 10**9
    dates = pd.to_datetime(np.random.randint(start_s, end_s, n), unit="s")
    return dates.strftime("%Y%m%d")
