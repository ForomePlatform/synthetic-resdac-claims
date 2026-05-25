"""Error injection for the internal beneficiary and MEDPAR databases.

The injected errors model real-world data-quality issues observed in
Medicare data: race miscoding, date-of-birth drift, missing MEDPAR rows,
and state-correlated null IDs / birth dates in MEDPAR. The error rates
are configurable via :class:`synthmed.config.GenerationConfig` and the
state-correlated rates are loaded from
``inputs/distributions/state_error_medpar_rates.csv``.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData

log = logging.getLogger(__name__)


# DOB-encoding errors in real Medicare data cluster cleanly at month
# boundaries: a "wrong month, right day" mistake is a single-character
# error in one field, far more common than mistakes that get both the
# month AND the day wrong. We model this as a mixture of mutually
# exclusive error MODES rather than a sum of additive layers, so that
# a 60-day error (= 2 months, single-character month typo) is more
# common than a 40-day error (which requires both month and day to be
# off). Each affected beneficiary gets exactly one mode drawn from
# the mixture.
#
# Each mode entry is (name, weight, scale, lambda_offset):
#   total_offset_days = sign * scale * (1 + Poisson(lambda_offset))
# where (1 + Poisson) guarantees a non-zero offset, ``sign`` is ±1, and
# ``combined`` overlays a small day-scale offset on top of a month-
# scale offset to model the rare "both wrong" case.
_DOB_ERROR_MODE_MONTH = "month_off"
_DOB_ERROR_MODE_DAY = "day_off"
_DOB_ERROR_MODE_YEAR = "year_off"
_DOB_ERROR_MODE_COMBINED = "combined"
_DOB_ERROR_MODES: tuple[tuple[str, float], ...] = (
    (_DOB_ERROR_MODE_MONTH,    0.55),  # ±30, ±60, ±90 days …
    (_DOB_ERROR_MODE_DAY,      0.30),  # ±1 to ~5 days
    (_DOB_ERROR_MODE_YEAR,     0.05),  # ±365, ±730 days …
    (_DOB_ERROR_MODE_COMBINED, 0.10),  # month-scale + day-scale (rare)
)


def generate_internal_errors(
    cohort: pd.DataFrame,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Inject race-miscoding, DOB-drift, and missing-MEDPAR errors into the cohort.

    Modifies ``cohort`` in place (and returns it) by:

    1. Rotating ``race`` for a small fraction of beneficiaries (cyclic
       increment, preserves the categorical support).
    2. Shifting ``birth_date`` by a randomly-signed sum of Poisson offsets
       (see :data:`_DOB_OFFSET_LAYERS`) for a small fraction of beneficiaries.
    3. Zeroing ``number_of_records`` for a small fraction of beneficiaries
       so they generate no MEDPAR rows that year.

    Bookkeeping columns ``race_error``, ``date_of_birth_error``,
    ``birth_date_error_amt``, ``number_of_records_error`` are added so
    downstream code can audit which rows were touched.
    """
    n = cohort.shape[0]

    race_rate = config.race_error_rate * config.overall_error_rate
    cohort["race_error"] = np.random.rand(n) < race_rate
    raced = cohort["race_error"].to_numpy()
    cohort.loc[raced, "race"] = (
        cohort.loc[raced, "race"] + np.random.randint(1, 6, size=raced.sum())
    ) % 7

    cohort["birth_date"] = pd.to_datetime(cohort["birth_date"])
    dob_rate = config.dob_error_rate * config.overall_error_rate
    cohort["date_of_birth_error"] = np.random.rand(n) < dob_rate
    dob_mask = cohort["date_of_birth_error"].to_numpy()
    n_dob = int(dob_mask.sum())
    cohort["birth_date_error_amt"] = pd.to_timedelta(0)

    if n_dob:
        offsets = _sample_dob_offsets(n_dob)
        cohort.loc[dob_mask, "birth_date_error_amt"] = offsets
        cohort.loc[dob_mask, "birth_date"] += offsets

    cohort["birth_date"] = cohort["birth_date"].dt.strftime("%Y%m%d")

    cohort["number_of_records_error"] = np.random.rand(n) < config.no_medpar_error_rate
    cohort.loc[cohort["number_of_records_error"], "number_of_records"] = 0
    return cohort


def _sample_dob_offsets(n: int) -> np.ndarray:
    """Return ``n`` randomly-signed DOB error offsets as ``timedelta64[ns]``.

    For each of the ``n`` flagged beneficiaries, draws one error mode
    from :data:`_DOB_ERROR_MODES`, then samples the magnitude in that
    mode. Modes are mutually exclusive, so month-scale errors land
    cleanly on ±30, ±60, ±90 … while day-scale errors stay within a
    few days; the small ``combined`` weight produces the rare "both
    month and day wrong" outcomes that fill in the gaps between month
    boundaries. Every returned offset is non-zero (the magnitude
    formula uses ``1 + Poisson(…)``).
    """
    days = np.zeros(n, dtype=np.int64)
    mode_indices = np.random.choice(
        len(_DOB_ERROR_MODES),
        size=n,
        p=np.array([w for _, w in _DOB_ERROR_MODES]),
    )
    for i, (mode_name, _) in enumerate(_DOB_ERROR_MODES):
        mask = mode_indices == i
        k = int(mask.sum())
        if k == 0:
            continue
        days[mask] = _draw_mode(mode_name, k)
    return pd.to_timedelta(days, unit="D").to_numpy()


def _draw_mode(mode: str, k: int) -> np.ndarray:
    """Sample ``k`` signed day offsets for a single error mode."""
    sign = 2 * np.random.randint(0, 2, k) - 1
    if mode == _DOB_ERROR_MODE_MONTH:
        return 30 * (1 + np.random.poisson(1.0, k)) * sign
    if mode == _DOB_ERROR_MODE_DAY:
        return (1 + np.random.poisson(1.5, k)) * sign
    if mode == _DOB_ERROR_MODE_YEAR:
        return 365 * (1 + np.random.poisson(0.5, k)) * sign
    if mode == _DOB_ERROR_MODE_COMBINED:
        # Month-scale shift plus a small day-scale offset, signed together.
        month_part = 30 * (1 + np.random.poisson(1.0, k))
        day_part = 1 + np.random.poisson(1.5, k)
        return (month_part + day_part) * sign
    raise ValueError(f"Unknown DOB error mode {mode!r}")


def generate_internal_medpar_errors(
    medpar: pd.DataFrame,
    dist: DistributionData,
) -> pd.DataFrame:
    """Null MEDPAR ``id`` and ``birth_date`` at per-state rates from the distribution.

    For each state, the total error rate ``r`` from
    ``state_error_medpar_rates.csv`` is split evenly between the two
    affected fields: ``[0, r/2)`` of rows lose their ``id``, ``[r/2, r)``
    lose their ``birth_date``. The disjoint bands mean no single row can
    lose both via this mechanism (see TODO in
    ``docs/distributions/state_error_medpar_rates.md`` for the trade-off).

    Modifies ``medpar`` in place (and returns it).
    """
    error_fields = ("id", "birth_date")
    n_fields = len(error_fields)
    state_error = dist.state_error_medpar

    for state in medpar["state_code"].unique():
        state_rate = state_error.loc[
            state_error["SSA Code"] == int(state), "Error Rate"
        ].iloc[0]
        state_mask = medpar["state_code"] == state
        in_state = medpar.loc[state_mask]
        probs = np.random.rand(in_state.shape[0])
        for idx, field in enumerate(error_fields):
            lo = state_rate * idx / n_fields
            hi = state_rate * (idx + 1) / n_fields
            in_range = (lo <= probs) & (probs < hi)
            log.debug(
                "state=%s field=%s injecting %d nulls", state, field, int(in_range.sum())
            )
            target = in_state.loc[in_range].index
            medpar.loc[target, field] = " "
    return medpar
