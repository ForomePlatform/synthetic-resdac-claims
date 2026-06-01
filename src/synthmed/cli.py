"""Command-line entry point: ``synthmed generate ...``."""

from __future__ import annotations

import argparse
from pathlib import Path

from synthmed.config import GenerationConfig
from synthmed.pipeline import run
from synthmed import samples as samples_mod


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthmed",
        description="Generate synthetic ResDAC/Medicare DAT files from FTS schemas.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Run the full generation pipeline.")
    g.add_argument("--data-root", type=Path, required=True,
                   help="Directory containing <cohort>/<year>/*.fts schema files.")
    g.add_argument("--distribution-dir", type=Path, required=True,
                   help="Directory with reference CSV/JSON distributions.")
    g.add_argument("--sample-dir", type=Path, required=True,
                   help="Directory with DE-SynPUF inpatient sample CSVs.")
    g.add_argument("--output-dir", type=Path, required=True,
                   help="Directory where generated DAT/FTS files will be written.")
    # CLI flags default to None so the GenerationConfig defaults in
    # config.py stay authoritative; only an explicit user value overrides.
    # Bumping a default in config.py is then enough -- no CLI drift.
    g.add_argument("--total-people", type=int, default=None,
                   help="Initial cohort size (default: GenerationConfig.total_people).")
    g.add_argument("--alive-ratio", type=float, default=None,
                   help="Mean per-year survival probability "
                        "(default: GenerationConfig.alive_ratio).")
    g.add_argument("--initial-dob-start", type=int, default=None)
    g.add_argument("--initial-dob-end", type=int, default=None)
    g.add_argument("--seed", type=int, default=None,
                   help="If set, seed all RNGs for reproducible output.")

    d = sub.add_parser(
        "download-samples",
        help="Download CMS DE-SynPUF inpatient sample CSVs into a cache dir.",
    )
    d.add_argument("--target-dir", type=Path, default=Path("inputs/samples"),
                   help="Where to cache the CSVs (default: inputs/samples).")
    d.add_argument("--force", action="store_true",
                   help="Re-download even if a correct copy exists.")
    d.add_argument("--offline", action="store_true",
                   help="Refuse to hit the network; raise on missing files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "generate":
        cli_overrides = {
            "total_people": args.total_people,
            "alive_ratio": args.alive_ratio,
            "initial_dob_start": args.initial_dob_start,
            "initial_dob_end": args.initial_dob_end,
            "seed": args.seed,
        }
        # Drop unset flags so GenerationConfig's own defaults take effect.
        cli_overrides = {k: v for k, v in cli_overrides.items() if v is not None}
        config = GenerationConfig(
            data_root=args.data_root,
            distribution_dir=args.distribution_dir,
            sample_dir=args.sample_dir,
            output_dir=args.output_dir,
            **cli_overrides,
        )
        run(config)
        return 0
    if args.command == "download-samples":
        return samples_mod.main([
            "--target-dir", str(args.target_dir),
            *(["--force"] if args.force else []),
            *(["--offline"] if args.offline else []),
        ])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
