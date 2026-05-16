"""Build and evolve the internal beneficiary cohort.

The "internal database" is a Pandas DataFrame that holds the canonical
beneficiary records (ID, location, demographics, MEDPAR record counts)
used to keep generated FTS files consistent across years.
"""

from __future__ import annotations

import random

import numpy as np
import pandas as pd

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData
from synthmed.generators import random_char_gen, random_date_gen


def generate_location(base: pd.DataFrame, dist: DistributionData) -> pd.DataFrame:
    """Attach ID, ZIP/FIPS, SSA state and county codes to ``base``."""
    num_people = base.shape[0]
    base["zip4"] = ""

    blocks = int(np.ceil(num_people / 1000))
    block_prefixes = [random_char_gen(12, 1) for _ in range(blocks)]
    prefixes = np.repeat(block_prefixes, 1000)[:num_people]
    suffixes = np.tile(np.arange(1000), int(np.ceil(num_people / 1000)))[:num_people].astype(str)
    suffixes = [s.zfill(3) for s in suffixes]
    base["id"] = [p + s for p, s in zip(prefixes, suffixes)]

    base["zip4"] = dist.zip2fips2pop.sample(
        weights=dist.zip2fips2pop["POP"],
        replace=True,
        n=num_people,
    ).reset_index(drop=True)["zipcode"]
    base["zip"] = base["zip4"].str.slice(0, 5)

    base = pd.merge(base, dist.zip2fips, how="left", left_on="zip", right_on="zipcode")
    base = pd.merge(base, dist.fip2ssa, how="left", left_on="FIPS", right_on="fipscounty")

    base["state_code"] = base["ssa_code"].str.slice(0, 2)
    base["county_code"] = base["ssa_code"].str.slice(2, 5)

    base = base.dropna()
    base = base.drop_duplicates("id")
    base = base.reset_index(drop=True)
    return base


def generate_demographic(
    base: pd.DataFrame,
    dist: DistributionData,
    config: GenerationConfig,
    dob_year_start: int,
    dob_year_end: int,
    generate_dead: bool = False,
    death_year: int = 2013,
) -> pd.DataFrame:
    """Attach birth date, death date, age, sex, race."""
    num_people = base.shape[0]

    start_dob = pd.to_datetime(f"{dob_year_start}-01-01")
    end_dob = pd.to_datetime(f"{dob_year_end}-12-31")
    base["birth_date"] = random_date_gen(start_dob, end_dob, num_people)

    base["death_date"] = " "
    if generate_dead:
        start_dod = pd.to_datetime(f"{death_year}-01-01")
        end_dod = pd.to_datetime(f"{death_year}-12-31")
        mask_alive = np.random.rand(num_people) < config.alive_ratio
        base.loc[~mask_alive, "death_date"] = random_date_gen(
            start_dod, end_dod, (~mask_alive).sum()
        )

    base["age"] = (
        pd.to_datetime(base["death_date"], errors="coerce")
        .fillna(pd.Timestamp(f"{death_year}-12-31"))
        - pd.to_datetime(base["birth_date"])
    ).dt.days // 365

    base["sex"] = random.choices(
        dist.demographic["sex"]["values"],
        k=num_people,
        weights=dist.demographic["sex"]["weights"],
    )
    base["race"] = random.choices(
        dist.demographic["race"]["values"],
        k=num_people,
        weights=dist.demographic["race"]["weights"],
    )
    return base


def generate_diagnosis(
    base: pd.DataFrame,
    dist: DistributionData,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Attach ``diag_1..diag_25`` columns sampled from the DE-SynPUF data."""
    num_people = base.shape[0]
    temp_sample = dist.de_sample.sample(num_people, ignore_index=True, replace=True)
    base["number_of_diagnoses"] = random.choices(
        dist.num_diag["number of diagnoses"],
        k=num_people,
        weights=dist.num_diag["share_of_rows"],
    )
    for i in range(config.max_diag_columns):
        j = i + 1
        col = f"diag_{j}"
        if i < config.sampled_diag_columns:
            base[col] = " "
            base[col] = temp_sample[f"ICD9_DGNS_CD_{j}"]
            base[col] = base[col].fillna(" ")
        else:
            base[col] = " "
    return base


def generate_medpar_stats(base: pd.DataFrame, config: GenerationConfig) -> pd.DataFrame:
    """Attach Poisson-distributed ``number_of_records`` per beneficiary."""
    base["number_of_records"] = np.random.poisson(
        config.average_medpar_records, base.shape[0]
    )
    return base


def generate_internal_database(
    num_people: int,
    dob_start: int,
    dob_end: int,
    generate_dead: bool,
    death_year: int,
    dist: DistributionData,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Create a fresh internal beneficiary database of (approximately) ``num_people``."""
    base = pd.DataFrame()
    base["index_dummy"] = range(num_people)
    base["id"] = range(num_people)
    base = generate_location(base, dist)
    base = generate_demographic(
        base, dist, config, dob_start, dob_end, generate_dead, death_year
    )
    base = generate_medpar_stats(base, config)

    base = base.dropna(subset=["ssa_code"])
    base = base.reset_index(drop=True)
    base["actual_id"] = base["id"]
    return base


def increment_internal_database(
    base: pd.DataFrame,
    next_year: int | str,
    dist: DistributionData,
    config: GenerationConfig,
) -> pd.DataFrame:
    """Advance the cohort one year forward.

    - Drops beneficiaries that died last year.
    - Generates fresh deaths for last year among survivors.
    - Adds a small cohort of new 65-year-olds.
    """
    print("incrementing internal database")
    next_year_int = int(next_year)
    dob_65_year = next_year_int - 65

    new_people_num = int(
        np.floor(
            np.random.normal(
                config.new_year_new_patients_mean,
                config.new_year_new_patients_sd,
            )
            * base.shape[0]
        )
    )
    print(new_people_num)

    delta = generate_internal_database(
        new_people_num, dob_65_year, dob_65_year, False, next_year_int - 1, dist, config
    )
    print("after delta")

    alive = base.loc[base["death_date"] == " "]
    base = alive

    start_dod = pd.to_datetime(f"{next_year_int - 1}-01-01")
    end_dod = pd.to_datetime(f"{next_year_int - 1}-12-31")
    mask_alive = np.random.rand(alive.shape[0]) < np.random.normal(
        config.alive_ratio, config.alive_ratio * 0.1
    )
    alive["death_date"] = " "
    alive.loc[~mask_alive, "death_date"] = random_date_gen(
        start_dod, end_dod, (~mask_alive).sum()
    )
    base.loc[base["death_date"] == " ", "death_date"] = alive["death_date"]

    base.loc[base["death_date"] == " ", "age"] = alive["age"] + 1

    base = generate_medpar_stats(base, config)

    error_mask = np.random.rand(delta.shape[0]) < config.new_enrollment_no_medpar_rate
    delta.loc[error_mask, "number_of_records"] = 0

    base = pd.concat([base, delta], ignore_index=True)
    base = base.reset_index(drop=True)
    return base
