# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIS5Packet
# Purpose: AXIS5 Packet - Stream protocol packet with AMBA5 extensions
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-12-21

"""
AXIS5 Packet - Stream protocol packet with AMBA5 extensions

This module provides packet classes for AXI5-Stream protocol with:
- TWAKEUP: Wake-up signaling
- Interface parity (IHI 0051B ch. 5): TDATACHK, TSTRBCHK, TLASTCHK, TIDCHK,
  TDESTCHK, TUSERCHK as packet fields (odd parity, one bit per 8 bits)
"""

import random

from ..axis4.axis_packet import AXISPacket
from ..shared.field_config import FieldConfig, FieldDefinition
from ..shared.flex_randomizer import FlexRandomizer
from .axis5_check import PAYLOAD_CHECK_FIELDS, chk_width, odd_parity_chk, payload_check_values


def calculate_odd_parity(data_value: int, num_bytes: int) -> int:
    """
    Calculate AXI5-Stream TDATACHK (IHI 0051B ch. 5: odd parity, one bit per byte).

    Each parity bit is set so that the corresponding data byte plus its
    parity bit contain an odd number of ones: parity = NOT XOR(byte bits).

    Args:
        data_value: Data word to protect
        num_bytes: Number of bytes (= number of parity bits)

    Returns:
        Parity value with bit i protecting byte i
    """
    return odd_parity_chk(data_value, num_bytes * 8)


class AXIS5Packet(AXISPacket):
    """
    AXIS5 Packet class for AXI5-Stream protocol.

    Extends AXISPacket with AMBA5-specific fields:
    - wakeup: Wake-up signaling
    - datachk/strbchk/lastchk/idchk/destchk/userchk: the IHI 0051B Table 5-1
      payload check signals (drive/sample {prefix}tdatachk etc.)
    - parity_error: Parity error indicator (no pin)
    """

    def __init__(self, field_config=None, skip_compare_fields=None,
                 data_width=32, enable_wakeup=True, enable_parity=False, **kwargs):
        """
        Initialize AXIS5 packet.

        Args:
            field_config: Field configuration (if None, creates default)
            skip_compare_fields: Fields to skip in comparison
            data_width: Data width in bits
            enable_wakeup: Enable wakeup signal field
            enable_parity: Enable parity signal field
            **kwargs: Initial field values
        """
        # Store AXIS5 configuration
        object.__setattr__(self, 'enable_wakeup', enable_wakeup)
        object.__setattr__(self, 'enable_parity', enable_parity)
        object.__setattr__(self, 'data_width', data_width)
        object.__setattr__(self, 'parity_width', data_width // 8)

        # Create field config if not provided
        if field_config is None:
            field_config = self.create_axis5_field_config(
                data_width=data_width,
                enable_wakeup=enable_wakeup,
                enable_parity=enable_parity
            )

        # Set default skip fields
        if skip_compare_fields is None:
            skip_compare_fields = ['start_time', 'end_time', 'count', 'parity_error']

        # Initialize parent. skip_compare_fields must be passed by keyword so it
        # reaches Packet.__init__ (GAXIPacket's positional args are randomizers).
        super().__init__(field_config, skip_compare_fields=skip_compare_fields, **kwargs)

    @staticmethod
    def create_axis5_field_config(data_width=32, id_width=8, dest_width=4, user_width=1,
                                   enable_wakeup=True, enable_parity=False):
        """
        Create field configuration for AXIS5 packets.

        Args:
            data_width: Data width in bits
            id_width: ID width in bits
            dest_width: Destination width in bits
            user_width: User width in bits
            enable_wakeup: Enable wakeup field
            enable_parity: Enable parity field

        Returns:
            FieldConfig object with AXIS5 fields
        """
        strb_width = data_width // 8
        config = FieldConfig()

        # Core AXIS fields
        config.add_field(FieldDefinition(
            name="data",
            bits=data_width,
            default=0,
            format="hex",
            display_width=data_width // 4,
            description="Stream Data"
        ))

        config.add_field(FieldDefinition(
            name="strb",
            bits=strb_width,
            default=(1 << strb_width) - 1,
            format="bin",
            display_width=strb_width,
            description="Byte Strobes"
        ))

        config.add_field(FieldDefinition(
            name="last",
            bits=1,
            default=0,
            format="dec",
            display_width=1,
            description="Last Transfer"
        ))

        config.add_field(FieldDefinition(
            name="id",
            bits=id_width,
            default=0,
            format="hex",
            display_width=max(1, id_width // 4),
            description="Stream ID"
        ))

        config.add_field(FieldDefinition(
            name="dest",
            bits=dest_width,
            default=0,
            format="hex",
            display_width=max(1, dest_width // 4),
            description="Destination"
        ))

        config.add_field(FieldDefinition(
            name="user",
            bits=user_width,
            default=0,
            format="hex",
            display_width=max(1, user_width // 4),
            description="User Signal"
        ))

        # AXIS5 extension fields
        if enable_wakeup:
            config.add_field(FieldDefinition(
                name="wakeup",
                bits=1,
                default=0,
                format="dec",
                display_width=1,
                description="Wake-up Signal"
            ))

        if enable_parity:
            # IHI 0051B Table 5-1 payload check signals, one bit per 8 bits
            for name, width in (('data', data_width), ('strb', strb_width),
                                ('last', 1), ('id', id_width),
                                ('dest', dest_width), ('user', user_width)):
                if width <= 0:
                    continue  # signal absent -> check omitted (§5.3)
                cw = chk_width(width)
                config.add_field(FieldDefinition(
                    name=f"{name}chk",
                    bits=cw,
                    default=0,
                    format="bin",
                    display_width=cw,
                    description=f"T{name.upper()}CHK (odd parity)"
                ))

            config.add_field(FieldDefinition(
                name="parity_error",
                bits=1,
                default=0,
                format="dec",
                display_width=1,
                description="Parity Error"
            ))

        return config

    # AXIS5-specific properties
    @property
    def wakeup(self):
        """Get wakeup signal."""
        return self.get_field_value('wakeup', 0)

    @wakeup.setter
    def wakeup(self, value):
        """Set wakeup signal."""
        self.set_field_value('wakeup', value)

    @property
    def parity(self):
        """TDATACHK (alias kept for the older TPARITY-named API)."""
        return self.get_field_value('datachk', 0)

    @parity.setter
    def parity(self, value):
        """Set TDATACHK."""
        self.set_field_value('datachk', value)

    @property
    def parity_error(self):
        """Get parity error indicator."""
        return self.get_field_value('parity_error', 0)

    @parity_error.setter
    def parity_error(self, value):
        """Set parity error indicator."""
        self.set_field_value('parity_error', value)

    # AXIS5-specific methods
    def check_widths(self) -> dict:
        """Width in bits of each protected payload field present in the config."""
        widths = {}
        for name in PAYLOAD_CHECK_FIELDS:
            if self.field_config.has_field(f'{name}chk') and self.field_config.has_field(name):
                widths[name] = self.field_config.get_field(name).bits
        return widths

    def calculate_check_fields(self) -> dict:
        """
        Odd-parity check values for every payload field (IHI 0051B ch. 5).

        Returns:
            {'datachk': ..., 'strbchk': ..., 'lastchk': ..., ...}
        """
        values = {name: self.get_field_value(name, 0) for name in PAYLOAD_CHECK_FIELDS}
        return payload_check_values(values, self.check_widths())

    def fill_check_fields(self):
        """Set every *chk field to the correct odd parity of its payload field."""
        for name, value in self.calculate_check_fields().items():
            self.set_field_value(name, value)

    def calculate_parity(self) -> int:
        """
        TDATACHK for the data field: odd parity, one bit per data byte.

        Returns:
            Calculated TDATACHK value
        """
        return calculate_odd_parity(self.data, getattr(self, 'parity_width', 4))

    def check_parity(self) -> bool:
        """
        Check every *chk field against the odd parity of its payload field.

        Returns:
            True if all check fields are correct, False otherwise
        """
        if not getattr(self, 'enable_parity', False):
            return True
        expected = self.calculate_check_fields()
        return all(self.get_field_value(name, 0) == value
                   for name, value in expected.items())

    def copy(self):
        """
        Create a copy of this packet, preserving AXIS5 constructor options.

        Overrides the base ``Packet.copy()``, which re-creates the packet
        without ``data_width``/``enable_wakeup``/``enable_parity`` — that
        would silently disable parity checking on the copy.

        Returns:
            New AXIS5Packet with the same configuration and field values
        """
        new_packet = self.__class__(
            field_config=self.field_config,
            skip_compare_fields=list(self.skip_compare_fields),
            data_width=self.data_width,
            enable_wakeup=self.enable_wakeup,
            enable_parity=self.enable_parity,
        )

        # Copy field values
        for field_name, value in self.fields.items():
            new_packet.fields[field_name] = value

        # Copy timing information
        new_packet.start_time = self.start_time
        new_packet.end_time = self.end_time

        return new_packet

    def set_wakeup(self, enable: bool = True):
        """Set wakeup signal state."""
        self.wakeup = 1 if enable else 0

    def is_wakeup_active(self) -> bool:
        """Check if wakeup is active."""
        return bool(self.wakeup)

    def to_axis4_packet(self):
        """
        Convert to AXIS4 packet (drop AXIS5 fields).

        Returns:
            AXISPacket without AXIS5 extensions
        """
        from ..axis4.axis_field_configs import AXISFieldConfigs
        axis4_config = AXISFieldConfigs.create_default_axis_config(
            data_width=getattr(self, 'data_width', 32))
        axis4_pkt = AXISPacket(field_config=axis4_config)
        axis4_pkt.data = self.data
        axis4_pkt.strb = self.strb
        axis4_pkt.last = self.last
        axis4_pkt.id = self.id
        axis4_pkt.dest = self.dest
        axis4_pkt.user = self.user
        return axis4_pkt

    def __str__(self):
        """String representation."""
        result = [
            "AXIS5 Packet:",
            f"  Data:     0x{self.data:X}",
            f"  Strobe:   0b{self.strb:b}",
            f"  Last:     {self.last}",
            f"  ID:       0x{self.id:X}",
            f"  Dest:     0x{self.dest:X}",
            f"  User:     0x{self.user:X}",
        ]

        if getattr(self, 'enable_wakeup', False):
            result.append(f"  Wakeup:   {self.wakeup}")

        if getattr(self, 'enable_parity', False):
            for name in self.calculate_check_fields():
                result.append(f"  {name:<9} 0b{self.get_field_value(name, 0):b}")
            result.append(f"  ParityOK: {self.check_parity()}")

        return "\n".join(result)


class AXIS5Transaction:
    """
    AXIS5 Transaction generator with randomization.
    """

    def __init__(self, data_width=32, id_width=8, dest_width=4, user_width=1,
                 enable_wakeup=True, enable_parity=False, randomizer=None):
        """
        Initialize AXIS5 transaction generator.

        Args:
            data_width: Data width in bits
            id_width: ID width in bits
            dest_width: Destination width in bits
            user_width: User width in bits
            enable_wakeup: Enable wakeup randomization
            enable_parity: Enable parity generation
            randomizer: Optional FlexRandomizer for value generation
        """
        self.data_width = data_width
        self.id_width = id_width
        self.dest_width = dest_width
        self.user_width = user_width
        self.enable_wakeup = enable_wakeup
        self.enable_parity = enable_parity
        self.strb_width = data_width // 8

        # Create field config
        self.field_config = AXIS5Packet.create_axis5_field_config(
            data_width=data_width,
            id_width=id_width,
            dest_width=dest_width,
            user_width=user_width,
            enable_wakeup=enable_wakeup,
            enable_parity=enable_parity
        )

        # Setup randomizer
        if randomizer is None:
            self.randomizer = FlexRandomizer({
                'data': ([(0, (1 << data_width) - 1)], [1]),
                'strb': ([((1 << self.strb_width) - 1, (1 << self.strb_width) - 1)], [1]),
                'last': ([(0, 0), (1, 1)], [3, 1]),
                'id': ([(0, (1 << id_width) - 1)], [1]),
                'dest': ([(0, (1 << dest_width) - 1)], [1]),
                'user': ([(0, (1 << user_width) - 1)], [1]),
                'wakeup': ([(0, 0), (1, 1)], [9, 1]),  # 10% wakeup probability
            })
        elif isinstance(randomizer, FlexRandomizer):
            self.randomizer = randomizer
        else:
            self.randomizer = FlexRandomizer(randomizer)

        # Current packet
        self.packet = AXIS5Packet(
            field_config=self.field_config,
            data_width=data_width,
            enable_wakeup=enable_wakeup,
            enable_parity=enable_parity
        )

    def next(self) -> AXIS5Packet:
        """
        Generate next random transaction.

        Returns:
            AXIS5Packet with randomized values
        """
        values = self.randomizer.next()

        packet = AXIS5Packet(
            field_config=self.field_config,
            data_width=self.data_width,
            enable_wakeup=self.enable_wakeup,
            enable_parity=self.enable_parity
        )

        # Set core fields
        packet.data = values.get('data', random.randint(0, (1 << self.data_width) - 1))
        packet.strb = values.get('strb', (1 << self.strb_width) - 1)
        packet.last = values.get('last', 0)
        packet.id = values.get('id', 0)
        packet.dest = values.get('dest', 0)
        packet.user = values.get('user', 0)

        # Set AXIS5 fields
        if self.enable_wakeup:
            packet.wakeup = values.get('wakeup', 0)

        if self.enable_parity:
            # Auto-calculate the check signals
            packet.fill_check_fields()

        self.packet = packet
        return packet.copy()

    def create_packet(self, data, last=0, id=0, dest=0, user=0,
                      wakeup=0, strb=None) -> AXIS5Packet:
        """
        Create a packet with specific values.

        Args:
            data: Data value
            last: Last transfer flag
            id: Stream ID
            dest: Destination
            user: User signal
            wakeup: Wakeup signal
            strb: Strobe value (if None, full strobe)

        Returns:
            AXIS5Packet with specified values
        """
        packet = AXIS5Packet(
            field_config=self.field_config,
            data_width=self.data_width,
            enable_wakeup=self.enable_wakeup,
            enable_parity=self.enable_parity
        )

        packet.data = data
        packet.strb = strb if strb is not None else (1 << self.strb_width) - 1
        packet.last = last
        packet.id = id
        packet.dest = dest
        packet.user = user

        if self.enable_wakeup:
            packet.wakeup = wakeup

        if self.enable_parity:
            packet.fill_check_fields()

        return packet
