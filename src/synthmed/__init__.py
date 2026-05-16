"""Synthetic ResDAC / Medicare claims generator.

`synthmed` produces fixed-width DAT files that conform to a set of ResDAC
File Transfer Specification (FTS) schemas, using a coherent internal cohort
of synthetic beneficiaries that is carried across years.

Typical use::

    from pathlib import Path
    from synthmed import GenerationConfig, run

    run(GenerationConfig(
        data_root=Path("input_files/data"),
        distribution_dir=Path("input_files/distribution_data"),
        sample_dir=Path("medicare_sample_data"),
        output_dir=Path("output_dat_files"),
        total_people=1000,
    ))

See ``docs-internal/Documentation.md`` for the underlying methodology.
"""

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData, load_distributions
from synthmed.pipeline import run

__all__ = [
    "GenerationConfig",
    "DistributionData",
    "load_distributions",
    "run",
]

__version__ = "0.1.0"
