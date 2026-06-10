# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI BFM chassis (issue #16).

:class:`DFIBase` is the shared configuration + sub-interface registry
that :class:`DFIMasterMC`, :class:`DFISlavePHY`, and :class:`DFIMonitor`
all inherit. It holds nothing cocotb-specific — the wire-layer drive
and capture code lives in the subclasses — so it's pure-Python testable
in isolation.

Responsibilities:
  - validate the (dfi_version, memory_type) pair against the spec envelope
  - own the set of enabled sub-interfaces (MVP default: command +
    write_data + read_data)
  - dispatch to the right ``*_field_config`` builder for each
    sub-interface
  - hold the address mapping + timings the slave/monitor will consume
  - maintain a free-running DFI cycle counter the subclasses advance
"""

from __future__ import annotations

from typing import FrozenSet, Optional

from ..shared.field_config import FieldConfig
from .dfi_field_configs import (
    command_field_config,
    read_data_field_config,
    write_data_field_config,
)
from .dfi_signals import (
    MVP_SUB_INTERFACES,
    DFIVersion,
    MemoryType,
    SubInterface,
    is_supported_pair,
)
from .dram_state import AddressMapping
from .jedec_timings import JedecTimings


_FIELD_CONFIG_BUILDERS = {
    SubInterface.COMMAND: command_field_config,
    SubInterface.WRITE_DATA: write_data_field_config,
    SubInterface.READ_DATA: read_data_field_config,
}


class DFIBase:
    """Shared chassis for the three DFI BFM roles.

    Subclasses (``DFIMasterMC`` / ``DFISlavePHY`` / ``DFIMonitor``)
    add the cocotb signal-binding and per-role drive/capture logic;
    everything they need to *configure* themselves lives here.

    The ``tick()`` method advances the cycle counter — subclasses
    call it once per DFI clock edge so the timing checker and the
    BFM share a clock domain.
    """

    def __init__(
        self,
        *,
        dfi_version: DFIVersion,
        memory_type: MemoryType,
        timings: JedecTimings,
        mapping: AddressMapping,
        sub_interfaces: Optional[FrozenSet[SubInterface]] = None,
    ):
        if not is_supported_pair(dfi_version, memory_type):
            raise ValueError(
                f"DFI version {dfi_version.value} + memory type "
                f"{memory_type.value} is not supported (see "
                f"SUPPORTED_MEMORY_BY_VERSION for the envelope)"
            )

        self.dfi_version = dfi_version
        self.memory_type = memory_type
        self.timings = timings
        self.mapping = mapping
        self.enabled_sub_interfaces: FrozenSet[SubInterface] = (
            sub_interfaces if sub_interfaces is not None else MVP_SUB_INTERFACES
        )
        self.cycle = 0

    # ----- Cycle accounting -----

    def tick(self) -> None:
        """Advance the DFI clock by one cycle."""
        self.cycle += 1

    # ----- Field-config dispatch -----

    def field_config_for(self, sub: SubInterface) -> FieldConfig:
        """Return the ``FieldConfig`` for ``sub``, sized to this chassis."""
        if sub not in self.enabled_sub_interfaces:
            raise ValueError(
                f"sub-interface {sub.value} not enabled "
                f"(enabled: {[s.value for s in self.enabled_sub_interfaces]})"
            )
        builder = _FIELD_CONFIG_BUILDERS.get(sub)
        if builder is None:
            raise ValueError(
                f"no field-config builder registered for sub-interface "
                f"{sub.value} (MVP supports COMMAND / WRITE_DATA / READ_DATA)"
            )
        return builder(
            version=self.dfi_version,
            memory_type=self.memory_type,
            bank_width=self.bank_width,
            addr_width=max(self.row_width, self.col_width),
        ) if sub == SubInterface.COMMAND else builder(
            version=self.dfi_version,
            memory_type=self.memory_type,
        )

    # ----- Address-width derivations -----

    @property
    def bank_width(self) -> int:
        """Bit width of the bank field, derived from the mapping geometry."""
        return self.mapping._widths["bank"]

    @property
    def row_width(self) -> int:
        return self.mapping._widths["row"]

    @property
    def col_width(self) -> int:
        return self.mapping._widths["col"]

    @property
    def rank_width(self) -> int:
        return self.mapping._widths["rank"]
