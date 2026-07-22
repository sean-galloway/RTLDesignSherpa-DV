# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: GAXIComponentBase
# Purpose: GAXIComponentBase - Unified base class for all GAXI components
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
GAXIComponentBase - Unified base class for all GAXI components

This base class consolidates common functionality across GAXIMaster, GAXIMonitor,
and GAXISlave, eliminating code duplication while preserving exact APIs and timing.

All existing parameters are preserved and used exactly as before.

FIXED: Now passes resolved signals directly to DataStrategies, eliminating guesswork.
ADDED: Optional signal_map parameter for manual signal mapping override.
"""

from __future__ import annotations

from logging import Logger
from typing import Any, Optional, Union

from cocotb.utils import get_sim_time

from ..shared.data_strategies import DataCollectionStrategy, DataDrivingStrategy
from ..shared.field_config import FieldConfig
from ..shared.flex_randomizer import FlexRandomizer
from ..shared.memory_model import MemoryModel
from ..shared.packet import Packet
from ..shared.protocol_types import validate_protocol_type
from ..shared.signal_mapping_helper import SignalResolver
from .gaxi_packet import GAXIPacket

# Type aliases for cocotb-specific handle types. Cocotb's handle classes are
# complex and not always import-safe (vendor sim shims), so we accept Any at
# the API surface and rely on cocotb's own runtime type checking downstream.
DutHandle = Any
ClockSignal = Any
FieldConfigInput = Union[FieldConfig, dict, None]


class GAXIComponentBase:
    """
    Unified base class for all GAXI components (Master, Monitor, Slave).

    Consolidates common initialization, signal resolution, data handling,
    and packet management while preserving component-specific functionality.

    FIXED: Data strategies now receive resolved signals directly from SignalResolver
    instead of doing their own signal discovery.

    ADDED: Optional signal_map parameter for manual signal override.
    ADDED: Coverage hooks for automatic transaction sampling.
    ADDED: `_build_packet()` packet-construction hook (see the method docstring)
    so protocol BFMs that delegate to the GAXI pipelines keep their own packet
    subclass instead of silently receiving plain GAXIPackets.
    """

    # Packet class used by :meth:`_build_packet` when neither the
    # ``packet_class`` constructor argument nor a hook override is supplied.
    # Subclass chassis for other protocols override this (e.g.
    # FIFOComponentBase sets it to FIFOPacket).
    _default_packet_class: type = GAXIPacket

    def __init__(
        self,
        dut: DutHandle,
        title: str,
        prefix: str,
        clock: ClockSignal,
        field_config: FieldConfigInput,
        protocol_type: str,  # Must be specified by subclass
        mode: str = "skid",
        bus_name: str = "",
        pkt_prefix: str = "",
        multi_sig: bool = False,
        randomizer: Optional[FlexRandomizer] = None,
        memory_model: Optional[MemoryModel] = None,
        log: Optional[Logger] = None,
        super_debug: bool = False,
        signal_map: Optional[dict] = None,  # NEW: Optional manual signal mapping
        packet_class: Optional[type] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize common GAXI component functionality.

        Args:
            dut: Device under test
            title: Component title/name
            prefix: Bus prefix
            clock: Clock signal
            field_config: Field configuration (FieldConfig or dict)
            protocol_type: Protocol type ('gaxi_master', 'gaxi_slave', 'axis_master',
                        'axis_slave', 'fifo_master', or 'fifo_slave')
            mode: GAXI mode ('skid', 'fifo_mux', 'fifo_flop')
            bus_name: Bus/channel name
            pkt_prefix: Packet field prefix
            multi_sig: Whether using multi-signal mode
            randomizer: Optional randomizer for timing
            memory_model: Optional memory model for transactions
            log: Logger instance
            super_debug: Enable detailed debugging
            signal_map: Optional dict mapping simplified signal names to DUT signal names.
                        Keys: 'valid', 'ready', 'data' (or field names for multi_sig=True)
                        Values: DUT signal name strings
                        If provided, bypasses automatic signal discovery.
            packet_class: Optional Packet subclass produced by the receive
                        pipeline. None (default) keeps the class-level
                        default (:class:`GAXIPacket` for GAXI components).
                        Must be a subclass of the shared ``Packet``.
            **kwargs: Additional arguments for specific component types
        """
        # Packet class used by the _build_packet() hook. Validated eagerly so a
        # bad value fails at construction rather than mid-simulation.
        if packet_class is not None and not (
            isinstance(packet_class, type) and issubclass(packet_class, Packet)
        ):
            raise TypeError(
                f"packet_class must be a subclass of Packet, got {packet_class!r}"
            )
        self.packet_class = packet_class

        # Store all parameters exactly as provided - no changes to APIs
        self.title = title
        self.clock = clock
        self.mode = mode
        self.super_debug = super_debug
        self.bus_name = bus_name
        self.pkt_prefix = pkt_prefix
        self.use_multi_signal = multi_sig
        self.memory_model = memory_model
        self.signal_map = signal_map  # NEW: Store signal map

        # Validate protocol_type against the canonical set (shared/protocol_types.py).
        # The shared set covers GAXI, AXIS, AXI4, AXI5, and FIFO. FIFO support
        # for this base added in #6 (FIFO BFMs inherit via FIFOComponentBase alias).
        validate_protocol_type(protocol_type)
        self.protocol_type = protocol_type

        # Normalize field_config - handle dict conversion uniformly
        self.field_config = self._normalize_field_config(field_config)

        # Set up logging early (will be overridden by cocotb parent if None)
        self.log = log

        # Set up randomizer with defaults if needed
        self.randomizer = self._setup_randomizer(randomizer, protocol_type)

        # Modern infrastructure - signal resolution
        self.signal_resolver = SignalResolver(
            protocol_type=protocol_type,
            dut=dut,
            bus=None,  # Set after cocotb parent class init
            log=self.log,
            component_name=title,
            prefix=prefix,
            field_config=self.field_config,
            multi_sig=self.use_multi_signal,
            bus_name=self.bus_name,
            pkt_prefix=self.pkt_prefix,
            mode=mode,
            super_debug=super_debug,
            signal_map=signal_map  # NEW: Pass signal map to resolver
        )

        # Get signal lists for cocotb Bus initialization
        self._signals, self._optional_signals = self.signal_resolver.get_signal_lists()

        # Data strategies - will be set up after signal resolution is complete
        self.data_collector = None
        self.data_driver = None

        # Store additional kwargs for subclass use
        self._component_kwargs = kwargs

        # Coverage hooks - list of callables that receive transaction info
        # Each hook is called with: (component, transaction, direction, interface)
        # where direction is 'tx' (transmit) or 'rx' (receive)
        self._coverage_hooks = []

    def _normalize_field_config(self, field_config: FieldConfigInput) -> FieldConfig:
        """
        Standardize field_config handling across all components.

        Args:
            field_config: FieldConfig object, dict, or None

        Returns:
            FieldConfig object
        """
        if isinstance(field_config, dict):
            return FieldConfig.validate_and_create(field_config)
        elif field_config is None:
            return FieldConfig.create_data_only()
        elif isinstance(field_config, FieldConfig):
            return field_config
        else:
            raise TypeError(f"field_config must be FieldConfig, dict, or None, got {type(field_config)}")

    def _setup_randomizer(
        self,
        randomizer: Optional[FlexRandomizer],
        protocol_type: str,
    ) -> FlexRandomizer:
        """
        Set up randomizer with appropriate defaults for component type.

        Args:
            randomizer: Provided randomizer or None
            protocol_type: Component protocol type

        Returns:
            FlexRandomizer instance
        """
        if randomizer is not None:
            return randomizer

        # Default constraints based on component type. FIFO uses
        # write_delay/read_delay; ready/valid protocols use valid_delay/ready_delay.
        if protocol_type == 'gaxi_master':
            default_constraints = {
                'valid_delay': ([(0, 0), (1, 8), (9, 20)], [5, 2, 1])
            }
        elif protocol_type == 'fifo_master':
            default_constraints = {
                'write_delay': ([(0, 0), (1, 8), (9, 20)], [5, 2, 1])
            }
        elif protocol_type == 'fifo_slave':
            default_constraints = {
                'read_delay': ([(0, 1), (2, 8), (9, 30)], [5, 2, 1])
            }
        else:  # gaxi_slave, axis_slave, axi4_*_slave, axi5_*_slave (ready_delay path)
            default_constraints = {
                'ready_delay': ([(0, 1), (2, 8), (9, 30)], [5, 2, 1])
            }

        return FlexRandomizer(default_constraints)

    def complete_base_initialization(self, bus: Any = None) -> None:
        """
        Complete initialization after cocotb parent class setup.

        This must be called by subclasses after their cocotb parent class
        (BusDriver/BusMonitor) initialization is complete.

        Args:
            bus: Bus object from cocotb parent class
        """
        # Apply signal mappings now that bus is available
        if bus is not None:
            self.signal_resolver.bus = bus
            self.signal_resolver.apply_to_component(self)

        # Set up data strategies now that signals are resolved
        self._setup_data_strategies()

        # Log successful initialization
        side_description = "slave" if "slave" in self.protocol_type else "master"
        signal_source = "manual signal_map" if self.signal_map else "automatic discovery"
        if self.log:
            self.log.info(f"GAXIComponentBase '{self.title}' initialized: {side_description} side, "
                        f"mode={self.mode}, multi_sig={self.use_multi_signal}, signals={signal_source}")

    def _setup_data_strategies(self) -> None:
        """
        Set up data collection and driving strategies based on component needs.

        FIXED: Now passes resolved signals directly to DataStrategies instead of
        letting them do their own signal discovery.
        """
        # Get the resolved signals from SignalResolver
        resolved_signals = self.signal_resolver.resolved_signals

        # Data collection strategy - used by all components for monitoring
        self.data_collector = DataCollectionStrategy(
            component=self,
            field_config=self.field_config,
            use_multi_signal=self.use_multi_signal,
            log=self.log,
            resolved_signals=resolved_signals  # FIXED: Pass resolved signals directly
        )

        # Data driving strategy - used by masters and slaves that drive signals
        self.data_driver = DataDrivingStrategy(
            component=self,
            field_config=self.field_config,
            use_multi_signal=self.use_multi_signal,
            log=self.log,
            resolved_signals=resolved_signals  # FIXED: Pass resolved signals directly
        )

    # =========================================================================
    # Packet construction hook
    # =========================================================================

    def _build_packet(self, **field_values: Any) -> Any:
        """Construct the packet used throughout this component's pipeline.

        This is the single extension point for packet construction in the
        GAXI/FIFO component family — every packet the receive pipeline,
        ``create_packet()``, and the master transmit path produce comes from
        here. It mirrors the APB precedent (``APBMonitor._build_packet``,
        overridden by ``APB5Monitor``); see
        ``docs/components/gaxi/components_gaxi_gaxi_component_base.md``.

        Resolution order for the class constructed:

        1. ``self.packet_class``, if a ``packet_class=`` was passed to the
           component or its factory.
        2. ``self._default_packet_class`` (``GAXIPacket`` for GAXI,
           ``FIFOPacket`` for the FIFO chassis).

        Protocol BFMs that delegate to the GAXI pipelines (AXI4/AXI5/AXIS/
        FIFO) should override this method when their packet needs constructor
        arguments beyond ``field_config``, so downstream ``isinstance()``
        checks against the protocol packet class keep working::

            class AXIS5Slave(GAXISlave):
                def _build_packet(self, **field_values):
                    return AXIS5Packet(
                        self.field_config,
                        parity_enabled=self.parity_enabled,
                        **field_values,
                    )

        Args:
            **field_values: Optional initial field values. Values naming a
                field the packet exposes are assigned after construction;
                unknown names are ignored (preserving the historical
                ``create_packet()`` contract).

        Returns:
            A newly constructed packet instance.
        """
        packet_class = self.packet_class or self._default_packet_class
        packet = packet_class(self.field_config)
        for field_name, value in field_values.items():
            if hasattr(packet, field_name):
                setattr(packet, field_name, value)
        return packet

    def get_data_dict_unified(self):
        """
        Get current data from signals with automatic field unpacking.

        Uses unified DataCollectionStrategy for consistent behavior.

        Returns:
            Dictionary of field values, properly unpacked
        """
        if self.data_collector:
            return self.data_collector.collect_and_unpack_data()
        return {}

    def drive_transaction_unified(self, transaction):
        """
        Drive transaction data using unified DataDrivingStrategy.

        Args:
            transaction: Transaction to drive

        Returns:
            True if successful, False otherwise
        """
        if self.data_driver:
            current_time = get_sim_time('ns')
            self.log.debug(f"Driving transaction @ {current_time}ns: {transaction.formatted(compact=True)}")
            return self.data_driver.drive_transaction(transaction)
        return False

    def clear_signals_unified(self):
        """Clear all data signals using unified strategy."""
        if self.data_driver:
            self.data_driver.clear_signals()

    def write_to_memory_unified(self, transaction):
        """
        Write transaction to memory using base MemoryModel directly.

        Args:
            transaction: Transaction to write

        Returns:
            (success, error_message) tuple
        """
        if self.memory_model:
            return self.memory_model.write_transaction(
                transaction,
                component_name=self.title
            )
        return False, "No memory model available"

    def read_from_memory_unified(self, transaction, update_transaction=True):
        """
        Read data from memory using base MemoryModel directly.

        Args:
            transaction: Transaction with address to read
            update_transaction: Whether to update transaction with read data

        Returns:
            (success, data, error_message) tuple
        """
        if self.memory_model:
            return self.memory_model.read_transaction(
                transaction,
                update_transaction=update_transaction,
                component_name=self.title
            )
        return False, None, "No memory model available"

    def get_base_stats_unified(self):
        """
        Get comprehensive base statistics common to all components.

        Returns:
            Dictionary containing base statistics
        """
        base_stats = {
            'component_type': self.protocol_type,
            'mode': self.mode,
            'multi_signal': self.use_multi_signal,
            'field_count': len(self.field_config) if self.field_config else 0,
            'title': self.title,
            'signal_mapping_source': 'manual' if self.signal_map else 'automatic'  # NEW
        }

        # Add signal resolver stats
        if self.signal_resolver:
            base_stats['signal_resolver_stats'] = self.signal_resolver.get_stats()

        # Add data strategy stats
        if self.data_collector:
            base_stats['data_collector_stats'] = self.data_collector.get_stats()
        if self.data_driver:
            base_stats['data_driver_stats'] = self.data_driver.get_stats()

        # Add memory stats if available
        if self.memory_model:
            base_stats['memory_stats'] = self.memory_model.get_stats()

        return base_stats

    def set_randomizer(self, randomizer):
        """
        Set new randomizer for timing control.

        Args:
            randomizer: FlexRandomizer instance
        """
        self.randomizer = randomizer
        if self.log:
            self.log.info(f"GAXIComponentBase '{self.title}': Set new randomizer")

    # =========================================================================
    # Coverage Hook Infrastructure
    # =========================================================================

    def add_coverage_hook(self, hook):
        """
        Register a coverage hook to be called on transactions.

        The hook will be called with:
            hook(component, transaction, direction, interface)

        Where:
            - component: This GAXIComponentBase instance
            - transaction: The GAXIPacket being transmitted/received
            - direction: 'tx' for transmit, 'rx' for receive
            - interface: Interface name (from bus_name or title)

        Args:
            hook: Callable that receives coverage data
        """
        if hook not in self._coverage_hooks:
            self._coverage_hooks.append(hook)
            if self.log:
                self.log.debug(f"GAXIComponentBase '{self.title}': Added coverage hook")

    def remove_coverage_hook(self, hook):
        """
        Remove a previously registered coverage hook.

        Args:
            hook: The hook to remove
        """
        if hook in self._coverage_hooks:
            self._coverage_hooks.remove(hook)
            if self.log:
                self.log.debug(f"GAXIComponentBase '{self.title}': Removed coverage hook")

    def clear_coverage_hooks(self):
        """Remove all coverage hooks."""
        self._coverage_hooks.clear()
        if self.log:
            self.log.debug(f"GAXIComponentBase '{self.title}': Cleared all coverage hooks")

    def _trigger_coverage_hooks(self, transaction, direction):
        """
        Trigger all registered coverage hooks.

        This is called by Master/Slave/Monitor subclasses when transactions complete.

        Args:
            transaction: The completed transaction (GAXIPacket)
            direction: 'tx' for transmit (master->slave), 'rx' for receive (slave->master)
        """
        if not self._coverage_hooks:
            return

        # Determine interface name from bus_name or title
        interface = self.bus_name if self.bus_name else self.title

        for hook in self._coverage_hooks:
            try:
                hook(self, transaction, direction, interface)
            except Exception as e:
                if self.log:
                    self.log.warning(f"GAXIComponentBase '{self.title}': "
                                   f"Coverage hook raised exception: {e}")
