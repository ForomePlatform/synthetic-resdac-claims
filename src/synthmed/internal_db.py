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
from synthmed.distributions import DesynpufTrajectories, DistributionData, age_band
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
    # OREC (Original Reason for Entitlement) is fixed at enrolment and
    # invariant for the life of the beneficiary; we sample it ONCE here
    # so survivors carry the same value through every increment_year
    # call. Codes 0-3 are the canonical ResDAC OREC values: 0 = old-age,
    # 1 = disability, 2 = ESRD, 3 = both. CUREC ("Current Reason") is
    # allowed to vary and is still drawn per-year by columns.char_generation.
    cohort["orec"] = np.random.choice(["0", "1", "2", "3"], size=n)
    return cohort


def generate_diagnosis(
    medpar: pd.DataFrame,
    dist: DistributionData,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Attach ``diag_1..diag_max_diag_columns`` columns to ``medpar`` via stratified trajectory replay.

    Each synthetic beneficiary in ``medpar`` is matched to a DE-SynPUF
    beneficiary from the same ``(age_band, sex, state)`` stratum, and
    that DE-SynPUF beneficiary's actual inpatient admission diagnoses
    are sampled (without replacement when possible) to fill the
    synthetic beneficiary's ``k`` admissions. This preserves both the
    within-admission joint structure (whole ``diag_1..diag_10`` rows
    drawn together) and the across-admission joint structure (a single
    DE-SynPUF beneficiary's chronic-condition trajectory shapes all of
    one synthetic beneficiary's admissions for the year).

    Stratum fallback when an exact (age_band, sex, state) cell is
    empty: try (age_band, sex) ignoring state, then (age_band) ignoring
    sex, then the global pool of benes with ≥ 1 admission. State-level
    cells are usually fine; small-state fallbacks happen on a few-%
    of beneficiaries at developer-laptop cohort sizes.

    Columns ``diag_(sampled_diag_columns + 1)..diag_max_diag_columns``
    are left as blank space because DE-SynPUF caps inpatient diagnoses
    at ten ICD-9 codes per admission.
    """
    n = medpar.shape[0]
    diag_block = np.full((n, 10), " ", dtype=object)
    desynpuf = dist.desynpuf

    # Iterate unique synthetic beneficiaries in insertion order (the
    # natural order of medpar after reindex.repeat).
    grouped = medpar.groupby("id", sort=False)
    for bene_id, row_idx in grouped.indices.items():
        first = medpar.iloc[row_idx[0]]
        stratum = (
            age_band(int(first["age"])),
            _map_sex_to_desynpuf(int(first["sex"])),
            str(first["state_code"]),
        )
        pool = _stratum_pool(desynpuf, stratum)
        desynpuf_id = np.random.choice(pool)
        adm = desynpuf.admissions_by_bene[desynpuf_id].diag_codes
        n_real = adm.shape[0]
        k = len(row_idx)
        replace = k > n_real
        sampled = np.random.choice(n_real, size=k, replace=replace)
        diag_block[row_idx] = adm[sampled]

    for i in range(config.max_diag_columns):
        col = f"diag_{i + 1}"
        if i < config.sampled_diag_columns:
            medpar[col] = diag_block[:, i]
        else:
            medpar[col] = " "
    return medpar


def _map_sex_to_desynpuf(synth_sex: int) -> int:
    """Map synthmed's {0, 1, 2} sex codes to DE-SynPUF's {1, 2}.

    Synthmed uses 0 = Unknown, 1 = Male, 2 = Female (RTI convention);
    DE-SynPUF has only 1 = Male, 2 = Female. We send the rare
    Unknown stratum to Male (≈ 0.1 % of the cohort, so the bias is
    negligible) and let the stratum-fallback chain coarsen further if
    needed.
    """
    return 1 if synth_sex == 0 else synth_sex


def _stratum_pool(desynpuf: DesynpufTrajectories, stratum: tuple[str, int, str]) -> np.ndarray:
    """Return the DE-SynPUF bene-ID pool for a stratum, falling back coarser if empty."""
    band, sex, state = stratum
    pool = desynpuf.bene_ids_by_stratum.get((band, sex, state))
    if pool is not None and len(pool):
        return pool
    # Fall back to (age_band, sex) across all states.
    matches = [v for (b, s, _), v in desynpuf.bene_ids_by_stratum.items() if b == band and s == sex]
    if matches:
        return np.concatenate(matches)
    # Fall back to age_band only.
    matches = [v for (b, _, _), v in desynpuf.bene_ids_by_stratum.items() if b == band]
    if matches:
        return np.concatenate(matches)
    # Last resort: the global pool.
    return np.concatenate(list(desynpuf.bene_ids_by_stratum.values()))


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
    # Clip the drawn ratio so even a tail draw can't produce >20%
    # mortality (or <0.5%); see GenerationConfig.alive_ratio_sd.
    start_dod = pd.to_datetime(f"{last_year}-01-01")
    end_dod = pd.to_datetime(f"{last_year}-12-31")
    alive_ratio_jittered = float(np.clip(
        np.random.normal(config.alive_ratio, config.alive_ratio_sd),
        0.80, 0.995,
    ))
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
