# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: APB3Packet
# Purpose: APB3 Packet Implementation — APB4 minus PPROT/PSTRB.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""APB3 Packet Implementation.

APB3 is literally APB4 with the optional sideband signals removed:
``PSTRB`` and ``PPROT`` are not part of the APB3 signal set.  This packet
class extends :class:`APBPacket` with a field configuration that omits those
signals, and overrides formatting/equality so that APB3 transactions compare
only the fields that exist on an APB3 bus.
"""

from ..apb.apb_packet import APBPacket
from ..shared.field_config import FieldConfig, FieldDefinition


class APB3Packet(APBPacket):
    """APB3 packet class.

    The APB3 signal set is the APB4 base set minus ``PSTRB`` and ``PPROT``.
    ``PSLVERR`` remains optional (it was introduced in AMBA APB2 rev1 and is
    the only optional signal an APB3 BFM binds best-effort).
    """

    def __init__(self, field_config=None, skip_compare_fields=None,
                 data_width=32, addr_width=32, **kwargs):
        """Initialize an APB3 packet.

        Args:
            field_config: Optional FieldConfig.  Defaults to the APB3 field set.
            skip_compare_fields: Fields to ignore during comparison.
            data_width: Width of PWDATA/PRDATA in bits.
            addr_width: Width of PADDR in bits.
            **kwargs: Initial field values (pwrite, paddr, pwdata, prdata,
                pslverr, plus timing/count fields).
        """
        if field_config is None:
            field_config = self.create_apb3_field_config(addr_width, data_width)

        # PSTRB/PPROT are not valid APB3 kwargs; drop them if a caller
        # accidentally passes them so the base constructor doesn't silently
        # store them as attributes.
        kwargs.pop('pstrb', None)
        kwargs.pop('pprot', None)

        super().__init__(
            field_config=field_config,
            skip_compare_fields=skip_compare_fields,
            data_width=data_width,
            addr_width=addr_width,
            strb_width=data_width // 8,
            **kwargs,
        )

    @staticmethod
    def create_apb3_field_config(addr_width, data_width):
        """Create the APB3 field configuration.

        Returns:
            FieldConfig with pwrite, paddr, pwdata, prdata, pslverr.
        """
        config = FieldConfig()

        config.add_field(FieldDefinition(
            name="pwrite",
            bits=1,
            default=0,
            format="dec",
            display_width=1,
            description="Write Enable (0=Read, 1=Write)",
        ))

        config.add_field(FieldDefinition(
            name="paddr",
            bits=addr_width,
            default=0,
            format="hex",
            display_width=addr_width // 4,
            description="Address",
        ))

        config.add_field(FieldDefinition(
            name="pwdata",
            bits=data_width,
            default=0,
            format="hex",
            display_width=data_width // 4,
            description="Write Data",
        ))

        config.add_field(FieldDefinition(
            name="prdata",
            bits=data_width,
            default=0,
            format="hex",
            display_width=data_width // 4,
            description="Read Data",
        ))

        config.add_field(FieldDefinition(
            name="pslverr",
            bits=1,
            default=0,
            format="dec",
            display_width=1,
            description="Slave Error",
        ))

        return config

    def __str__(self):
        """String representation of the APB3 packet."""
        result = [
            "APB3 Packet:",
            f"  Direction:  {self.direction}",
            f"  Address:    {self._format_field('paddr', self.fields['paddr'])}",
        ]

        if self.direction == 'WRITE':
            result.append(f"  Write Data: {self._format_field('pwdata', self.fields['pwdata'])}")
        else:
            result.append(f"  Read Data:  {self._format_field('prdata', self.fields['prdata'])}")

        result.append(f"  Slave Err:  {self._format_field('pslverr', self.fields['pslverr'])}")

        if self.start_time > 0:
            result.append(f"  Start Time: {self.start_time} ns")
        if self.end_time > 0:
            result.extend((
                f"  End Time:   {self.end_time} ns",
                f"  Duration:   {self.end_time - self.start_time} ns",
            ))
        result.append(f"  Count:      {self.count}")

        return "\n".join(result)

    def formatted(self, compact=False):
        """Return a formatted string representation."""
        if not compact:
            return self.__str__()

        fields = [
            f"time={self.start_time}",
            f"dir={self.direction}",
            f"addr={self._format_field('paddr', self.fields['paddr'])}",
        ]

        if self.direction == 'WRITE':
            fields.append(f"wdata={self._format_field('pwdata', self.fields['pwdata'])}")
        else:
            fields.append(f"rdata={self._format_field('prdata', self.fields['prdata'])}")

        if self.fields['pslverr']:
            fields.append(f"err={self.fields['pslverr']}")

        return f"APB3Packet({', '.join(fields)})"

    def __eq__(self, other):
        """Compare APB3 packets: only the APB3 signal set matters."""
        if not isinstance(other, APB3Packet):
            return NotImplemented

        if self.direction != other.direction:
            return False
        if self.fields.get('paddr', 0) != other.fields.get('paddr', 0):
            return False
        if self.fields.get('pslverr', 0) != other.fields.get('pslverr', 0):
            return False

        if self.direction == 'WRITE':
            return self.fields.get('pwdata', 0) == other.fields.get('pwdata', 0)
        return self.fields.get('prdata', 0) == other.fields.get('prdata', 0)
