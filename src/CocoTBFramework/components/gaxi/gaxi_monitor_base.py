# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: GAXIMonitorBase
# Purpose: Updated GAXIMonitorBase - Using GAXIComponentBase for unified functionality
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
Updated GAXIMonitorBase - Using GAXIComponentBase for unified functionality

Eliminates duplication while preserving exact APIs and timing.
All existing parameters are maintained and used exactly as before.
"""

from __future__ import annotations

from collections import deque
from logging import Logger
from typing import Any, List, Optional

from cocotb.utils import get_sim_time
from cocotb_bus.monitors import BusMonitor

from ..shared.init_kwargs import strip_framework_kwargs
from ..shared.monitor_statistics import MonitorStatistics
from .gaxi_component_base import (
    ClockSignal,
    DutHandle,
    FieldConfigInput,
    GAXIComponentBase,
)


class GAXIMonitorBase(GAXIComponentBase, BusMonitor):
    """
    Base class providing common GAXI monitoring functionality using unified infrastructure.

    Inherits common functionality from GAXIComponentBase:
    - Signal resolution and data collection setup
    - Unified field configuration handling
    - Memory model integration using base MemoryModel directly
    - Statistics and logging patterns

    Shared by GAXIMonitor and GAXISlave to eliminate code duplication
    while preserving exact APIs and timing-critical behavior.
    """
    def __init__(
        self,
        dut: DutHandle,
        title: str,
        prefix: str,
        clock: ClockSignal,
        field_config: FieldConfigInput,
        mode: str = "skid",
        bus_name: str = "",
        pkt_prefix: str = "",
        multi_sig: bool = False,
        protocol_type: Optional[str] = None,  # set by subclass
        log: Optional[Logger] = None,
        super_debug: bool = False,
        signal_map: Optional[dict] = None,
        packet_class: Optional[type] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize common GAXI monitoring functionality - EXACT SAME API AS BEFORE.

        Args:
            dut: Device under test
            title: Component title/name
            prefix: Bus prefix
            clock: Clock signal
            field_config: Field configuration
            bus_name: Bus/channel name
            pkt_prefix: Packet field prefix
            multi_sig: Whether using multi-signal mode
            protocol_type: Must be set by subclass ('gaxi_master' or 'gaxi_slave')
            log: Logger instance
            super_debug: Enable detailed debugging
            packet_class: Optional Packet subclass for the receive pipeline
                          (None = GAXIPacket). See GAXIComponentBase._build_packet.
            **kwargs: Additional arguments for BusMonitor
        """
        # Extract values we need to forward to GAXIComponentBase, then strip
        # all framework-only kwargs so the remainder is safe for BusMonitor.
        # See components/shared/init_kwargs.py for the canonical set.
        memory_model = kwargs.pop('memory_model', None)
        randomizer = kwargs.pop('randomizer', None)
        optional_fields = kwargs.pop('optional_fields', None)
        strip_framework_kwargs(kwargs)

        # Initialize base class with all parameters preserved
        GAXIComponentBase.__init__(
            self,
            dut=dut,
            title=title,
            prefix=prefix,  # Keep for our internal signal discovery
            clock=clock,
            field_config=field_config,
            protocol_type=protocol_type,
            mode=mode,
            bus_name=bus_name,
            pkt_prefix=pkt_prefix,
            multi_sig=multi_sig,
            memory_model=memory_model,
            randomizer=randomizer,
            log=log,
            super_debug=super_debug,
            signal_map=signal_map,
            packet_class=packet_class,
            optional_fields=optional_fields,
            **{k: v for k, v in kwargs.items()}  # Pass remaining clean kwargs
        )

        # Remove prefix from kwargs so it doesn't get passed to BusDriver/BusMonitor
        kwargs.pop('prefix', None)

        # CLEAN APPROACH: Explicitly pass empty prefix to cocotb
        # Our signal lists already contain full signal names
        BusMonitor.__init__(self, dut, '', clock, callback=None, event=None, **kwargs)

        # Validate log parameter - MUST be provided from TBBase
        if log is None:
            raise ValueError(
                f"GAXIMonitorBase '{title}': log parameter is required!\n"
                "  You must pass a logger from TBBase:\n"
                "    tb = MyTestbench(dut)  # Inherits from TBBase\n"
                "    slave = create_axi4_slave_wr(dut, ..., log=tb.log)\n"
                "  Do NOT rely on self._log - it doesn't exist in this context."
            )

        self.log = log

        # Complete base class initialization now that bus is available
        self.complete_base_initialization(self.bus)

        # Statistics - unified setup for all GAXI monitoring components
        self.stats = MonitorStatistics()

        # Completed-packet drain queue (opt-in). This is SEPARATE from the
        # cocotb _recvQ so the documented `monitor._recvQ.popleft()` usage is
        # completely unaffected. See enable_completed_packet_tracking().
        self._completed_packet_tracking = False
        self._completedQ: deque = deque()

        side_description = "slave" if protocol_type == 'gaxi_slave' else "master"
        self.log.info(f"GAXIMonitorBase '{title}' initialized: {side_description} side, "
                        f"mode={mode}, multi_sig={self.use_multi_signal}")

    def _get_data_dict(self):
        """
        UNIFIED: Clean data collection with automatic field unpacking.

        This replaces the messy _get_data_dict() + conditional unpacking logic
        that was duplicated in both GAXIMonitor and GAXISlave.

        Uses the unified DataCollectionStrategy.collect_and_unpack_data() method
        that eliminates all the conditional mess.

        Returns:
            Dictionary of field values, properly unpacked
        """
        return self.get_data_dict_unified()

    def _finish_packet(self, current_time, packet, data_dict=None):
        """
        UNIFIED: Clean packet finishing without conditional mess.

        This replaces the duplicate _finish_packet logic that was in both
        GAXIMonitor and GAXISlave with identical functionality.

        Args:
            current_time: Current simulation time
            packet: Packet to finish
            data_dict: Optional field data (if None, will collect fresh data)
        """
        # Get data if not provided
        if data_dict is None:
            data_dict = self._get_data_dict()

        # Use the packet's unpack_from_fifo method for field handling
        if data_dict:
            if hasattr(packet, 'unpack_from_fifo'):
                packet.unpack_from_fifo(data_dict)
            else:
                # Legacy fallback - set fields directly
                for field_name, value in data_dict.items():
                    if value != -1:  # Skip X/Z values
                        if hasattr(packet, field_name):
                            setattr(packet, field_name, value)

        # Set end time
        packet.end_time = current_time

        # Update statistics - use fields that exist in MonitorStatistics
        if hasattr(self.stats, 'received_transactions'):
            self.stats.received_transactions += 1
        if hasattr(self.stats, 'transactions_observed'):
            self.stats.transactions_observed += 1

        # Log the transaction
        packet_str = (packet.formatted(compact=True)
                        if hasattr(packet, 'formatted')
                        else str(packet))
        current_time = get_sim_time('ns')
        self.log.debug(f"GAXIMonitorBase({self.title}) Transaction at {current_time}ns: {packet_str}")

        # Record for the opt-in completed-packet drain API (no-op unless enabled)
        self._record_completed_packet(packet)

        # ESSENTIAL: Use cocotb _recv method to add to _recvQ and trigger callbacks
        self._recv(packet)

    # ------------------------------------------------------------------
    # Completed-packet drain API (opt-in)
    #
    # Contract:
    # - The drain queue is fed from _finish_packet() alongside (not instead
    #   of) the standard cocotb _recvQ. Draining it never touches _recvQ, so
    #   the documented `monitor._recvQ.popleft()` verification pattern keeps
    #   working unchanged.
    # - Tracking is OFF by default to avoid unbounded growth for the vast
    #   majority of monitors that nobody drains. Consumers (e.g. the AXI4/
    #   AXI5/AXIL4 compliance checkers) call enable_completed_packet_tracking()
    #   once at setup; only packets observed AFTER enabling are recorded.
    # - get_completed_packets() is destructive on the drain queue only: each
    #   packet is returned exactly once, in observation order.
    # ------------------------------------------------------------------

    def enable_completed_packet_tracking(self) -> None:
        """Opt in to recording completed packets for get_completed_packets().

        Idempotent. Only packets observed after this call are recorded.
        """
        self._completed_packet_tracking = True

    def _record_completed_packet(self, packet) -> None:
        """Append a finished packet to the drain queue if tracking is enabled."""
        if self._completed_packet_tracking:
            self._completedQ.append(packet)

    def get_completed_packets(self, count: Optional[int] = None) -> List[Any]:
        """Drain and return completed packets observed since the last call.

        Auto-enables tracking on first use (in which case the first call
        returns only packets observed after a prior explicit
        enable_completed_packet_tracking(), or an empty list).

        Args:
            count: Maximum number of packets to drain (None = all)

        Returns:
            List of packets in observation order; each packet is returned
            exactly once. The standard cocotb _recvQ is NOT modified.
        """
        if not self._completed_packet_tracking:
            self.enable_completed_packet_tracking()

        if count is None:
            drained = list(self._completedQ)
            self._completedQ.clear()
        else:
            drained = [self._completedQ.popleft()
                       for _ in range(min(count, len(self._completedQ)))]
        return drained

    def create_packet(self, **field_values):
        """
        UNIFIED: Create a packet with specified field values.

        This was duplicated identically in both GAXIMonitor and GAXISlave.

        Delegates to the :meth:`_build_packet` hook so subclasses (and the
        ``packet_class=`` factory argument) control the concrete packet type.

        Args:
            **field_values: Initial field values

        Returns:
            Packet instance (GAXIPacket by default) with the specified fields
        """
        return self._build_packet(**field_values)

    def get_observed_packets(self, count=None):
        """
        Get observed packets from standard cocotb _recvQ.

        Args:
            count: Number of packets to return (None = all)

        Returns:
            List of observed packets
        """
        if count is None:
            return list(self._recvQ)
        return list(self._recvQ)[-count:]

    def clear_queue(self):
        """Clear the observed transactions queue - standard cocotb pattern"""
        self._recvQ.clear()
        self.log.info(f"GAXIMonitorBase ({self.title}): Observed queue cleared")

    # Memory operations using base MemoryModel directly (for slave components)
    def handle_memory_write(self, packet):
        """Handle memory write using unified memory integration"""
        success, error = self.write_to_memory_unified(packet)
        if success:
            self.log.debug("GAXIMonitorBase: Memory write successful")
        else:
            self.log.warning(f"GAXIMonitorBase: Memory write failed: {error}")
        return success

    def handle_memory_read(self, packet):
        """Handle memory read using unified memory integration"""
        success, data, error = self.read_from_memory_unified(packet, update_transaction=True)
        if success:
            self.log.debug(f"GAXIMonitorBase: Memory read successful, data=0x{data:X}")
        else:
            self.log.warning(f"GAXIMonitorBase: Memory read failed: {error}")
        return success, data

    def get_base_stats(self):
        """
        Get base statistics that are common to all GAXI monitoring components.

        Subclasses should call this and add their own specific statistics.

        Returns:
            Dictionary containing base statistics
        """
        base_stats = self.get_base_stats_unified()
        base_stats.update({
            'monitor_stats': self.stats.get_stats(),
            'observed_packets': len(self._recvQ)
        })
        return base_stats

    def __str__(self):
        """String representation"""
        side = "Slave" if self.protocol_type == 'gaxi_slave' else "Master"
        return (f"GAXIMonitorBase '{self.title}' ({side} Side): "
                f"{len(self._recvQ)} packets observed")
