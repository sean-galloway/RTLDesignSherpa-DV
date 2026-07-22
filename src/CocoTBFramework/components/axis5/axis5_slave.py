# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIS5Slave
# Purpose: AXIS5 Slave - Stream protocol slave with AMBA5 extensions
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-12-21

"""
AXIS5 Slave - Stream protocol slave with AMBA5 extensions

This module provides AXIS5 Slave functionality with:
- TWAKEUP: Wake-up signaling detection
- TPARITY: Data parity checking
"""

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from ..axis4.axis_slave import AXISSlave
from .axis5_field_configs import AXIS5FieldConfigs
from .axis5_packet import AXIS5Packet


class AXIS5Slave(AXISSlave):
    """
    AXIS5 Slave component for receiving AXI5-Stream protocol.

    Extends AXISSlave with AMBA5-specific features:
    - Wake-up signaling detection (TWAKEUP)
    - Parity checking (TPARITY, odd parity per byte)
    - Power management coordination

    Packets are captured by the GAXI receive pipeline (inherited via
    AXISSlave); parity checking is layered on through the AXIS packet
    callback hook. :meth:`_build_packet` is overridden so the pipeline
    produces real :class:`AXIS5Packet` instances with the wakeup / parity
    options this slave was configured with.
    """

    _default_packet_class = AXIS5Packet

    def __init__(self, dut, title, prefix, clock, field_config=None,
                 timeout_cycles=1000, mode='skid',
                 bus_name='', pkt_prefix='', multi_sig=False,
                 randomizer=None, memory_model=None, log=None,
                 super_debug=False, pipeline_debug=False,
                 signal_map=None, enable_wakeup=True, enable_parity=False,
                 **kwargs):
        """
        Initialize AXIS5 Slave.

        Args:
            dut: Device under test
            title: Component title/name
            prefix: Bus prefix (e.g., "s_axis5_", "axis5_")
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
            enable_wakeup: Enable TWAKEUP detection
            enable_parity: Enable TPARITY checking
            **kwargs: Additional configuration
        """
        # Store AXIS5 configuration before super().__init__
        self.enable_wakeup = enable_wakeup
        self.enable_parity = enable_parity

        # Create AXIS5 field config if none provided
        if field_config is None:
            field_config = AXIS5FieldConfigs.create_axis5_field_config(
                enable_wakeup=enable_wakeup,
                enable_parity=enable_parity
            )

        # Initialize parent
        super().__init__(
            dut=dut, title=title, prefix=prefix, clock=clock,
            field_config=field_config, timeout_cycles=timeout_cycles,
            mode=mode, bus_name=bus_name, pkt_prefix=pkt_prefix,
            multi_sig=multi_sig, randomizer=randomizer,
            memory_model=memory_model, log=log,
            super_debug=super_debug, pipeline_debug=pipeline_debug,
            signal_map=signal_map, **kwargs
        )

        # AXIS5 state
        self._wakeup_detected = False
        self._last_wakeup_time = None

        # AXIS5 statistics
        self.wakeup_events = 0
        self.parity_errors_detected = 0
        self.parity_checks_passed = 0

        # Resolve AXIS5-specific signals
        self._resolve_axis5_signals()

        # Start wakeup monitor if enabled
        if self.enable_wakeup and self.wakeup_signal is not None:
            cocotb.start_soon(self._monitor_wakeup())

        if self.log:
            self.log.info(f"AXIS5Slave '{self.title}' initialized: "
                         f"wakeup={self.enable_wakeup}, parity={self.enable_parity}")

    def _resolve_axis5_signals(self):
        """Resolve AXIS5-specific signals."""
        # Try to find TWAKEUP signal
        self.wakeup_signal = None
        if self.enable_wakeup:
            wakeup_names = [
                f"{self.prefix}twakeup",
                f"{self.prefix}wakeup",
                f"{self.prefix}TWAKEUP",
            ]
            for name in wakeup_names:
                if hasattr(self.dut, name):
                    self.wakeup_signal = getattr(self.dut, name)
                    break

        # Try to find TPARITY signal
        self.parity_signal = None
        if self.enable_parity:
            parity_names = [
                f"{self.prefix}tparity",
                f"{self.prefix}parity",
                f"{self.prefix}TPARITY",
            ]
            for name in parity_names:
                if hasattr(self.dut, name):
                    self.parity_signal = getattr(self.dut, name)
                    break

    async def _monitor_wakeup(self):
        """Monitor for TWAKEUP signaling."""
        try:
            while True:
                await RisingEdge(self.clock)

                if self.wakeup_signal is not None:
                    try:
                        wakeup_val = int(self.wakeup_signal.value)
                        if wakeup_val and not self._wakeup_detected:
                            self._wakeup_detected = True
                            self._last_wakeup_time = get_sim_time(units='ns')
                            self.wakeup_events += 1

                            if self.log and self.super_debug:
                                self.log.debug(f"AXIS5Slave '{self.title}': "
                                             f"TWAKEUP detected at {self._last_wakeup_time}ns")

                        elif not wakeup_val and self._wakeup_detected:
                            self._wakeup_detected = False

                    except ValueError:
                        pass  # Signal may be X/Z

        except Exception as e:
            if self.log:
                self.log.error(f"AXIS5Slave '{self.title}': Exception in _monitor_wakeup: {e}")

    def _axis_packet_callback(self, packet):
        """
        AXIS5 packet hook, fed by the GAXI receive pipeline.

        Adds TPARITY verification before the standard AXIS frame tracking.

        Args:
            packet: Packet captured by the GAXI receive pipeline
        """
        if self.enable_parity:
            self._check_parity(packet)

        super()._axis_packet_callback(packet)

    def _axis5_data_width(self):
        """Data width in bits for this slave's field configuration."""
        if 'data' in self.field_config:
            return self.field_config['data'].bits
        return 32

    def _build_packet(self, **field_values):
        """
        Build the AXIS5 packet used by the GAXI receive pipeline.

        Overrides ``GAXIComponentBase._build_packet`` because AXIS5Packet needs
        the wakeup / parity / data-width options that this slave was configured
        with; without them the pipeline would hand back a packet that cannot
        self-check its parity.

        Args:
            **field_values: Optional initial field values

        Returns:
            AXIS5Packet (or the explicit ``packet_class=``) instance
        """
        packet_class = self.packet_class or self._default_packet_class
        packet = packet_class(
            self.field_config,
            data_width=self._axis5_data_width(),
            enable_wakeup=self.enable_wakeup,
            enable_parity=self.enable_parity,
        )
        for field_name, value in field_values.items():
            if hasattr(packet, field_name):
                setattr(packet, field_name, value)
        return packet

    def _check_parity(self, packet):
        """
        Check TPARITY (odd parity per byte) for a received packet.

        The GAXI pipeline now hands back real AXIS5Packet instances (see
        :meth:`_build_packet`), so the packet checks its own parity.

        Args:
            packet: AXIS5Packet captured by the GAXI receive pipeline
        """
        if not isinstance(packet, AXIS5Packet) or 'parity' not in packet.fields:
            return

        if packet.check_parity():
            self.parity_checks_passed += 1
        else:
            self.parity_errors_detected += 1
            packet.parity_error = 1

            if self.log:
                self.log.warning(f"AXIS5Slave '{self.title}': "
                               f"Parity error detected - expected=0x{packet.calculate_parity():X}, "
                               f"received=0x{packet.parity:X}")

    def is_wakeup_active(self):
        """Check if wakeup is currently detected."""
        return self._wakeup_detected

    def get_last_wakeup_time(self):
        """Get timestamp of last wakeup event."""
        return self._last_wakeup_time

    def get_stats(self):
        """Get comprehensive statistics including AXIS5 extensions."""
        base_stats = super().get_stats()

        # Add AXIS5-specific statistics
        axis5_stats = {
            'wakeup_enabled': self.enable_wakeup,
            'parity_enabled': self.enable_parity,
            'wakeup_events': self.wakeup_events,
            'wakeup_active': self._wakeup_detected,
            'last_wakeup_time': self._last_wakeup_time,
            'parity_errors_detected': self.parity_errors_detected,
            'parity_checks_passed': self.parity_checks_passed,
            'parity_error_rate': (self.parity_errors_detected /
                                 max(1, self.parity_errors_detected + self.parity_checks_passed)),
        }

        base_stats.update(axis5_stats)
        return base_stats

    def __str__(self):
        """String representation."""
        return (f"AXIS5Slave '{self.title}': "
                f"{self.packets_received} packets received, "
                f"{self.frames_received} frames received, "
                f"wakeup_events={self.wakeup_events}, "
                f"parity_errors={self.parity_errors_detected}")
