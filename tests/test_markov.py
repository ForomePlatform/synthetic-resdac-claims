"""Unit tests for the buy-in / HMO Markov coverage chains.

These tests don't load any DE-SynPUF samples and don't depend on
``inputs/``; they exercise ``_build_buyhmo_sequence`` and the cached
dispatch in ``char_generation`` directly. Two of these would have caught
the bugs found in the original buy-in/HMO merge: the missing return in
``char_generation`` (test_char_generation_returns_cached_markov_slices)
and the case-sensitivity mismatch on the chain-name dispatch
(test_char_generation_matches_label_case_insensitively).

Each test seeds ``numpy`` inside its body so a pass/fail is reproducible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from synthmed.columns import (
    _ENUMERATED_MARKOV_CHAINS,
    MarkovConfig,
    _build_buyhmo_sequence,
    char_generation,
)


# ---------------------------------------------------------------------------
# _build_buyhmo_sequence: shape, alphabet, proportions
# ---------------------------------------------------------------------------


@pytest.mark.statistical
@pytest.mark.parametrize(
    "chain_name", list(_ENUMERATED_MARKOV_CHAINS.keys())
)
def test_buyhmo_sequence_shape_and_alphabet(chain_name):
    """Output is ``(n, 12)`` and every code is in the configured alphabet."""
    np.random.seed(0)
    n = 5_000
    cfg = _ENUMERATED_MARKOV_CHAINS[chain_name]
    seq = _build_buyhmo_sequence(n, cfg)

    assert seq.shape == (n, 12)
    allowed = {cfg.dominant_code, cfg.secondary_code, *cfg.markov_states}
    actual = set(np.unique(seq).tolist())
    assert actual <= allowed, (
        f"{chain_name}: emitted codes {actual - allowed} not in alphabet {allowed}"
    )


@pytest.mark.statistical
@pytest.mark.parametrize(
    "chain_name", list(_ENUMERATED_MARKOV_CHAINS.keys())
)
def test_buyhmo_sequence_dominant_secondary_proportions(chain_name):
    """All-dominant and all-secondary row fractions match the config (~4σ band)."""
    np.random.seed(1)
    n = 20_000
    cfg = _ENUMERATED_MARKOV_CHAINS[chain_name]
    seq = _build_buyhmo_sequence(n, cfg)

    # Dominant-code rows and secondary-code rows are flat 12-month patterns;
    # Markov-walk rows can't contain dominant_code or secondary_code because
    # neither appears in markov_states, so identification is unambiguous.
    is_all_dominant = np.all(seq == cfg.dominant_code, axis=1)
    is_all_secondary = np.all(seq == cfg.secondary_code, axis=1)

    for label, observed, expected_p in [
        ("dominant", is_all_dominant.mean(), cfg.dominant_prob),
        ("secondary", is_all_secondary.mean(), cfg.secondary_prob),
    ]:
        sigma = np.sqrt(expected_p * (1 - expected_p) / n)
        assert abs(observed - expected_p) < 4 * sigma, (
            f"{chain_name}/{label}: observed {observed:.4f} vs expected "
            f"{expected_p:.4f} (4σ = {4 * sigma:.4f})"
        )


# ---------------------------------------------------------------------------
# Markov walk: stickiness and state coverage
# ---------------------------------------------------------------------------


@pytest.mark.statistical
def test_markov_walk_is_sticky_with_full_state_coverage():
    """With 100 % Markov-walk rows, adjacent months match ~99.5 % of the time.

    Uses a synthetic config that disables the dominant and secondary
    populations so every row is a pure Markov walk. The self-loop
    probability in ``_build_buyhmo_sequence`` is 0.995, so the aggregate
    adjacent-month match rate across all rows × 11 transitions should
    land tightly around 0.995.
    """
    np.random.seed(2)
    n = 5_000
    cfg = MarkovConfig(
        dominant_code="X",
        dominant_prob=0.0,
        secondary_code="Y",
        secondary_prob=0.0,
        markov_states=["1", "2", "4"],
    )
    seq = _build_buyhmo_sequence(n, cfg)

    # No row should contain the disabled dominant/secondary codes.
    assert "X" not in np.unique(seq).tolist()
    assert "Y" not in np.unique(seq).tolist()
    # All three states should appear somewhere in the matrix.
    assert set(np.unique(seq).tolist()) == set(cfg.markov_states)

    adjacent_matches = (seq[:, 1:] == seq[:, :-1]).mean()
    # Expected ≈ 0.995. n × 11 ≈ 55k trials, σ ≈ 0.0003, so 4σ ≈ 0.0012.
    # Use a loose 0.985–1.000 band; tighter bounds would be noise-sensitive.
    assert 0.985 < adjacent_matches < 1.0, (
        f"adjacent-month match rate {adjacent_matches:.4f} outside [0.985, 1.0]"
    )


# ---------------------------------------------------------------------------
# char_generation: cache invariants + per-chain separation
# ---------------------------------------------------------------------------


def _underlying(n: int) -> pd.DataFrame:
    """Minimal frame with the columns the buy-in/HMO branch actually reads."""
    return pd.DataFrame({"id": np.arange(n)})


def test_char_generation_returns_cached_markov_slices():
    """Months 1 and 2 of the same chain are columns 0 and 1 of one cached array.

    Regression for the missing ``return`` bug in the original merge: a
    missing return would fall through to the random-digit default, and
    the cached array would either be absent or unrelated to the values
    actually returned.
    """
    np.random.seed(3)
    n = 200
    underlying = _underlying(n)

    jan = char_generation(
        column_name="BUYIN01",
        column_width=1,
        column_label="Buy-In Indicator, January",
        underlying=underlying,
        is_medpar=False,
    )
    feb = char_generation(
        column_name="BUYIN02",
        column_width=1,
        column_label="Buy-In Indicator, February",
        underlying=underlying,
        is_medpar=False,
    )

    cached = underlying.attrs["_buyhmo_seq::buy-in indicator"]
    assert cached.shape == (n, 12)
    np.testing.assert_array_equal(np.asarray(jan.values), cached[:, 0])
    np.testing.assert_array_equal(np.asarray(feb.values), cached[:, 1])
    assert jan.fmt == "%s" and feb.fmt == "%s"


def test_char_generation_separates_caches_per_chain():
    """Buy-In and HMO get distinct cache entries, not a shared sequence."""
    np.random.seed(4)
    n = 500
    underlying = _underlying(n)

    char_generation(
        column_name="BUYIN01", column_width=1,
        column_label="Buy-In Indicator, January",
        underlying=underlying, is_medpar=False,
    )
    char_generation(
        column_name="HMOIND01", column_width=1,
        column_label="HMO Indicator, January",
        underlying=underlying, is_medpar=False,
    )

    cached_buyin = underlying.attrs["_buyhmo_seq::buy-in indicator"]
    cached_hmo = underlying.attrs["_buyhmo_seq::hmo indicator"]

    # Distinct cache objects (regression for the shared-key bug).
    assert cached_buyin is not cached_hmo

    # Alphabet check (regression for the per-chain config-dispatch bug):
    # buy-in Markov states are {0,1,2,A,B}; HMO Markov states are {1,2,4}.
    # If HMO had silently reused the buy-in config, we'd see "0", "A", or
    # "B" in the HMO sequence.
    hmo_codes = set(np.unique(cached_hmo).tolist())
    assert hmo_codes.isdisjoint({"0", "A", "B"}), (
        f"HMO sequence leaked buy-in-only codes: {hmo_codes & {'0', 'A', 'B'}}"
    )


def test_char_generation_matches_label_case_insensitively():
    """Mixed-case FTS labels still hit the lowercase dispatch dict.

    Regression for the case-sensitivity bug in the original merge: dict
    keys were lowercase but matched against the raw ``column_label``,
    so the Markov branch never fired in practice.
    """
    np.random.seed(5)
    n = 100
    underlying = _underlying(n)

    result = char_generation(
        column_name="BUYIN01",
        column_width=1,
        column_label="BUY-IN INDICATOR Code (Jan)",  # all-uppercase
        underlying=underlying,
        is_medpar=False,
    )

    assert "_buyhmo_seq::buy-in indicator" in underlying.attrs
    cached = underlying.attrs["_buyhmo_seq::buy-in indicator"]
    np.testing.assert_array_equal(np.asarray(result.values), cached[:, 0])
