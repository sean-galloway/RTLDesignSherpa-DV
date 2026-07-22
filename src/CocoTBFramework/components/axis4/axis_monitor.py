# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXISMonitor
# Purpose: AXIS Monitor - Stream protocol monitor implementation
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXIS Monitor - Stream protocol monitor implementation

This module provides AXIS Monitor functionality using GAXI infrastructure.
Similar API to AXI4Monitor but adapted for stream protocol.
"""

from cocotb.triggers import RisingEdge

from ..gaxi.gaxi_monitor import GAXIMonitor
from .axis_field_configs import AXISFieldConfigs
from .axis_packet import AXISPacket


class AXISMonitor(GAXIMonitor):
    """
    AXIS Monitor component for observing AXI4-Stream protocol.

    Inherits from :class:`GAXIMonitor` to reuse the GAXI receive pipeline:
    handshake detection, signal sampling on the falling edge, packet
    construction, statistics, coverage hooks, and the standard cocotb
    ``_recvQ`` delivery path. The monitor is passive - it drives nothing.

    AXIS-level behaviour is layered on through the two documented extension
    points rather than a forked receive loop:

    - :meth:`_build_packet` (via ``_default_packet_class``) so the pipeline
      produces real :class:`AXISPacket` instances.
    - :meth:`_finish_packet`, which calls the GAXI implementation first (so
      ``_recvQ``, callbacks, and coverage hooks behave exactly as for any GAXI
      monitor) and then runs :meth:`_axis_packet_observed`.

    .. note::

        AXIS frame accounting is deliberately hooked into ``_finish_packet``
        rather than registered with ``add_callback``. cocotb's
        ``Monitor._recv()`` stops appending to ``_recvQ`` as soon as any
        callback is registered, and ``monitor._recvQ.popleft()`` is the
        documented way to consume monitor traffic.

    AXIS-specific features:
    - Stream transaction monitoring
    - Frame boundary detection with TLAST
    - Protocol violation detection
    - Comprehensive stream statistics
    """

    # Packets produced by the GAXI receive pipeline (see
    # GAXIComponentBase._build_packet). An explicit packet_class= argument
    # still wins over this default.
    _default_packet_class = AXISPacket

    def __init__(self, dut, title, prefix, clock, field_config=None,
                is_slave=False, mode='skid',
                bus_name='', pkt_prefix='', multi_sig=False,
                log=None, super_debug=False, signal_map=None, **kwargs):
        """
        Initialize AXIS Monitor.

        Args:
            dut: Device under test
            title: Component title/name
            prefix: Bus prefix (e.g., "s_axis_", "m_axis_", "axis_")
            clock: Clock signal
            field_config: Field configuration (if None, creates default)
            is_slave: True if monitoring slave side, False for master side
            mode: Protocol mode ('skid', 'blocking', etc.)
            bus_name: Bus/channel name
            pkt_prefix: Packet field prefix
            multi_sig: Whether using multi-signal mode
            log: Logger instance
            super_debug: Enable detailed debugging
            signal_map: Optional manual signal mapping
            **kwargs: Additional configuration
        """
        # Create default field config if none provided
        if field_config is None:
            field_config = AXISFieldConfigs.create_default_axis_config()

        # AXIS frame/statistics state must exist before the GAXI receive
        # pipeline can deliver its first packet to _finish_packet().
        self._current_frame = []
        self._frame_id = None
        self.packets_observed = 0
        self.frames_observed = 0
        self.total_data_bytes = 0
        self.protocol_violations = 0

        # Initialize via GAXIMonitor - which forwards through GAXIMonitorBase
        # to GAXIComponentBase and calls complete_base_initialization() itself.
        # protocol_type='axis_master'/'axis_slave' makes SignalResolver pick
        # the AXIS signal table.
        super().__init__(
            dut=dut, title=title, prefix=prefix, clock=clock,
            field_config=field_config, is_slave=is_slave,
            protocol_type='axis_slave' if is_slave else 'axis_master',
            mode=mode, bus_name=bus_name, pkt_prefix=pkt_prefix,
            multi_sig=multi_sig, log=log, super_debug=super_debug,
            signal_map=signal_map, **kwargs
        )

        if self.log:
            side = "slave" if self.is_slave else "master"
            self.log.info(f"AXISMonitor '{self.title}' initialized: "
                         f"{side} side, mode={self.mode}")

    # ------------------------------------------------------------------
    # GAXI pipeline hook
    # ------------------------------------------------------------------

    def _finish_packet(self, current_time, packet, data_dict=None):
        """
        Complete a packet captured by the GAXI receive pipeline.

        Runs the unified GAXI completion first (field unpacking, statistics,
        ``_recvQ``/callback delivery) and then layers AXIS frame accounting on
        top, preserving the original ordering of the forked AXIS loop.

        Args:
            current_time: Current simulation time
            packet: Packet under construction
            data_dict: Optional field data (collected fresh when None)
        """
        super()._finish_packet(current_time, packet, data_dict)
        self._axis_packet_observed(packet)

    def _axis_packet_observed(self, packet):
        """
        AXIS frame tracking hook, fed by the GAXI receive pipeline.

        The pipeline owns handshake detection and data capture; this hook only
        adds TLAST-delimited frame accounting, AXIS protocol checks, and the
        optional memory-model write.

        Args:
            packet: AXISPacket captured by the GAXI receive pipeline
        """
        # Update statistics
        self.packets_observed += 1
        self.total_data_bytes += packet.get_byte_count()

        # Handle frame boundaries
        if packet.is_last():
            self.frames_observed += 1
            self._current_frame.append(packet)
            self._process_complete_frame(self._current_frame)
            self._current_frame = []
            self._frame_id = None
        else:
            self._current_frame.append(packet)
            if self._frame_id is None:
                self._frame_id = packet.id

        # Check for protocol violations
        self._check_protocol_violations(packet)

        # Write to memory model if available
        if self.memory_model:
            self.write_to_memory_unified(packet)

        if self.log and self.super_debug:
            self.log.debug(f"AXISMonitor '{self.title}': "
                         f"Observed packet {packet}")

    def _is_handshake_valid(self):
        """Check if valid/ready handshake is occurring."""
        try:
            # Get signals using inherited signal resolution
            valid_signal = getattr(self, 'valid_sig', None)
            ready_signal = getattr(self, 'ready_sig', None)

            if valid_signal is None or ready_signal is None:
                return False

            return bool(valid_signal.value) and bool(ready_signal.value)

        except Exception:
            return False

    def _check_protocol_violations(self, packet):
        """
        Check for AXIS protocol violations.

        Args:
            packet: AXISPacket to check
        """
        violations = []

        # Check if strobe has any holes (non-contiguous 1s)
        if hasattr(packet, 'strb') and packet.strb:
            strb_val = packet.strb
            # Find first and last set bits
            first_bit = -1
            last_bit = -1
            bit_pos = 0
            temp_strb = strb_val

            while temp_strb > 0:
                if temp_strb & 1:
                    if first_bit == -1:
                        first_bit = bit_pos
                    last_bit = bit_pos
                temp_strb >>= 1
                bit_pos += 1

            # Check for holes between first and last bits
            if first_bit != -1 and last_bit != -1:
                for i in range(first_bit, last_bit + 1):
                    if not (strb_val & (1 << i)):
                        violations.append(f"Non-contiguous strobe at bit {i}")
                        break

        # Check for zero strobe with valid data
        if hasattr(packet, 'strb') and packet.strb == 0 and packet.data != 0:
            violations.append("Zero strobe with non-zero data")

        # Log violations
        if violations:
            self.protocol_violations += len(violations)
            if self.log:
                for violation in violations:
                    self.log.warning(f"AXISMonitor '{self.title}': "
                                   f"Protocol violation: {violation}")

    def _process_complete_frame(self, frame_packets):
        """
        Process a complete frame (packets ending with TLAST).

        Args:
            frame_packets: List of AXISPacket objects forming a complete frame
        """
        if not frame_packets:
            return

        frame_size = sum(p.get_byte_count() for p in frame_packets)
        frame_id = frame_packets[0].id

        if self.log and self.super_debug:
            self.log.debug(f"AXISMonitor '{self.title}': "
                         f"Observed complete frame ID={frame_id}, size={frame_size} bytes, "
                         f"packets={len(frame_packets)}")

    def get_current_frame_info(self):
        """
        Get information about the currently observed frame.

        Returns:
            Dictionary with frame information
        """
        return {
            'packets_in_frame': len(self._current_frame),
            'frame_id': self._frame_id,
            'total_bytes': sum(p.get_byte_count() for p in self._current_frame) if self._current_frame else 0,
            'is_receiving': len(self._current_frame) > 0
        }

    def get_protocol_stats(self):
        """
        Get protocol-specific statistics.

        Returns:
            Dictionary with protocol statistics
        """
        return {
            'protocol_violations': self.protocol_violations,
            'avg_frame_size': (self.total_data_bytes / self.frames_observed) if self.frames_observed > 0 else 0,
            'avg_packets_per_frame': (self.packets_observed / self.frames_observed) if self.frames_observed > 0 else 0,
        }

    def get_bandwidth_stats(self):
        """
        Get bandwidth and throughput statistics.

        Returns:
            Dictionary with bandwidth statistics
        """
        # Basic bandwidth calculation would need timing information
        # This is a placeholder for more sophisticated bandwidth analysis
        return {
            'total_bytes': self.total_data_bytes,
            'total_packets': self.packets_observed,
            'total_frames': self.frames_observed,
            'avg_packet_size': (self.total_data_bytes / self.packets_observed) if self.packets_observed > 0 else 0
        }

    def get_stats(self):
        """Get comprehensive statistics."""
        base_stats = self.get_base_stats_unified()

        # Add AXIS monitor specific statistics
        axis_stats = {
            'monitor_type': 'slave' if self.is_slave else 'master',
            'packets_observed': self.packets_observed,
            'frames_observed': self.frames_observed,
            'total_data_bytes': self.total_data_bytes,
            'current_frame_info': self.get_current_frame_info(),
            'protocol_stats': self.get_protocol_stats(),
            'bandwidth_stats': self.get_bandwidth_stats()
        }

        # Add base monitor statistics
        if hasattr(self, 'stats'):
            axis_stats.update(self.stats.get_stats())

        # Merge base stats with AXIS-specific stats
        base_stats.update(axis_stats)
        return base_stats

    async def wait_for_frames(self, frame_count, timeout_cycles=1000):
        """
        Wait for a specific number of frames to be observed.

        Args:
            frame_count: Number of frames to wait for
            timeout_cycles: Maximum cycles to wait

        Returns:
            True if frames observed, False if timeout
        """
        initial_frame_count = self.frames_observed
        target_frames = initial_frame_count + frame_count
        cycles = 0

        while cycles < timeout_cycles:
            if self.frames_observed >= target_frames:
                return True

            await RisingEdge(self.clock)
            cycles += 1

        return False

    async def wait_for_packets(self, packet_count, timeout_cycles=1000):
        """
        Wait for a specific number of packets to be observed.

        Args:
            packet_count: Number of packets to wait for
            timeout_cycles: Maximum cycles to wait

        Returns:
            True if packets observed, False if timeout
        """
        initial_packet_count = self.packets_observed
        target_packets = initial_packet_count + packet_count
        cycles = 0

        while cycles < timeout_cycles:
            if self.packets_observed >= target_packets:
                return True

            await RisingEdge(self.clock)
            cycles += 1

        return False

    def __str__(self):
        """String representation."""
        side = "Slave" if self.is_slave else "Master"
        return (f"AXISMonitor '{self.title}' ({side} Side): "
                f"{self.packets_observed} packets observed, "
                f"{self.frames_observed} frames observed, "
                f"{self.protocol_violations} violations")
