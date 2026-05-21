"""Synthetic ResDAC / Medicare claims generator.

`synthmed` produces fixed-width DAT files that conform to a set of ResDAC
File Transfer Specification (FTS) schemas, using a coherent internal cohort
of synthetic beneficiaries that is carried across years.

Typical use::

    from pathlib import Path
    from synthmed import GenerationConfig, run

    run(GenerationConfig(
        data_root=Path("inputs/schemas"),
        distribution_dir=Path("inputs/distributions"),
        sample_dir=Path("inputs/samples"),
        output_dir=Path("output_dat_files"),
        total_people=1000,
        seed=42,
    ))
"""

from importlib.metadata import PackageNotFoundError, version

from synthmed.config import GenerationConfig
from synthmed.distributions import DistributionData, load_distributions
from synthmed.pipeline import run

__all__ = [
    "GenerationConfig",
    "DistributionData",
    "load_distributions",
    "run",
    "__version__",
]

try:
    __version__ = version("synthmed")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
