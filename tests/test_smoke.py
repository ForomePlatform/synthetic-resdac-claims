"""End-to-end smoke test for the `synthmed` pipeline.

Runs a 100-patient generation with a fixed seed against the real
inputs/ tree and asserts that:

  * the pipeline completes without raising,
  * every input FTS schema has a matching .dat output,
  * every output file is non-empty, and
  * row counts fall in plausible bands.

Runtime is dominated by `load_distributions` (which concatenates ~320 MB
of DE-SynPUF samples), so this is a slow test — typically 30 s to a
minute on a developer laptop. It's the *smallest* test that exercises
real loaders, real schemas, and real output writing in one go.

Skipped automatically when `inputs/samples/` hasn't been populated
(e.g. fresh checkout, no `synthmed download-samples` run yet).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUTS = REPO_ROOT / "inputs"
SAMPLES_DIR = INPUTS / "samples"


def _samples_present() -> bool:
    """Cheap check; the lazy downloader handles full verification."""
    sentinel = SAMPLES_DIR / "DE1_0_2008_to_2010_Inpatient_Claims_Sample_1.csv"
    return sentinel.is_file()


@pytest.mark.skipif(
    not _samples_present(),
    reason=(
        "DE-SynPUF samples not present under inputs/samples/; "
        "run `synthmed download-samples` first."
    ),
)
def test_pipeline_smoke(tmp_path: Path) -> None:
    """100 patients, fixed seed, expect 'ran + outputs look right'."""
    from synthmed import GenerationConfig, run

    config = GenerationConfig(
        data_root=INPUTS / "schemas",
        distribution_dir=INPUTS / "distributions",
        sample_dir=SAMPLES_DIR,
        output_dir=tmp_path / "out",
        total_people=100,
        seed=42,
    )

    directory_map = run(config)
    assert directory_map, "pipeline returned an empty directory_map"

    for year, paths in directory_map.items():
        out = Path(paths["output"])
        ftses = sorted(out.glob("*.fts"))
        dats = sorted(out.glob("*.dat"))

        assert ftses, f"{year}: no FTS files copied to {out}"
        assert len(dats) == len(ftses), (
            f"{year}: expected one .dat per .fts in {out}; "
            f"got {len(dats)} .dat / {len(ftses)} .fts "
            f"(.dat names: {[d.name for d in dats]})"
        )

        # Each .dat is paired with a same-stem .fts
        fts_stems = {f.stem for f in ftses}
        dat_stems = {d.stem for d in dats}
        assert fts_stems == dat_stems, (
            f"{year}: FTS/DAT stem mismatch — "
            f"only-fts={fts_stems - dat_stems}, "
            f"only-dat={dat_stems - fts_stems}"
        )

        for dat in dats:
            size = dat.stat().st_size
            assert size > 0, f"{year}: empty DAT {dat}"

            n_lines = sum(1 for _ in dat.open("rb"))
            is_medpar = "medpar" in dat.name.lower()
            if is_medpar:
                # 100 patients × Poisson(0.267) admissions/patient ≈ ~27;
                # very loose band: anywhere between 0 and 500.
                assert 0 < n_lines < 500, (
                    f"{year}: MEDPAR {dat.name} has {n_lines} rows, "
                    f"outside plausible band [1, 500) for 100 patients"
                )
            else:
                # MBSF files: one row per beneficiary (after location drops);
                # the cohort grows slightly across years via increment.
                assert 0 < n_lines <= 200, (
                    f"{year}: MBSF {dat.name} has {n_lines} rows, "
                    f"outside plausible band [1, 200] for 100 patients"
                )


def test_seed_is_reproducible(tmp_path: Path) -> None:
    """Two runs with the same seed should produce byte-identical DAT files."""
    if not _samples_present():
        pytest.skip("DE-SynPUF samples not present under inputs/samples/")

    from synthmed import GenerationConfig, run

    def _run(out_subdir: str) -> dict[str, bytes]:
        config = GenerationConfig(
            data_root=INPUTS / "schemas",
            distribution_dir=INPUTS / "distributions",
            sample_dir=SAMPLES_DIR,
            output_dir=tmp_path / out_subdir,
            total_people=100,
            seed=123,
        )
        directory_map = run(config)
        return {
            f"{year}/{p.name}": p.read_bytes()
            for year, paths in directory_map.items()
            for p in sorted(Path(paths["output"]).glob("*.dat"))
        }

    first = _run("a")
    second = _run("b")
    assert first.keys() == second.keys(), "two runs produced different file sets"
    differing = [k for k in first if first[k] != second[k]]
    assert not differing, f"seeded runs differed in: {differing}"
