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


# Two parallel sets of DE-SynPUF downloads are needed:
#
#   * The Inpatient Claims sample (1..20) drives the within-admission
#     joint diagnosis distribution.
#   * The Beneficiary Summary sample (1..20, 2008 vintage) carries the
#     per-beneficiary demographics used to stratify trajectory replay
#     (age × sex × state). The 2008 file is sufficient because the
#     demographic axes we stratify on -- sex, race, state of residence,
#     birth date -- are essentially time-invariant for the cohort.
#
# Each sample is published as a ZIP containing a single CSV with the
# matching stem.
_INPATIENT_URL = (
    "https://www.cms.gov/research-statistics-data-and-systems/"
    "downloadable-public-use-files/synpufs/downloads/"
    "de1_0_2008_to_2010_inpatient_claims_sample_{n}.zip"
)
_INPATIENT_CSV = "DE1_0_2008_to_2010_Inpatient_Claims_Sample_{n}.csv"

_BENEFICIARY_URL = (
    "https://www.cms.gov/research-statistics-data-and-systems/"
    "downloadable-public-use-files/synpufs/downloads/"
    "de1_0_2008_beneficiary_summary_file_sample_{n}.zip"
)
_BENEFICIARY_CSV = "DE1_0_2008_Beneficiary_Summary_File_Sample_{n}.csv"


@dataclass(frozen=True)
class Sample:
    """One DE-SynPUF sample file (inpatient claims or beneficiary summary)."""

    n: int
    sha256: str
    url_pattern: str
    csv_name_pattern: str

    @property
    def csv_name(self) -> str:
        return self.csv_name_pattern.format(n=self.n)

    @property
    def zip_url(self) -> str:
        return self.url_pattern.format(n=self.n)


def _inpatient(n: int, sha: str) -> Sample:
    return Sample(n=n, sha256=sha, url_pattern=_INPATIENT_URL, csv_name_pattern=_INPATIENT_CSV)


def _beneficiary(n: int, sha: str) -> Sample:
    return Sample(n=n, sha256=sha, url_pattern=_BENEFICIARY_URL, csv_name_pattern=_BENEFICIARY_CSV)


# SHA-256 hashes computed from a verified local copy of the CMS samples
# (inpatient: 2026-05-16; beneficiary: 2026-05-21). The CMS-hosted files
# are versionless; if a hash check fails after a successful download,
# the upstream content has changed.
INPATIENT_SAMPLES: tuple[Sample, ...] = (
    _inpatient( 1, "040e2489292f55a89838393303be9a7a6a5e38c41016df88090b7c561d975ae9"),
    _inpatient( 2, "8e7f26ae8d8fc49c7c988c2f55374c2c759f9942e0a110a303fbb78f3f1a4334"),
    _inpatient( 3, "aca2484aa9d852fb454a062c7593b35d31bf423a1f158058509d9059e88a5c8c"),
    _inpatient( 4, "1f67f31fd1777337edc1a373a9e3e2050c134f6d100ecd84eb8deb7de9ccff10"),
    _inpatient( 5, "2f0f57b20edc3a72a50e02c804b245d1dd1d6fe22f99cd3d7bcb4840f1be321d"),
    _inpatient( 6, "356e292dbbb46ff14be2fba083de0a8b1f6ca3a83358c4f2084c8ab9fbb37ac5"),
    _inpatient( 7, "b428b92dc6308a6d5cdc93a307e132553fe9d4a6f6dfc6244ae6a36bb4d1c815"),
    _inpatient( 8, "2f90d4911b8ac09d594ea82bc59ba75b8b95fa5e2a477ef669e3781898bf0c98"),
    _inpatient( 9, "56a084a0770d04892e2b30773fef4798f05b6c64fd30de6d1306820338492ca3"),
    _inpatient(10, "efe9e017aee2d5bdf48fefed599176a9240cd96856040c72783ebd5a7d63a9ea"),
    _inpatient(11, "3c0eac84529f8592ecdcc0dc82984cd7038de67038dc470fd5bc452a191b8bc3"),
    _inpatient(12, "0d48a89340b84a0b250b9f346b1cb5a2177233a9a586ead538eff9d44381f978"),
    _inpatient(13, "788aaab5ccf48620eeb0fd41dd72b89b270e655b5c76d5320d3030f8fda0addc"),
    _inpatient(14, "93f08a6de1d2bad93713707a7540258430c557e49eaf5ca5f9cdcc96e82cd5a4"),
    _inpatient(15, "514317822401acabff194d202c35b9b985ce72067c33073b7452f686cc1815cd"),
    _inpatient(16, "48d4f5c310a00813bfca44590fc9817b9a67045565ed2a3ad51ee3c1445863b4"),
    _inpatient(17, "56249c3e67a8972a47978936e4cee17c48e6b0b4df711772c21b9aa037967694"),
    _inpatient(18, "a6b5811deebc30f1dd0ca7bbba9724deae2ed68ad28789acebea182c2abaf62f"),
    _inpatient(19, "860e10b513e437ae4df41b957bb462c1fcc50d0584ecb7c510fe5928b151d316"),
    _inpatient(20, "98f86db9901b0e50076fc27e55b76079f516d8bf09c8c87d8d1227d8666a66a6"),
)


BENEFICIARY_SAMPLES: tuple[Sample, ...] = (
    _beneficiary( 1, "b83c724638bab8a2134b26b46ddec6f04938078cb32b7305227c3aba6814d7ac"),
    _beneficiary( 2, "e0e29338b392a7e176b11af67f6b0be88b02acc672983eeb983ad65fcc8e4668"),
    _beneficiary( 3, "2f11f542608b5f831c08b4dc931b4e34abbbc14b1585f784fb9c499be79876d5"),
    _beneficiary( 4, "104434d29b84c33d0eebbcf009135ee2354122ea802e25bc38ecb3763c5f9fcd"),
    _beneficiary( 5, "a72b32b4556d7915bf287cd6e7f80eb8d375e2d0140333d6cc859c6cbd72d1ff"),
    _beneficiary( 6, "57e7a22fd0642d4ebe6a00471c7145dfd4bf112f75448a097aee77a22111bf33"),
    _beneficiary( 7, "933e60257609775e7c86b8017486f755ae24847a4cb37f038f735d2c071ba6f6"),
    _beneficiary( 8, "9547a0a32a7413de1f674038d9de5a8b3521cca5774bd55e39cc041c6cd56a86"),
    _beneficiary( 9, "616afc0da4e3e7d3211f16a547be0fbb103ba2cdf397716e69f88c58cd34236c"),
    _beneficiary(10, "c51e423bac89bd6176d2fc345fba0cb7e69aafce6986099ebdf665ce2acca0d1"),
    _beneficiary(11, "2849ec27f05b8f25b356eece2dd2bcf638b143aae19417d1bfd192dcc375ff4b"),
    _beneficiary(12, "746b7b22930032e1b7aeb03ed287b41b5d492d0a02254ca9738bc28c5d6348d3"),
    _beneficiary(13, "37faba82110ab1a595fd96d3469c1f07c91c617c35bdce45b5235ed76e26e871"),
    _beneficiary(14, "2b3c562f512eab81612031e1b737bc864cb98f637e85524405688f8e69610644"),
    _beneficiary(15, "734eedf80de59f64ba692896c54fee29b3ef3b596f7cdcf541fd31848240c751"),
    _beneficiary(16, "ca9ee0bb92ea1877164692574c5337db8da8acee69770ad5a4d2c00c7bb074bb"),
    _beneficiary(17, "d3469a5a1173def37859d500ad437b2a78fd970af903cd2d672f697268c99a8b"),
    _beneficiary(18, "975fa375acf8bc72dd5b859d565a925aac52a718528429fc041ea79c8d5bf513"),
    _beneficiary(19, "540f5c4359304796309a8e7fce0f101ed1151f13953f0a917981cd55a61d50f7"),
    _beneficiary(20, "28457a33aa2ed799b5fcc6a406fc8748af4cde8030b868d23185d9d039e01033"),
)


ALL_SAMPLES: tuple[Sample, ...] = INPATIENT_SAMPLES + BENEFICIARY_SAMPLES


OFFLINE_ENV_VAR = "SYNTHMED_OFFLINE"


class OfflineError(RuntimeError):
    """Raised when a sample is missing and offline mode is set."""


class HashMismatchError(RuntimeError):
    """Raised when a downloaded sample's SHA-256 does not match the manifest."""


def _sha256_of(path: Path) -> str:
    """SHA-256 of the file content, normalizing CRLF to LF first.

    CMS has been observed to re-emit the DE-SynPUF ZIPs with Windows-style
    CRLF line endings without changing any actual record content. The
    manifest pins the content hash, not the byte hash, so the verifier
    is robust to that cosmetic churn while still tripping on any real
    data change.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for line in f:
            if line.endswith(b"\r\n"):
                h.update(line[:-2])
                h.update(b"\n")
            elif line.endswith(b"\r"):
                h.update(line[:-1])
                h.update(b"\n")
            else:
                h.update(line)
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
    samples: tuple[Sample, ...] = ALL_SAMPLES,
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
