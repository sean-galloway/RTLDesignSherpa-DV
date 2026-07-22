# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXISMaster
# Purpose: AXIS Master - Stream protocol master implementation
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXIS Master - Stream protocol master implementation

This module provides AXIS Master functionality by delegating to the GAXI
infrastructure. All signal driving goes through GAXIMaster's structured
transmit pipeline (queue -> phase1 delay -> phase2 drive/handshake ->
phase3 complete); AXIS adds packet/frame conveniences and TLAST-aware
statistics on top.
"""

from cocotb.triggers import RisingEdge

from ..gaxi.gaxi_master import GAXIMaster
from .axis_field_configs import AXISFieldConfigs
from .axis_packet import AXISPacket


class AXISMaster(GAXIMaster):
    """
    AXIS Master component for driving AXI4-Stream protocol.

    Inherits the transmit pipeline from :class:`GAXIMaster`:
    - Signal resolution and data driving setup
    - Structured transmit pipeline with handshake/timeout handling
    - Unified field configuration handling
    - Statistics and logging patterns

    AXIS-specific features added by this subclass:
    - Stream/frame conveniences (``send_stream_data``, ``send_frame``,
      ``send_single_beat``)
    - Packet/frame boundary handling with TLAST
    - Frame-level statistics (``packets_sent`` / ``frames_sent``)
    """

    def __init__(self, dut, title, prefix, clock, field_config=None,
                timeout_cycles=1000, mode='skid',
                bus_name='', pkt_prefix='',
                multi_sig=False, randomizer=None, memory_model=None,
                log=None, super_debug=False, pipeline_debug=False,
                signal_map=None, **kwargs):
        """
        Initialize AXIS Master.

        Args:
            dut: Device under test
            title: Component title/name
            prefix: Bus prefix (e.g., "m_axis_", "fub_axis_")
            clock: Clock signal
            field_config: Field configuration (if None, creates default)
            timeout_cycles: Maximum cycles to wait for ready
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

        # Initialize GAXIMaster - this sets up the transmit pipeline,
        # statistics (self.stats), signal resolution, and completes base
        # initialization. AXIS reuses all of it unchanged.
        super().__init__(
            dut=dut, title=title, prefix=prefix, clock=clock,
            field_config=field_config, timeout_cycles=timeout_cycles,
            mode=mode, bus_name=bus_name, pkt_prefix=pkt_prefix,
            multi_sig=multi_sig, randomizer=randomizer,
            memory_model=memory_model, log=log,
            super_debug=super_debug, pipeline_debug=pipeline_debug,
            signal_map=signal_map, protocol_type='axis_master', **kwargs
        )

        # AXIS-specific counters (frame-level, not in base MasterStatistics)
        self.packets_sent = 0
        self.frames_sent = 0

        if self.log:
            self.log.info(f"AXISMaster '{self.title}' initialized: "
                         f"mode={self.mode}, timeout={self.timeout_cycles} cycles")

    @staticmethod
    def _packet_is_last(packet):
        """Return True if the packet's TLAST field is set."""
        return bool(packet.fields.get('last', 0))

    def _record_packet_sent(self, packet):
        """Update AXIS-level statistics and memory model for a sent packet."""
        self.packets_sent += 1
        if self._packet_is_last(packet):
            self.frames_sent += 1

        # Write to memory model if available
        if self.memory_model:
            self.write_to_memory_unified(packet)

        if self.log and self.super_debug:
            self.log.debug(f"AXISMaster '{self.title}': "
                         f"Successfully sent packet {packet}")

    def _build_stream_packets(self, data_list, id=0, dest=0, user=0,
                              auto_last=True, strb_list=None):
        """Build AXISPacket objects for a stream of data values."""
        packets = []
        for i, data in enumerate(data_list):
            # Determine if this is the last transfer
            is_last = auto_last and (i == len(data_list) - 1)

            # Get strobe value
            strb = None
            if strb_list and i < len(strb_list):
                strb = strb_list[i]

            # Create packet
            packet = AXISPacket(field_config=self.field_config)
            packet.data = data
            packet.last = 1 if is_last else 0
            packet.id = id
            packet.dest = dest
            packet.user = user

            # Set strobe
            if strb is not None:
                packet.strb = strb
            elif 'strb' in self.field_config:
                # Auto-generate full strobe
                strb_bits = self.field_config['strb'].bits
                packet.strb = (1 << strb_bits) - 1

            packets.append(packet)

        return packets

    async def send_stream_data(self, data_list, id=0, dest=0, user=0,
                              auto_last=True, strb_list=None):
        """
        Send stream data with automatic packet management.

        All beats are queued on the GAXI transmit pipeline up front so they
        stream back-to-back (zero-bubble when the slave keeps ready high),
        then this method waits for the pipeline to drain.

        Args:
            data_list: List of data values to send
            id: Stream ID for all transfers
            dest: Destination for all transfers
            user: User signal for all transfers
            auto_last: Automatically set TLAST on final transfer
            strb_list: Optional list of strobe values (if None, auto-generate)

        Returns:
            True if successful (a handshake timeout raises TestFailure from
            the GAXI pipeline)
        """
        if not data_list:
            return True

        packets = self._build_stream_packets(
            data_list, id=id, dest=dest, user=user,
            auto_last=auto_last, strb_list=strb_list
        )

        # Queue all beats on the GAXI pipeline for back-to-back transmission
        for packet in packets:
            await self._driver_send(packet, sync=True)

        # Wait for the pipeline to drain
        while self.transmit_coroutine is not None:
            await RisingEdge(self.clock)

        for packet in packets:
            self._record_packet_sent(packet)

        return True

    async def send_packet(self, packet):
        """
        Send a single AXIS packet via the GAXI transmit pipeline.

        Args:
            packet: AXISPacket to send

        Returns:
            True if successful (a handshake timeout raises TestFailure from
            the GAXI pipeline)
        """
        if self.log and self.super_debug:
            self.log.debug(f"AXISMaster '{self.title}': Sending packet {packet}")

        # Delegate to GAXIMaster's pipelined send (queues the packet and
        # waits for the transmit pipeline to complete).
        result = await self.send(packet)

        self._record_packet_sent(packet)
        return result

    async def send_frame(self, frame_data, frame_id=0, dest=0, user=0):
        """
        Send a complete frame (multiple transfers with TLAST on final).

        Args:
            frame_data: List of data values for the frame
            frame_id: Frame ID
            dest: Destination
            user: User signal

        Returns:
            True if successful
        """
        return await self.send_stream_data(
            data_list=frame_data,
            id=frame_id,
            dest=dest,
            user=user,
            auto_last=True
        )

    async def send_single_beat(self, data, last=1, id=0, dest=0, user=0, strb=None):
        """
        Send a single beat/transfer.

        Args:
            data: Data value
            last: TLAST value
            id: Stream ID
            dest: Destination
            user: User signal
            strb: Strobe value (if None, auto-generate)

        Returns:
            True if successful
        """
        packet = AXISPacket(field_config=self.field_config)
        packet.data = data
        packet.last = last
        packet.id = id
        packet.dest = dest
        packet.user = user

        if strb is not None:
            packet.strb = strb
        elif 'strb' in self.field_config:
            strb_bits = self.field_config['strb'].bits
            packet.strb = (1 << strb_bits) - 1

        return await self.send_packet(packet)

    def is_busy(self):
        """Check if master is currently busy sending."""
        return self.transfer_busy or len(self.transmit_queue) > 0

    def get_queue_depth(self):
        """Get current send queue depth (GAXI transmit queue)."""
        return len(self.transmit_queue)

    def get_stats(self):
        """Get comprehensive statistics."""
        # GAXIMaster stats: base stats + master_stats + pipeline_stats
        base_stats = super().get_stats()

        # Add AXIS master specific statistics
        axis_stats = {
            'packets_sent': self.packets_sent,
            'frames_sent': self.frames_sent,
            'total_data_bytes': self.stats.bytes_transferred,
            'timeouts': self.stats.timeout_events,
            'errors': self.stats.transactions_failed,
            'queue_depth': self.get_queue_depth(),
            'is_busy': self.is_busy()
        }

        # Merge base stats with AXIS-specific stats
        base_stats.update(axis_stats)
        return base_stats

    def __str__(self):
        """String representation."""
        return (f"AXISMaster '{self.title}': "
                f"{self.packets_sent} packets sent, "
                f"{self.frames_sent} frames sent, "
                f"queue_depth={self.get_queue_depth()}")
