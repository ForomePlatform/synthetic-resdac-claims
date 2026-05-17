"""MEDPAR-specific helpers.

The MEDPAR "internal database" repeats each beneficiary row ``number_of_records``
times so that each generated record can share consistent demographics with
the master cohort while still varying its diagnosis codes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData
from synthmed.generators import random_char_gen
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

    _inject_orphan_ids(medpar, config.orphan_admission_rate)

    medpar = generate_diagnosis(medpar, dist, config)
    return base, medpar


def _inject_orphan_ids(medpar: pd.DataFrame, rate: float) -> None:
    """Replace BENE_ID on ``rate`` fraction of admissions with fresh, unseen IDs.

    Models the real-world Medicare pattern of admissions for beneficiaries
    whose enrollment row is missing in the admission month (enrollment-data
    lag, retroactive enrollment, admin errors). The resulting MEDPAR rows
    have BENE_IDs that don't appear in MBSF, so downstream QC tooling sees
    them as orphan admissions -- matching the behavior dorieh's
    ``medicare.qc_admissions`` materialized view expects.

    Operates in place on ``medpar``. New IDs use the same 12-char prefix
    + 3-digit suffix format as :func:`synthmed.internal_db.generate_location`,
    so format-based ID validators continue to pass.
    """
    if rate <= 0:
        return
    n = medpar.shape[0]
    mask = np.random.rand(n) < rate
    k = int(mask.sum())
    if k == 0:
        return
    blocks = int(np.ceil(k / 1000))
    block_prefixes = [random_char_gen(12, 1) for _ in range(blocks)]
    prefixes = np.repeat(block_prefixes, 1000)[:k]
    suffixes = np.tile(np.arange(1000), blocks)[:k].astype(str)
    suffixes = [s.zfill(3) for s in suffixes]
    medpar.loc[mask, "id"] = [p + s for p, s in zip(prefixes, suffixes)]
