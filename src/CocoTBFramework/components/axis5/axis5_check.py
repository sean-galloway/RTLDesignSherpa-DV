# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: axis5_check
# Purpose: AXI5-Stream interface parity (IHI 0051B ch. 5) - the *CHK signals
#
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-12

"""
AXI5-Stream interface parity protection, IHI 0051B chapter 5.

Check_Type = Odd_Parity_Byte_All:

- ODD parity: a check bit plus the bits it covers always hold an odd number
  of ones (§5.3).
- Check bit [n] covers bits [8n+7:8n] of its signal; when the signal is not a
  whole number of bytes the top check bit covers the short remainder (§5.3).
- Table 5-1 widths: TDATACHK = TDATA_WIDTH/8, TSTRBCHK and TKEEPCHK =
  ceil(TDATA_WIDTH/64), TIDCHK/TDESTCHK/TUSERCHK = ceil(width/8), and one bit
  for TLASTCHK, TVALIDCHK, TREADYCHK and TWAKEUPCHK. A one-bit check is the
  inversion of its signal.
- Payload checks are enabled by TVALID; TVALIDCHK, TREADYCHK and TWAKEUPCHK
  by ARESETn, i.e. every cycle out of reset.

Every helper here takes the width in BITS of the protected signal, so
``chk_width(strb_width)`` gives TSTRBCHK's width directly.
"""

import cocotb
from cocotb.triggers import FallingEdge

# Payload fields that carry a check signal, in the GAXI field naming
# (field "data" <-> signal "{prefix}tdata", check "{prefix}tdatachk").
PAYLOAD_CHECK_FIELDS = ('data', 'strb', 'last', 'id', 'dest', 'user')


def chk_width(width: int) -> int:
    """Check-signal width for a ``width``-bit signal: one bit per 8 bits."""
    return (max(width, 1) + 7) // 8


def odd_parity_chk(value: int, width: int) -> int:
    """
    Odd-parity check vector for a ``width``-bit signal (IHI 0051B §5.3).

    Bit n covers value[8n+7:8n]; the last piece may be shorter than 8 bits.
    """
    width = max(width, 1)
    chk = 0
    for n in range(chk_width(width)):
        lo = 8 * n
        piece_w = min(8, width - lo)
        piece = (value >> lo) & ((1 << piece_w) - 1)
        chk |= ((bin(piece).count('1') & 1) ^ 1) << n
    return chk


def is_odd_parity(value: int, chk: int, width: int) -> bool:
    """True when every (piece, check bit) pair holds an odd number of ones."""
    return odd_parity_chk(value, width) == chk


def payload_check_values(values: dict, widths: dict) -> dict:
    """
    Check values for the payload fields present in ``widths``.

    Args:
        values: field name -> value (e.g. {'data': 0x1234, 'last': 1})
        widths: field name -> width in bits of the protected signal

    Returns:
        {'datachk': ..., 'strbchk': ..., ...} for every field in ``widths``
    """
    return {f'{name}chk': odd_parity_chk(values.get(name, 0), widths[name])
            for name in PAYLOAD_CHECK_FIELDS if name in widths}


async def drive_inverse_every_cycle(clock, src, dst):
    """
    Keep a single-bit check signal equal to the inversion of its signal.

    For TVALIDCHK / TREADYCHK / TWAKEUPCHK (Check Enable = ARESETn). The
    signal is sampled on the falling edge, after the rising-edge drivers
    have settled, so ``dst`` is correct at the next rising edge.
    """
    while True:
        await FallingEdge(clock)
        try:
            dst.value = 0 if int(src.value) else 1
        except ValueError:
            dst.value = 1  # X/Z on the source: drive the reset-low value's check


def start_inverse_driver(dut, clock, prefix, signal, log=None):
    """
    Start ``drive_inverse_every_cycle`` for ``{prefix}t{signal}chk`` when the
    DUT has both pins. Returns the task, or None when a pin is missing.
    """
    src_name, dst_name = f'{prefix}t{signal}', f'{prefix}t{signal}chk'
    if not (hasattr(dut, src_name) and hasattr(dut, dst_name)):
        if log:
            log.debug(f"AXIS5 check: no {dst_name}, not driven")
        return None
    return cocotb.start_soon(drive_inverse_every_cycle(
        clock, getattr(dut, src_name), getattr(dut, dst_name)))
