# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: axil4_factories
# Purpose: AXIL4 Factory Functions - COMPLETE UPDATED FILE
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXIL4 Factory Functions - COMPLETE UPDATED FILE

CHANGES:
1. ✅ SIMPLIFIED: Removed all user signal support (not in AXIL4 spec)
2. ✅ API CONSISTENCY: Factory returns now identical to AXI4
3. ✅ UNIFIED COMPLIANCE: Uses unified compliance reporting functions
4. ✅ PERFECT API: All convenience methods included for seamless protocol switching

This file is ready to replace the existing axil4_factories.py
"""

import os
from typing import Any, Dict, Tuple

from .axil4_interfaces import AXIL4MasterRead, AXIL4MasterWrite, AXIL4SlaveRead, AXIL4SlaveWrite

# ==============================================================================
# RETURN-DICT BUILDERS -- ONE definition of the factory contract
# ==============================================================================
# The dictionaries these return ARE the factory API: callers index them by key,
# so a key present in one protocol's factory and absent from another's is a
# KeyError in user code rather than a type error here. AXI5-Lite reuses these
# builders (see components/axil5/axil5_factories.py) so its factories cannot
# quietly return a smaller dict than AXI4-Lite's -- which is exactly what a
# hand-written copy did first time round, dropping 'write', 'read', 'read_reg',
# 'write_reg', 'simple_read', 'simple_write' and both compliance checkers.
#
# They take already-constructed interface objects, so they are protocol-family
# agnostic and unit-testable without a simulator.

def build_master_rd_components(read_if) -> Dict[str, Any]:
    """Read-master factory dict (AR + R)."""
    return {
        'AR': read_if.ar_channel,
        'R': read_if.r_channel,
        'interface': read_if,
        'compliance_checker': read_if.compliance_checker,
        'read_transaction': read_if.read_transaction,
        'single_read': read_if.single_read,
        'simple_read': read_if.simple_read,
        'read_register': read_if.read_register,
    }


def build_master_wr_components(write_if) -> Dict[str, Any]:
    """Write-master factory dict (AW + W + B)."""
    return {
        'AW': write_if.aw_channel,
        'W': write_if.w_channel,
        'B': write_if.b_channel,
        'interface': write_if,
        'compliance_checker': write_if.compliance_checker,
        'write_transaction': write_if.write_transaction,
        'single_write': write_if.single_write,
        'simple_write': write_if.simple_write,
        'write_register': write_if.write_register,
    }


def build_slave_rd_components(read_if) -> Dict[str, Any]:
    """Read-slave factory dict."""
    return {
        'AR': read_if.ar_channel,
        'R': read_if.r_channel,
        'interface': read_if,
        'compliance_checker': read_if.compliance_checker,
    }


def build_slave_wr_components(write_if) -> Dict[str, Any]:
    """Write-slave factory dict."""
    return {
        'AW': write_if.aw_channel,
        'W': write_if.w_channel,
        'B': write_if.b_channel,
        'interface': write_if,
        'compliance_checker': write_if.compliance_checker,
    }


def build_master_components(write_if, read_if) -> Dict[str, Any]:
    """Full-master factory dict (both directions)."""
    return {
        'write': write_if,
        'read': read_if,
        'write_interface': write_if,
        'read_interface': read_if,

        'AW': write_if.aw_channel,
        'W': write_if.w_channel,
        'B': write_if.b_channel,
        'AR': read_if.ar_channel,
        'R': read_if.r_channel,

        'read_transaction': read_if.read_transaction,
        'write_transaction': write_if.write_transaction,
        'single_read': read_if.single_read,
        'single_write': write_if.single_write,
        'simple_read': read_if.simple_read,
        'simple_write': write_if.simple_write,
        'read_register': read_if.read_register,
        'write_register': write_if.write_register,

        'read_reg': read_if.read_register,
        'write_reg': write_if.write_register,

        'write_compliance_checker': write_if.compliance_checker,
        'read_compliance_checker': read_if.compliance_checker,
    }


def build_slave_components(write_if, read_if, memory_model=None) -> Dict[str, Any]:
    """Full-slave factory dict (both directions)."""
    return {
        'write': write_if,
        'read': read_if,
        'write_interface': write_if,
        'read_interface': read_if,

        'AW': write_if.aw_channel,
        'W': write_if.w_channel,
        'B': write_if.b_channel,
        'AR': read_if.ar_channel,
        'R': read_if.r_channel,

        'memory_model': memory_model,

        'write_compliance_checker': write_if.compliance_checker,
        'read_compliance_checker': read_if.compliance_checker,
    }


def create_axil4_master_rd(dut, clock, prefix="", log=None, **kwargs) -> Dict[str, Any]:
    """
    Create AXIL4 Master Read interface - PERFECT API consistency with AXI4.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    ENHANCED: Returns identical structure to AXI4 factory.
    """
    # Remove user_width if accidentally passed (AXIL4 doesn't use it)
    kwargs.pop('user_width', None)

    master_read = AXIL4MasterRead(dut, clock, prefix, log=log, **kwargs)

    return build_master_rd_components(master_read)


def create_axil4_master_wr(dut, clock, prefix="", log=None, **kwargs) -> Dict[str, Any]:
    """
    Create AXIL4 Master Write interface - PERFECT API consistency with AXI4.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    ENHANCED: Returns identical structure to AXI4 factory.
    """
    # Remove user_width if accidentally passed (AXIL4 doesn't use it)
    kwargs.pop('user_width', None)

    master_write = AXIL4MasterWrite(dut, clock, prefix, log=log, **kwargs)

    # PERFECT API CONSISTENCY: Identical structure to AXI4
    return build_master_wr_components(master_write)


def create_axil4_slave_rd(dut, clock, prefix="", log=None, **kwargs) -> Dict[str, Any]:
    """
    Create AXIL4 Slave Read interface - PERFECT API consistency with AXI4.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    """
    # Remove user_width if accidentally passed (AXIL4 doesn't use it)
    kwargs.pop('user_width', None)

    slave_read = AXIL4SlaveRead(dut, clock, prefix, log=log, **kwargs)

    # PERFECT API CONSISTENCY: Identical structure to AXI4
    return build_slave_rd_components(slave_read)


def create_axil4_slave_wr(dut, clock, prefix="", log=None, **kwargs) -> Dict[str, Any]:
    """
    Create AXIL4 Slave Write interface - PERFECT API consistency with AXI4.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    """
    # Remove user_width if accidentally passed (AXIL4 doesn't use it)
    kwargs.pop('user_width', None)

    slave_write = AXIL4SlaveWrite(dut, clock, prefix, log=log, **kwargs)

    # PERFECT API CONSISTENCY: Identical structure to AXI4
    return build_slave_wr_components(slave_write)


def create_axil4_master_interface(dut, clock, prefix="", log=None, **kwargs) -> Tuple[AXIL4MasterWrite, AXIL4MasterRead]:
    """
    Create both read and write master interfaces - SIMPLIFIED and API consistent.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    """
    # Remove user_width if accidentally passed
    kwargs.pop('user_width', None)

    write_if = AXIL4MasterWrite(dut, clock, prefix, log=log, **kwargs)
    read_if = AXIL4MasterRead(dut, clock, prefix, log=log, **kwargs)
    return write_if, read_if


def create_axil4_slave_interface(dut, clock, prefix="", log=None, **kwargs) -> Tuple[AXIL4SlaveWrite, AXIL4SlaveRead]:
    """
    Create both read and write slave interfaces - SIMPLIFIED and API consistent.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    """
    # Remove user_width if accidentally passed
    kwargs.pop('user_width', None)

    write_if = AXIL4SlaveWrite(dut, clock, prefix, log=log, **kwargs)
    read_if = AXIL4SlaveRead(dut, clock, prefix, log=log, **kwargs)
    return write_if, read_if


def create_axil4_master(dut, clock, prefix="", log=None, **kwargs) -> Dict[str, Any]:
    """
    Create complete AXIL4 master - PERFECT API consistency with AXI4.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    """
    # Remove user_width if accidentally passed
    kwargs.pop('user_width', None)

    # Create both interfaces
    write_if = AXIL4MasterWrite(dut, clock, prefix, log=log, **kwargs)
    read_if = AXIL4MasterRead(dut, clock, prefix, log=log, **kwargs)

    return build_master_components(write_if, read_if)


def create_axil4_slave(dut, clock, prefix="", log=None, **kwargs) -> Dict[str, Any]:
    """
    Create complete AXIL4 slave - PERFECT API consistency with AXI4.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    """
    # Remove user_width if accidentally passed
    kwargs.pop('user_width', None)

    # Create both interfaces
    write_if = AXIL4SlaveWrite(dut, clock, prefix, log=log, **kwargs)
    read_if = AXIL4SlaveRead(dut, clock, prefix, log=log, **kwargs)

    return build_slave_components(write_if, read_if, kwargs.get('memory_model'))


def create_axil4_system(dut, clock, prefix="", log=None, memory_model=None, **kwargs) -> Dict[str, Any]:
    """
    Create complete AXIL4 system - SIMPLIFIED and API consistent.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    """
    from ..shared.memory_model import MemoryModel

    # Remove user_width if accidentally passed
    kwargs.pop('user_width', None)

    # Create shared memory model if not provided
    if memory_model is None:
        memory_model = MemoryModel(
            num_lines=1024,
            bytes_per_line=4,  # 32-bit default
            log=log
        )

    # Add memory model to kwargs for slave
    kwargs_with_memory = {**kwargs, 'memory_model': memory_model}

    # Create master and slave
    master = create_axil4_master(dut, clock, prefix + "m_", log=log, **kwargs)
    slave = create_axil4_slave(dut, clock, prefix + "s_", log=log, **kwargs_with_memory)

    return {
        'master': master,
        'slave': slave,
        'memory_model': memory_model,

        # Convenience transaction methods (identical to AXI4)
        'read_reg': master['read_reg'],
        'write_reg': master['write_reg'],

        # All compliance checkers
        'master_write_compliance_checker': master['write_compliance_checker'],
        'master_read_compliance_checker': master['read_compliance_checker'],
        'slave_write_compliance_checker': slave['write_compliance_checker'],
        'slave_read_compliance_checker': slave['read_compliance_checker'],
    }


# ==============================================================================
# UNIFIED COMPLIANCE REPORTING (works for both AXI4 and AXIL4)
# ==============================================================================

def get_unified_compliance_reports(components: Dict[str, Any]) -> Dict[str, Any]:
    """
    UNIFIED: Get compliance reports - works for both AXI4 and AXIL4.
    Replaces protocol-specific get_compliance_reports_from_components functions.
    """
    reports = {}
    protocol = "UNKNOWN"

    # Check if compliance checker exists
    if 'compliance_checker' in components and components['compliance_checker']:
        report = components['compliance_checker'].get_compliance_report()
        if report:
            reports['compliance'] = report
            protocol = report.get('protocol', 'AXI4')

    # Check for multiple compliance checkers
    for checker_key in ['write_compliance_checker', 'read_compliance_checker']:
        if checker_key in components and components[checker_key]:
            checker_name = checker_key.replace('_compliance_checker', '')
            report = components[checker_key].get_compliance_report()
            if report:
                reports[f'{checker_name}_compliance'] = report
                protocol = report.get('protocol', protocol)

    # Check if interface has compliance reporting
    if 'interface' in components:
        interface = components['interface']
        if hasattr(interface, 'get_compliance_report'):
            report = interface.get_compliance_report()
            if report:
                reports['interface_compliance'] = report
                protocol = report.get('protocol', protocol)

    # Add summary information
    if reports:
        reports['protocol'] = protocol
        reports['total_reports'] = len([r for r in reports.values() if isinstance(r, dict)])

    return reports


def print_unified_compliance_reports(components: Dict[str, Any]):
    """
    UNIFIED: Print compliance reports - works for both AXI4 and AXIL4.
    Replaces protocol-specific print_compliance_reports_from_components functions.
    """
    protocol = "AXI4"  # Default

    # Print from compliance checker
    if 'compliance_checker' in components and components['compliance_checker']:
        components['compliance_checker'].print_compliance_report()
        if hasattr(components['compliance_checker'], 'get_compliance_report'):
            report = components['compliance_checker'].get_compliance_report()
            protocol = report.get('protocol', 'AXI4')
        return

    # Print from multiple compliance checkers
    printed_any = False
    for checker_key in ['write_compliance_checker', 'read_compliance_checker']:
        if checker_key in components and components[checker_key]:
            components[checker_key].print_compliance_report()
            if hasattr(components[checker_key], 'get_compliance_report'):
                report = components[checker_key].get_compliance_report()
                protocol = report.get('protocol', 'AXI4')
            printed_any = True

    if printed_any:
        return

    # Print from interface
    if 'interface' in components:
        interface = components['interface']
        if hasattr(interface, 'print_compliance_report'):
            interface.print_compliance_report()
            return

    # If no compliance checking available
    if components.get('interface') and hasattr(components['interface'], 'log') and components['interface'].log:
        components['interface'].log.info(f"{protocol} compliance checking is disabled (set {protocol}_COMPLIANCE_CHECK=1 to enable)")
    else:
        print(f"{protocol} compliance checking is disabled (set {protocol}_COMPLIANCE_CHECK=1 to enable)")


def is_unified_compliance_checking_enabled() -> bool:
    """
    UNIFIED: Check if compliance checking is enabled - works for both protocols.
    """
    return (os.environ.get('AXI4_COMPLIANCE_CHECK', '0') == '1' or
            os.environ.get('AXIL4_COMPLIANCE_CHECK', '0') == '1')


# Legacy aliases for backward compatibility
get_compliance_reports_from_components = get_unified_compliance_reports
print_compliance_reports_from_components = print_unified_compliance_reports
is_compliance_checking_enabled = is_unified_compliance_checking_enabled


def print_all_compliance_reports_from_system(system_components: Dict[str, Any]):
    """
    Print all compliance reports from a complete system (AXI4 or AXIL4).
    """
    if not is_unified_compliance_checking_enabled():
        # Determine protocol from components
        protocol = "AXIL4"  # Default for this file
        if 'master' in system_components and 'compliance_checker' in system_components['master']:
            checker = system_components['master']['compliance_checker']
            if checker and hasattr(checker, 'get_compliance_report'):
                report = checker.get_compliance_report()
                protocol = report.get('protocol', 'AXIL4')

        print(f"{protocol} compliance checking is disabled (set {protocol}_COMPLIANCE_CHECK=1 to enable)")
        return

    print("\n" + "="*80)
    print("PROTOCOL COMPLIANCE REPORTS")
    print("="*80)

    # Print master compliance reports
    if 'master' in system_components:
        print("MASTER COMPLIANCE REPORTS:")
        print("-" * 40)
        print_unified_compliance_reports(system_components['master'])

    # Print slave compliance reports
    if 'slave' in system_components:
        print("\nSLAVE COMPLIANCE REPORTS:")
        print("-" * 40)
        print_unified_compliance_reports(system_components['slave'])

    print("="*80)


# ==============================================================================
# SIMPLIFIED CONVENIENCE FUNCTIONS
# ==============================================================================

def create_simple_axil4_master(dut, clock, prefix="s_axil_", data_width=32, addr_width=32, log=None):
    """
    Create simple AXIL4 master - SIMPLIFIED and specification compliant.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    PERFECT: API consistency with AXI4.
    """
    return create_axil4_master(
        dut=dut,
        clock=clock,
        prefix=prefix,
        log=log,
        data_width=data_width,
        addr_width=addr_width
        # SIMPLIFIED: No user_width parameter
    )


def create_simple_axil4_slave(dut, clock, prefix="m_axil_", data_width=32, addr_width=32, log=None):
    """
    Create simple AXIL4 slave - SIMPLIFIED and specification compliant.

    SIMPLIFIED: No user_width parameter (not in AXIL4 spec).
    """
    from ..shared.memory_model import MemoryModel

    # Create memory model
    memory_model = MemoryModel(
        num_lines=1024,
        bytes_per_line=data_width // 8,
        log=log
    )

    return create_axil4_slave(
        dut=dut,
        clock=clock,
        prefix=prefix,
        log=log,
        data_width=data_width,
        addr_width=addr_width,
        memory_model=memory_model
        # SIMPLIFIED: No user_width parameter
    )


# ==============================================================================
# ENHANCED COMPLIANCE LOGGING
# ==============================================================================

def print_compliance_to_log(components, log):
    """
    Print compliance reports to log file instead of console.

    UNIFIED: Works for both AXI4 and AXIL4.
    """
    if not isinstance(components, list):
        components = [components]

    for comp in components:
        if isinstance(comp, dict):
            # Handle factory function returns
            if 'compliance_checker' in comp and comp['compliance_checker']:
                report = comp['compliance_checker'].get_compliance_report()
                _log_compliance_report(report, log)

            # Handle multiple checkers
            for checker_key in ['write_compliance_checker', 'read_compliance_checker']:
                if checker_key in comp and comp[checker_key]:
                    report = comp[checker_key].get_compliance_report()
                    checker_name = checker_key.replace('_compliance_checker', '').upper()
                    _log_compliance_report(report, log, f"AXIL4 {checker_name} ")
        elif hasattr(comp, 'get_compliance_report'):
            # Handle interface objects directly
            report = comp.get_compliance_report()
            _log_compliance_report(report, log)


def _log_compliance_report(report, log, prefix="AXIL4 "):
    """Helper function to log a single compliance report."""
    if report and report.get('compliance_checking') == 'enabled':
        protocol = report.get('protocol', 'AXIL4')
        log.info("=" * 80)
        log.info(f"{prefix}{protocol} PROTOCOL COMPLIANCE REPORT")
        log.info("=" * 80)
        log.info(f"Status: {report['compliance_status']}")
        log.info(f"Total Violations: {report['total_violations']}")
        log.info(f"Checks Performed: {report['statistics']['checks_performed']}")

        if report['violation_summary']:
            log.info("Violation Summary:")
            for vtype, count in report['violation_summary'].items():
                log.info(f"  {vtype}: {count}")

        # AXIL4-specific stats
        if 'address_alignment_checks' in report['statistics']:
            log.info("AXIL4-Specific Checks:")
            log.info(f"  Address Alignment: {report['statistics']['address_alignment_checks']}")
            log.info(f"  Write Strobe: {report['statistics']['strobe_checks']}")

        log.info("=" * 80)
    else:
        log.info(f"{prefix}compliance checking was disabled")


# ==============================================================================
# API CONSISTENCY DEMONSTRATION
# ==============================================================================

def demonstrate_perfect_api_consistency():
    """
    Shows perfect API consistency between AXI4 and AXIL4.

    PERFECT API CONSISTENCY ACHIEVED:
    ================================

    This IDENTICAL code now works for BOTH AXI4 and AXIL4:
    """

    async def test_protocol_agnostic(master_factory, dut, clock):
        """Generic test that works identically for both protocols."""

        # Create master using either factory
        master = master_factory(dut, clock)

        # These calls work IDENTICALLY for both protocols:
        data1 = await master['single_read'](0x1000)
        resp1 = await master['single_write'](0x2000, data1)

        data2 = await master['simple_read'](0x3000)  # Backward compatibility
        resp2 = await master['simple_write'](0x4000, data2)  # Backward compatibility

        reg_data = await master['read_register'](0x5000)  # Semantic alias
        reg_resp = await master['write_register'](0x6000, reg_data)  # Semantic alias

        # Short aliases work identically:
        quick_data = await master['read_reg'](0x7000)
        quick_resp = await master['write_reg'](0x8000, quick_data)

        # Unified compliance reporting:
        print_unified_compliance_reports(master)

        return {
            'data1': data1, 'resp1': resp1,
            'data2': data2, 'resp2': resp2,
            'reg_data': reg_data, 'reg_resp': reg_resp,
            'quick_data': quick_data, 'quick_resp': quick_resp
        }

    print("PERFECT API CONSISTENCY DEMONSTRATION")
    print("=" * 50)
    print("This function shows how identical code works for both protocols:")
    print("")
    print("# Use with AXI4:")
    print("axi4_results = await test_protocol_agnostic(create_simple_axi4_master, dut, clock)")
    print("")
    print("# Use with AXIL4 - IDENTICAL CODE:")
    print("axil4_results = await test_protocol_agnostic(create_simple_axil4_master, dut, clock)")
    print("")
    print("RESULT: Perfect protocol interoperability! 🎉")


# Example usage showing perfect consistency
if __name__ == "__main__":
    print("AXIL4 Factory Functions - COMPLETE UPDATED VERSION")
    print("=" * 70)
    print("IMPROVEMENTS:")
    print("  ✅ SIMPLIFIED: Removed all user signal support (AXIL4 spec compliant)")
    print("  ✅ API CONSISTENCY: Factory returns identical to AXI4")
    print("  ✅ UNIFIED COMPLIANCE: Works seamlessly with AXI4 compliance functions")
    print("  ✅ PERFECT API: All convenience methods included")
    print("  ✅ BACKWARD COMPATIBLE: All existing functionality preserved")
    print("")
    print("SPECIFICATION COMPLIANCE:")
    print("  - Only AXIL4-specified signals included")
    print("  - No user signals (not in AXIL4 spec)")
    print("  - Minimal, register-oriented design")
    print("  - Perfect for embedded register interfaces")
    print("")
    print("API CONSISTENCY EXAMPLES:")
    print("  master = create_simple_axil4_master(dut, clock)  # Same API as AXI4")
    print("  data = await master['single_read'](0x1000)      # Identical to AXI4")
    print("  resp = await master['single_write'](0x2000, data)  # Identical to AXI4")
    print("  print_unified_compliance_reports(master)        # Works for both protocols")
    print("")
    print("PERFECT API CONSISTENCY WITH AXI4 ACHIEVED! 🎉")
