"""Unit tests for JEDEC timing CSV loader (issue #16)."""

from __future__ import annotations

import math
from pathlib import Path
from textwrap import dedent

import pytest

from CocoTBFramework.components.dfi.jedec_timings import (
    JedecTimings,
    builtin_timings,
    load_timings,
    ns_to_cycles,
)


# ---------------------------------------------------------------------
# ns_to_cycles arithmetic
# ---------------------------------------------------------------------


def test_ns_to_cycles_rounds_up():
    """Spec convention: ceil so the BFM enforces at least the timing
    the spec calls for. 13.75 / 1.25 = 11.0 exactly here."""
    assert ns_to_cycles(13.75, 1.25) == 11


def test_ns_to_cycles_rounds_up_when_not_exact():
    """ceil(15.0 / 1.25) = ceil(12.0) = 12, but 14.99/1.25 = 11.99 → 12."""
    assert ns_to_cycles(14.99, 1.25) == 12


def test_ns_to_cycles_rejects_zero_clock():
    with pytest.raises(ValueError, match="tCK_ns must be positive"):
        ns_to_cycles(13.75, 0)


# ---------------------------------------------------------------------
# Builtin DDR3-1600 CSV
# ---------------------------------------------------------------------


def test_builtin_ddr3_1600_loads_clean():
    t = builtin_timings("ddr3-1600")
    assert isinstance(t, JedecTimings)
    assert t.tCK_ns == 1.25
    # DDR3-1600 standard: tRCD = 13.75 ns → 11 cycles at 800 MHz DFI clock
    assert t.tRCD_cycles == 11
    assert t.tRP_cycles == 11
    assert t.CL == 11
    assert t.CWL == 8
    assert t.BL == 8


def test_builtin_ddr3_1600_tras_correct():
    t = builtin_timings("ddr3-1600")
    # tRAS_min = 35.0 ns → ceil(35.0 / 1.25) = 28 cycles
    assert t.tRAS_min_cycles == 28


# ---------------------------------------------------------------------
# CSV parsing — happy path
# ---------------------------------------------------------------------


def _write_csv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.csv"
    p.write_text(dedent(content))
    return p


def test_csv_strips_comments_and_blanks(tmp_path):
    p = _write_csv(tmp_path, """
        # comment line 1

        # comment line 2
        parameter, unit, value, description
        tCK,       ns,   1.25,  clock
        tRCD,      ns,   13.75, ACT to RD
        tRP,       ns,   13.75, PRE
        tRAS_min,  ns,   35.0,  ACT to PRE
        tRC,       ns,   48.75, ACT to ACT
        tWR,       ns,   15.0,  write recovery
        tWTR,      ns,   7.5,   WR to RD
        tRTP,      ns,   7.5,   RD to PRE
        tRRD,      ns,   6.0,   ACT to ACT diff bank
        tFAW,      ns,   30.0,  4 ACT window
        tREFI,     ns,   7800,  refresh interval
        tRFC,      ns,   260,   refresh cycle
        CL,        CK,   11,    CAS latency
        CWL,       CK,   8,     CAS write latency
        BL,        beats,8,     burst length
    """)
    t = load_timings(p)
    assert t.tCK_ns == 1.25
    assert t.tRCD_cycles == 11


def test_csv_passes_through_extras(tmp_path):
    """Unknown parameters get stashed in .extras for forward compat."""
    p = _write_csv(tmp_path, """
        parameter, unit, value, description
        tCK,       ns,   1.25,  clock
        tRCD,      ns,   13.75, _
        tRP,       ns,   13.75, _
        tRAS_min,  ns,   35.0,  _
        tRC,       ns,   48.75, _
        tWR,       ns,   15.0,  _
        tWTR,      ns,   7.5,   _
        tRTP,      ns,   7.5,   _
        tRRD,      ns,   6.0,   _
        tFAW,      ns,   30.0,  _
        tREFI,     ns,   7800,  _
        tRFC,      ns,   260,   _
        CL,        CK,   11,    _
        CWL,       CK,   8,     _
        BL,        beats,8,     _
        tXYZ_future, CK, 42,    future param the loader doesn't know
    """)
    t = load_timings(p)
    assert "tXYZ_future" in t.extras
    assert t.extras["tXYZ_future"] == 42


# ---------------------------------------------------------------------
# CSV parsing — error paths
# ---------------------------------------------------------------------


def test_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_timings("/nonexistent/path.csv")


def test_load_missing_tCK_raises(tmp_path):
    p = _write_csv(tmp_path, """
        parameter, unit, value, description
        tRCD,      ns,   13.75, _
    """)
    with pytest.raises(ValueError, match="tCK"):
        load_timings(p)


def test_load_missing_required_param_raises(tmp_path):
    p = _write_csv(tmp_path, """
        parameter, unit, value, description
        tCK,       ns,   1.25,  _
        tRCD,      ns,   13.75, _
    """)
    # tRP and friends are missing
    with pytest.raises(ValueError, match="missing required parameter"):
        load_timings(p)


def test_load_bad_header_raises(tmp_path):
    p = _write_csv(tmp_path, """
        wrong, header, here
        tCK,   ns,     1.25
    """)
    with pytest.raises(ValueError, match="bad header"):
        load_timings(p)


def test_load_unknown_unit_raises(tmp_path):
    """An unknown unit should be a clear error, not silent corruption."""
    p = _write_csv(tmp_path, """
        parameter, unit, value, description
        tCK,       ns,   1.25,  _
        tRCD,      bogus,13.75, _
        tRP,       ns,   13.75, _
        tRAS_min,  ns,   35.0,  _
        tRC,       ns,   48.75, _
        tWR,       ns,   15.0,  _
        tWTR,      ns,   7.5,   _
        tRTP,      ns,   7.5,   _
        tRRD,      ns,   6.0,   _
        tFAW,      ns,   30.0,  _
        tREFI,     ns,   7800,  _
        tRFC,      ns,   260,   _
        CL,        CK,   11,    _
        CWL,       CK,   8,     _
        BL,        beats,8,     _
    """)
    with pytest.raises(ValueError, match="Unknown unit"):
        load_timings(p)


# ---------------------------------------------------------------------
# Vendored profiles (issue #49)
# ---------------------------------------------------------------------
# The CSVs are package data. They were absent from every built wheel until
# pyproject declared them, and `builtin_timings` resolves them against the
# INSTALLED module, so the failure only appeared downstream. Enumerating the
# directory means a newly vendored profile is covered the moment it lands
# rather than when someone remembers to add a case.

def _vendored_profiles():
    jedec = Path(builtin_timings.__globals__["__file__"]).parent / "jedec"
    return sorted(p.stem for p in jedec.glob("*.csv"))


def test_jedec_directory_is_present_and_populated():
    """Catches the install-time symptom: the data directory vanishing whole."""
    assert _vendored_profiles(), (
        "no vendored JEDEC CSVs found next to jedec_timings -- if this fails "
        "in an installed build, package-data is not declared in pyproject"
    )


@pytest.mark.parametrize("name", _vendored_profiles())
def test_every_vendored_profile_loads(name):
    t = builtin_timings(name)
    assert t.tCK_ns > 0, f"{name}: tCK must be positive"
