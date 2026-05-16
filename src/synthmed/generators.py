"""Low-level random value generators used by higher-level modules."""

from __future__ import annotations

import string
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def random_char_gen(
    width: int,
    row: int,
    allowed_chars: Iterable[str] = string.ascii_uppercase,
    weights: Sequence[float] | None = None,
) -> list[str]:
    """Generate ``row`` strings, each the concatenation of ``width`` symbols.

    Parameters
    ----------
    width:
        Number of symbols drawn per output string.
    row:
        Number of strings to produce.
    allowed_chars:
        Pool of symbols to sample from. May be characters or fixed-length
        tokens (e.g. ``["10","20","30"]``).
    weights:
        Optional sampling weights aligned with ``allowed_chars``. Currently
        unused by ``np.random.choice`` here; preserved for API symmetry.
    """
    width = int(width)
    row = int(row)
    pool = list(allowed_chars)
    drawn = np.random.choice(pool, size=(row, width))
    return ["".join(r) for r in drawn]


def random_date_gen(
    start: pd.Timestamp,
    end: pd.Timestamp,
    num_entries: int,
) -> np.ndarray:
    """Generate ``num_entries`` random ``CCYYMMDD`` date strings in ``[start, end)``."""
    start_u = start.value // 10**9
    end_u = end.value // 10**9
    dates = pd.to_datetime(
        np.random.randint(start_u, end_u, num_entries), unit="s"
    )
    return dates.strftime("%Y%m%d")
