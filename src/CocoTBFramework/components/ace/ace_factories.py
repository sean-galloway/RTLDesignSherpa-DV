# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: ACE factory functions
# Purpose: Factory functions for creating ACE BFM components.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-05

"""Factory functions for ACE BFM components."""

from typing import Any, Dict, Tuple

from .ace_interfaces import (
    AXI4ACEMasterRead,
    AXI4ACEMasterWrite,
    AXI4ACESnoopMaster,
    AXI4ACESnoopSlave,
)


def create_axi4ace_master_rd(
    dut,
    clock,
    prefix: str = "",
    log=None,
    ifc_name: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """
    Create an ACE master read interface.

    Args:
        dut: Device under test
        clock: Clock signal
        prefix: Signal prefix (e.g. "m_axi_")
        log: Logger instance
        ifc_name: Interface name suffix for debug
        **kwargs: Configuration parameters

    Returns:
        Dictionary containing the AR/R channel components and the interface
    """
    master_read = AXI4ACEMasterRead(dut, clock, prefix, log=log, ifc_name=ifc_name, **kwargs)

    return {
        "AR": master_read.ar_channel,
        "R": master_read.r_channel,
        "interface": master_read,
    }


def create_axi4ace_master_wr(
    dut,
    clock,
    prefix: str = "",
    log=None,
    ifc_name: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """
    Create an ACE master write interface.

    Args:
        dut: Device under test
        clock: Clock signal
        prefix: Signal prefix (e.g. "m_axi_")
        log: Logger instance
        ifc_name: Interface name suffix for debug
        **kwargs: Configuration parameters

    Returns:
        Dictionary containing the AW/W/B channel components and the interface
    """
    master_write = AXI4ACEMasterWrite(dut, clock, prefix, log=log, ifc_name=ifc_name, **kwargs)

    return {
        "AW": master_write.aw_channel,
        "W": master_write.w_channel,
        "B": master_write.b_channel,
        "interface": master_write,
    }


def create_axi4ace_snoop_slave(
    dut,
    clock,
    prefix: str = "",
    log=None,
    ifc_name: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """
    Create an ACE snoop slave (cache-side responder).

    Args:
        dut: Device under test
        clock: Clock signal
        prefix: Signal prefix (e.g. "m_axi_")
        log: Logger instance
        ifc_name: Interface name suffix for debug
        **kwargs: Configuration parameters

    Returns:
        Dictionary containing the AC/CR/CD channel components and the interface
    """
    snoop_slave = AXI4ACESnoopSlave(dut, clock, prefix, log=log, ifc_name=ifc_name, **kwargs)

    return {
        "AC": snoop_slave.ac_channel,
        "CR": snoop_slave.cr_channel,
        "CD": snoop_slave.cd_channel,
        "interface": snoop_slave,
    }


def create_axi4ace_snoop_master(
    dut,
    clock,
    prefix: str = "",
    log=None,
    ifc_name: str = "",
    **kwargs,
) -> Dict[str, Any]:
    """
    Create an ACE snoop master (CCU-side initiator).

    Args:
        dut: Device under test
        clock: Clock signal
        prefix: Signal prefix (e.g. "m_axi_")
        log: Logger instance
        ifc_name: Interface name suffix for debug
        **kwargs: Configuration parameters

    Returns:
        Dictionary containing the AC/CR/CD channel components and the interface
    """
    snoop_master = AXI4ACESnoopMaster(dut, clock, prefix, log=log, ifc_name=ifc_name, **kwargs)

    return {
        "AC": snoop_master.ac_channel,
        "CR": snoop_master.cr_channel,
        "CD": snoop_master.cd_channel,
        "interface": snoop_master,
    }


def create_axi4ace_master_interface(
    dut,
    clock,
    prefix: str = "",
    log=None,
    **kwargs,
) -> Tuple[AXI4ACEMasterWrite, AXI4ACEMasterRead]:
    """Create both ACE read and write master interfaces."""
    write_if = AXI4ACEMasterWrite(dut, clock, prefix, log=log, **kwargs)
    read_if = AXI4ACEMasterRead(dut, clock, prefix, log=log, **kwargs)
    return write_if, read_if


def create_axi4ace_snoop_interface(
    dut,
    clock,
    prefix: str = "",
    log=None,
    **kwargs,
) -> Tuple[AXI4ACESnoopMaster, AXI4ACESnoopSlave]:
    """Create both ACE snoop master and slave interfaces."""
    master_if = AXI4ACESnoopMaster(dut, clock, prefix, log=log, **kwargs)
    slave_if = AXI4ACESnoopSlave(dut, clock, prefix, log=log, **kwargs)
    return master_if, slave_if


def create_complete_axi4ace_testbench_components(
    dut,
    clock,
    master_prefix: str = "m_axi_",
    slave_prefix: str = "s_axi_",
    log=None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Create a complete set of ACE components for a testbench.

    Args:
        dut: Device under test
        clock: Clock signal
        master_prefix: Prefix for master-side signals
        slave_prefix: Prefix for slave-side signals
        log: Logger instance
        **kwargs: Configuration parameters

    Returns:
        Dictionary with all ACE components that resolve on the DUT
    """
    components = {}

    try:
        if hasattr(dut, f"{master_prefix}arvalid"):
            components["master_read"] = create_axi4ace_master_rd(
                dut, clock, master_prefix, log=log, **kwargs
            )
        if hasattr(dut, f"{master_prefix}awvalid"):
            components["master_write"] = create_axi4ace_master_wr(
                dut, clock, master_prefix, log=log, **kwargs
            )
    except Exception as e:
        if log:
            log.debug(f"ACE master interface creation: {e}")

    try:
        if hasattr(dut, f"{slave_prefix}acvalid"):
            components["snoop_slave"] = create_axi4ace_snoop_slave(
                dut, clock, slave_prefix, log=log, **kwargs
            )
        if hasattr(dut, f"{slave_prefix}arready"):
            components["slave_read"] = create_axi4ace_master_rd(
                dut, clock, slave_prefix, log=log, **kwargs
            )
        if hasattr(dut, f"{slave_prefix}awready"):
            components["slave_write"] = create_axi4ace_master_wr(
                dut, clock, slave_prefix, log=log, **kwargs
            )
    except Exception as e:
        if log:
            log.debug(f"ACE slave/snoop interface creation: {e}")

    return components
