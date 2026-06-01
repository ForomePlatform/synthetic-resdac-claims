"""MEDPAR-specific helpers.

The MEDPAR "internal database" repeats each beneficiary row
``number_of_records`` times so each admission carries the beneficiary's
demographics while still varying its diagnoses, admission dates, and
other claim-level attributes independently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData
from synthmed.internal_db import generate_diagnosis, mint_beneficiary_ids


def generate_medpar_internal_database(
    cohort: pd.DataFrame,
    dist: DistributionData,
    config: GenerationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Expand ``cohort`` into a per-admission MEDPAR frame.

    Returns ``(cohort, medpar)`` where ``medpar`` has one row per admission
    (each beneficiary repeated ``number_of_records`` times). The
    ``last_record`` boolean flags the final admission per beneficiary so
    downstream column generators can place once-per-person values
    (death-date, switches) on a single row.

    Orphan admissions — admissions whose ``id`` is rewritten to a fresh,
    never-enrolled ID — are then injected at ``config.orphan_admission_rate``
    to model the real-world Medicare pattern of admissions whose
    enrolment row is missing (enrolment-data lag, retroactive enrolment,
    admin errors). Diagnosis codes are sampled last so they are
    independent across admissions for the same beneficiary. Finally a
    small fraction of rows (``config.duplicate_admission_rate``) are
    cloned verbatim to model duplicate claims.
    """
    medpar = cohort.reindex(cohort.index.repeat(cohort.number_of_records))
    medpar["prev_id"] = medpar["id"].shift(-1)
    medpar["last_record"] = medpar["id"] != medpar["prev_id"]
    medpar = medpar.reset_index(drop=True)
    cohort = cohort.reset_index(drop=True)

    _inject_orphan_ids(medpar, config.orphan_admission_rate)
    medpar = generate_diagnosis(medpar, dist, config)
    medpar = _inject_duplicate_admissions(medpar, config.duplicate_admission_rate)
    return cohort, medpar


def _inject_orphan_ids(medpar: pd.DataFrame, rate: float) -> None:
    """Replace BENE_ID on a ``rate`` fraction of admissions with fresh, unseen IDs.

    The resulting MEDPAR rows have BENE_IDs that don't appear in MBSF,
    so downstream QC tooling (e.g. dorieh's ``medicare.qc_admissions``
    materialised view) sees them as orphan admissions — matching the
    pattern observed in real Medicare data. Operates in place.

    New IDs use the same 15-character format as
    :func:`synthmed.internal_db.mint_beneficiary_ids`, so format-based
    ID validators continue to pass.
    """
    if rate <= 0:
        return
    mask = np.random.rand(medpar.shape[0]) < rate
    n_orphans = int(mask.sum())
    if n_orphans == 0:
        return
    medpar.loc[mask, "id"] = mint_beneficiary_ids(n_orphans)


def _inject_duplicate_admissions(medpar: pd.DataFrame, rate: float) -> pd.DataFrame:
    """Clone a ``rate`` fraction of MEDPAR rows verbatim and append to the frame.

    Each cloned row carries the same BENE_ID, admission/discharge
    dates, diagnosis codes, and every other column as its source,
    modelling "duplicate claim" rows seen in real Medicare data
    (split bills, adjustments overlapping originals, crossover claims
    appearing twice). Downstream QC code is expected to detect and
    dedupe these.

    Clones are forced to ``last_record = False`` so the original row
    remains the single carrier of once-per-beneficiary outputs
    (notably the death-date column), avoiding double-emission of
    those values.

    Returns a new frame (concat of the original and the clones); does
    not mutate ``medpar`` in place.
    """
    if rate <= 0:
        return medpar
    mask = np.random.rand(medpar.shape[0]) < rate
    if not mask.any():
        return medpar
    duplicates = medpar.loc[mask].copy()
    if "last_record" in duplicates.columns:
        duplicates["last_record"] = False
    return pd.concat([medpar, duplicates], ignore_index=True)
