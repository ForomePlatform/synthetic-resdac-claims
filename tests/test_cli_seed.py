"""Tests for the ``--seed`` CLI value resolver (incl. ``--seed today``)."""

from datetime import date

import argparse
import pytest

from synthmed.cli import resolve_seed, _build_parser


def test_resolve_seed_integer_literal():
    assert resolve_seed("12345") == 12345
    assert resolve_seed("0") == 0


def test_resolve_seed_today_is_run_date_yyyymmdd():
    expected = int(date.today().strftime("%Y%m%d"))
    assert resolve_seed("today") == expected
    assert resolve_seed(" TODAY ") == expected


def test_resolve_seed_rejects_garbage():
    with pytest.raises(argparse.ArgumentTypeError):
        resolve_seed("tomorrow")


def test_parser_accepts_seed_today():
    args = _build_parser().parse_args(
        [
            "generate",
            "--data-root", "x",
            "--distribution-dir", "x",
            "--sample-dir", "x",
            "--output-dir", "x",
            "--seed", "today",
        ]
    )
    assert args.seed == int(date.today().strftime("%Y%m%d"))
