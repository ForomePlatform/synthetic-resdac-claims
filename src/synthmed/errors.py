"""Error injection for the internal beneficiary and MEDPAR databases.

The injected errors model real-world data quality issues observed in
Medicare data: race miscoding, date-of-birth drift, missing MEDPAR rows,
and state-correlated null IDs / birth dates in MEDPAR.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData


def generate_internal_errors(
    base: pd.DataFrame,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Inject race, date-of-birth, and missing-MEDPAR errors into the cohort."""
    n = base.shape[0]

    base["race_error"] = np.random.rand(n) < config.race_error_rate * config.overall_error_rate
    masked = base["race_error"] == True  # noqa: E712 (pandas mask)
    base.loc[masked, "race"] = (
        base.loc[masked, "race"]
        + np.random.randint(1, 6, size=masked.sum())
    ) % 7

    base["birth_date"] = pd.to_datetime(base["birth_date"])
    base["date_of_birth_error"] = np.random.rand(n) < config.dob_error_rate * config.overall_error_rate
    dob_mask = base["date_of_birth_error"] == True  # noqa: E712
    k = dob_mask.sum()
    base["birth_date_error_amt"] = pd.to_timedelta(0)

    def _offset(scale: float, mean: float, size: int) -> pd.TimedeltaIndex:
        sign = 2 * np.random.randint(0, 2, size) - 1
        return pd.to_timedelta(scale * np.random.poisson(mean, size) * sign, unit="D")

    base.loc[dob_mask, "birth_date_error_amt"] += _offset(1, 1.0, k)
    base.loc[dob_mask, "birth_date_error_amt"] += _offset(3, 0.2, k)
    base.loc[dob_mask, "birth_date_error_amt"] += _offset(10, 0.35, k)
    base.loc[dob_mask, "birth_date_error_amt"] += _offset(30, 0.05, k)
    base.loc[dob_mask, "birth_date_error_amt"] += _offset(365, 0.005, k)

    still_zero = (base["birth_date_error_amt"] == pd.to_timedelta(0)) & dob_mask
    z = int(still_zero.sum())
    if z:
        sign = 2 * np.random.randint(0, 2, z) - 1
        base.loc[still_zero, "birth_date_error_amt"] += pd.to_timedelta(
            (1 + np.random.poisson(0.2, z)) * sign, unit="D"
        )

    base.loc[dob_mask, "birth_date"] += base.loc[dob_mask, "birth_date_error_amt"]
    base["birth_date"] = base["birth_date"].dt.strftime("%Y%m%d")

    base["number_of_records_error"] = np.random.rand(n) < config.no_medpar_error_rate
    base.loc[base["number_of_records_error"], "number_of_records"] = 0
    return base


def generate_internal_medpar_errors(
    medpar: pd.DataFrame,
    dist: DistributionData,
) -> pd.DataFrame:
    """Inject state-correlated nulls into MEDPAR ``id`` and ``birth_date``."""
    error_fields = ["id", "birth_date"]
    n_fields = len(error_fields)
    state_error = dist.state_error_medpar

    for state in medpar["state_code"].unique():
        state_rate = state_error.loc[
            state_error["SSA Code"] == int(state), "Error Rate"
        ].iloc[0]
        state_mask = medpar["state_code"] == state
        probs = np.random.rand(medpar.loc[state_mask].shape[0])
        for idx, field in enumerate(error_fields):
            lo = state_rate * idx / n_fields
            hi = state_rate * (idx + 1) / n_fields
            in_range = (lo <= probs) & (probs < hi)
            print(int(in_range.sum()))
            target = medpar.loc[state_mask].loc[in_range].index
            medpar.loc[target, field] = " "
    return medpar
