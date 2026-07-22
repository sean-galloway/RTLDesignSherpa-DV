# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXISSlave
# Purpose: AXIS Slave - Stream protocol slave implementation
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXIS Slave - Stream protocol slave implementation

This module provides AXIS Slave functionality using GAXI infrastructure.
Similar API to AXI4Slave but adapted for stream protocol.
"""

from cocotb.triggers import RisingEdge

from ..gaxi.gaxi_slave import GAXISlave
from .axis_field_configs import AXISFieldConfigs


class AXISSlave(GAXISlave):
    """
    AXIS Slave component for receiving AXI4-Stream protocol.

    Inherits from :class:`GAXISlave` to reuse the structured pipeline state
    machine, ready-signal driving, statistics, and ``complete_base_initialization``
    plumbing. AXIS adds frame-level (TLAST) tracking and stream-specific
    monitoring on top of the same ready/valid chassis.

    The GAXI receive pipeline is the sole driver of the ready signal
    (including randomized ready delays via the slave randomizer). AXIS-level
    frame tracking is layered on via the standard cocotb callback mechanism:
    every packet captured by the GAXI pipeline is also fed to
    :meth:`_axis_packet_callback` for TLAST-delimited frame accounting.

    AXIS-specific features added by this subclass:
    - Frame boundary detection via TLAST
    - Packet and frame statistics
    - ``apply_backpressure`` and ``wait_for_frame`` extensions
    """

    def __init__(self, dut, title, prefix, clock, field_config=None,
                timeout_cycles=1000, mode='skid',
                bus_name='', pkt_prefix='', multi_sig=False,
                randomizer=None, memory_model=None, log=None,
                super_debug=False, pipeline_debug=False,
                signal_map=None, **kwargs):
        """
        Initialize AXIS Slave.

        Args:
            dut: Device under test
            title: Component title/name
            prefix: Bus prefix (e.g., "s_axis_", "axis_")
            clock: Clock signal
            field_config: Field configuration (if None, creates default)
            timeout_cycles: Maximum cycles for operations
            mode: Protocol mode ('skid', 'blocking', etc.)
            bus_name: Bus/channel name
            pkt_prefix: Packet field prefix
            multi_sig: Whether using multi-signal mode
            randomizer: Optional randomizer for timing
            memory_model: Optional memory model
            log: Logger instance
            super_debug: Enable detailed debugging
            pipeline_debug: Enable pipeline debugging
            signal_map: Optional manual signal mapping
            **kwargs: Additional configuration
        """
        # Create default field config if none provided
        if field_config is None:
            field_config = AXISFieldConfigs.create_default_axis_config()

        # Initialize via GAXISlave — which forwards through GAXIMonitorBase to
        # GAXIComponentBase and calls complete_base_initialization() itself.
        # We pass protocol_type='axis_slave' so SignalResolver picks the AXIS
        # signal table; all other framework kwargs (randomizer, memory_model,
        # pipeline_debug, etc.) flow through GAXISlave's normal handling.
        super().__init__(
            dut=dut, title=title, prefix=prefix, clock=clock,
            field_config=field_config,
            timeout_cycles=timeout_cycles,
            mode=mode,
            bus_name=bus_name,
            pkt_prefix=pkt_prefix,
            multi_sig=multi_sig,
            randomizer=randomizer,
            memory_model=memory_model,
            log=log,
            super_debug=super_debug,
            pipeline_debug=pipeline_debug,
            signal_map=signal_map,
            protocol_type='axis_slave',
            **kwargs,
        )

        # AXIS-specific reception state
        self._receiving = False
        self._current_frame = []
        self._frame_id = None

        # AXIS-specific statistics (frame-level)
        self.packets_received = 0
        self.frames_received = 0
        self.total_data_bytes = 0
        self.errors = 0

        # Layer AXIS frame tracking on top of the GAXI receive pipeline:
        # every packet the pipeline captures is fed to the callback below.
        self.add_callback(self._axis_packet_callback)

        if self.log:
            self.log.info(f"AXISSlave '{self.title}' initialized: "
                         f"mode={self.mode}, timeout={self.timeout_cycles} cycles")

    @staticmethod
    def _packet_byte_count(packet):
        """Number of valid bytes in a captured beat, based on TSTRB bits."""
        return bin(packet.fields.get('strb', 0)).count('1')

    def _axis_packet_callback(self, packet):
        """
        AXIS frame tracking hook, fed by the GAXI receive pipeline.

        The GAXI pipeline owns handshake detection, data capture, ready
        driving, and memory-model writes; this callback only layers
        TLAST-delimited frame accounting and AXIS statistics on top.

        Args:
            packet: Packet captured by the GAXI receive pipeline
        """
        # Update statistics
        self.packets_received += 1
        self.total_data_bytes += self._packet_byte_count(packet)

        # Handle frame boundaries
        if packet.fields.get('last', 0):
            self.frames_received += 1
            self._current_frame.append(packet)
            self._process_complete_frame(self._current_frame)
            self._current_frame = []
            self._frame_id = None
        else:
            self._current_frame.append(packet)
            if self._frame_id is None:
                self._frame_id = packet.fields.get('id', 0)

        if self.log and self.super_debug:
            self.log.debug(f"AXISSlave '{self.title}': "
                         f"Received packet {packet.formatted(compact=True)}")

    def _process_complete_frame(self, frame_packets):
        """
        Process a complete frame (packets ending with TLAST).

        Args:
            frame_packets: List of packets forming a complete frame
        """
        if not frame_packets:
            return

        frame_size = sum(self._packet_byte_count(p) for p in frame_packets)
        frame_id = frame_packets[0].fields.get('id', 0)

        if self.log and self.super_debug:
            self.log.debug(f"AXISSlave '{self.title}': "
                         f"Completed frame ID={frame_id}, size={frame_size} bytes, "
                         f"packets={len(frame_packets)}")

        # Frame processing can be extended here for specific applications
        # For now, just log the completion

    def set_ready_always(self, ready=True):
        """
        Force the ready signal to a fixed value right now.

        .. note::

            The GAXI receive pipeline actively manages ready during
            handshakes, so this override only holds between pipeline
            actions (e.g. while the pipeline is waiting for valid).
            For sustained randomized backpressure use
            :meth:`apply_backpressure` instead.

        Args:
            ready: True for ready asserted, False for ready deasserted
        """
        if hasattr(self, 'ready_sig'):
            self.ready_sig.value = 1 if ready else 0
            if self.log:
                self.log.info(f"AXISSlave '{self.title}': "
                             f"Ready signal set to {'always ready' if ready else 'never ready'}")

    def apply_backpressure(self, probability=0.2, min_cycles=1, max_cycles=5):
        """
        Apply random backpressure by controlling ready signal.

        Args:
            probability: Probability of applying backpressure (0.0 to 1.0)
            min_cycles: Minimum cycles to hold ready low
            max_cycles: Maximum cycles to hold ready low
        """
        # This would be implemented with a background coroutine
        # For now, use randomizer for ready timing
        if self.randomizer:
            constraints = {
                'ready_delay': ([(0, 0), (min_cycles, max_cycles)],
                              [1.0-probability, probability])
            }
            self.randomizer.update_constraints(constraints)

    def get_current_frame_info(self):
        """
        Get information about the currently receiving frame.

        Returns:
            Dictionary with frame information
        """
        return {
            'packets_in_frame': len(self._current_frame),
            'frame_id': self._frame_id,
            'total_bytes': sum(self._packet_byte_count(p) for p in self._current_frame),
            'is_receiving': self._receiving
        }

    def get_stats(self):
        """Get comprehensive statistics."""
        base_stats = self.get_base_stats_unified()

        # Add AXIS slave specific statistics
        axis_stats = {
            'packets_received': self.packets_received,
            'frames_received': self.frames_received,
            'total_data_bytes': self.total_data_bytes,
            'errors': self.errors,
            'current_frame_info': self.get_current_frame_info()
        }

        # Add base monitor statistics
        if hasattr(self, 'stats'):
            axis_stats.update(self.stats.get_stats())

        # Merge base stats with AXIS-specific stats
        base_stats.update(axis_stats)
        return base_stats

    async def wait_for_frame(self, timeout_cycles=None):
        """
        Wait for a complete frame to be received.

        Args:
            timeout_cycles: Maximum cycles to wait (uses self.timeout_cycles if None)

        Returns:
            True if a complete frame was received, False if timeout
        """
        if timeout_cycles is None:
            timeout_cycles = self.timeout_cycles

        initial_frame_count = self.frames_received
        cycles = 0

        while cycles < timeout_cycles:
            if self.frames_received > initial_frame_count:
                # Frame was completed
                return True

            await RisingEdge(self.clock)
            cycles += 1

        # Timeout
        return False

    def __str__(self):
        """String representation."""
        return (f"AXISSlave '{self.title}': "
                f"{self.packets_received} packets received, "
                f"{self.frames_received} frames received, "
                f"current_frame_packets={len(self._current_frame)}")
