"""Load and bundle the reference distributions consumed during generation.

All loaders are called once per run by :func:`load_distributions`, which
returns a :class:`DistributionData` instance. The result is then threaded
through the cohort and per-column generators so that no module reaches
back into the filesystem during the hot loop.

See ``docs/distributions/*.md`` for the provenance, schema, and license
of each input file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import addfips
import numpy as np
import pandas as pd
import zipcodes
from faker import Faker

from synthmed.samples import ensure_samples

log = logging.getLogger(__name__)

# DE-SynPUF beneficiary summary file demographic reference year. The
# 2008 file is sufficient because the stratification axes we care about
# (sex, state of residence, birth date) are essentially time-invariant
# over the 2008-2010 DE-SynPUF window.
_DESYNPUF_BSF_REFERENCE_YEAR = 2008
_DESYNPUF_DIAG_COLS = tuple(f"ICD9_DGNS_CD_{i}" for i in range(1, 11))


@dataclass(frozen=True)
class _BeneAdmissions:
    """One DE-SynPUF beneficiary's inpatient admission record, compact form.

    Stores only the ten ICD-9 diagnosis-code columns as a ``(k, 10)``
    object array so trajectory replay can index by row position without
    pandas overhead.
    """
    diag_codes: np.ndarray  # shape (k, 10), dtype object, missing → " "


@dataclass(frozen=True)
class DesynpufTrajectories:
    """DE-SynPUF inpatient admissions indexed for stratified trajectory replay.

    - ``admissions_by_bene`` maps each ``DESYNPUF_ID`` (that has at
      least one inpatient admission) to its compact admission record.
    - ``bene_ids_by_stratum`` indexes those bene-IDs by
      ``(age_band, sex, state)`` so :func:`synthmed.internal_db.generate_diagnosis`
      can pull a DE-SynPUF bene matching a synthetic bene's
      demographics. Strata follow the granularity the generator chose
      (currently age band × sex × state code).
    """
    admissions_by_bene: dict[str, _BeneAdmissions]
    bene_ids_by_stratum: dict[tuple[str, int, str], np.ndarray]


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
    desynpuf: DesynpufTrajectories
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


def age_band(age: int) -> str:
    """Map a Medicare age to one of three coarse bands used for stratification."""
    if age < 75:
        return "65-74"
    if age < 85:
        return "75-84"
    return "85+"


def _load_desynpuf_trajectories(sample_dir: Path) -> DesynpufTrajectories:
    """Load both DE-SynPUF sample sets and build a stratified trajectory index.

    Missing files are downloaded lazily by
    :func:`synthmed.samples.ensure_samples` unless ``SYNTHMED_OFFLINE=1``
    is set in the environment.

    The result indexes inpatient admissions by ``DESYNPUF_ID`` (compact
    array form) and provides a ``(age_band, sex, state) → bene-IDs``
    lookup whose values are sample pools restricted to beneficiaries
    with at least one inpatient admission.
    """
    ensure_samples(sample_dir)

    log.info("Loading 20 DE-SynPUF beneficiary summary files…")
    bsf = pd.concat(
        [
            pd.read_csv(
                sample_dir / f"DE1_0_2008_Beneficiary_Summary_File_Sample_{n}.csv",
                usecols=["DESYNPUF_ID", "BENE_BIRTH_DT", "BENE_SEX_IDENT_CD", "SP_STATE_CODE"],
                dtype={"DESYNPUF_ID": str, "BENE_BIRTH_DT": str},
            )
            for n in range(1, 21)
        ],
        ignore_index=True,
    )
    birth_year = pd.to_datetime(bsf["BENE_BIRTH_DT"], format="%Y%m%d").dt.year
    bsf["age_band"] = (_DESYNPUF_BSF_REFERENCE_YEAR - birth_year).map(age_band)
    bsf["state_str"] = bsf["SP_STATE_CODE"].astype(int).astype(str).str.zfill(2)

    log.info("Loading 20 DE-SynPUF inpatient claim files…")
    inpatient = pd.concat(
        [
            pd.read_csv(
                sample_dir / f"DE1_0_2008_to_2010_Inpatient_Claims_Sample_{n}.csv",
                usecols=["DESYNPUF_ID", *_DESYNPUF_DIAG_COLS],
                dtype={"DESYNPUF_ID": str, **{c: str for c in _DESYNPUF_DIAG_COLS}},
            )
            for n in range(1, 21)
        ],
        ignore_index=True,
    )
    for col in _DESYNPUF_DIAG_COLS:
        inpatient[col] = inpatient[col].fillna(" ")

    log.info("Indexing %d DE-SynPUF inpatient admissions by beneficiary…", len(inpatient))
    admissions_by_bene: dict[str, _BeneAdmissions] = {}
    diag_block = inpatient[list(_DESYNPUF_DIAG_COLS)].to_numpy(dtype=object)
    bene_ids = inpatient["DESYNPUF_ID"].to_numpy()
    # Sort by bene id once, then iterate consecutive runs to extract per-bene blocks.
    order = bene_ids.argsort(kind="stable")
    sorted_ids = bene_ids[order]
    sorted_diag = diag_block[order]
    # Find segment boundaries; each run of identical IDs becomes one bene record.
    change = np.flatnonzero(np.r_[True, sorted_ids[1:] != sorted_ids[:-1], True])
    for start, end in zip(change[:-1], change[1:]):
        admissions_by_bene[sorted_ids[start]] = _BeneAdmissions(
            diag_codes=sorted_diag[start:end]
        )

    benes_with_admissions = bsf["DESYNPUF_ID"].isin(admissions_by_bene)
    bsf_admitted = bsf.loc[benes_with_admissions, ["DESYNPUF_ID", "age_band", "BENE_SEX_IDENT_CD", "state_str"]]
    bene_ids_by_stratum: dict[tuple[str, int, str], np.ndarray] = {}
    for (band, sex, state), grp in bsf_admitted.groupby(["age_band", "BENE_SEX_IDENT_CD", "state_str"], sort=False):
        bene_ids_by_stratum[(band, int(sex), str(state))] = grp["DESYNPUF_ID"].to_numpy()
    log.info(
        "DE-SynPUF trajectories: %d benes with ≥1 admission across %d strata",
        len(admissions_by_bene), len(bene_ids_by_stratum),
    )

    return DesynpufTrajectories(
        admissions_by_bene=admissions_by_bene,
        bene_ids_by_stratum=bene_ids_by_stratum,
    )


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
    desynpuf = _load_desynpuf_trajectories(sample_dir)

    return DistributionData(
        demographic=demographic,
        state_error_medpar=state_error_medpar,
        fip2ssa=fip2ssa,
        zip2fips=zip2fips,
        zip2fips2pop=zip2fips2pop,
        desynpuf=desynpuf,
        faker=Faker(),
        addfips_helper=addfips.AddFIPS(),
        valid_zip_codes=[z["zip_code"] for z in zipcodes.list_all()],
    )
