# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: APB3Factories
# Purpose: Factory functions for creating APB3 BFM components.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""Factory functions for creating APB3 BFM components."""

from ..shared.flex_randomizer import FlexRandomizer
from ..shared.memory_model import MemoryModel
from .apb3_components import APB3Master, APB3Monitor, APB3Slave


def create_apb3_master(entity, title, prefix, clock,
                       bus_width=32, addr_width=12, randomizer=None, log=None):
    """Create an APB3 Master BFM.

    Args:
        entity: The DUT entity.
        title: Name/title for the master.
        prefix: Signal prefix for APB signals.
        clock: Clock signal.
        bus_width: Data bus width in bits.
        addr_width: Address width in bits.
        randomizer: Optional FlexRandomizer for PSEL/PENABLE delays.
        log: Logger instance.

    Returns:
        APB3Master instance.
    """
    if randomizer is None:
        randomizer = FlexRandomizer({
            'psel':    ([(0, 0), (1, 5), (6, 10)], [5, 3, 1]),
            'penable': ([(0, 0), (1, 3)], [3, 1]),
        })

    return APB3Master(
        entity=entity,
        title=title,
        prefix=prefix,
        clock=clock,
        bus_width=bus_width,
        addr_width=addr_width,
        randomizer=randomizer,
        log=log,
    )


def create_apb3_slave(entity, title, prefix, clock, registers,
                      bus_width=32, addr_width=12, randomizer=None, log=None,
                      error_overflow=False):
    """Create an APB3 Slave BFM.

    Args:
        entity: The DUT entity.
        title: Name/title for the slave.
        prefix: Signal prefix for APB signals.
        clock: Clock signal.
        registers: Initial register values (or number of registers).
        bus_width: Data bus width in bits.
        addr_width: Address width in bits.
        randomizer: Optional FlexRandomizer for PREADY delays/errors.
        log: Logger instance.
        error_overflow: Whether to generate errors on address overflow.

    Returns:
        APB3Slave instance.
    """
    if registers is None:
        registers = []
    elif isinstance(registers, int):
        registers = [0] * (registers * (bus_width // 8))

    if randomizer is None:
        randomizer = FlexRandomizer({
            'ready': ([(0, 1), (2, 5), (6, 10)], [5, 2, 1]),
            'error': ([(0, 0), (1, 1)], [10, 0]),
        })

    return APB3Slave(
        entity=entity,
        title=title,
        prefix=prefix,
        clock=clock,
        registers=registers,
        bus_width=bus_width,
        addr_width=addr_width,
        randomizer=randomizer,
        log=log,
        error_overflow=error_overflow,
    )


def create_apb3_monitor(entity, title, prefix, clock,
                        bus_width=32, addr_width=12, log=None):
    """Create an APB3 Monitor.

    Args:
        entity: The DUT entity.
        title: Name/title for the monitor.
        prefix: Signal prefix for APB signals.
        clock: Clock signal.
        bus_width: Data bus width in bits.
        addr_width: Address width in bits.
        log: Logger instance.

    Returns:
        APB3Monitor instance.
    """
    return APB3Monitor(
        entity=entity,
        title=title,
        prefix=prefix,
        clock=clock,
        bus_width=bus_width,
        addr_width=addr_width,
        log=log,
    )


def create_apb3_components(entity, clock, title_prefix="",
                           bus_width=32, addr_width=12,
                           memory_lines=1024, randomizer=None, log=None):
    """Create a complete set of APB3 components (master, slave, monitor).

    Args:
        entity: The DUT entity.
        clock: Clock signal.
        title_prefix: Prefix for component titles.
        bus_width: Data bus width in bits.
        addr_width: Address width in bits.
        memory_lines: Number of memory lines for the shared memory model.
        randomizer: Optional FlexRandomizer for the master.
        log: Logger instance.

    Returns:
        Dictionary containing the master, monitor, and memory model.  No
        scoreboard is created because APB3 does not have a dedicated
        scoreboard in this package.
    """
    if log is None:
        log = getattr(entity, '_log', None)

    memory_model = MemoryModel(
        num_lines=memory_lines,
        bytes_per_line=bus_width // 8,
        log=log,
    )

    master = create_apb3_master(
        entity=entity,
        title=f"{title_prefix}APB3 Master",
        prefix="s_apb",
        clock=clock,
        bus_width=bus_width,
        addr_width=addr_width,
        randomizer=randomizer,
        log=log,
    )

    monitor = create_apb3_monitor(
        entity=entity,
        title=f"{title_prefix}APB3 Monitor",
        prefix="s_apb",
        clock=clock,
        bus_width=bus_width,
        addr_width=addr_width,
        log=log,
    )

    return {
        'master': master,
        'monitor': monitor,
        'memory_model': memory_model,
    }
