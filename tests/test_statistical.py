"""Goodness-of-fit checks on the distributions ``synthmed`` claims to emit.

Included in the default ``pytest`` run; opt out with
``pytest -m 'not statistical'`` if you only want the smoke and
reproducibility checks. The full file runs in about 5 s.

Each test seeds the RNGs inside its body so a pass/fail is reproducible
rather than flaky. Tolerances are deliberately loose (p > 0.01 for χ²,
~4σ binomial bands) — the goal is to catch a real distribution
regression, not to police small-N sampling noise.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUTS = REPO_ROOT / "inputs"
DISTRIBUTIONS = INPUTS / "distributions"
SAMPLES_DIR = INPUTS / "samples"


def _samples_present() -> bool:
    sentinel = SAMPLES_DIR / "DE1_0_2008_to_2010_Inpatient_Claims_Sample_1.csv"
    return sentinel.is_file()


pytestmark = [
    pytest.mark.statistical,
    pytest.mark.skipif(
        not _samples_present(),
        reason=(
            "DE-SynPUF samples not present under inputs/samples/; "
            "run `synthmed download-samples` first."
        ),
    ),
]


@pytest.fixture(scope="module")
def dist():
    """One full DistributionData load shared by every statistical test."""
    from synthmed.distributions import load_distributions
    return load_distributions(DISTRIBUTIONS, SAMPLES_DIR)


@pytest.fixture(scope="module")
def config_factory():
    """Factory for fresh GenerationConfig instances with paths pre-filled."""
    from synthmed.config import GenerationConfig

    def _make(**overrides):
        defaults: dict = dict(
            data_root=INPUTS / "schemas",
            distribution_dir=DISTRIBUTIONS,
            sample_dir=SAMPLES_DIR,
            output_dir=Path("/tmp/synthmed-stat-tests-unused"),
        )
        defaults.update(overrides)
        return GenerationConfig(**defaults)

    return _make


def _seed(seed: int) -> None:
    """Re-seed every RNG synthmed reads from. Mirrors pipeline._seed_all_rngs."""
    import random
    import faker as faker_mod
    random.seed(seed)
    np.random.seed(seed)
    faker_mod.Faker.seed(seed)


def _build_cohort(dist, config, n: int) -> pd.DataFrame:
    from synthmed.internal_db import generate_internal_database
    return generate_internal_database(
        num_people=n,
        dob_start=config.initial_dob_start,
        dob_end=config.initial_dob_end,
        generate_dead=True,
        death_year=2010,
        dist=dist,
        config=config,
    )


# ---------------------------------------------------------------------------
# Demographic marginals (claim: cohort race/sex match the JSON weights)
# ---------------------------------------------------------------------------


def _load_demographic_weights() -> dict[str, dict]:
    with open(DISTRIBUTIONS / "demographic_distributions.json") as f:
        return json.load(f)


@pytest.mark.parametrize("attribute", ["race", "sex"])
def test_demographic_marginal_chi2(dist, config_factory, attribute):
    """Cohort race/sex frequencies match the JSON sampling weights (χ², p > 0.01)."""
    _seed(42)
    n = 10_000
    cohort = _build_cohort(dist, config_factory(total_people=n), n)
    weights = _load_demographic_weights()[attribute]

    observed = (
        cohort[attribute].value_counts().reindex(weights["values"], fill_value=0)
    )
    expected_freq = np.array(weights["weights"]) * observed.sum()

    # Drop zero-expected bins (e.g. NA Native at 0.5 %, may be 0 expected at N=10k);
    # chisquare requires every expected count > 0.
    nonzero = expected_freq > 1
    chi2, p = stats.chisquare(
        f_obs=observed.values[nonzero],
        f_exp=expected_freq[nonzero],
    )
    assert p > 0.01, (
        f"{attribute}: χ²={chi2:.2f}, p={p:.4f} (n={n}); "
        f"observed={observed.to_dict()}, expected≈{dict(zip(weights['values'], expected_freq.round(1)))}"
    )


# ---------------------------------------------------------------------------
# Orphan admissions (claim: ~rate fraction of MEDPAR rows have unseen BENE_IDs)
# ---------------------------------------------------------------------------


def test_orphan_admission_rate(dist, config_factory):
    """Configured orphan_admission_rate=0.05 lands within a 4σ binomial band."""
    _seed(43)
    from synthmed.internal_db import generate_internal_database
    from synthmed.medpar import generate_medpar_internal_database

    rate = 0.05
    config = config_factory(
        total_people=10_000,
        average_medpar_records=1.0,  # → ~10k admissions (one per beneficiary)
        orphan_admission_rate=rate,
    )
    cohort = generate_internal_database(
        10_000, config.initial_dob_start, config.initial_dob_end,
        generate_dead=False, death_year=2010, dist=dist, config=config,
    )
    cohort, medpar = generate_medpar_internal_database(cohort, dist, config)

    base_ids = set(cohort["id"])
    n_orphan = int((~medpar["id"].isin(base_ids)).sum())
    n_total = len(medpar)
    observed = n_orphan / n_total

    sigma = np.sqrt(rate * (1 - rate) / n_total)
    lo, hi = rate - 4 * sigma, rate + 4 * sigma
    assert lo < observed < hi, (
        f"orphan rate {observed:.4f} not in [{lo:.4f}, {hi:.4f}] "
        f"(target={rate}, n_orphan={n_orphan}, n_total={n_total})"
    )


# ---------------------------------------------------------------------------
# Error injection rates
# ---------------------------------------------------------------------------


def test_race_error_rate(dist, config_factory):
    """Configured race-error rate lands within a 4σ binomial band."""
    _seed(44)
    from synthmed.errors import generate_internal_errors

    config = config_factory(
        total_people=10_000,
        overall_error_rate=0.05,   # set high so the test is sensitive
        race_error_rate=0.5,       # target marginal = 0.025
    )
    cohort = _build_cohort(dist, config, 10_000)
    cohort = generate_internal_errors(cohort, config)

    target = config.race_error_rate * config.overall_error_rate
    observed = cohort["race_error"].mean()
    n = len(cohort)
    sigma = np.sqrt(target * (1 - target) / n)
    lo, hi = target - 4 * sigma, target + 4 * sigma
    assert lo < observed < hi, (
        f"race-error rate {observed:.4f} not in [{lo:.4f}, {hi:.4f}] (target={target})"
    )


def test_dob_error_rate(dist, config_factory):
    """Configured DOB-error rate lands within a 4σ binomial band."""
    _seed(45)
    from synthmed.errors import generate_internal_errors

    config = config_factory(
        total_people=10_000,
        overall_error_rate=0.05,
        dob_error_rate=0.5,        # target marginal = 0.025
    )
    cohort = _build_cohort(dist, config, 10_000)
    cohort = generate_internal_errors(cohort, config)

    target = config.dob_error_rate * config.overall_error_rate
    observed = cohort["date_of_birth_error"].mean()
    n = len(cohort)
    sigma = np.sqrt(target * (1 - target) / n)
    lo, hi = target - 4 * sigma, target + 4 * sigma
    assert lo < observed < hi, (
        f"DOB-error rate {observed:.4f} not in [{lo:.4f}, {hi:.4f}] (target={target})"
    )


# ---------------------------------------------------------------------------
# Year-to-year cohort evolution (claim: deaths removed, ages +1, new 65s added)
# ---------------------------------------------------------------------------


def test_year_to_year_cohort_size_is_stable(dist, config_factory):
    """Under default `alive_ratio_sd`, per-year cohort swings stay within ±3 %.

    Pins the post-fix behaviour: the previously hardcoded
    ``alive_ratio * 0.1`` jitter (~σ = 0.095) produced bimodal swings
    of ±5pp+ year-over-year. The new ``alive_ratio_sd = 0.005`` default
    should keep yearly deltas within a tight band around the
    new-65 vs. deaths balance, regardless of seed.
    """
    from synthmed.internal_db import (
        generate_internal_database,
        increment_internal_database,
    )
    from synthmed.errors import generate_internal_errors

    config = config_factory(total_people=20_000)
    sizes = []
    for seed_offset in range(5):
        _seed(50 + seed_offset)
        cohort = generate_internal_database(
            20_000, 1940, 1950, generate_dead=True, death_year=2010,
            dist=dist, config=config,
        )
        sizes.append(len(cohort))
        for year in (2012, 2013, 2014, 2015, 2016):
            cohort = increment_internal_database(cohort, year, dist, config)
            cohort = generate_internal_errors(cohort, config)
            sizes.append(len(cohort))

    sizes_arr = np.asarray(sizes, dtype=float)
    # Group consecutive years per seed (6 sizes each) and check deltas.
    per_seed = sizes_arr.reshape(5, 6)
    pct_deltas = np.abs(np.diff(per_seed, axis=1) / per_seed[:, :-1])
    worst = pct_deltas.max()
    # Default alive_ratio = 0.97 and new = 0.05 produce ~2 %/yr mean
    # growth; with σ ≈ 0.7 % per year the 4σ envelope is roughly ±3 %
    # around the mean, so individual deltas land in ~[-1 %, +5 %].
    assert worst < 0.05, (
        f"max year-over-year cohort swing was {worst:.2%}; "
        f"expected < 5% under tightened alive_ratio_sd"
    )


def test_orec_invariant_across_years(dist, config_factory):
    """OREC is fixed at enrolment and stays identical across all of a beneficiary's years.

    Regression for the "OREC mutates across years" bug: previously
    ENTLMT_RSN_ORIG hit no override in ``char_generation`` and fell
    through to a per-year random-digit draw, silently breaking
    natural-joins like dorieh's ``enrollments ⋈ beneficiaries``.
    """
    _seed(47)
    from synthmed.internal_db import (
        generate_internal_database,
        increment_internal_database,
    )

    config = config_factory(total_people=3_000)
    cohort = generate_internal_database(
        3_000, 1940, 1950, generate_dead=True, death_year=2010,
        dist=dist, config=config,
    )
    orec_by_id = dict(zip(cohort["id"], cohort["orec"]))

    for year in (2012, 2013, 2014, 2015, 2016):
        cohort = increment_internal_database(cohort, year, dist, config)
        carried = cohort["id"].isin(orec_by_id)
        if not carried.any():
            continue
        observed = cohort.loc[carried, "orec"].to_numpy()
        expected = cohort.loc[carried, "id"].map(orec_by_id).to_numpy()
        mismatches = int((observed != expected).sum())
        assert mismatches == 0, (
            f"year {year}: {mismatches} beneficiaries changed OREC across years"
        )

    # OREC support is the four canonical ResDAC codes.
    assert set(np.unique(cohort["orec"])) <= {"0", "1", "2", "3"}


def test_year_evolution_invariants(dist, config_factory):
    """Increment removes deaths, ages survivors by one, and adds new 65-year-olds."""
    _seed(46)
    from synthmed.internal_db import (
        generate_internal_database,
        increment_internal_database,
    )

    config = config_factory(
        total_people=5_000,
        alive_ratio=0.9,
        new_year_new_patients_mean=0.05,
        new_year_new_patients_sd=0.001,
    )
    year1 = generate_internal_database(
        5_000, 1940, 1950, generate_dead=True, death_year=2010,
        dist=dist, config=config,
    )
    dead_in_year1 = set(year1.loc[year1["death_date"] != " ", "id"])
    alive_in_year1 = year1.loc[year1["death_date"] == " "].copy()
    ages_by_id_year1 = dict(zip(alive_in_year1["id"], alive_in_year1["age"]))

    year2 = increment_internal_database(year1, 2012, dist, config)

    # (1) Beneficiaries who died in year 1 must not appear in year 2.
    leaked = dead_in_year1 & set(year2["id"])
    assert not leaked, f"{len(leaked)} dead beneficiaries leaked into the next year"

    # (2) Beneficiaries who are still alive in year 2 must be aged +1.
    survivors_year2 = year2.loc[year2["death_date"] == " "].copy()
    survivors_year2 = survivors_year2[survivors_year2["id"].isin(ages_by_id_year1)]
    expected = survivors_year2["id"].map(ages_by_id_year1) + 1
    age_diff = (survivors_year2["age"].to_numpy() - expected.to_numpy())
    assert (age_diff == 0).all(), (
        f"{(age_diff != 0).sum()} surviving beneficiaries did not age by exactly 1"
    )

    # (3) New enrollees added at ~new_year_new_patients_mean rate (4σ band).
    new_ids = set(year2["id"]) - set(year1["id"])
    target_n = config.new_year_new_patients_mean * len(year1)
    sigma_n = config.new_year_new_patients_sd * len(year1)
    lo, hi = target_n - 4 * sigma_n, target_n + 4 * sigma_n
    assert lo < len(new_ids) < hi, (
        f"new-enrollee count {len(new_ids)} not in [{lo:.0f}, {hi:.0f}] "
        f"(target ≈ {target_n:.0f})"
    )


# ---------------------------------------------------------------------------
# State-correlated MEDPAR error rates (claim: per-state rates match the CSV)
# ---------------------------------------------------------------------------


def test_diagnosis_rows_are_verbatim_from_desynpuf(dist, config_factory):
    """Every synthetic MEDPAR diag_1..diag_10 row is a verbatim copy of some real DE-SynPUF admission row.

    This is the construction guarantee of trajectory replay: synthmed
    samples whole DE-SynPUF inpatient rows, so every emitted row must
    have an exact match in DE-SynPUF (modulo blank padding from
    samples with fewer than ten codes).
    """
    _seed(48)
    from synthmed.internal_db import generate_internal_database
    from synthmed.medpar import generate_medpar_internal_database

    config = config_factory(
        total_people=500, average_medpar_records=1.5,
        orphan_admission_rate=0.0,
    )
    cohort = generate_internal_database(
        500, config.initial_dob_start, config.initial_dob_end,
        generate_dead=False, death_year=2010, dist=dist, config=config,
    )
    cohort, medpar = generate_medpar_internal_database(cohort, dist, config)

    real_rows = set()
    for bene_adm in dist.desynpuf.admissions_by_bene.values():
        for row in bene_adm.diag_codes:
            real_rows.add(tuple(row))

    diag_cols = [f"diag_{i}" for i in range(1, 11)]
    synth_rows = [tuple(r) for r in medpar[diag_cols].to_numpy()]
    missing = [r for r in synth_rows if r not in real_rows]
    assert not missing, (
        f"{len(missing)} of {len(synth_rows)} synthetic diag rows not in DE-SynPUF; "
        f"first: {missing[0]}"
    )


def test_diagnosis_shared_within_synthetic_beneficiary(dist, config_factory):
    """A synthetic bene with k>1 admissions: those k rows come from one DE-SynPUF bene's history.

    Checks the across-admission joint contract: for every synthetic
    beneficiary whose MEDPAR contains 2+ admissions, all of that
    beneficiary's diag rows must trace to a single DE-SynPUF
    beneficiary -- i.e. there exists at least one DESYNPUF_ID whose
    admission set contains every one of those rows.
    """
    _seed(49)
    from synthmed.internal_db import generate_internal_database
    from synthmed.medpar import generate_medpar_internal_database

    config = config_factory(
        total_people=500, average_medpar_records=3.0,  # force several multi-admission benes
        orphan_admission_rate=0.0,
    )
    cohort = generate_internal_database(
        500, config.initial_dob_start, config.initial_dob_end,
        generate_dead=False, death_year=2010, dist=dist, config=config,
    )
    cohort, medpar = generate_medpar_internal_database(cohort, dist, config)

    # Build a row → set of source DE-SynPUF bene IDs index, for fast intersection.
    row_to_benes: dict[tuple, set[str]] = {}
    for bene_id, bene_adm in dist.desynpuf.admissions_by_bene.items():
        for row in bene_adm.diag_codes:
            row_to_benes.setdefault(tuple(row), set()).add(bene_id)

    diag_cols = [f"diag_{i}" for i in range(1, 11)]
    violations = []
    for synth_id, group in medpar.groupby("id", sort=False):
        if len(group) < 2:
            continue
        rows = [tuple(r) for r in group[diag_cols].to_numpy()]
        # Intersection of source-bene sets across the synthetic bene's k rows.
        common = row_to_benes.get(rows[0], set()).copy()
        for r in rows[1:]:
            common &= row_to_benes.get(r, set())
            if not common:
                break
        if not common:
            violations.append((synth_id, len(rows)))

    assert not violations, (
        f"{len(violations)} synthetic benes have admissions that can't trace to one DE-SynPUF bene"
    )


def test_dob_error_shape_peaks_at_month_boundaries(dist, config_factory):
    """DOB errors cluster at multiples of 30 days (month-typos), not in between.

    A 60-day error (= 2 months) is a single-character mistake in the
    month field and is empirically more common than a 40-day error
    (which requires both the month and the day to be wrong). Lock
    that ordering in so the additive-Poisson regression from the
    pre-2026-05-21 model doesn't sneak back.
    """
    _seed(50)
    from synthmed.errors import _sample_dob_offsets

    days = np.abs(pd.to_timedelta(_sample_dob_offsets(50_000)).days.to_numpy())

    def density_at(d: int) -> int:
        return int((days == d).sum())

    d30, d60, d90 = density_at(30), density_at(60), density_at(90)
    d40, d50, d70, d80 = density_at(40), density_at(50), density_at(70), density_at(80)

    # Each month boundary should clearly beat each in-between value.
    for boundary in (d30, d60, d90):
        assert boundary > 4 * max(d40, d50, d70, d80), (
            f"Month-boundary density {boundary} not >> off-boundary densities "
            f"40d={d40} 50d={d50} 70d={d70} 80d={d80}"
        )

    # Multiples of 30 should appear in approximate decreasing order
    # (1 month ≈ 2 months > 3 months under Poisson(1.0) on the count).
    assert d30 > d90 and d60 > d90, (
        f"Expected month-boundary tail: 30d={d30}, 60d={d60}, 90d={d90}"
    )


def test_state_medpar_error_rate(dist, config_factory):
    """For each well-sampled state, observed MEDPAR null-id+null-dob rate matches the CSV.

    Wide tolerance (5σ on the binomial mean) because the per-state sample
    size is small even at N=10k beneficiaries — most states get a few
    hundred admissions at most.
    """
    _seed(47)
    from synthmed.errors import generate_internal_medpar_errors
    from synthmed.internal_db import generate_internal_database
    from synthmed.medpar import generate_medpar_internal_database

    config = config_factory(
        total_people=10_000,
        average_medpar_records=2.0,  # ~20k admissions
        orphan_admission_rate=0.0,
    )
    cohort = generate_internal_database(
        10_000, config.initial_dob_start, config.initial_dob_end,
        generate_dead=False, death_year=2010, dist=dist, config=config,
    )
    cohort, medpar = generate_medpar_internal_database(cohort, dist, config)
    medpar = generate_internal_medpar_errors(medpar, dist)

    nulled = (medpar["id"] == " ") | (medpar["birth_date"] == " ")
    state_rates = dist.state_error_medpar.set_index("SSA Code")["Error Rate"]

    failures: list[str] = []
    for state, state_df in medpar.groupby("state_code"):
        try:
            target = float(state_rates.loc[int(state)])
        except KeyError:
            continue
        n_state = len(state_df)
        if n_state < 200:
            continue  # too small to be statistically informative
        observed = nulled.loc[state_df.index].mean()
        sigma = np.sqrt(target * (1 - target) / n_state)
        lo, hi = target - 5 * sigma, target + 5 * sigma
        if not (lo < observed < hi):
            failures.append(
                f"state={state}: observed={observed:.4f}, target={target:.4f}, "
                f"band=[{lo:.4f}, {hi:.4f}], n={n_state}"
            )

    # Tolerate up to 1 state out of band — at 5σ, a single false-positive
    # is still ~6e-7 expected, so even one failure means a real shift.
    assert len(failures) <= 1, (
        f"{len(failures)} states outside 5σ band:\n  " + "\n  ".join(failures)
    )
