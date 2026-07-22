# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL4ViolationType
# Purpose: AXIL4 Protocol Compliance Checker
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXIL4 Protocol Compliance Checker

A non-intrusive compliance checker for AXIL4 (AXI4-Lite) protocol validation
that can be optionally enabled in existing testbenches without requiring code changes.

Key differences from AXI4 compliance checker:
- No burst checking (always single transfer)
- No ID tracking
- Simplified transaction validation
- Register-oriented compliance rules

Features:
- Minimal performance impact when disabled
- Easy integration with existing testbenches
- Comprehensive AXIL4 protocol rule checking
- Detailed violation reporting
- Statistics collection

Usage:
  # In testbench __init__:
  self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
      dut=dut, clock=clock, log=self.log, prefix='m_axil'
  )

  # Automatic checking happens in background
  # Optional: Get compliance report at end of test
  if self.compliance_checker:
      report = self.compliance_checker.get_compliance_report()
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

import cocotb
from cocotb.triggers import RisingEdge

from CocoTBFramework.components.axil4.axil4_field_configs import AXIL4FieldConfigHelper
from CocoTBFramework.components.axil4.axil4_packet import AXIL4Packet
from CocoTBFramework.components.gaxi.gaxi_monitor import GAXIMonitor


class AXIL4ViolationType(Enum):
    """Types of AXIL4 protocol violations."""
    # Handshake violations
    VALID_DROPPED = "valid_dropped"
    READY_BEFORE_VALID = "ready_before_valid"
    VALID_UNSTABLE = "valid_unstable"
    DATA_UNSTABLE = "data_unstable"

    # Address violations
    ADDRESS_ALIGNMENT_VIOLATION = "address_alignment_violation"
    ADDRESS_WIDTH_VIOLATION = "address_width_violation"

    # Response violations
    RESPONSE_CODE_VIOLATION = "response_code_violation"
    INVALID_RESPONSE_TIMING = "invalid_response_timing"

    # Data violations
    DATA_WIDTH_VIOLATION = "data_width_violation"
    STROBE_VIOLATION = "strobe_violation"
    STROBE_DATA_CONSISTENCY = "strobe_data_consistency"

    # Protocol violations
    # Retained for API compatibility. Concurrent reads and writes are LEGAL
    # in AXI4-Lite (independent channels); the checker no longer emits this.
    CONCURRENT_TRANSACTIONS = "concurrent_transactions"
    BURST_ATTEMPT = "burst_attempt"  # AXIL4 is single transfer only

    # Timing violations
    RESET_VIOLATION = "reset_violation"
    CLOCK_VIOLATION = "clock_violation"

    # PROT field violations
    PROT_FIELD_VIOLATION = "prot_field_violation"


@dataclass
class AXIL4Violation:
    """Represents a single AXIL4 protocol violation."""
    violation_type: AXIL4ViolationType
    channel: str  # 'AR', 'AW', 'W', 'R', 'B'
    cycle: int
    message: str
    severity: str = 'ERROR'  # 'ERROR', 'WARNING', 'INFO'
    additional_data: Dict[str, Any] = field(default_factory=dict)


class AXIL4ComplianceChecker:
    """
    Non-intrusive AXIL4 protocol compliance checker.

    Can be optionally enabled via environment variables without modifying
    existing testbench code.

    Key differences from AXI4 checker:
    - No burst validation (single transfer only)
    - No ID tracking or ordering checks
    - Simplified transaction flow validation
    - Register access pattern validation
    """

    def __init__(self, dut, clock, prefix="", log=None, **kwargs):
        """Initialize AXIL4 compliance checker."""
        self.dut = dut
        self.clock = clock
        self.prefix = prefix
        self.log = log
        self.enabled = True

        # Configuration
        self.data_width = kwargs.get('data_width', 32)
        self.addr_width = kwargs.get('addr_width', 32)
        self.user_width = kwargs.get('user_width', 0)  # Usually 0 for AXIL4
        self.multi_sig = kwargs.get('multi_sig', True)

        # Violation tracking
        self.violations: List[AXIL4Violation] = []
        self.violation_counts: Dict[AXIL4ViolationType, int] = {}
        self.cycle_count = 0

        # Transaction state tracking (simpler than AXI4).
        # AXI4-Lite permits multiple outstanding transactions (and concurrent
        # reads and writes -- the channels are independent), so we track
        # outstanding depth as informational statistics, not violations.
        self.outstanding_reads = 0
        self.outstanding_writes = 0
        self.write_data_received = False

        # Previous state tracking for stability checks
        self.prev_signals = {}

        # Statistics
        self.stats = {
            'total_ar_transactions': 0,
            'total_aw_transactions': 0,
            'total_w_transactions': 0,
            'total_r_responses': 0,
            'total_b_responses': 0,
            'total_violations': 0,
            'checks_performed': 0,
            'address_alignment_checks': 0,
            'strobe_checks': 0,
            'max_outstanding_reads': 0,
            'max_outstanding_writes': 0
        }

        # Start monitoring if signals exist
        self.monitors_active = False
        self.setup_monitors()

    @classmethod
    def create_if_enabled(cls, dut, clock, prefix="", log=None, **kwargs):
        """
        Factory method that returns None if compliance checking is disabled.

        This allows testbenches to conditionally enable compliance checking
        without code changes:

        self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(...)
        """
        # Check if compliance checking is enabled
        if not cls.is_enabled():
            return None

        try:
            return cls(dut, clock, prefix, log, **kwargs)
        except Exception as e:
            if log:
                log.warning(f"Could not create AXIL4 compliance checker: {e}")
            return None

    @staticmethod
    def is_enabled() -> bool:
        """Check if compliance checking is enabled via environment."""
        return (os.environ.get('AXIL4_COMPLIANCE_CHECK', '0') == '1' or
                os.environ.get('AXI4_COMPLIANCE_CHECK', '0') == '1')

    def setup_monitors(self):
        """Setup signal monitors for all AXIL4 channels."""
        try:
            # Create monitors for each channel
            self.monitors = {}

            # AR Channel Monitor
            if self._has_channel_signals('ar'):
                self.monitors['AR'] = GAXIMonitor(
                    dut=self.dut,
                    title="AR_Monitor",
                    prefix=self.prefix,
                    clock=self.clock,
                    field_config=AXIL4FieldConfigHelper.create_ar_field_config(
                        self.addr_width
                    ),
                    pkt_prefix="ar",
                    multi_sig=self.multi_sig,
                    log=self.log
                )

            # AW Channel Monitor
            if self._has_channel_signals('aw'):
                self.monitors['AW'] = GAXIMonitor(
                    dut=self.dut,
                    title="AW_Monitor",
                    prefix=self.prefix,
                    clock=self.clock,
                    field_config=AXIL4FieldConfigHelper.create_aw_field_config(
                        self.addr_width
                    ),
                    pkt_prefix="aw",
                    multi_sig=self.multi_sig,
                    log=self.log
                )

            # W Channel Monitor
            if self._has_channel_signals('w'):
                self.monitors['W'] = GAXIMonitor(
                    dut=self.dut,
                    title="W_Monitor",
                    prefix=self.prefix,
                    clock=self.clock,
                    field_config=AXIL4FieldConfigHelper.create_w_field_config(
                        self.data_width
                    ),
                    pkt_prefix="w",
                    multi_sig=self.multi_sig,
                    log=self.log
                )

            # R Channel Monitor
            if self._has_channel_signals('r'):
                self.monitors['R'] = GAXIMonitor(
                    dut=self.dut,
                    title="R_Monitor",
                    prefix=self.prefix,
                    clock=self.clock,
                    field_config=AXIL4FieldConfigHelper.create_r_field_config(
                        self.data_width
                    ),
                    pkt_prefix="r",
                    multi_sig=self.multi_sig,
                    log=self.log
                )

            # B Channel Monitor
            if self._has_channel_signals('b'):
                self.monitors['B'] = GAXIMonitor(
                    dut=self.dut,
                    title="B_Monitor",
                    prefix=self.prefix,
                    clock=self.clock,
                    field_config=AXIL4FieldConfigHelper.create_b_field_config(),
                    pkt_prefix="b",
                    multi_sig=self.multi_sig,
                    log=self.log
                )

            # Opt in to the completed-packet drain API so monitor_transactions()
            # actually receives packets (see GAXIMonitorBase.get_completed_packets)
            for monitor in self.monitors.values():
                monitor.enable_completed_packet_tracking()

            # Start monitoring tasks
            if self.monitors:
                self.monitors_active = True
                cocotb.start_soon(self.monitor_transactions())
                cocotb.start_soon(self.monitor_handshakes())
                cocotb.start_soon(self.cycle_counter())

                if self.log:
                    channels = list(self.monitors.keys())
                    self.log.info(f"AXIL4 compliance checker active for channels: {channels}")

        except Exception as e:
            if self.log:
                self.log.warning(f"Could not setup AXIL4 monitors: {e}")
            self.enabled = False

    def _has_channel_signals(self, channel: str) -> bool:
        """Check if the DUT has signals for the specified channel."""
        try:
            # Check for required signals (AXIL4 naming)
            if channel.lower() == 'ar':
                return (hasattr(self.dut, f'{self.prefix}arvalid') and
                       hasattr(self.dut, f'{self.prefix}arready'))
            elif channel.lower() == 'aw':
                return (hasattr(self.dut, f'{self.prefix}awvalid') and
                       hasattr(self.dut, f'{self.prefix}awready'))
            elif channel.lower() == 'w':
                return (hasattr(self.dut, f'{self.prefix}wvalid') and
                       hasattr(self.dut, f'{self.prefix}wready'))
            elif channel.lower() == 'r':
                return (hasattr(self.dut, f'{self.prefix}rvalid') and
                       hasattr(self.dut, f'{self.prefix}rready'))
            elif channel.lower() == 'b':
                return (hasattr(self.dut, f'{self.prefix}bvalid') and
                       hasattr(self.dut, f'{self.prefix}bready'))
        except:
            pass
        return False

    async def monitor_transactions(self):
        """Monitor and validate AXIL4 transactions."""
        if not self.monitors_active:
            return

        try:
            while True:
                # Monitor each channel for new transactions
                for channel_name, monitor in self.monitors.items():
                    if hasattr(monitor, 'get_completed_packets'):
                        packets = monitor.get_completed_packets()
                        for packet in packets:
                            await self.validate_transaction(channel_name, packet)
                            self.stats['checks_performed'] += 1

                await RisingEdge(self.clock)
        except Exception as e:
            if self.log:
                self.log.debug(f"Monitor transactions stopped: {e}")

    async def monitor_handshakes(self):
        """Monitor AXIL4 handshake protocol compliance."""
        if not self.monitors_active:
            return

        try:
            while True:
                # Check handshake rules for each channel.
                # NOTE: concurrent read and write activity (ARVALID together
                # with AWVALID/WVALID) is LEGAL in AXI4-Lite -- the read and
                # write channels are independent -- so no cross-channel
                # concurrency check is performed.
                for channel in ['ar', 'aw', 'w', 'r', 'b']:
                    if self._has_channel_signals(channel):
                        await self.check_handshake_rules(channel)
                        await self.check_data_stability(channel)

                await RisingEdge(self.clock)

        except Exception as e:
            if self.log:
                self.log.debug(f"Monitor handshakes stopped: {e}")

    async def check_handshake_rules(self, channel: str):
        """Check handshake protocol rules for a specific channel.

        Rule (AMBA AXI A3.2.1): once VALID is asserted it must remain
        asserted until the rising clock edge where READY is also asserted.
        We track the previous cycle's (VALID, READY) pair per channel; VALID
        may legally deassert after a completed handshake (previous cycle had
        VALID and READY both high), so only a drop with no prior handshake
        is a violation.
        """
        try:
            valid_signal = getattr(self.dut, f'{self.prefix}{channel}valid', None)
            ready_signal = getattr(self.dut, f'{self.prefix}{channel}ready', None)

            if valid_signal is None or ready_signal is None:
                return

            valid_val = bool(valid_signal.value)
            ready_val = bool(ready_signal.value)

            prev = self.prev_signals.get(f'{channel}_handshake')

            # Rule: Once VALID is asserted, it must remain asserted until handshake
            if prev is not None:
                prev_valid, prev_ready = prev
                if prev_valid and not prev_ready and not valid_val:
                    self.record_violation(
                        AXIL4ViolationType.VALID_DROPPED,
                        channel.upper(),
                        f"{channel.upper()}VALID dropped before handshake completed"
                    )

            # Update state
            self.prev_signals[f'{channel}_handshake'] = (valid_val, ready_val)
            self.stats['checks_performed'] += 1

        except Exception:
            # Silently ignore signal access errors
            pass

    async def check_data_stability(self, channel: str):
        """Check that data/address signals are stable while VALID is asserted.

        Stability is only required from VALID assertion until the handshake
        (VALID and READY both high) completes. The held value is therefore
        cleared whenever VALID is low OR a handshake completes, so legal
        back-to-back transfers (VALID high across two beats with different
        payloads) are NOT flagged.
        """
        try:
            valid_signal = getattr(self.dut, f'{self.prefix}{channel}valid', None)
            if valid_signal is None:
                return

            # Payload signal under stability check for this channel
            if channel in ['ar', 'aw']:
                payload_name = f'{self.prefix}{channel}addr'
                payload_desc = f"{channel.upper()}ADDR"
            elif channel in ['w', 'r']:
                payload_name = f'{self.prefix}{channel}data'
                payload_desc = f"{channel.upper()}DATA"
            else:
                return  # B channel: no payload stability check

            payload_signal = getattr(self.dut, payload_name, None)
            if payload_signal is None:
                return

            stable_key = f'{channel}_stable_payload'

            if not bool(valid_signal.value):
                # VALID low: nothing to hold stable
                self.prev_signals.pop(stable_key, None)
                return

            current_value = int(payload_signal.value)
            held_value = self.prev_signals.get(stable_key)

            if held_value is not None and held_value != current_value:
                self.record_violation(
                    AXIL4ViolationType.DATA_UNSTABLE,
                    channel.upper(),
                    f"{payload_desc} changed while {channel.upper()}VALID asserted"
                )

            ready_signal = getattr(self.dut, f'{self.prefix}{channel}ready', None)
            ready_val = bool(ready_signal.value) if ready_signal is not None else False

            if ready_val:
                # Handshake completes this cycle -- the next beat may legally
                # present a new payload, so stop holding the current value.
                self.prev_signals.pop(stable_key, None)
            else:
                # Transfer not yet accepted: payload must hold next cycle
                self.prev_signals[stable_key] = current_value

        except Exception:
            pass

    async def validate_transaction(self, channel: str, packet: AXIL4Packet):
        """Validate a completed transaction for AXIL4 compliance."""
        try:
            if channel == 'AR':
                await self.validate_ar_transaction(packet)
            elif channel == 'AW':
                await self.validate_aw_transaction(packet)
            elif channel == 'W':
                await self.validate_w_transaction(packet)
            elif channel == 'R':
                await self.validate_r_transaction(packet)
            elif channel == 'B':
                await self.validate_b_transaction(packet)

        except Exception as e:
            if self.log:
                self.log.debug(f"Transaction validation error for {channel}: {e}")

    async def validate_ar_transaction(self, packet: AXIL4Packet):
        """Validate AR (Address Read) transaction."""
        self.stats['total_ar_transactions'] += 1

        # Check address alignment
        addr = getattr(packet, 'addr', 0)
        if not self.check_address_alignment(addr):
            self.record_violation(
                AXIL4ViolationType.ADDRESS_ALIGNMENT_VIOLATION,
                'AR',
                f"Address 0x{addr:08X} not aligned to {self.data_width//8}-byte boundary"
            )

        # Check PROT field validity
        prot = getattr(packet, 'prot', 0)
        if prot > 7:  # PROT is 3 bits
            self.record_violation(
                AXIL4ViolationType.PROT_FIELD_VIOLATION,
                'AR',
                f"Invalid PROT value {prot} (should be 0-7)"
            )

        # Track outstanding read depth. AXI4-Lite does not forbid multiple
        # outstanding transactions (ordering is implicit -- no IDs), so depth
        # is recorded as an informational statistic, not a violation.
        self.outstanding_reads += 1
        self.stats['max_outstanding_reads'] = max(
            self.stats['max_outstanding_reads'], self.outstanding_reads)

    async def validate_aw_transaction(self, packet: AXIL4Packet):
        """Validate AW (Address Write) transaction."""
        self.stats['total_aw_transactions'] += 1

        # Check address alignment
        addr = getattr(packet, 'addr', 0)
        if not self.check_address_alignment(addr):
            self.record_violation(
                AXIL4ViolationType.ADDRESS_ALIGNMENT_VIOLATION,
                'AW',
                f"Address 0x{addr:08X} not aligned to {self.data_width//8}-byte boundary"
            )

        # Check PROT field validity
        prot = getattr(packet, 'prot', 0)
        if prot > 7:
            self.record_violation(
                AXIL4ViolationType.PROT_FIELD_VIOLATION,
                'AW',
                f"Invalid PROT value {prot} (should be 0-7)"
            )

        # Track outstanding write depth (informational -- see validate_ar)
        self.outstanding_writes += 1
        self.stats['max_outstanding_writes'] = max(
            self.stats['max_outstanding_writes'], self.outstanding_writes)

    async def validate_w_transaction(self, packet: AXIL4Packet):
        """Validate W (Write Data) transaction."""
        self.stats['total_w_transactions'] += 1

        # Check write strobes
        strb = getattr(packet, 'strb', 0)
        data = getattr(packet, 'data', 0)

        if not self.check_write_strobes(strb, data):
            self.record_violation(
                AXIL4ViolationType.STROBE_VIOLATION,
                'W',
                f"Invalid write strobe pattern: 0x{strb:X}"
            )

        self.write_data_received = True

    async def validate_r_transaction(self, packet: AXIL4Packet):
        """Validate R (Read Data) transaction."""
        self.stats['total_r_responses'] += 1

        # Check response code
        resp = getattr(packet, 'resp', 0)
        if resp > 3:
            self.record_violation(
                AXIL4ViolationType.RESPONSE_CODE_VIOLATION,
                'R',
                f"Invalid response code {resp} (should be 0-3)"
            )

        # Retire one outstanding read
        self.outstanding_reads = max(0, self.outstanding_reads - 1)

    async def validate_b_transaction(self, packet: AXIL4Packet):
        """Validate B (Write Response) transaction."""
        self.stats['total_b_responses'] += 1

        # Check response code
        resp = getattr(packet, 'resp', 0)
        if resp > 3:
            self.record_violation(
                AXIL4ViolationType.RESPONSE_CODE_VIOLATION,
                'B',
                f"Invalid response code {resp} (should be 0-3)"
            )

        # Retire one outstanding write
        self.outstanding_writes = max(0, self.outstanding_writes - 1)
        self.write_data_received = False

    def check_address_alignment(self, addr: int) -> bool:
        """Check if address is properly aligned for the data width."""
        self.stats['address_alignment_checks'] += 1
        bytes_per_transfer = self.data_width // 8
        return (addr % bytes_per_transfer) == 0

    def check_write_strobes(self, strb: int, data: int) -> bool:
        """Check write strobe validity."""
        self.stats['strobe_checks'] += 1

        # Check strobe width
        max_strb = (1 << (self.data_width // 8)) - 1
        if strb > max_strb:
            return False

        # AXIL4 allows any strobe pattern including sparse patterns
        # Just check that it's not zero (that would be meaningless)
        return strb != 0

    def record_violation(self, violation_type: AXIL4ViolationType, channel: str, message: str, **kwargs):
        """Record a protocol violation."""
        violation = AXIL4Violation(
            violation_type=violation_type,
            channel=channel,
            cycle=self.cycle_count,
            message=message,
            severity=kwargs.get('severity', 'ERROR'),
            additional_data=kwargs.get('additional_data', {})
        )

        self.violations.append(violation)
        self.violation_counts[violation_type] = self.violation_counts.get(violation_type, 0) + 1
        self.stats['total_violations'] += 1

        if self.log:
            self.log.error(f"AXIL4 Violation [{channel}]: {message}")

    async def cycle_counter(self):
        """Count clock cycles for violation timestamps."""
        try:
            while True:
                await RisingEdge(self.clock)
                self.cycle_count += 1
        except:
            pass

    def get_compliance_report(self) -> Dict[str, Any]:
        """Get comprehensive compliance report."""
        if not self.enabled:
            return {'compliance_checking': 'disabled'}

        total_violations = len(self.violations)
        violation_summary = {}

        for vtype in AXIL4ViolationType:
            count = self.violation_counts.get(vtype, 0)
            if count > 0:
                violation_summary[vtype.value] = count

        return {
            'protocol': 'AXIL4',
            'compliance_checking': 'enabled',
            'total_violations': total_violations,
            'violation_summary': violation_summary,
            'statistics': self.stats.copy(),
            'violations': [
                {
                    'type': v.violation_type.value,
                    'channel': v.channel,
                    'cycle': v.cycle,
                    'message': v.message,
                    'severity': v.severity
                }
                for v in self.violations[-10:]  # Last 10 violations
            ],
            'compliance_status': 'PASSED' if total_violations == 0 else 'FAILED'
        }

    def print_compliance_report(self):
        """Print formatted compliance report."""
        if not self.enabled:
            if self.log:
                self.log.info("AXIL4 compliance checking was disabled")
            return

        report = self.get_compliance_report()

        if self.log:
            self.log.info("=" * 80)
            self.log.info("AXIL4 PROTOCOL COMPLIANCE REPORT")
            self.log.info("=" * 80)
            self.log.info(f"Status: {report['compliance_status']}")
            self.log.info(f"Total Violations: {report['total_violations']}")
            self.log.info(f"Checks Performed: {report['statistics']['checks_performed']}")

            if report['violation_summary']:
                self.log.info("Violation Summary:")
                for vtype, count in report['violation_summary'].items():
                    self.log.info(f"  {vtype}: {count}")

            # AXIL4-specific stats
            self.log.info("AXIL4-Specific Checks:")
            self.log.info(f"  Address Alignment: {report['statistics']['address_alignment_checks']}")
            self.log.info(f"  Write Strobe: {report['statistics']['strobe_checks']}")

            self.log.info("=" * 80)


# Integration helper for existing testbenches
def add_axil4_compliance_checking(testbench_class):
    """
    Decorator to add AXIL4 compliance checking to existing testbenches.

    Usage:
        @add_axil4_compliance_checking
        class MyAXIL4Testbench(TBBase):
            ...
    """

    original_init = testbench_class.__init__
    original_final = getattr(testbench_class, 'finalize_test', None)

    def new_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        # Add compliance checker
        if hasattr(self, 'dut') and hasattr(self, 'aclk'):
            self.axil4_compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
                dut=self.dut,
                clock=self.aclk,
                prefix='m_axil',  # Default prefix
                log=self.log
            )

    def new_finalize(self):
        # Print compliance report
        if hasattr(self, 'axil4_compliance_checker') and self.axil4_compliance_checker:
            self.axil4_compliance_checker.print_compliance_report()

        # Call original finalize if it exists
        if original_final:
            original_final(self)

    testbench_class.__init__ = new_init
    testbench_class.finalize_test = new_finalize

    return testbench_class
