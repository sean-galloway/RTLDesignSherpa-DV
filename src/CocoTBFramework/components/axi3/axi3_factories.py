# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: axi3_factories
# Purpose: AXI3 Factory Functions
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""AXI3 Factory Functions.

Mirrors the AXI4 factory API but returns the standalone AXI3 protocol
family implemented in this package.  See issue #87.
"""

from typing import Any, Dict

from .axi3_interfaces import AXI3MasterRead, AXI3MasterWrite, AXI3SlaveRead, AXI3SlaveWrite


def create_axi3_master_rd(dut, clock, prefix="", log=None, ifc_name="", **kwargs) -> Dict[str, Any]:
    """Create an AXI3 Master Read interface.

    Args:
        dut: Device under test.
        clock: Clock signal.
        prefix: Signal prefix (e.g. "m_axi_", "s_axi_").
        log: Logger instance.
        ifc_name: Interface name for debug.
        **kwargs: Additional configuration (data_width, id_width, addr_width,
            user_width, optional_fields, etc.).

    Returns:
        Dictionary with AR master, R slave, and the high-level interface.
    """
    master_read = AXI3MasterRead(dut, clock, prefix, log=log, ifc_name=ifc_name, **kwargs)
    return {
        'AR': master_read.ar_channel,
        'R': master_read.r_channel,
        'interface': master_read,
    }


def create_axi3_master_wr(dut, clock, prefix="", log=None, ifc_name="", **kwargs) -> Dict[str, Any]:
    """Create an AXI3 Master Write interface.

    Returns:
        Dictionary with AW master, W master, B slave, and the high-level
        interface.
    """
    master_write = AXI3MasterWrite(dut, clock, prefix, log=log, ifc_name=ifc_name, **kwargs)
    return {
        'AW': master_write.aw_channel,
        'W': master_write.w_channel,
        'B': master_write.b_channel,
        'interface': master_write,
    }


def create_axi3_slave_rd(dut, clock, prefix="", log=None, ifc_name="", **kwargs) -> Dict[str, Any]:
    """Create an AXI3 Slave Read interface.

    Args:
        dut: Device under test.
        clock: Clock signal.
        prefix: Signal prefix.
        log: Logger instance.
        ifc_name: Interface name for debug.
        **kwargs: Additional configuration including memory_model,
            enable_ooo, ooo_config, response_delay, optional_fields, etc.

    Returns:
        Dictionary with AR slave, R master, and the high-level interface.
    """
    slave_read = AXI3SlaveRead(dut, clock, prefix, log=log, ifc_name=ifc_name, **kwargs)
    return {
        'AR': slave_read.ar_channel,
        'R': slave_read.r_channel,
        'interface': slave_read,
    }


def create_axi3_slave_wr(dut, clock, prefix="", log=None, ifc_name="", **kwargs) -> Dict[str, Any]:
    """Create an AXI3 Slave Write interface.

    The AXI3 slave demuxes incoming W beats by WID so it can tolerate
    interleaved write data from external masters.

    Returns:
        Dictionary with AW slave, W slave, B master, and the high-level
        interface.
    """
    slave_write = AXI3SlaveWrite(dut, clock, prefix, log=log, ifc_name=ifc_name, **kwargs)
    return {
        'AW': slave_write.aw_channel,
        'W': slave_write.w_channel,
        'B': slave_write.b_channel,
        'interface': slave_write,
    }


def create_axi3_master_interface(dut, clock, prefix="", log=None, **kwargs):
    """Create both AXI3 read and write master interfaces.

    Returns:
        Tuple of (write_interface, read_interface).
    """
    write_if = AXI3MasterWrite(dut, clock, prefix, log=log, **kwargs)
    read_if = AXI3MasterRead(dut, clock, prefix, log=log, **kwargs)
    return write_if, read_if


def create_axi3_slave_interface(dut, clock, prefix="", log=None, **kwargs):
    """Create both AXI3 read and write slave interfaces.

    Returns:
        Tuple of (write_interface, read_interface).
    """
    write_if = AXI3SlaveWrite(dut, clock, prefix, log=log, **kwargs)
    read_if = AXI3SlaveRead(dut, clock, prefix, log=log, **kwargs)
    return write_if, read_if


def create_complete_axi3_testbench_components(dut, clock, master_prefix="m_axi_",
                                              slave_prefix="s_axi_", log=None, **kwargs):
    """Create a complete set of AXI3 components for a testbench.

    Args:
        dut: Device under test.
        clock: Clock signal.
        master_prefix: Prefix for master-side signals.
        slave_prefix: Prefix for slave-side signals.
        log: Logger instance.
        **kwargs: Additional configuration.

    Returns:
        Dictionary with all created AXI3 components.
    """
    components = {}

    try:
        if hasattr(dut, f'{master_prefix}awvalid'):
            components['master_write'] = create_axi3_master_wr(
                dut, clock, master_prefix, log=log, **kwargs
            )
        if hasattr(dut, f'{master_prefix}arvalid'):
            components['master_read'] = create_axi3_master_rd(
                dut, clock, master_prefix, log=log, **kwargs
            )
    except Exception as e:
        if log:
            log.debug(f"Master interface creation: {e}")

    try:
        if hasattr(dut, f'{slave_prefix}awready'):
            components['slave_write'] = create_axi3_slave_wr(
                dut, clock, slave_prefix, log=log, **kwargs
            )
        if hasattr(dut, f'{slave_prefix}arready'):
            components['slave_read'] = create_axi3_slave_rd(
                dut, clock, slave_prefix, log=log, **kwargs
            )
    except Exception as e:
        if log:
            log.debug(f"Slave interface creation: {e}")

    return components
