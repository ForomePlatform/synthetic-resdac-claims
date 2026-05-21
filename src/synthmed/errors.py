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


# DOB drift is sampled as a sum of five independent Poisson layers, each
# scaled to a different temporal scale (days / few days / weeks / month
# / year). This mirrors the empirical shape of DOB-encoding errors in
# real Medicare data: most are off by one or two days (transposed digit),
# fewer by a week or so (month-edge confusion), and a long tail are
# off by months or a full year (year-typo). Each layer contributes a
# signed Poisson-distributed offset in days; the total is the sum.
_DOB_OFFSET_LAYERS: tuple[tuple[int, float], ...] = (
    # (day-scale, mean): scale * Poisson(mean) days, randomly signed.
    (1, 1.0),     # ~1 day off (digit transposition)
    (3, 0.2),     # ~few days off
    (10, 0.35),   # ~week off
    (30, 0.05),   # ~month off
    (365, 0.005), # ~year off (year-typo)
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
    """Return ``n`` randomly-signed Poisson-mixture day offsets as ``timedelta64[ns]``.

    Sums :data:`_DOB_OFFSET_LAYERS` to model real DOB-encoding errors,
    then guarantees every returned offset is non-zero so a flagged row
    always moves at least one day (otherwise a 99 %-probability zero
    from the smallest layer would make the "error" invisible).
    """
    days = np.zeros(n, dtype=np.int64)
    for scale, mean in _DOB_OFFSET_LAYERS:
        sign = 2 * np.random.randint(0, 2, n) - 1
        days += scale * np.random.poisson(mean, n) * sign

    still_zero = days == 0
    n_zero = int(still_zero.sum())
    if n_zero:
        sign = 2 * np.random.randint(0, 2, n_zero) - 1
        days[still_zero] = (1 + np.random.poisson(0.2, n_zero)) * sign

    return pd.to_timedelta(days, unit="D").to_numpy()


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
