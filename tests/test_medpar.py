"""Unit tests for MEDPAR-specific helpers.

Currently covers explicit duplicate-admission injection
(:func:`synthmed.medpar._inject_duplicate_admissions`). These tests
don't load any inputs and stand up a tiny synthetic ``medpar`` frame
in-memory.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from synthmed.medpar import _inject_duplicate_admissions


def _toy_medpar(n: int) -> pd.DataFrame:
    """Minimal MEDPAR-like frame with the columns the cloner touches."""
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "id": [f"BENE{i // 3:06d}" for i in range(n)],
        "adm_date": [f"2014{(i % 12) + 1:02d}15" for i in range(n)],
        "dis_date": [f"2014{(i % 12) + 1:02d}20" for i in range(n)],
        "diag_1": rng.choice(["4019", "25000", "2724", "4280"], size=n),
        "last_record": [(i % 3) == 2 for i in range(n)],
    })


def test_duplicate_admissions_zero_rate_is_noop():
    """Rate ≤ 0 returns the frame unchanged (and without copy overhead)."""
    medpar = _toy_medpar(100)
    result = _inject_duplicate_admissions(medpar, rate=0.0)
    assert result is medpar


def test_duplicate_admissions_appended_count_matches_rate():
    """Number of clones is within ~4σ of the configured binomial rate."""
    np.random.seed(0)
    n = 10_000
    rate = 0.1
    medpar = _toy_medpar(n)
    result = _inject_duplicate_admissions(medpar, rate=rate)

    n_clones = len(result) - n
    expected = n * rate
    sigma = np.sqrt(n * rate * (1 - rate))
    assert abs(n_clones - expected) < 4 * sigma, (
        f"got {n_clones} clones, expected {expected:.0f} ± 4σ ({4 * sigma:.0f})"
    )


def test_duplicate_admissions_are_byte_identical_to_source():
    """Each appended clone equals its source row in every column except last_record."""
    np.random.seed(1)
    n = 1_000
    rate = 0.05
    medpar = _toy_medpar(n)

    # Reproduce the same mask the function will draw so we know which
    # rows it will clone.
    np.random.seed(1)
    mask = np.random.rand(n) < rate

    np.random.seed(1)
    result = _inject_duplicate_admissions(medpar, rate=rate)

    n_clones = len(result) - n
    assert n_clones == int(mask.sum()) > 0

    expected = medpar.loc[mask].copy()
    expected["last_record"] = False
    expected = expected.reset_index(drop=True)
    actual = result.iloc[n:].reset_index(drop=True)

    pd.testing.assert_frame_equal(actual, expected)


def test_duplicate_admissions_force_last_record_false():
    """Even when the source row had last_record=True, the clone is False.

    Prevents double-emission of once-per-beneficiary outputs (notably
    the MEDPAR death-date column).
    """
    np.random.seed(2)
    # All rows are last-record; every clone must come from a True source.
    n = 200
    medpar = _toy_medpar(n)
    medpar["last_record"] = True

    result = _inject_duplicate_admissions(medpar, rate=0.5)
    clones = result.iloc[n:]
    assert len(clones) > 0
    assert not clones["last_record"].any(), (
        "clones must have last_record=False to avoid double-emitting "
        "once-per-beneficiary values"
    )
    # Originals untouched.
    assert result.iloc[:n]["last_record"].all()


def test_duplicate_admissions_handles_missing_last_record_column():
    """Frames without a last_record column are still safely cloneable."""
    np.random.seed(3)
    medpar = _toy_medpar(100).drop(columns=["last_record"])
    result = _inject_duplicate_admissions(medpar, rate=0.1)
    assert len(result) >= len(medpar)
    assert "last_record" not in result.columns
