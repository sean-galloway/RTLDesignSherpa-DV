# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5 factories
# Purpose: AXI5-Lite component factories over the shared AXIL4 contract
#
# Subsystem: framework

"""AXI5-Lite component factories.

Same functions, same argument order and the same returned dictionaries as the
AXIL4 factories, so a testbench moves between the two by changing the import
and adding whichever optional-signal-group switches its DUT implements.

The return dictionaries are not restated here. They come from the
``build_*_components`` helpers in ``axil4_factories``, which are the single
definition of the factory contract. That matters because the dictionary IS the
API -- callers index it by key, so a key present in the AXI4-Lite factory and
missing from the AXI5-Lite one is a ``KeyError`` in user code, not an error
here. A first, hand-written version of this module made exactly that mistake:
it dropped ``write``, ``read``, ``read_reg``, ``write_reg``, ``simple_read``,
``simple_write``, ``memory_model`` and both compliance checkers, and every
static test still passed because nothing compared the two contracts.

The protocol-agnostic compliance helpers are re-exported rather than copied --
they walk the returned dictionaries and never touch a protocol type.

Unlike the AXIL4 factories these do NOT strip ``user_width``: on AXI5-Lite the
USER group is a real, spec-defined option, and silently discarding it would
leave the BFM ignoring signals the DUT drives.
"""

from typing import Any, Dict, Tuple

# Two things come from the AXI4-Lite factories, both deliberately shared:
#   build_* -- the single definition of the factory return-dict contract, so
#              AXIL5 cannot return a smaller dict than AXIL4 does.
#   the compliance helpers -- protocol-agnostic (they walk the returned dicts
#              and never touch a protocol type), re-exported rather than copied
#              so AXIL5 users import them from the module they already use.
from ..axil4.axil4_factories import (  # noqa: F401  (re-exported API)
    build_master_components,
    build_master_rd_components,
    build_master_wr_components,
    build_slave_components,
    build_slave_rd_components,
    build_slave_wr_components,
    get_unified_compliance_reports,
    is_unified_compliance_checking_enabled,
    print_all_compliance_reports_from_system,
    print_compliance_to_log,
    print_unified_compliance_reports,
)
from .axil5_interfaces import (
    AXIL5MasterRead,
    AXIL5MasterWrite,
    AXIL5SlaveRead,
    AXIL5SlaveWrite,
)

# ==============================================================================
# SINGLE-DIRECTION FACTORIES
# ==============================================================================

def create_axil5_master_rd(dut, clock, prefix="", log=None,
                           **kwargs) -> Dict[str, Any]:
    """Create an AXI5-Lite master read interface (AR + R)."""
    return build_master_rd_components(
        AXIL5MasterRead(dut, clock, prefix, log=log, **kwargs))


def create_axil5_master_wr(dut, clock, prefix="", log=None,
                           **kwargs) -> Dict[str, Any]:
    """Create an AXI5-Lite master write interface (AW + W + B)."""
    return build_master_wr_components(
        AXIL5MasterWrite(dut, clock, prefix, log=log, **kwargs))


def create_axil5_slave_rd(dut, clock, prefix="", log=None,
                          **kwargs) -> Dict[str, Any]:
    """Create an AXI5-Lite slave read interface."""
    return build_slave_rd_components(
        AXIL5SlaveRead(dut, clock, prefix, log=log, **kwargs))


def create_axil5_slave_wr(dut, clock, prefix="", log=None,
                          **kwargs) -> Dict[str, Any]:
    """Create an AXI5-Lite slave write interface."""
    return build_slave_wr_components(
        AXIL5SlaveWrite(dut, clock, prefix, log=log, **kwargs))


# ==============================================================================
# BOTH-DIRECTION FACTORIES
# ==============================================================================

def create_axil5_master_interface(dut, clock, prefix="", log=None,
                                  **kwargs) -> Tuple[AXIL5MasterWrite,
                                                     AXIL5MasterRead]:
    """Both master halves as a ``(write, read)`` pair."""
    return (AXIL5MasterWrite(dut, clock, prefix, log=log, **kwargs),
            AXIL5MasterRead(dut, clock, prefix, log=log, **kwargs))


def create_axil5_slave_interface(dut, clock, prefix="", log=None,
                                 **kwargs) -> Tuple[AXIL5SlaveWrite,
                                                    AXIL5SlaveRead]:
    """Both slave halves as a ``(write, read)`` pair."""
    return (AXIL5SlaveWrite(dut, clock, prefix, log=log, **kwargs),
            AXIL5SlaveRead(dut, clock, prefix, log=log, **kwargs))


def create_axil5_master(dut, clock, prefix="", log=None,
                        **kwargs) -> Dict[str, Any]:
    """Complete AXI5-Lite master: both directions in one dictionary."""
    write_if, read_if = create_axil5_master_interface(
        dut, clock, prefix, log, **kwargs)
    return build_master_components(write_if, read_if)


def create_axil5_slave(dut, clock, prefix="", log=None,
                       **kwargs) -> Dict[str, Any]:
    """Complete AXI5-Lite slave: both directions in one dictionary."""
    write_if, read_if = create_axil5_slave_interface(
        dut, clock, prefix, log, **kwargs)
    return build_slave_components(write_if, read_if,
                                  kwargs.get('memory_model'))


# ==============================================================================
# SYSTEM AND CONVENIENCE FACTORIES
# ==============================================================================

def create_axil5_system(dut, clock, prefix="", log=None, memory_model=None,
                        **kwargs) -> Dict[str, Any]:
    """Complete AXI5-Lite system: master, slave and a shared memory model."""
    from ..shared.memory_model import MemoryModel

    if memory_model is None:
        memory_model = MemoryModel(
            num_lines=1024,
            bytes_per_line=kwargs.get('data_width', 32) // 8,
            log=log,
        )

    master = create_axil5_master(dut, clock, prefix + "m_", log=log, **kwargs)
    slave = create_axil5_slave(dut, clock, prefix + "s_", log=log,
                               memory_model=memory_model, **kwargs)

    return {
        'master': master,
        'slave': slave,
        'memory_model': memory_model,

        'read_reg': master['read_reg'],
        'write_reg': master['write_reg'],

        'master_write_compliance_checker': master['write_compliance_checker'],
        'master_read_compliance_checker': master['read_compliance_checker'],
        'slave_write_compliance_checker': slave['write_compliance_checker'],
        'slave_read_compliance_checker': slave['read_compliance_checker'],
    }


def create_simple_axil5_master(dut, clock, prefix="s_axil_", data_width=32,
                               addr_width=32, log=None, **options):
    """An AXI5-Lite master with the common defaults filled in.

    ``options`` are the optional-signal-group switches (``user_width``,
    ``trace``, ...); with none passed this is an AXI4-Lite master.
    """
    return create_axil5_master(
        dut=dut, clock=clock, prefix=prefix, log=log,
        data_width=data_width, addr_width=addr_width, **options)


def create_simple_axil5_slave(dut, clock, prefix="m_axil_", data_width=32,
                              addr_width=32, log=None, **options):
    """An AXI5-Lite slave backed by a fresh memory model."""
    from ..shared.memory_model import MemoryModel

    memory_model = MemoryModel(
        num_lines=1024,
        bytes_per_line=data_width // 8,
        log=log,
    )
    return create_axil5_slave(
        dut=dut, clock=clock, prefix=prefix, log=log,
        data_width=data_width, addr_width=addr_width,
        memory_model=memory_model, **options)
