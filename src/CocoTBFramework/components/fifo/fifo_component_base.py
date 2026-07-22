# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: FIFOComponentBase
# Purpose: Deprecated alias for GAXIComponentBase
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway

"""DEPRECATED — FIFOComponentBase is a thin subclass of :class:`GAXIComponentBase`.

The original ``FIFOComponentBase`` was a ~95% duplicate of
``GAXIComponentBase`` (same constructor, same SignalResolver wiring, same
``complete_base_initialization``, same ``_setup_data_strategies``). Per issue
#6, the FIFO and GAXI bases have been unified: ``GAXIComponentBase`` is now
the canonical ready/valid component chassis and accepts ``fifo_master`` /
``fifo_slave`` as ``protocol_type`` values (with the appropriate
``write_delay`` / ``read_delay`` randomizer defaults).

This module is kept as a thin compatibility shim:

- Existing imports of ``FIFOComponentBase`` continue to work.
- ``FIFOMaster`` / ``FIFOSlave`` / ``FIFOMonitor`` retain their
  ``FIFOComponentBase`` base class for one release cycle.
- A future release will switch the FIFO BFMs to inherit
  ``GAXIComponentBase`` directly and remove this shim.

The only behavioral delta from the parent is that the default ``mode``
parameter is ``'fifo_mux'`` (FIFO convention) rather than ``'skid'``
(GAXI convention).
"""

from __future__ import annotations

from ..gaxi.gaxi_component_base import GAXIComponentBase
from .fifo_packet import FIFOPacket


class FIFOComponentBase(GAXIComponentBase):
    """Deprecated alias for :class:`GAXIComponentBase`.

    Will be removed in a future release. Subclass ``GAXIComponentBase``
    directly and pass ``protocol_type='fifo_master'`` or ``'fifo_slave'``.
    """

    # FIFO components default to FIFOPacket rather than GAXIPacket. The
    # inherited GAXIComponentBase._build_packet() hook honours this, so
    # `packet_class=` and hook overrides work identically for FIFO BFMs.
    _default_packet_class: type = FIFOPacket

    def __init__(
        self,
        dut,
        title,
        prefix,
        clock,
        field_config,
        protocol_type,
        mode: str = "fifo_mux",
        **kwargs,
    ):
        super().__init__(
            dut=dut,
            title=title,
            prefix=prefix,
            clock=clock,
            field_config=field_config,
            protocol_type=protocol_type,
            mode=mode,
            **kwargs,
        )
