# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5 factories
# Purpose: AXI5-Lite component factories mirroring the AXIL4 factory API
#
# Subsystem: framework

"""AXI5-Lite component factories.

Same shape and same returned dictionaries as the AXIL4 factories, so a
testbench moves between the two by changing the import and adding whichever
optional-group switches its DUT implements.

Unlike the AXIL4 factories these do NOT strip ``user_width``: on AXI5-Lite the
USER group is a real, spec-defined option, and silently discarding it would
leave the BFM ignoring signals the DUT drives.
"""

from typing import Any, Dict, Tuple

from .axil5_interfaces import (
    AXIL5MasterRead,
    AXIL5MasterWrite,
    AXIL5SlaveRead,
    AXIL5SlaveWrite,
)


def create_axil5_master_rd(dut, clock, prefix="", log=None,
                           **kwargs) -> Dict[str, Any]:
    """Create an AXI5-Lite master read interface."""
    master_read = AXIL5MasterRead(dut, clock, prefix, log=log, **kwargs)
    return {
        'AR': master_read.ar_channel,
        'R': master_read.r_channel,
        'interface': master_read,
        'compliance_checker': master_read.compliance_checker,
        'read_transaction': master_read.read_transaction,
        'single_read': master_read.single_read,
        'simple_read': master_read.simple_read,
        'read_register': master_read.read_register,
    }


def create_axil5_master_wr(dut, clock, prefix="", log=None,
                           **kwargs) -> Dict[str, Any]:
    """Create an AXI5-Lite master write interface."""
    master_write = AXIL5MasterWrite(dut, clock, prefix, log=log, **kwargs)
    return {
        'AW': master_write.aw_channel,
        'W': master_write.w_channel,
        'B': master_write.b_channel,
        'interface': master_write,
        'compliance_checker': master_write.compliance_checker,
        'write_transaction': master_write.write_transaction,
        'single_write': master_write.single_write,
        'simple_write': master_write.simple_write,
        'write_register': master_write.write_register,
    }


def create_axil5_slave_rd(dut, clock, prefix="", log=None,
                          **kwargs) -> Dict[str, Any]:
    """Create an AXI5-Lite slave read interface."""
    slave_read = AXIL5SlaveRead(dut, clock, prefix, log=log, **kwargs)
    return {
        'AR': slave_read.ar_channel,
        'R': slave_read.r_channel,
        'interface': slave_read,
        'compliance_checker': slave_read.compliance_checker,
    }


def create_axil5_slave_wr(dut, clock, prefix="", log=None,
                          **kwargs) -> Dict[str, Any]:
    """Create an AXI5-Lite slave write interface."""
    slave_write = AXIL5SlaveWrite(dut, clock, prefix, log=log, **kwargs)
    return {
        'AW': slave_write.aw_channel,
        'W': slave_write.w_channel,
        'B': slave_write.b_channel,
        'interface': slave_write,
        'compliance_checker': slave_write.compliance_checker,
    }


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
    """Full AXI5-Lite master: both directions in one dictionary."""
    write, read = create_axil5_master_interface(dut, clock, prefix, log,
                                                **kwargs)
    return {
        'AW': write.aw_channel, 'W': write.w_channel, 'B': write.b_channel,
        'AR': read.ar_channel, 'R': read.r_channel,
        'write_interface': write, 'read_interface': read,
        'write_transaction': write.write_transaction,
        'read_transaction': read.read_transaction,
        'single_write': write.single_write,
        'single_read': read.single_read,
        'write_register': write.write_register,
        'read_register': read.read_register,
    }


def create_axil5_slave(dut, clock, prefix="", log=None,
                       **kwargs) -> Dict[str, Any]:
    """Full AXI5-Lite slave: both directions in one dictionary."""
    write, read = create_axil5_slave_interface(dut, clock, prefix, log,
                                               **kwargs)
    return {
        'AW': write.aw_channel, 'W': write.w_channel, 'B': write.b_channel,
        'AR': read.ar_channel, 'R': read.r_channel,
        'write_interface': write, 'read_interface': read,
    }
