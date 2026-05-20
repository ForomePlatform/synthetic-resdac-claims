"""Loading of external reference distributions used as generator inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import addfips
import pandas as pd
import zipcodes
from faker import Faker

from synthmed.samples import ensure_samples


@dataclass
class DistributionData:
    """Container for all reference data needed during generation.

    Built once per run by :func:`load_distributions` and threaded through
    the generator functions.
    """

    demographic: dict[str, Any]
    state_error_medpar: pd.DataFrame
    num_diag: pd.DataFrame
    fip2ssa: pd.DataFrame
    zip2fips: pd.DataFrame
    zip2fips2pop: pd.DataFrame
    de_sample: pd.DataFrame
    faker: Faker
    addfips_helper: addfips.AddFIPS
    valid_zip_codes: list[str]


def _load_demographic_distributions(path: Path) -> dict[str, Any]:
    df = pd.read_json(path, orient="index")
    return df.to_dict(orient="index")


def _build_zip2fips2pop(distribution_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fip2ssa = pd.read_csv(
        distribution_dir / "ssa_fips_state_county_2025.csv",
        dtype={"fipscounty": str, "ssa_code": str},
    )[["fipscounty", "ssa_code"]]

    zip2fips = pd.read_csv(
        distribution_dir / "zip2fips.csv",
        dtype={"zipcode": str, "FIPS": str},
    )[["zipcode", "FIPS"]]

    zip2pop = pd.read_csv(distribution_dir / "DECENNIALDHC2020.P1-Data.csv")
    zip2pop["ZIP"] = zip2pop["GEO_ID"].str.slice(9)
    zip2pop["POP"] = zip2pop["P1_001N"] / zip2pop["P1_001N"].sum()
    zip2pop = zip2pop[["ZIP", "POP"]]

    zip2fips2pop = pd.merge(
        zip2fips, zip2pop[["ZIP", "POP"]],
        left_on="zipcode", right_on="ZIP", how="left",
    )
    zip2fips2pop["cum_POP"] = zip2fips2pop["POP"].cumsum()
    missing = zip2fips2pop["POP"].isna()
    if missing.any():
        leftover = (1 - zip2fips2pop["POP"].sum()) / missing.sum()
        zip2fips2pop.loc[missing, "POP"] = leftover

    return fip2ssa, zip2fips, zip2fips2pop


def _load_de_sample(sample_dir: Path) -> pd.DataFrame:
    """Concatenate the CMS DE-SynPUF inpatient sample files (1..20).

    Missing files are downloaded from CMS via :func:`synthmed.samples.ensure_samples`
    unless ``SYNTHMED_OFFLINE=1`` is set in the environment.
    """
    ensure_samples(sample_dir)
    frames = []
    for i in range(1, 21):
        f = sample_dir / f"DE1_0_2008_to_2010_Inpatient_Claims_Sample_{i}.csv"
        frames.append(pd.read_csv(f))
    return pd.concat(frames, ignore_index=True)


def load_distributions(
    distribution_dir: Path,
    sample_dir: Path,
) -> DistributionData:
    """Load every reference distribution needed by a generation run.

    The work done here mirrors the initialization cells of the original
    notebook so behavior is unchanged; only the side-effects (module-level
    globals) are eliminated in favor of a returned dataclass.
    """
    distribution_dir = Path(distribution_dir)
    sample_dir = Path(sample_dir)

    demographic = _load_demographic_distributions(
        distribution_dir / "demographic_distributions.json"
    )
    state_error_medpar = pd.read_csv(
        distribution_dir / "state_error_medpar_rates.csv"
    )

    num_diag = pd.read_csv(
        distribution_dir / "number_of_diagnoses.csv", delimiter="\t"
    )

    fip2ssa, zip2fips, zip2fips2pop = _build_zip2fips2pop(distribution_dir)
    de_sample = _load_de_sample(sample_dir)

    return DistributionData(
        demographic=demographic,
        state_error_medpar=state_error_medpar,
        num_diag=num_diag,
        fip2ssa=fip2ssa,
        zip2fips=zip2fips,
        zip2fips2pop=zip2fips2pop,
        de_sample=de_sample,
        faker=Faker(),
        addfips_helper=addfips.AddFIPS(),
        valid_zip_codes=[z["zip_code"] for z in zipcodes.list_all()],
    )
