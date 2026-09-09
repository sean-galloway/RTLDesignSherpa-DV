"""The out-of-range contract in shared/memory_model.py: one definition every
memory-backed slave BFM answers with (SLVERR, nothing written, pattern data,
one warning). See the module comment above OOR_READ_PATTERN."""
from __future__ import annotations

import logging

import pytest

from CocoTBFramework.components.shared.memory_model import (
    OOR_READ_PATTERN,
    MemoryModel,
    oor_read_data,
)


def test_pattern_replicates_to_width():
    assert oor_read_data(4) == 0xDEADDEAD
    assert oor_read_data(8) == 0xDEADDEADDEADDEAD
    assert oor_read_data(2) == 0xDEAD
    assert oor_read_data(16) == int.from_bytes(OOR_READ_PATTERN.to_bytes(4, 'little') * 4, 'little')


def test_in_range_is_inclusive_of_the_last_byte():
    mem = MemoryModel(num_lines=4, bytes_per_line=4)   # 16 bytes
    assert mem.in_range(0, 16)
    assert mem.in_range(12, 4)
    assert not mem.in_range(13, 4)
    assert not mem.in_range(16, 1)
    assert not mem.in_range(-1, 1)


def test_oor_warning_counts_and_names_the_slave(caplog):
    mem = MemoryModel(num_lines=4, bytes_per_line=4)
    log = logging.getLogger("oor-test")
    before = mem.stats['boundary_violations']
    with caplog.at_level(logging.WARNING, logger="oor-test"):
        mem.oor_warning(log, 'AXI4SlaveWrite', 0x8000_0100, 8, txn=3)
    assert mem.stats['boundary_violations'] == before + 1
    msg = caplog.records[-1].getMessage()
    assert 'AXI4SlaveWrite' in msg and '0x80000100' in msg and 'SLVERR' in msg and '16-byte' in msg


def test_apb_slaves_default_to_the_error_not_expansion():
    """The APB family used to grow its memory on overflow by default; the
    contract makes the error the default and expansion opt-in."""
    import inspect

    from CocoTBFramework.components.apb.apb_components import APBSlave
    from CocoTBFramework.components.apb5.apb5_components import APB5Slave
    from CocoTBFramework.components.apb5.apb5_factories import create_apb5_slave
    for fn in (APBSlave.__init__, APB5Slave.__init__, create_apb5_slave):
        assert inspect.signature(fn).parameters['error_overflow'].default is True, fn


@pytest.mark.parametrize("family", ["axi4", "axi5", "axil4", "apb"])
def test_every_slave_family_uses_the_shared_helper(family):
    """Structural: the contract is one code path, not four rewrites."""
    import importlib
    mod = {
        "axi4": "CocoTBFramework.components.axi4.axi4_interfaces",
        "axi5": "CocoTBFramework.components.axi5.axi5_interfaces",
        "axil4": "CocoTBFramework.components.axil4.axil4_interfaces",
        "apb": "CocoTBFramework.components.apb.apb_components",
    }[family]
    src = open(importlib.import_module(mod).__file__).read()
    assert "oor_read_data(" in src and "oor_warning(" in src
