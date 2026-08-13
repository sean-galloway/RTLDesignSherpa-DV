"""dfi_cmdaddr transport packing for DDR-CA memories — DFI v6.0 §3.1.2.

The v6.0 command path carries the memory's CA bus on ``dfi_cmdaddr``.
For DDR (double-data-rate) CA buses the two phases concatenate: the
rising-edge CA rides the lower half, the falling-edge CA the upper
half. Per-protocol geometry:

* LPDDR5 (Table 15): 7-bit DDR CA — cmdaddr[6:0]=rise, [13:7]=fall.
* LPDDR6 DDR command mode (Table 16): 4-bit DDR CA —
  cmdaddr[3:0]=rise, [7:4]=fall.
* LPDDR6 SDR command mode (Table 17): 4-bit SDR CA on cmdaddr[3:0];
  [7:4] must be ignored by the PHY if present — SDR is a passthrough,
  no packing helper needed.
* DDR5 without RCD (Table 18): 14-bit SDR CA, width-matched
  passthrough (1N holds a value 1 clock/phase, 2N holds it for 2).
* HBM4 (Table 22) has row/column sub-lanes inside each phase — see
  :mod:`hbm_ca` for its dedicated packer.

Command *contents* (opcodes, fields) are the CA maps' business
(:mod:`ca_map`, :mod:`ddr5_ca_map`); this module is only the
phase-lane plumbing between CA edge values and the DFI word.
"""

from typing import NamedTuple

LPDDR5_CA_WIDTH = 7
LPDDR6_CA_WIDTH = 4
DDR5_CA_WIDTH = 14


class CAPhases(NamedTuple):
    rise: int
    fall: int


def pack_ddr_cmdaddr(ca_width: int, rise: int, fall: int) -> int:
    """Concatenate one CK of a DDR CA bus into a dfi_cmdaddr value:
    rising-edge CA on the lower ``ca_width`` bits, falling-edge CA on
    the upper (v6.0 Tables 15/16)."""
    lim = 1 << ca_width
    if not 0 <= rise < lim:
        raise ValueError(f"rise 0x{rise:X} exceeds {ca_width}-bit CA bus")
    if not 0 <= fall < lim:
        raise ValueError(f"fall 0x{fall:X} exceeds {ca_width}-bit CA bus")
    return (fall << ca_width) | rise


def unpack_ddr_cmdaddr(ca_width: int, word: int) -> CAPhases:
    """Split a dfi_cmdaddr value back into (rise, fall) CA phases."""
    if not 0 <= word < (1 << (2 * ca_width)):
        raise ValueError(
            f"cmdaddr 0x{word:X} exceeds {2 * ca_width} bits")
    mask = (1 << ca_width) - 1
    return CAPhases(rise=word & mask, fall=(word >> ca_width) & mask)
