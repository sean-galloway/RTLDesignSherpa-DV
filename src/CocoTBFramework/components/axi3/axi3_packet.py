# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXI3Packet
# Purpose: AXI3 Packet Implementation with WID support.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""
AXI3 Packet Implementation.

Mirrors the AXI4 packet API but encodes the AXI3 protocol deltas:

* AW/AR ``len`` is 4 bits (1-16 beats).
* AW/AR ``lock`` is 2 bits (normal / exclusive / locked).
* No QoS or REGION fields.
* W beats carry an ``id`` field (WID), matching the AWID for this master.

The AXI3 master in this framework sets WID equal to AWID and does not
interleave write data; the AXI3 slave, however, demuxes incoming W beats
by WID so it can tolerate interleaved write data from external masters.
See issue #87.
"""

from typing import Any, Dict, Tuple

from ..shared.packet import Packet
from .axi3_field_configs import AXI3FieldConfigHelper


class AXI3Packet(Packet):
    """AXI3 Packet class extending the optimized base Packet class."""

    def __init__(self, field_config, **kwargs):
        """Initialize AXI3 packet with field configuration."""
        super().__init__(field_config, **kwargs)
        self._channel_type = None

    @classmethod
    def create_aw_packet(cls, id_width: int = 8, addr_width: int = 32, user_width: int = 1, **field_values):
        """Create a Write Address (AW) channel packet."""
        field_config = AXI3FieldConfigHelper.create_aw_field_config(id_width, addr_width, user_width)
        pkt = cls(field_config, **field_values)
        pkt._channel_type = 'AW'
        return pkt

    @classmethod
    def create_w_packet(cls, id_width: int = 8, data_width: int = 32, user_width: int = 1, **field_values):
        """Create a Write Data (W) channel packet."""
        field_config = AXI3FieldConfigHelper.create_w_field_config(id_width, data_width, user_width)
        pkt = cls(field_config, **field_values)
        pkt._channel_type = 'W'
        return pkt

    @classmethod
    def create_b_packet(cls, id_width: int = 8, user_width: int = 1, **field_values):
        """Create a Write Response (B) channel packet."""
        field_config = AXI3FieldConfigHelper.create_b_field_config(id_width, user_width)
        pkt = cls(field_config, **field_values)
        pkt._channel_type = 'B'
        return pkt

    @classmethod
    def create_ar_packet(cls, id_width: int = 8, addr_width: int = 32, user_width: int = 1, **field_values):
        """Create a Read Address (AR) channel packet."""
        field_config = AXI3FieldConfigHelper.create_ar_field_config(id_width, addr_width, user_width)
        pkt = cls(field_config, **field_values)
        pkt._channel_type = 'AR'
        return pkt

    @classmethod
    def create_r_packet(cls, id_width: int = 8, data_width: int = 32, user_width: int = 1, **field_values):
        """Create a Read Data (R) channel packet."""
        field_config = AXI3FieldConfigHelper.create_r_field_config(id_width, data_width, user_width)
        pkt = cls(field_config, **field_values)
        pkt._channel_type = 'R'
        return pkt

    def get_channel_type(self) -> str:
        """Determine which AXI3 channel this packet belongs to."""
        if self._channel_type:
            return self._channel_type

        has_addr = hasattr(self, 'addr')
        has_data = hasattr(self, 'data')
        has_strb = hasattr(self, 'strb')
        has_last = hasattr(self, 'last')
        has_resp = hasattr(self, 'resp')
        has_len = hasattr(self, 'len')

        if has_addr and has_len and not has_data:
            if hasattr(self, 'cache') or hasattr(self, 'prot'):
                self._channel_type = 'AW'
            else:
                self._channel_type = 'AR'
        elif has_data and has_strb and has_last and not has_resp:
            self._channel_type = 'W'
        elif has_data and has_resp and has_last and not has_strb:
            self._channel_type = 'R'
        elif has_resp and not has_data and not has_addr:
            self._channel_type = 'B'
        else:
            self._channel_type = 'UNKNOWN'

        return self._channel_type

    def validate_axi3_protocol(self) -> Tuple[bool, str]:
        """Validate packet against AXI3 protocol rules."""
        channel_type = self.get_channel_type()
        errors = []

        if channel_type in ['AW', 'AR']:
            burst_len = getattr(self, 'len', 0)
            if not (0 <= burst_len <= 15):
                errors.append(f"Invalid burst length: {burst_len} (must be 0-15)")

            size = getattr(self, 'size', 0)
            if not (0 <= size <= 7):
                errors.append(f"Invalid size: {size} (must be 0-7)")

            burst_type = getattr(self, 'burst', 0)
            if burst_type not in [0, 1, 2]:
                errors.append(f"Invalid burst type: {burst_type} (must be 0=FIXED, 1=INCR, 2=WRAP)")

            lock = getattr(self, 'lock', 0)
            if lock not in [0, 1, 2]:
                errors.append(f"Invalid lock: {lock} (must be 0=Normal, 1=Exclusive, 2=Locked)")

        elif channel_type == 'W':
            if not hasattr(self, 'last'):
                errors.append("W channel must have 'last' field")

            wid = getattr(self, 'id', 0)
            if not (0 <= wid <= ((1 << 16) - 1)):
                errors.append(f"Invalid WID: {wid}")

        elif channel_type == 'R':
            if not hasattr(self, 'last'):
                errors.append("R channel must have 'last' field")

            resp = getattr(self, 'resp', 0)
            if resp not in [0, 1, 2, 3]:
                errors.append(f"Invalid response: {resp} (must be 0-3)")

        elif channel_type == 'B':
            resp = getattr(self, 'resp', 0)
            if resp not in [0, 1, 2, 3]:
                errors.append(f"Invalid response: {resp} (must be 0-3)")

        is_valid = len(errors) == 0
        error_message = "; ".join(errors) if errors else ""

        return is_valid, error_message

    def get_burst_info(self) -> Dict[str, Any]:
        """Get burst information from address packets (AW/AR)."""
        channel_type = self.get_channel_type()

        if channel_type in ['AW', 'AR']:
            return {
                'burst_type': getattr(self, 'burst', None),
                'burst_length': (getattr(self, 'len', 0) + 1),
                'burst_size': getattr(self, 'size', None),
                'bytes_per_beat': (1 << getattr(self, 'size', 0)),
                'total_bytes': (getattr(self, 'len', 0) + 1) * (1 << getattr(self, 'size', 0)),
                'address': getattr(self, 'addr', None)
            }

        return {}

    def get_response_info(self) -> Dict[str, Any]:
        """Get response information from response packets (B/R)."""
        channel_type = self.get_channel_type()

        if channel_type in ['B', 'R']:
            resp_code = getattr(self, 'resp', 0)
        else:
            return {}

        resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}

        info = {
            'response_code': resp_code,
            'response_name': resp_names.get(resp_code, 'UNKNOWN'),
            'is_error': resp_code >= 2,
            'is_exclusive': resp_code == 1
        }

        if channel_type == 'R':
            info['is_last'] = getattr(self, 'last', 0) == 1

        return info

    def __str__(self) -> str:
        """String representation of the packet using generic field names."""
        channel_type = self.get_channel_type()

        if channel_type == 'AW':
            return f"AXI3Packet(AW: id={getattr(self, 'id', '?')}, addr=0x{getattr(self, 'addr', 0):X}, len={getattr(self, 'len', 0)})"
        elif channel_type == 'W':
            return f"AXI3Packet(W: id={getattr(self, 'id', '?')}, data=0x{getattr(self, 'data', 0):X}, last={getattr(self, 'last', '?')})"
        elif channel_type == 'B':
            resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
            resp = resp_names.get(getattr(self, 'resp', 0), 'UNKNOWN')
            return f"AXI3Packet(B: id={getattr(self, 'id', '?')}, resp={resp})"
        elif channel_type == 'AR':
            return f"AXI3Packet(AR: id={getattr(self, 'id', '?')}, addr=0x{getattr(self, 'addr', 0):X}, len={getattr(self, 'len', 0)})"
        elif channel_type == 'R':
            resp_names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
            resp = resp_names.get(getattr(self, 'resp', 0), 'UNKNOWN')
            return f"AXI3Packet(R: id={getattr(self, 'id', '?')}, data=0x{getattr(self, 'data', 0):X}, resp={resp}, last={getattr(self, 'last', '?')})"
        else:
            return f"AXI3Packet({channel_type})"


def create_simple_write_packets(id_val: int, addr: int, data: int,
                            id_width: int = 8, addr_width: int = 32, data_width: int = 32) -> Tuple[AXI3Packet, AXI3Packet]:
    """Create AW and W packets for a simple single-beat write."""
    aw_packet = AXI3Packet.create_aw_packet(
        id_width=id_width, addr_width=addr_width,
        id=id_val, addr=addr, len=0, size=2, burst=1
    )

    strb_width = data_width // 8
    w_packet = AXI3Packet.create_w_packet(
        id_width=id_width, data_width=data_width,
        id=id_val, data=data, strb=(1 << strb_width) - 1, last=1
    )

    return aw_packet, w_packet


def create_simple_read_packet(id_val: int, addr: int,
                            id_width: int = 8, addr_width: int = 32) -> AXI3Packet:
    """Create AR packet for a simple single-beat read."""
    return AXI3Packet.create_ar_packet(
        id_width=id_width, addr_width=addr_width,
        id=id_val, addr=addr, len=0, size=2, burst=1
    )


if __name__ == "__main__":
    print("AXI3 Packet - Generic Field Names Implementation Testing")
    print("=" * 70)

    aw_packet = AXI3Packet.create_aw_packet(id=1, addr=0x1000, len=3)
    print(f"AW Packet: {aw_packet}")
    print(f"Channel Type: {aw_packet.get_channel_type()}")
    print(f"Burst Info: {aw_packet.get_burst_info()}")

    is_valid, error_msg = aw_packet.validate_axi3_protocol()
    print(f"Validation: {is_valid}, Message: {error_msg}")

    w_packet = AXI3Packet.create_w_packet(id=1, data=0xDEADBEEF, last=1)
    print(f"\nW Packet: {w_packet}")

    r_packet = AXI3Packet.create_r_packet(id=2, data=0x12345678, resp=0, last=1)
    print(f"R Packet: {r_packet}")
    print(f"Response Info: {r_packet.get_response_info()}")

    aw, w = create_simple_write_packets(1, 0x2000, 0x12345678)
    print(f"\nSimple Write - AW: {aw}")
    print(f"Simple Write - W: {w}")

    ar = create_simple_read_packet(2, 0x3000)
    print(f"Simple Read - AR: {ar}")

    print("\nAll packets created successfully using GENERIC field names!")
