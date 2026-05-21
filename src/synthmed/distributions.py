"""Load and bundle the reference distributions consumed during generation.

All loaders are called once per run by :func:`load_distributions`, which
returns a :class:`DistributionData` instance. The result is then threaded
through the cohort and per-column generators so that no module reaches
back into the filesystem during the hot loop.

See ``docs/distributions/*.md`` for the provenance, schema, and license
of each input file.
"""

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
    """Container for every reference dataset the generator needs.

    Built once by :func:`load_distributions` and passed by reference into
    the cohort / column / error / MEDPAR modules so that the hot path
    never re-reads the filesystem.
    """

    demographic: dict[str, Any]
    state_error_medpar: pd.DataFrame
    fip2ssa: pd.DataFrame
    zip2fips: pd.DataFrame
    zip2fips2pop: pd.DataFrame
    de_sample: pd.DataFrame
    faker: Faker
    addfips_helper: addfips.AddFIPS
    valid_zip_codes: list[str]


def _load_demographic_distributions(path: Path) -> dict[str, Any]:
    """Parse the JSON sex/race sampling weights into a nested dict."""
    df = pd.read_json(path, orient="index")
    return df.to_dict(orient="index")


def _build_zip2fips2pop(
    distribution_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Join the three crosswalk tables into a single ZIP-weighted sampling frame.

    Returns ``(fip2ssa, zip2fips, zip2fips2pop)``:

    - ``fip2ssa`` maps FIPS county codes to SSA county codes (NBER 2025).
    - ``zip2fips`` maps ZIPs to one representative FIPS county
      (clauswilke/zipcodes, currently 1:1; see TODO for HUD 1:N upgrade).
    - ``zip2fips2pop`` is ``zip2fips`` joined to 2020 ZCTA population so
      a downstream sampler can weight ZIP draws by population.

    ZIPs missing from the population table get the leftover mass
    redistributed uniformly across them — a placeholder for proper
    imputation. See ``docs/distributions/DECENNIALDHC2020.P1-Data.md``.
    """
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
        zip2fips,
        zip2pop[["ZIP", "POP"]],
        left_on="zipcode",
        right_on="ZIP",
        how="left",
    )
    zip2fips2pop["cum_POP"] = zip2fips2pop["POP"].cumsum()

    missing = zip2fips2pop["POP"].isna()
    if missing.any():
        leftover_share = (1 - zip2fips2pop["POP"].sum()) / missing.sum()
        zip2fips2pop.loc[missing, "POP"] = leftover_share

    return fip2ssa, zip2fips, zip2fips2pop


def _load_de_synpuf_sample(sample_dir: Path) -> pd.DataFrame:
    """Concatenate the 20 CMS DE-SynPUF inpatient sample CSVs.

    Missing files are downloaded lazily by
    :func:`synthmed.samples.ensure_samples` unless ``SYNTHMED_OFFLINE=1``
    is set in the environment.
    """
    ensure_samples(sample_dir)
    frames = [
        pd.read_csv(sample_dir / f"DE1_0_2008_to_2010_Inpatient_Claims_Sample_{i}.csv")
        for i in range(1, 21)
    ]
    return pd.concat(frames, ignore_index=True)


def load_distributions(
    distribution_dir: Path,
    sample_dir: Path,
) -> DistributionData:
    """Load every reference distribution needed by a generation run."""
    distribution_dir = Path(distribution_dir)
    sample_dir = Path(sample_dir)

    demographic = _load_demographic_distributions(
        distribution_dir / "demographic_distributions.json"
    )
    state_error_medpar = pd.read_csv(
        distribution_dir / "state_error_medpar_rates.csv"
    )

    fip2ssa, zip2fips, zip2fips2pop = _build_zip2fips2pop(distribution_dir)
    de_sample = _load_de_synpuf_sample(sample_dir)

    return DistributionData(
        demographic=demographic,
        state_error_medpar=state_error_medpar,
        fip2ssa=fip2ssa,
        zip2fips=zip2fips,
        zip2fips2pop=zip2fips2pop,
        de_sample=de_sample,
        faker=Faker(),
        addfips_helper=addfips.AddFIPS(),
        valid_zip_codes=[z["zip_code"] for z in zipcodes.list_all()],
    )
