"""Lazy downloader for the CMS DE-SynPUF inpatient sample CSVs.

These 20 files (~16 MB each as CSV, ~10 MB each zipped) are too large
to commit to git. :func:`ensure_samples` is invoked by
:func:`synthmed.distributions.load_distributions` and by the
``synthmed download-samples`` CLI subcommand: it checks the target
directory, downloads any missing files from CMS, unzips them, and
verifies their SHA-256 against the manifest below.

Set ``SYNTHMED_OFFLINE=1`` to disable the auto-download path; in that
mode a missing file raises rather than triggering a network call.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


# Parametric URL pattern. Sample 1..20 are each published as a ZIP that
# contains a single CSV with the same stem.
_URL_PATTERN = (
    "https://www.cms.gov/research-statistics-data-and-systems/"
    "downloadable-public-use-files/synpufs/downloads/"
    "de1_0_2008_to_2010_inpatient_claims_sample_{n}.zip"
)
_CSV_NAME_PATTERN = "DE1_0_2008_to_2010_Inpatient_Claims_Sample_{n}.csv"


@dataclass(frozen=True)
class Sample:
    """One DE-SynPUF inpatient sample file."""

    n: int
    sha256: str

    @property
    def csv_name(self) -> str:
        return _CSV_NAME_PATTERN.format(n=self.n)

    @property
    def zip_url(self) -> str:
        return _URL_PATTERN.format(n=self.n)


# SHA-256 hashes computed from a verified local copy of the CMS samples
# on 2026-05-16. The CMS-hosted files are versionless; if a hash check
# fails after a successful download, the upstream content has changed.
INPATIENT_SAMPLES: tuple[Sample, ...] = (
    Sample(1,  "040e2489292f55a89838393303be9a7a6a5e38c41016df88090b7c561d975ae9"),
    Sample(2,  "8e7f26ae8d8fc49c7c988c2f55374c2c759f9942e0a110a303fbb78f3f1a4334"),
    Sample(3,  "aca2484aa9d852fb454a062c7593b35d31bf423a1f158058509d9059e88a5c8c"),
    Sample(4,  "1f67f31fd1777337edc1a373a9e3e2050c134f6d100ecd84eb8deb7de9ccff10"),
    Sample(5,  "2f0f57b20edc3a72a50e02c804b245d1dd1d6fe22f99cd3d7bcb4840f1be321d"),
    Sample(6,  "356e292dbbb46ff14be2fba083de0a8b1f6ca3a83358c4f2084c8ab9fbb37ac5"),
    Sample(7,  "b428b92dc6308a6d5cdc93a307e132553fe9d4a6f6dfc6244ae6a36bb4d1c815"),
    Sample(8,  "2f90d4911b8ac09d594ea82bc59ba75b8b95fa5e2a477ef669e3781898bf0c98"),
    Sample(9,  "56a084a0770d04892e2b30773fef4798f05b6c64fd30de6d1306820338492ca3"),
    Sample(10, "efe9e017aee2d5bdf48fefed599176a9240cd96856040c72783ebd5a7d63a9ea"),
    Sample(11, "3c0eac84529f8592ecdcc0dc82984cd7038de67038dc470fd5bc452a191b8bc3"),
    Sample(12, "0d48a89340b84a0b250b9f346b1cb5a2177233a9a586ead538eff9d44381f978"),
    Sample(13, "788aaab5ccf48620eeb0fd41dd72b89b270e655b5c76d5320d3030f8fda0addc"),
    Sample(14, "93f08a6de1d2bad93713707a7540258430c557e49eaf5ca5f9cdcc96e82cd5a4"),
    Sample(15, "514317822401acabff194d202c35b9b985ce72067c33073b7452f686cc1815cd"),
    Sample(16, "48d4f5c310a00813bfca44590fc9817b9a67045565ed2a3ad51ee3c1445863b4"),
    Sample(17, "56249c3e67a8972a47978936e4cee17c48e6b0b4df711772c21b9aa037967694"),
    Sample(18, "a6b5811deebc30f1dd0ca7bbba9724deae2ed68ad28789acebea182c2abaf62f"),
    Sample(19, "860e10b513e437ae4df41b957bb462c1fcc50d0584ecb7c510fe5928b151d316"),
    Sample(20, "98f86db9901b0e50076fc27e55b76079f516d8bf09c8c87d8d1227d8666a66a6"),
)


OFFLINE_ENV_VAR = "SYNTHMED_OFFLINE"


class OfflineError(RuntimeError):
    """Raised when a sample is missing and offline mode is set."""


class HashMismatchError(RuntimeError):
    """Raised when a downloaded sample's SHA-256 does not match the manifest."""


def _sha256_of(path: Path, _chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_chunk):
            h.update(chunk)
    return h.hexdigest()


def _download_zip(url: str, dest: Path) -> None:
    """Stream ``url`` to ``dest`` atomically (writes to ``dest.tmp`` first)."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    log.info("downloading %s -> %s", url, dest)
    req = urllib.request.Request(url, headers={"User-Agent": "synthmed/0.1"})
    with urllib.request.urlopen(req) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out, length=1024 * 1024)
    tmp.replace(dest)


def _extract_single_csv(zip_path: Path, expected_csv_name: str, dest_dir: Path) -> Path:
    """Extract ``expected_csv_name`` from ``zip_path`` into ``dest_dir``."""
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.namelist()
        # CMS ZIPs sometimes hold the CSV at the root, sometimes nested; match by basename.
        match = next((m for m in members if Path(m).name == expected_csv_name), None)
        if match is None:
            raise RuntimeError(
                f"{zip_path}: ZIP does not contain {expected_csv_name!r}; "
                f"members={members!r}"
            )
        out_path = dest_dir / expected_csv_name
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        with zf.open(match) as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        tmp.replace(out_path)
        return out_path


def _fetch_one(sample: Sample, target_dir: Path) -> Path:
    csv_path = target_dir / sample.csv_name
    with tempfile.TemporaryDirectory(prefix="synthmed-dl-", dir=target_dir) as td:
        zip_path = Path(td) / f"sample_{sample.n}.zip"
        _download_zip(sample.zip_url, zip_path)
        _extract_single_csv(zip_path, sample.csv_name, target_dir)
    return csv_path


def _is_good(path: Path, expected_sha256: str) -> bool:
    if not path.is_file():
        return False
    return _sha256_of(path) == expected_sha256


def ensure_samples(
    target_dir: Path | str,
    *,
    offline: bool | None = None,
    force: bool = False,
    samples: tuple[Sample, ...] = INPATIENT_SAMPLES,
) -> Path:
    """Ensure every sample in ``samples`` exists under ``target_dir``.

    Missing or mis-hashed files are re-downloaded (unless ``offline`` is
    true, in which case a missing file raises :class:`OfflineError`).
    Returns ``target_dir`` for convenience.

    Parameters
    ----------
    target_dir:
        Cache directory. Created if it doesn't exist.
    offline:
        If ``True``, never hit the network; raise on missing files. If
        ``None`` (default), reads the ``SYNTHMED_OFFLINE`` env var.
    force:
        If ``True``, re-download every file even if a correct copy
        already exists locally.
    samples:
        Override the manifest (mostly for testing).
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    if offline is None:
        offline = os.environ.get(OFFLINE_ENV_VAR) == "1"

    for sample in samples:
        csv_path = target_dir / sample.csv_name
        if not force and _is_good(csv_path, sample.sha256):
            continue

        if csv_path.is_file() and not force:
            log.warning(
                "%s exists but SHA-256 mismatches manifest; re-downloading",
                csv_path,
            )

        if offline:
            raise OfflineError(
                f"{csv_path} is missing or corrupt and "
                f"{OFFLINE_ENV_VAR}=1; run `synthmed download-samples` or "
                f"populate {target_dir} manually."
            )

        _fetch_one(sample, target_dir)
        if not _is_good(csv_path, sample.sha256):
            raise HashMismatchError(
                f"{csv_path}: SHA-256 after download does not match the "
                f"pinned hash {sample.sha256}; CMS upstream content may "
                f"have changed."
            )
        log.info("ok %s", csv_path.name)

    return target_dir


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``synthmed download-samples``.

    Re-exported via :mod:`synthmed.cli`; you generally don't call this
    directly.
    """
    import argparse

    p = argparse.ArgumentParser(
        prog="synthmed download-samples",
        description="Download the CMS DE-SynPUF inpatient sample CSVs.",
    )
    p.add_argument("--target-dir", type=Path, default=Path("inputs/samples"))
    p.add_argument("--force", action="store_true",
                   help="Re-download every file even if a correct copy exists.")
    p.add_argument("--offline", action="store_true",
                   help="Refuse to hit the network; raise on missing files.")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    try:
        out = ensure_samples(args.target_dir, offline=args.offline, force=args.force)
    except (OfflineError, HashMismatchError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
