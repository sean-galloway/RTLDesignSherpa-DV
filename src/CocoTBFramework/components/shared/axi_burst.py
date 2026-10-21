"""AXI burst addressing (AMBA AXI A3.4.1), shared by the AXI3/AXI4/AXI5 slaves.

beat_addr(start, i, size, burst, length) is the address of beat i of a burst
that starts at `start` with AxSIZE `size`, AxBURST `burst` and AxLEN `length`:

- FIXED (0): every beat is at `start`.
- INCR (1): beat 0 is at `start`; every later beat is on the size grid,
  aligned(start) + i * bytes. Only the first beat of a burst may be
  unaligned.
- WRAP (2): the beats walk up through a (length + 1) * bytes container
  aligned to its own size and wrap to its base. A WRAP start must be aligned
  to the size; the container rule is applied to the aligned address.
- 3 (reserved) is treated as INCR.
"""
from __future__ import annotations

FIXED, INCR, WRAP = 0, 1, 2


def beat_addr(start: int, i: int, size: int, burst: int, length: int) -> int:
    nb = 1 << size
    if burst == FIXED or i == 0:
        return start
    aligned = start & ~(nb - 1)
    if burst == WRAP:
        span = (length + 1) * nb
        base = aligned & ~(span - 1)
        return base + ((aligned - base + i * nb) % span)
    return aligned + i * nb


def beat_lanes(start: int, i: int, size: int, burst: int, length: int,
               bus_bytes: int) -> tuple[int, int]:
    """(wstrb, lane) for beat i on a bus of bus_bytes: the strobes cover the
    beat's bytes from its address to the end of its aligned window (an
    unaligned beat asserts none below its address, A3.4.3), and `lane` is
    where that window starts on the bus -- a narrow beat's data rides there."""
    a = beat_addr(start, i, size, burst, length)
    nb = 1 << size
    if nb >= bus_bytes:
        lane = 0
        width = bus_bytes
    else:
        lane = (a & ~(nb - 1)) % bus_bytes
        width = nb
    strb = ((1 << width) - 1) << lane
    strb &= ~((1 << (a % bus_bytes)) - 1)
    return strb, lane
