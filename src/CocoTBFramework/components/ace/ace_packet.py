# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: ACEPacket
# Purpose: ACE packet implementation extending AXI4Packet with snoop channels.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-05

"""ACE packet implementation.

ACE reuses the AXI4 AW/W/B/AR/R channels and adds three snoop channels
(AC/CR/CD). ``ACEPacket`` extends ``AXI4Packet`` so the front-side coherent
read/write packets keep all AXI4 behaviour, while factory methods are added
for the snoop channels.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..axi4.axi4_packet import AXI4Packet
from .ace_field_configs import AXI4ACEFieldConfigHelper
from .ace_transaction import CRRESP, ACETransactionType, SnoopType


class ACEPacket(AXI4Packet):
    """ACE packet class extending AXI4Packet with snoop-channel support."""

    def __init__(self, field_config, **kwargs):
        """Initialize ACE packet with field configuration."""
        super().__init__(field_config, **kwargs)

    @classmethod
    def create_aw_packet(
        cls,
        id_width: int = 8,
        addr_width: int = 32,
        user_width: int = 1,
        **field_values,
    ) -> "ACEPacket":
        """Create an ACE Write Address (AW) channel packet."""
        field_config = AXI4ACEFieldConfigHelper.create_aw_field_config(
            id_width, addr_width, user_width
        )
        return cls(field_config, **field_values)

    @classmethod
    def create_ar_packet(
        cls,
        id_width: int = 8,
        addr_width: int = 32,
        user_width: int = 1,
        **field_values,
    ) -> "ACEPacket":
        """Create an ACE Read Address (AR) channel packet."""
        field_config = AXI4ACEFieldConfigHelper.create_ar_field_config(
            id_width, addr_width, user_width
        )
        return cls(field_config, **field_values)

    @classmethod
    def create_ac_packet(
        cls,
        addr_width: int = 32,
        **field_values,
    ) -> "ACEPacket":
        """Create a snoop address (AC) channel packet."""
        field_config = AXI4ACEFieldConfigHelper.create_ac_field_config(addr_width)
        return cls(field_config, **field_values)

    @classmethod
    def create_cr_packet(
        cls,
        **field_values,
    ) -> "ACEPacket":
        """Create a snoop response (CR) channel packet."""
        field_config = AXI4ACEFieldConfigHelper.create_cr_field_config()
        return cls(field_config, **field_values)

    @classmethod
    def create_cd_packet(
        cls,
        data_width: int = 32,
        **field_values,
    ) -> "ACEPacket":
        """Create a snoop data (CD) channel packet."""
        field_config = AXI4ACEFieldConfigHelper.create_cd_field_config(data_width)
        return cls(field_config, **field_values)

    def get_channel_type(self) -> str:
        """Determine which ACE channel this packet belongs to."""
        if self._channel_type:
            return self._channel_type

        has_addr = hasattr(self, "addr")
        has_data = hasattr(self, "data")
        has_last = hasattr(self, "last")
        has_strb = hasattr(self, "strb")
        has_resp = hasattr(self, "resp")
        has_len = hasattr(self, "len")
        has_snoop = hasattr(self, "snoop")
        has_prot = hasattr(self, "prot")

        if has_addr and has_snoop and has_prot and not has_len:
            self._channel_type = "AC"
        elif has_resp and not has_data and not has_addr:
            self._channel_type = "CR"
        elif has_data and has_last and not has_strb and not has_resp:
            self._channel_type = "CD"
        else:
            # Fall back to AXI4 channel detection
            self._channel_type = super().get_channel_type()

        return self._channel_type

    def get_ace_features(self) -> Dict[str, Any]:
        """Get ACE-specific feature information."""
        features = self.get_axi5_features() if hasattr(super(), "get_axi5_features") else {}
        channel_type = self.get_channel_type()

        if hasattr(self, "snoop"):
            features["snoop"] = getattr(self, "snoop", 0)

        if channel_type == "CR":
            features["crresp"] = CRRESP(getattr(self, "resp", 0))

        return features

    def __str__(self) -> str:
        """String representation using generic field names."""
        channel_type = self.get_channel_type()

        if channel_type == "AC":
            snoop = getattr(self, "snoop", 0)
            stype = SnoopType(snoop).name if snoop in SnoopType._value2member_map_ else f"UNKNOWN({snoop})"
            return (
                f"ACEPacket(AC: addr=0x{getattr(self, 'addr', 0):X}, "
                f"snoop={stype}, prot={getattr(self, 'prot', 0)})"
            )
        if channel_type == "CR":
            return f"ACEPacket(CR: resp={CRRESP(getattr(self, 'resp', 0))})"
        if channel_type == "CD":
            return (
                f"ACEPacket(CD: data=0x{getattr(self, 'data', 0):X}, "
                f"last={getattr(self, 'last', '?')})"
            )

        return super().__str__().replace("AXI4Packet", "ACEPacket")


class SnoopPacket:
    """Convenience container for a complete snoop transaction result."""

    def __init__(
        self,
        addr: int,
        snoop_type: SnoopType,
        crresp: CRRESP,
        data: Optional[List[int]] = None,
        beats: int = 0,
    ):
        self.addr = addr
        self.snoop_type = snoop_type
        self.crresp = crresp
        self.data = data or []
        self.beats = beats if beats else len(self.data)

    def __repr__(self) -> str:
        return (
            f"SnoopPacket(addr=0x{self.addr:X}, snoop={self.snoop_type.name}, "
            f"crresp={self.crresp}, beats={self.beats})"
        )


# Convenience packet builders

def create_simple_read_packet(
    id_val: int,
    addr: int,
    snoop_type: ACETransactionType = ACETransactionType.READ_SHARED,
    id_width: int = 8,
    addr_width: int = 32,
) -> ACEPacket:
    """Create a simple single-beat ACE read address packet."""
    return ACEPacket.create_ar_packet(
        id_width=id_width,
        addr_width=addr_width,
        id=id_val,
        addr=addr,
        len=0,
        size=2,
        burst=1,
        snoop=int(snoop_type),
    )


def create_simple_write_packet(
    id_val: int,
    addr: int,
    data: int,
    snoop_type: ACETransactionType = ACETransactionType.WRITE_UNIQUE,
    id_width: int = 8,
    addr_width: int = 32,
    data_width: int = 32,
) -> Tuple[ACEPacket, ACEPacket]:
    """Create simple single-beat ACE write address and data packets."""
    aw_packet = ACEPacket.create_aw_packet(
        id_width=id_width,
        addr_width=addr_width,
        id=id_val,
        addr=addr,
        len=0,
        size=2,
        burst=1,
        snoop=int(snoop_type),
    )
    strb_width = data_width // 8
    w_packet = ACEPacket.create_w_packet(
        data_width=data_width,
        data=data,
        strb=(1 << strb_width) - 1,
        last=1,
    )
    return aw_packet, w_packet


def create_snoop_address_packet(
    addr: int,
    snoop_type: SnoopType,
    prot: int = 0,
    addr_width: int = 32,
) -> ACEPacket:
    """Create a snoop address (AC) packet."""
    return ACEPacket.create_ac_packet(
        addr_width=addr_width,
        addr=addr,
        snoop=int(snoop_type),
        prot=prot,
    )


def create_snoop_response_packet(
    crresp: CRRESP,
) -> ACEPacket:
    """Create a snoop response (CR) packet."""
    return ACEPacket.create_cr_packet(resp=int(crresp))


def create_snoop_data_packet(
    data: int,
    last: bool = True,
    data_width: int = 32,
) -> ACEPacket:
    """Create a snoop data (CD) packet."""
    return ACEPacket.create_cd_packet(
        data_width=data_width,
        data=data,
        last=int(last),
    )
