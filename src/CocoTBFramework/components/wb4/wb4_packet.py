# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: WB4Packet
# Purpose: Wishbone B4 packet on the generic Packet base class
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-09-09
"""Wishbone B4 packet: one request and its termination."""

from ..shared.field_config import FieldConfig, FieldDefinition
from ..shared.packet import Packet
from ..shared.wb4_common import WB4_STATUS_NAMES, WE_DIR


class WB4Packet(Packet):
    """One Wishbone transfer: the request fields the master drives (``we``,
    ``adr``, ``dat_w``, ``sel``) and the termination the slave returns
    (``status`` = ACK 0 / ERR 1 / RTY 2, ``dat_r``).

    ``start_time`` is when the request was presented, ``end_time`` when it
    terminated, ``count`` its ordinal at the component that built it. Those
    three are skipped in comparisons by default.
    """

    def __init__(self, field_config=None, skip_compare_fields=None,
                 addr_width=32, data_width=32, sel_width=None, **kwargs):
        sel_width = sel_width if sel_width is not None else data_width // 8
        object.__setattr__(self, 'addr_width', addr_width)
        object.__setattr__(self, 'data_width', data_width)
        object.__setattr__(self, 'sel_width', sel_width)
        object.__setattr__(self, 'count', kwargs.pop('count', 0))
        object.__setattr__(self, 'start_time', kwargs.pop('start_time', 0))
        object.__setattr__(self, 'end_time', kwargs.pop('end_time', 0))
        if field_config is None:
            field_config = WB4Packet.create_wb4_field_config(addr_width, data_width, sel_width)
        if skip_compare_fields is None:
            skip_compare_fields = ['start_time', 'end_time', 'count']
        super().__init__(field_config, skip_compare_fields, **kwargs)

    @staticmethod
    def create_wb4_field_config(addr_width, data_width, sel_width):
        config = FieldConfig()
        config.add_field(FieldDefinition(
            name="we", bits=1, default=0, format="dec", display_width=1,
            description="Write enable (0=read, 1=write)"))
        config.add_field(FieldDefinition(
            name="adr", bits=addr_width, default=0, format="hex",
            display_width=(addr_width + 3) // 4, description="Address"))
        config.add_field(FieldDefinition(
            name="dat_w", bits=data_width, default=0, format="hex",
            display_width=(data_width + 3) // 4, description="Write data (DAT_O at the master)"))
        config.add_field(FieldDefinition(
            name="sel", bits=sel_width, default=(1 << sel_width) - 1, format="bin",
            display_width=sel_width, description="Byte select"))
        config.add_field(FieldDefinition(
            name="dat_r", bits=data_width, default=0, format="hex",
            display_width=(data_width + 3) // 4, description="Read data (DAT_I at the master)"))
        config.add_field(FieldDefinition(
            name="status", bits=2, default=0, format="dec", display_width=1,
            description="Termination: ACK=0 ERR=1 RTY=2",
            encoding={0: "ACK", 1: "ERR", 2: "RTY"}))
        return config

    @property
    def direction(self):
        return WE_DIR[int(self.fields.get('we', 0)) & 1]

    @property
    def status_name(self):
        return WB4_STATUS_NAMES[int(self.fields.get('status', 0)) & 3]

    def formatted(self, compact=False, show_fifo=False):
        if not compact:
            return super().formatted(compact=False, show_fifo=show_fifo)
        f = self.fields
        s = (f"WB {self.direction:5s} adr=0x{int(f.get('adr', 0)):0{(self.addr_width + 3) // 4}X} "
             f"sel=0b{int(f.get('sel', 0)):0{self.sel_width}b}")
        if self.direction == 'WRITE':
            s += f" dat_w=0x{int(f.get('dat_w', 0)):0{(self.data_width + 3) // 4}X}"
        else:
            s += f" dat_r=0x{int(f.get('dat_r', 0)):0{(self.data_width + 3) // 4}X}"
        return s + f" {self.status_name}"
