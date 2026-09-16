"""Tests for the durable run manifest (seed must never live only in stdout)."""

import json

from synthmed.config import GenerationConfig
from synthmed.pipeline import _write_manifest


def _config(tmp_path, seed):
    return GenerationConfig(
        data_root=tmp_path / "schemas",
        distribution_dir=tmp_path / "dist",
        sample_dir=tmp_path / "samples",
        output_dir=tmp_path / "out",
        seed=seed,
    )


def test_manifest_written_with_seed(tmp_path):
    path = _write_manifest(_config(tmp_path, 20260912))
    assert path == tmp_path / "out" / "generation-manifest.json"
    m = json.loads(path.read_text())
    assert m["seed"] == 20260912
    assert m["generator"] == "synthmed"
    assert "bit-identical" in m["reproducibility"]
    assert m["total_people"] > 0


def test_manifest_marks_unseeded_runs(tmp_path):
    m = json.loads(_write_manifest(_config(tmp_path, None)).read_text())
    assert m["seed"] is None
    assert "UNSEEDED" in m["reproducibility"]
