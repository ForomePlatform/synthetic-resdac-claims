"""Build and evolve the internal beneficiary cohort.

The "cohort" (called the "internal database" in upstream documentation)
is a single pandas ``DataFrame``, one row per synthetic beneficiary,
that holds every attribute the per-column DAT generators read from:
identity, geography, demographics, MEDPAR admission count, and any
error flags from :mod:`synthmed.errors`.

This cohort *is* the MBSF source data: there is one row per beneficiary
and that row's columns are what get serialised into the MBSF
fixed-width DAT files. It also seeds MEDPAR via
:func:`synthmed.medpar.generate_medpar_internal_database`, which
repeats each cohort row ``number_of_records`` times to make the
per-admission frame.

The cohort is created once for the first calendar year by
:func:`generate_internal_database` and then advanced one calendar year
at a time by :func:`increment_internal_database`. The actual on-disk
write happens in :func:`synthmed.year.generate_year_files`.
"""

from __future__ import annotations

import logging
import random

import numpy as np
import pandas as pd

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData
from synthmed.generators import random_char_gen, random_date_gen

log = logging.getLogger(__name__)


_ID_BLOCK_SIZE = 1000
_ID_PREFIX_WIDTH = 12


def mint_beneficiary_ids(n: int) -> list[str]:
    """Return ``n`` 15-character synthetic beneficiary IDs.

    IDs are minted in blocks of 1000 sharing a single 12-character
    random prefix so they look like real CMS beneficiary IDs (which
    cluster on enrolment-batch boundaries) while remaining cheap to
    generate in bulk.
    """
    n_blocks = int(np.ceil(n / _ID_BLOCK_SIZE))
    block_prefixes = [random_char_gen(_ID_PREFIX_WIDTH, 1) for _ in range(n_blocks)]
    prefixes = np.repeat(block_prefixes, _ID_BLOCK_SIZE)[:n]
    suffixes = np.tile(np.arange(_ID_BLOCK_SIZE), n_blocks)[:n].astype(str)
    suffixes = [s.zfill(3) for s in suffixes]
    return [p + s for p, s in zip(prefixes, suffixes)]


def generate_location(cohort: pd.DataFrame, dist: DistributionData) -> pd.DataFrame:
    """Attach beneficiary ID, ZIP, FIPS, and SSA state/county codes to ``cohort``.

    ZIPs are sampled with weights proportional to 2020 ZCTA population
    so the cohort lands in plausible places. ZIPs that don't resolve to
    a known FIPS or SSA county are dropped silently — see TODO.md for
    the Connecticut planning-region edge case this exposes.
    """
    n = cohort.shape[0]

    cohort["id"] = mint_beneficiary_ids(n)
    cohort["zip4"] = dist.zip2fips2pop.sample(
        weights=dist.zip2fips2pop["POP"],
        replace=True,
        n=n,
    ).reset_index(drop=True)["zipcode"]
    cohort["zip"] = cohort["zip4"].str.slice(0, 5)

    cohort = pd.merge(cohort, dist.zip2fips, how="left", left_on="zip", right_on="zipcode")
    cohort = pd.merge(cohort, dist.fip2ssa, how="left", left_on="FIPS", right_on="fipscounty")

    cohort["state_code"] = cohort["ssa_code"].str.slice(0, 2)
    cohort["county_code"] = cohort["ssa_code"].str.slice(2, 5)

    cohort = cohort.dropna()
    cohort = cohort.drop_duplicates("id")
    return cohort.reset_index(drop=True)


def generate_demographic(
    cohort: pd.DataFrame,
    dist: DistributionData,
    config: GenerationConfig,
    dob_year_start: int,
    dob_year_end: int,
    generate_dead: bool = False,
    death_year: int = 2013,
) -> pd.DataFrame:
    """Attach ``birth_date``, ``death_date``, ``age``, ``sex``, ``race``.

    When ``generate_dead`` is true, a small ``(1 - alive_ratio)`` fraction
    of beneficiaries are killed off during ``death_year`` (used by the
    initial-cohort build so the very first year has plausible mortality).
    Otherwise everyone is left alive and the death-date column is the
    blank-space sentinel.
    """
    n = cohort.shape[0]

    start_dob = pd.to_datetime(f"{dob_year_start}-01-01")
    end_dob = pd.to_datetime(f"{dob_year_end}-12-31")
    cohort["birth_date"] = random_date_gen(start_dob, end_dob, n)

    cohort["death_date"] = " "
    if generate_dead:
        start_dod = pd.to_datetime(f"{death_year}-01-01")
        end_dod = pd.to_datetime(f"{death_year}-12-31")
        is_alive = np.random.rand(n) < config.alive_ratio
        cohort.loc[~is_alive, "death_date"] = random_date_gen(
            start_dod, end_dod, (~is_alive).sum()
        )

    cohort["age"] = (
        pd.to_datetime(cohort["death_date"], format="%Y%m%d", errors="coerce")
        .fillna(pd.Timestamp(f"{death_year}-12-31"))
        - pd.to_datetime(cohort["birth_date"], format="%Y%m%d")
    ).dt.days // 365

    cohort["sex"] = random.choices(
        dist.demographic["sex"]["values"],
        k=n,
        weights=dist.demographic["sex"]["weights"],
    )
    cohort["race"] = random.choices(
        dist.demographic["race"]["values"],
        k=n,
        weights=dist.demographic["race"]["weights"],
    )
    return cohort


def generate_diagnosis(
    cohort: pd.DataFrame,
    dist: DistributionData,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Attach ``diag_1..diag_max_diag_columns`` columns to ``cohort``.

    The first ``config.sampled_diag_columns`` columns are filled from one
    DE-SynPUF inpatient sample row per cohort row, preserving the
    within-admission joint distribution of diagnosis codes; the remaining
    slots (DE-SynPUF tops out at ten ICD-9 codes per admission) are left
    as blank spaces.
    """
    n = cohort.shape[0]
    sample = dist.de_sample.sample(n, ignore_index=True, replace=True)

    for i in range(config.max_diag_columns):
        col = f"diag_{i + 1}"
        if i < config.sampled_diag_columns:
            cohort[col] = sample[f"ICD9_DGNS_CD_{i + 1}"].fillna(" ")
        else:
            cohort[col] = " "
    return cohort


def generate_medpar_stats(cohort: pd.DataFrame, config: GenerationConfig) -> pd.DataFrame:
    """Attach ``number_of_records`` — a Poisson-distributed per-beneficiary admission count."""
    cohort["number_of_records"] = np.random.poisson(
        config.average_medpar_records, cohort.shape[0]
    )
    return cohort


def generate_internal_database(
    num_people: int,
    dob_start: int,
    dob_end: int,
    generate_dead: bool,
    death_year: int,
    dist: DistributionData,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Build a fresh internal database of (approximately) ``num_people`` rows.

    The actual row count is slightly less because :func:`generate_location`
    drops ZIPs that don't resolve to an SSA county. ``actual_id`` is
    pinned to the original ``id`` here so that subsequent merges
    (e.g. cross-file lookups in :mod:`synthmed.year`) can reach the
    original beneficiary identity even after later error-injection
    rounds rotate ``id`` for orphan-admission rows.
    """
    cohort = pd.DataFrame({"index_dummy": range(num_people), "id": range(num_people)})
    cohort = generate_location(cohort, dist)
    cohort = generate_demographic(
        cohort, dist, config, dob_start, dob_end, generate_dead, death_year
    )
    cohort = generate_medpar_stats(cohort, config)
    cohort = cohort.dropna(subset=["ssa_code"]).reset_index(drop=True)
    cohort["actual_id"] = cohort["id"]
    return cohort


def increment_internal_database(
    cohort: pd.DataFrame,
    next_year: int | str,
    dist: DistributionData,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Advance the cohort by one calendar year.

    Order of operations matters and is:

    1. Drop beneficiaries who already died in a previous year.
    2. Mint a fresh delta cohort of new 65-year-olds (configurable rate).
    3. Generate deaths for the surviving cohort during the elapsed year.
    4. Increment ages of those who are still alive.
    5. Re-draw MEDPAR admission counts for the survivors.
    6. Zero out MEDPAR counts for the configured fraction of new
       enrollees (mid-year enrollment lag).
    7. Concatenate survivors and delta into the year's cohort.
    """
    next_year_int = int(next_year)
    last_year = next_year_int - 1
    dob_65_year = next_year_int - 65

    # (1) Drop the already-dead.
    survivors = cohort.loc[cohort["death_date"] == " "].copy()

    # (2) Mint new 65-year-olds.
    n_new = int(
        np.floor(
            np.random.normal(
                config.new_year_new_patients_mean,
                config.new_year_new_patients_sd,
            )
            * cohort.shape[0]
        )
    )
    delta = generate_internal_database(
        n_new, dob_65_year, dob_65_year, False, last_year, dist, config
    )

    # (3) Kill off (1 - alive_ratio) of survivors during the elapsed year.
    start_dod = pd.to_datetime(f"{last_year}-01-01")
    end_dod = pd.to_datetime(f"{last_year}-12-31")
    alive_ratio_jittered = np.random.normal(
        config.alive_ratio, config.alive_ratio * 0.1
    )
    is_alive = np.random.rand(survivors.shape[0]) < alive_ratio_jittered
    n_deaths = int((~is_alive).sum())
    survivors["death_date"] = " "
    survivors.loc[~is_alive, "death_date"] = random_date_gen(
        start_dod, end_dod, n_deaths
    )

    # (4) Age survivors who didn't die this year.
    still_alive = survivors["death_date"] == " "
    survivors.loc[still_alive, "age"] = survivors.loc[still_alive, "age"] + 1

    # (5) Fresh MEDPAR admission counts for survivors.
    survivors = generate_medpar_stats(survivors, config)

    # (6) Zero out MEDPAR for a fraction of new enrollees (enrollment lag).
    no_medpar_mask = np.random.rand(delta.shape[0]) < config.new_enrollment_no_medpar_rate
    delta.loc[no_medpar_mask, "number_of_records"] = 0

    # (7) Concatenate.
    next_cohort = pd.concat([survivors, delta], ignore_index=True).reset_index(drop=True)
    log.info(
        "Transition %d → %d: −%d deaths during %d, +%d new 65-year-olds → cohort %d → %d",
        last_year, next_year_int, n_deaths, last_year, delta.shape[0],
        cohort.shape[0], next_cohort.shape[0],
    )
    return next_cohort
