# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""FieldConfig builders for the three MVP DFI sub-interfaces (issue #16).

Each builder returns a ``FieldConfig`` populated with the fields that
actually exist for the requested ``(memory_type, sub_interface)``
combination. The width-keyword sentinels in ``dfi_signals`` are
resolved against the caller-supplied width parameters.
"""

from __future__ import annotations

from typing import Dict

from ..shared.field_config import FieldConfig, FieldDefinition
from .dfi_signals import (
    WIDTH_ADDR,
    WIDTH_BANK,
    WIDTH_CS,
    WIDTH_CTRL,
    WIDTH_DATA,
    WIDTH_DATA_DIV8,
    WIDTH_DATA_EN,
    WIDTH_RD_VALID,
    DFIVersion,
    MemoryType,
    SubInterface,
    signals_for,
)


def _resolve_widths(
    *,
    addr_width: int = 16,
    bank_width: int = 3,
    cs_width: int = 1,
    ctrl_width: int = 1,
    data_width: int = 64,
    data_enable_width: int = 1,
    rd_valid_width: int = 1,
) -> Dict[str, int]:
    """Map width-keyword sentinels (from ``dfi_signals``) to concrete ints.

    All defaults match a typical DDR3 ×4 single-rank config (16-bit
    address, 3-bit bank, single chip select, 64-bit data path).
    """
    return {
        WIDTH_ADDR: addr_width,
        WIDTH_BANK: bank_width,
        WIDTH_CS: cs_width,
        WIDTH_CTRL: ctrl_width,
        WIDTH_DATA: data_width,
        WIDTH_DATA_EN: data_enable_width,
        WIDTH_RD_VALID: rd_valid_width,
        WIDTH_DATA_DIV8: max(1, data_width // 8),
    }


def _build_for(
    sub_interface: SubInterface,
    version: DFIVersion,
    memory_type: MemoryType,
    widths: Dict[str, int],
) -> FieldConfig:
    """Walk the signal catalog for one sub-interface and emit a FieldConfig."""
    cfg = FieldConfig()
    for spec in signals_for(version, memory_type, frozenset({sub_interface})):
        bits = widths[spec.width_key]
        cfg.add_field(FieldDefinition(
            name=spec.name,
            bits=bits,
            default=0,
            format="hex",
            description=spec.description,
        ))
    return cfg


# ----------------------------------------------------------------------
# Public builders — one per MVP sub-interface
# ----------------------------------------------------------------------


def command_field_config(
    *,
    version: DFIVersion = DFIVersion.V2_1,
    memory_type: MemoryType = MemoryType.DDR3,
    addr_width: int = 16,
    bank_width: int = 3,
    cs_width: int = 1,
    ctrl_width: int = 1,
) -> FieldConfig:
    """FieldConfig for the DFI Command (a.k.a. Control) Interface.

    v6.0 renamed the interface and the address bus
    (``dfi_address`` → ``dfi_cmdaddr``); the role is unchanged.
    """
    widths = _resolve_widths(
        addr_width=addr_width,
        bank_width=bank_width,
        cs_width=cs_width,
        ctrl_width=ctrl_width,
    )
    return _build_for(SubInterface.COMMAND, version, memory_type, widths)


def write_data_field_config(
    *,
    version: DFIVersion = DFIVersion.V2_1,
    memory_type: MemoryType = MemoryType.DDR3,
    data_width: int = 64,
    data_enable_width: int = 1,
) -> FieldConfig:
    """FieldConfig for the DFI Write Data Interface."""
    widths = _resolve_widths(
        data_width=data_width,
        data_enable_width=data_enable_width,
    )
    return _build_for(SubInterface.WRITE_DATA, version, memory_type, widths)


def read_data_field_config(
    *,
    version: DFIVersion = DFIVersion.V2_1,
    memory_type: MemoryType = MemoryType.DDR3,
    data_width: int = 64,
    data_enable_width: int = 1,
    rd_valid_width: int = 1,
) -> FieldConfig:
    """FieldConfig for the DFI Read Data Interface."""
    widths = _resolve_widths(
        data_width=data_width,
        data_enable_width=data_enable_width,
        rd_valid_width=rd_valid_width,
    )
    return _build_for(SubInterface.READ_DATA, version, memory_type, widths)
