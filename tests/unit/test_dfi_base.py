"""Unit tests for the DFIBase chassis (issue #16).

DFIBase is the shared configuration + sub-interface registry that
DFIMasterMC / DFISlavePHY / DFIMonitor all inherit. It owns nothing
cocotb-specific — that lives in the subclasses — so it's Tier 1
testable in isolation.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi import (
    AddressMapping,
    DFIVersion,
    MemoryType,
    SubInterface,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_base import DFIBase


@pytest.fixture
def timings():
    return builtin_timings("ddr3-1600")


@pytest.fixture
def mapping():
    return AddressMapping(num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024)


@pytest.fixture
def base(timings, mapping):
    return DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
    )


# ---------------------------------------------------------------------
# Construction / configuration validation
# ---------------------------------------------------------------------


def test_base_stores_configuration(base, timings, mapping):
    assert base.dfi_version == DFIVersion.V2_1
    assert base.memory_type == MemoryType.DDR3
    assert base.timings is timings
    assert base.mapping is mapping


def test_base_rejects_unsupported_version_memory_pair(timings, mapping):
    """v2.1 + DDR5 is not a supported pair."""
    with pytest.raises(ValueError, match="not supported"):
        DFIBase(
            dfi_version=DFIVersion.V2_1,
            memory_type=MemoryType.DDR5,
            timings=timings,
            mapping=mapping,
        )


def test_base_defaults_sub_interfaces_to_mvp_set(base):
    """MVP: command + write_data + read_data sub-interfaces enabled."""
    enabled = base.enabled_sub_interfaces
    assert SubInterface.COMMAND in enabled
    assert SubInterface.WRITE_DATA in enabled
    assert SubInterface.READ_DATA in enabled


def test_base_accepts_custom_sub_interfaces(timings, mapping):
    """Caller can restrict to a subset — e.g. command-only for a stub."""
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
        sub_interfaces=frozenset({SubInterface.COMMAND}),
    )
    assert base.enabled_sub_interfaces == frozenset({SubInterface.COMMAND})


# ---------------------------------------------------------------------
# Cycle counter
# ---------------------------------------------------------------------


def test_cycle_starts_at_zero(base):
    assert base.cycle == 0


def test_tick_advances_cycle(base):
    base.tick()
    base.tick()
    assert base.cycle == 2


# ---------------------------------------------------------------------
# Field-config dispatch
# ---------------------------------------------------------------------


def test_field_config_for_each_enabled_sub_interface(base):
    """Each enabled sub-interface has a corresponding field config."""
    cmd_cfg = base.field_config_for(SubInterface.COMMAND)
    wr_cfg = base.field_config_for(SubInterface.WRITE_DATA)
    rd_cfg = base.field_config_for(SubInterface.READ_DATA)
    assert cmd_cfg is not None
    assert wr_cfg is not None
    assert rd_cfg is not None
    # Different sub-interfaces should produce different field configs
    assert cmd_cfg is not wr_cfg


def test_field_config_for_disabled_sub_interface_raises(timings, mapping):
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
        sub_interfaces=frozenset({SubInterface.COMMAND}),
    )
    with pytest.raises(ValueError, match="not enabled"):
        base.field_config_for(SubInterface.WRITE_DATA)


# ---------------------------------------------------------------------
# Address widths derived from mapping
# ---------------------------------------------------------------------


def test_widths_match_mapping(base):
    """The chassis exposes the widths needed to size DFI signals."""
    assert base.bank_width == 3   # ceil(log2(8))
    assert base.row_width == 13   # ceil(log2(8192))
    assert base.col_width == 10   # ceil(log2(1024))
