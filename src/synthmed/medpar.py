"""MEDPAR-specific helpers.

The MEDPAR "internal database" repeats each beneficiary row ``number_of_records``
times so that each generated record can share consistent demographics with
the master cohort while still varying its diagnosis codes.
"""

from __future__ import annotations

import pandas as pd

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData
from synthmed.internal_db import generate_diagnosis


def generate_medpar_internal_database(
    base: pd.DataFrame,
    dist: DistributionData,
    config: GenerationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(base, medpar)`` where ``medpar`` has one row per admission."""
    medpar = base.reindex(base.index.repeat(base.number_of_records))
    medpar["prev_id"] = medpar["id"].shift(-1)
    medpar["last_record"] = medpar["id"] != medpar["prev_id"]
    medpar = medpar.reset_index(drop=True)
    base = base.reset_index(drop=True)

    medpar = generate_diagnosis(medpar, dist, config)
    return base, medpar
