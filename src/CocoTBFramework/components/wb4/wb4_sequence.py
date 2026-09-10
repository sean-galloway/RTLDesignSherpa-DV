# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: WB4Sequence
# Purpose: Traffic description for Wishbone B4 -- the SEQUENCE axis
#
# Documentation: docs/components/wb4/components_wb4_wb4_sequence.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-09-10

"""Wishbone B4 sequences: WHAT traffic, independent of who drives it and
when.

The three axes are orthogonal. A ``WB4Master`` is who drives, a
``FlexRandomizer`` is when, and this is what: a list of single-beat
transactions a test can build, filter, shuffle, replay and hand to a
master.

Built as a builder in the AXI4Sequence style rather than the older parallel
list style, minus everything Wishbone does not have. B4 has no bursts, so a
transaction is one word; no protection bits, so there is no prot field; and
the termination status is the slave's answer, never part of the stimulus.

What IS Wishbone-flavoured is ``windows``. A B4 slave may answer ERR or RTY,
and a test usually provokes those by aiming at address ranges the device
under test decodes that way. Every hand-written wb4 testbench in the main
repo grew its own copy of that address picking; ``add_random_workload``
takes the windows directly.

Example::

    seq = WB4Sequence("smoke", addr_width=32, data_width=32, seed=1)
    seq.add_write(0x1000, 0xDEADBEEF)
    seq.add_read(0x1000)
    seq.add_random_workload(100, addr_hi=0xD000, write_frac=0.6,
                            windows=[(0xE000, 0xEFFF, 0.1),    # ERR range
                                     (0xF000, 0xFFFF, 0.1)])   # RTY range
    for pkt in seq.to_packets():
        await master.send(pkt)
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

from .wb4_packet import WB4Packet


@dataclass
class WB4Transaction:
    """One single-beat Wishbone transfer.

    ``sel`` is the byte select; it defaults to all-ones and a read carries
    all-ones by convention. ``tag`` is free-form and is for the test's own
    bookkeeping (which window an address came from, say) -- nothing in the
    framework interprets it.
    """
    we: int
    adr: int
    dat_w: int = 0
    sel: int = 0
    tag: str = ""

    @property
    def is_write(self) -> bool:
        return bool(self.we)


class WB4Sequence:
    """A builder for Wishbone B4 traffic.

    Deterministic when constructed with ``seed``: the sequence owns its own
    ``random.Random`` rather than touching the global one, so building a
    sequence never perturbs any other randomisation in the test.
    """

    def __init__(self, name: str = "seq", *, addr_width: int = 32,
                 data_width: int = 32, sel_width: Optional[int] = None,
                 seed: Optional[int] = None):
        self.name = name
        self.addr_width = addr_width
        self.data_width = data_width
        self.sel_width = sel_width if sel_width is not None else max(1, data_width // 8)
        self.transactions: List[WB4Transaction] = []
        self.rng = random.Random(seed)
        self._seed = seed

    # ---- primitives ------------------------------------------------------
    @property
    def all_sel(self) -> int:
        return (1 << self.sel_width) - 1

    def _mask_addr(self, addr: int) -> int:
        return addr & ((1 << self.addr_width) - 1)

    def _mask_data(self, data: int) -> int:
        return data & ((1 << self.data_width) - 1)

    def add_write(self, addr: int, data: int, *, sel: Optional[int] = None,
                  tag: str = "") -> "WB4Sequence":
        """Append one write. ``sel`` defaults to every byte."""
        self.transactions.append(WB4Transaction(
            we=1, adr=self._mask_addr(addr), dat_w=self._mask_data(data),
            sel=self.all_sel if sel is None else (sel & self.all_sel), tag=tag))
        return self

    def add_read(self, addr: int, *, tag: str = "") -> "WB4Sequence":
        """Append one read. Reads carry an all-ones select."""
        self.transactions.append(WB4Transaction(
            we=0, adr=self._mask_addr(addr), dat_w=0, sel=self.all_sel, tag=tag))
        return self

    # ---- patterns --------------------------------------------------------
    def add_block(self, base: int, count: int, *, we: bool = True,
                  stride: Optional[int] = None, data: Optional[Sequence[int]] = None,
                  tag: str = "block") -> "WB4Sequence":
        """A run of ``count`` transfers from ``base``, one word apart by
        default. ``data`` cycles if it is shorter than ``count``."""
        stride = self.sel_width if stride is None else stride
        for i in range(count):
            addr = base + i * stride
            if we:
                d = self.rng.getrandbits(self.data_width) if not data else data[i % len(data)]
                self.add_write(addr, d, tag=tag)
            else:
                self.add_read(addr, tag=tag)
        return self

    def add_readback_pairs(self, base: int, count: int, *,
                           stride: Optional[int] = None,
                           data: Optional[Sequence[int]] = None,
                           tag: str = "readback") -> "WB4Sequence":
        """``count`` write/read pairs on the same address, which is the
        shape a data-integrity check wants: each read follows its own write,
        so the expected value is unambiguous even in order-preserving
        pipelined traffic."""
        stride = self.sel_width if stride is None else stride
        for i in range(count):
            addr = base + i * stride
            d = self.rng.getrandbits(self.data_width) if not data else data[i % len(data)]
            self.add_write(addr, d, tag=tag)
            self.add_read(addr, tag=tag)
        return self

    def add_strobed_writes(self, base: int, count: int, *,
                           stride: Optional[int] = None,
                           tag: str = "strobe") -> "WB4Sequence":
        """Partial writes: a full write, then a write with a random partial
        select, then a read back. The untouched bytes must survive, which is
        what makes a dropped ``SEL`` visible."""
        if self.sel_width < 2:
            raise ValueError("add_strobed_writes needs sel_width >= 2")
        stride = self.sel_width if stride is None else stride
        for i in range(count):
            addr = base + i * stride
            self.add_write(addr, self.rng.getrandbits(self.data_width), tag=tag)
            partial = self.rng.randint(1, self.all_sel - 1)
            self.add_write(addr, self.rng.getrandbits(self.data_width), sel=partial, tag=tag)
            self.add_read(addr, tag=tag)
        return self

    def add_random_workload(self, count: int, *, addr_lo: int = 0,
                            addr_hi: int = 0x1000, write_frac: float = 0.5,
                            align: bool = True, random_sel: bool = False,
                            windows: Optional[Sequence[Tuple[int, int, float]]] = None,
                            unique_addrs: bool = False,
                            tag: str = "rand") -> "WB4Sequence":
        """``count`` random transfers.

        ``windows`` is a list of ``(lo, hi, probability)``; each transfer
        draws from a window with that probability, otherwise from
        ``[addr_lo, addr_hi)``. Probabilities are taken in order and must sum
        to at most 1.0. A transfer drawn from a window is tagged with its
        index (``"<tag>:w0"``), so a scoreboard can tell which range an
        address came from without re-deriving the decode.

        ``unique_addrs`` refuses to repeat an address within this call, which
        is what a test wants when several transfers are in flight at once and
        a per-address model would otherwise race itself.
        """
        if not 0.0 <= write_frac <= 1.0:
            raise ValueError(f"write_frac must be in [0, 1], got {write_frac}")
        windows = list(windows or [])
        total_p = sum(w[2] for w in windows)
        if total_p > 1.0 + 1e-9:
            raise ValueError(f"window probabilities sum to {total_p}, must be <= 1.0")
        for lo, hi, _ in windows:
            if hi < lo:
                raise ValueError(f"window ({lo:#x}, {hi:#x}) is inverted")
        if addr_hi <= addr_lo:
            raise ValueError(f"addr_hi ({addr_hi:#x}) must exceed addr_lo ({addr_lo:#x})")

        step = self.sel_width if align else 1
        seen = set()
        made = 0
        guard = 0
        while made < count:
            guard += 1
            if guard > 100 * max(count, 1):
                raise RuntimeError(
                    f"add_random_workload could not place {count} unique addresses "
                    f"in the ranges given; widen them or drop unique_addrs")
            roll = self.rng.random()
            addr, wtag = None, tag
            acc = 0.0
            for idx, (lo, hi, p) in enumerate(windows):
                acc += p
                if roll < acc:
                    addr = self.rng.randrange(lo, hi + 1)
                    wtag = f"{tag}:w{idx}"
                    break
            if addr is None:
                addr = self.rng.randrange(addr_lo, addr_hi)
            if align:
                addr = (addr // step) * step
            if unique_addrs:
                if addr in seen:
                    continue
                seen.add(addr)
            if self.rng.random() < write_frac:
                sel = self.rng.randint(1, self.all_sel) if random_sel else None
                self.add_write(addr, self.rng.getrandbits(self.data_width), sel=sel, tag=wtag)
            else:
                self.add_read(addr, tag=wtag)
            made += 1
        return self

    # ---- shaping ---------------------------------------------------------
    def filter(self, predicate: Callable[[WB4Transaction], bool]) -> "WB4Sequence":
        """A new sequence holding the transfers that match. The original is
        untouched, so a built workload can be sliced several ways."""
        out = WB4Sequence(f"{self.name}.filter", addr_width=self.addr_width,
                          data_width=self.data_width, sel_width=self.sel_width,
                          seed=self._seed)
        out.transactions = [t for t in self.transactions if predicate(t)]
        return out

    def shuffle(self) -> "WB4Sequence":
        """Shuffle in place, using this sequence's own generator so a seeded
        sequence shuffles the same way every run."""
        self.rng.shuffle(self.transactions)
        return self

    def reset(self) -> "WB4Sequence":
        """Drop every transfer and re-seed, so the same builder calls rebuild
        an identical sequence."""
        self.transactions = []
        self.rng = random.Random(self._seed)
        return self

    # ---- output ----------------------------------------------------------
    def to_packets(self, master=None) -> List[WB4Packet]:
        """Build ``WB4Packet`` objects ready for ``master.send()``.

        Pass ``master`` to take the widths from the BFM instead of this
        sequence, which catches a sequence built for the wrong bus rather
        than silently truncating an address.
        """
        if master is not None:
            aw, dw, sw = master.addr_width, master.data_width, master.sel_width
            if (aw, dw, sw) != (self.addr_width, self.data_width, self.sel_width):
                raise ValueError(
                    f"sequence '{self.name}' is {self.addr_width}/{self.data_width}/"
                    f"{self.sel_width} (addr/data/sel) but the master is {aw}/{dw}/{sw}")
        else:
            aw, dw, sw = self.addr_width, self.data_width, self.sel_width
        return [WB4Packet(addr_width=aw, data_width=dw, sel_width=sw,
                          we=t.we, adr=t.adr, dat_w=t.dat_w, sel=t.sel)
                for t in self.transactions]

    @property
    def stats(self) -> dict:
        writes = sum(1 for t in self.transactions if t.is_write)
        return {
            'total': len(self.transactions),
            'writes': writes,
            'reads': len(self.transactions) - writes,
            'unique_addrs': len({t.adr for t in self.transactions}),
            'partial_writes': sum(1 for t in self.transactions
                                  if t.is_write and t.sel != self.all_sel),
        }

    def __len__(self) -> int:
        return len(self.transactions)

    def __iter__(self) -> Iterator[WB4Transaction]:
        return iter(self.transactions)

    def __repr__(self) -> str:
        s = self.stats
        return (f"WB4Sequence('{self.name}', {s['total']} transfers, "
                f"{s['writes']}w/{s['reads']}r, seed={self._seed})")
