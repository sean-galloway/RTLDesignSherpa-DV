"""Unit tests for the DFIBase.beats_per_burst field (issue #16, BL=8 phase)."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi import (
    AddressMapping,
    DFIBase,
    DFIVersion,
    MemoryType,
    builtin_timings,
)


@pytest.fixture
def mapping():
    return AddressMapping(num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024)


@pytest.fixture
def ddr3_timings():
    return builtin_timings("ddr3-1600")  # BL=8


@pytest.fixture
def ddr2_timings():
    return builtin_timings("ddr2-650-mt47h64m16hr")  # BL=4


def _make(timings, mapping, **kw):
    return DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
        **kw,
    )


def test_default_beats_per_burst_is_BL_over_2(ddr3_timings, mapping):
    """K=2 PHY ratio: DDR3-1600 BL=8 → 4 DFI beats per DRAM burst."""
    base = _make(ddr3_timings, mapping)
    assert base.beats_per_burst == 4


def test_default_for_BL4_is_2(ddr2_timings, mapping):
    """DDR2-650 has BL=4 → 2 DFI beats per DRAM burst by default."""
    base = _make(ddr2_timings, mapping)
    assert base.beats_per_burst == 2


def test_explicit_override_to_1_for_mvp(ddr3_timings, mapping):
    """The MVP loopback test wants BL=1 conceptually — one DFI beat per command."""
    base = _make(ddr3_timings, mapping, beats_per_burst=1)
    assert base.beats_per_burst == 1


def test_explicit_override_to_8_for_K1_phy(ddr3_timings, mapping):
    """K=1 PHY (DFI bus = DRAM bus width) → beats_per_burst == BL."""
    base = _make(ddr3_timings, mapping, beats_per_burst=8)
    assert base.beats_per_burst == 8


def test_rejects_zero_beats(ddr3_timings, mapping):
    with pytest.raises(ValueError, match="beats_per_burst"):
        _make(ddr3_timings, mapping, beats_per_burst=0)
