# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: cxs_cntl
# Purpose: CXSCNTL encode / decode / format check (IHI 0079D 4.3)
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-15
"""CXSCNTL: the per-flit packet control word.

A :class:`CXSCntl` holds what a flit says about packet boundaries, in units
the spec uses: start pointers in alignment units (16 or 4 bytes), end
pointers in 4-byte units pointing at the LAST aligned 4 bytes of a packet,
and one ENDERROR bit per ending packet. ``encode``/``decode`` convert to and
from the CXSCNTL integer of a given :class:`CXSConfig`; ``violations`` lists
every Table 4-4 / 4.1 rule a word breaks.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

from .cxs_config import CXSConfig


def _is_thermometer(bits):
    """True when bits is 0b0..01..1 (every set bit has all lower bits set)."""
    return (bits & (bits + 1)) == 0


@dataclass(frozen=True)
class CXSCntl:
    """Packet boundaries in one flit.

    ``starts``: start pointers, ascending, in alignment units.
    ``ends``:   end pointers, ascending, in 4-byte units.
    ``end_errors``: one bool per entry of ``ends`` (ENDERROR).
    """
    starts: Tuple[int, ...] = ()
    ends: Tuple[int, ...] = ()
    end_errors: Tuple[bool, ...] = ()
    # Raw START / END / ENDERROR masks when decoded from a malformed word,
    # kept so a checker can report what was really on the wire.
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'starts', tuple(int(s) for s in self.starts))
        object.__setattr__(self, 'ends', tuple(int(e) for e in self.ends))
        errs = tuple(bool(e) for e in self.end_errors) or (False,) * len(self.ends)
        object.__setattr__(self, 'end_errors', errs)

    # Byte positions
    def start_bytes(self, cfg: CXSConfig):
        unit = 16 if cfg.start_align == 16 else 4
        return [s * unit for s in self.starts]

    def end_bytes(self):
        """Index of each ending packet's LAST byte: (ENDnPTR << 2) + 3."""
        return [(e << 2) + 3 for e in self.ends]

    # ------------------------------------------------------------------
    def encode(self, cfg: CXSConfig) -> int:
        n = cfg.max_pkt_per_flit
        if n <= 1:
            return 0
        if len(self.starts) > n or len(self.ends) > n:
            raise ValueError(f"CXSCNTL: {len(self.starts)} starts / {len(self.ends)} ends "
                             f"exceed CXSMAXPKTPERFLIT={n}")
        word = (1 << len(self.starts)) - 1
        for k, s in enumerate(self.starts):
            word |= (s & ((1 << cfg.start_ptr_width) - 1)) << cfg.start_ptr_lsb(k)
        word |= ((1 << len(self.ends)) - 1) << cfg.end_lsb
        for k, (e, err) in enumerate(zip(self.ends, self.end_errors)):
            word |= int(err) << (cfg.enderror_lsb + k)
            word |= (e & ((1 << cfg.end_ptr_width) - 1)) << cfg.end_ptr_lsb_k(k)
        return word

    @classmethod
    def decode(cls, cfg: CXSConfig, word: int) -> 'CXSCntl':
        """Decode a CXSCNTL word. A malformed START/END (not a thermometer
        code) decodes by popcount; ``violations`` reports it."""
        n = cfg.max_pkt_per_flit
        if n <= 1:
            return cls()
        mask_n = (1 << n) - 1
        start = word & mask_n
        end = (word >> cfg.end_lsb) & mask_n
        enderr = (word >> cfg.enderror_lsb) & mask_n
        ns, ne = bin(start).count('1'), bin(end).count('1')
        sp_mask = (1 << cfg.start_ptr_width) - 1
        ep_mask = (1 << cfg.end_ptr_width) - 1
        starts = [(word >> cfg.start_ptr_lsb(k)) & sp_mask for k in range(ns)]
        ends = [(word >> cfg.end_ptr_lsb_k(k)) & ep_mask for k in range(ne)]
        errs = [bool((enderr >> k) & 1) for k in range(ne)]
        return cls(tuple(starts), tuple(ends), tuple(errs),
                   raw={'start': start, 'end': end, 'enderror': enderr})

    # ------------------------------------------------------------------
    def violations(self, cfg: CXSConfig, open_before: bool = False) -> List[str]:
        """Every placement / format rule this flit's control breaks.

        ``open_before``: a packet was left open by the previous flit.
        """
        out = []
        n = cfg.max_pkt_per_flit
        if n <= 1:
            return out
        raw = self.raw
        if raw:
            if not _is_thermometer(raw['start']):
                out.append(f"START 0b{raw['start']:b} is not a thermometer code")
            if not _is_thermometer(raw['end']):
                out.append(f"END 0b{raw['end']:b} is not a thermometer code")
            if raw['enderror'] & ~raw['end']:
                out.append(f"ENDERROR 0b{raw['enderror']:b} without END 0b{raw['end']:b}")
        if list(self.starts) != sorted(set(self.starts)):
            out.append(f"start pointers {self.starts} are not strictly increasing")
        if list(self.ends) != sorted(set(self.ends)):
            out.append(f"end pointers {self.ends} are not strictly increasing")
        opens = int(open_before) + len(self.starts) - len(self.ends)
        if opens < 0:
            out.append("a packet ends that never started")
        if opens > 1:
            out.append(f"{opens} packets left open at the end of the flit")
        # Packets with bytes in this flit (continuing + starting) <= N
        if int(open_before) + len(self.starts) > n:
            out.append(f"{int(open_before) + len(self.starts)} packets in a flit "
                       f"exceeds CXSMAXPKTPERFLIT={n}")
        out += self._order_violations(cfg, open_before)
        return out

    def _order_violations(self, cfg, open_before):
        """Starts and ends interleave in byte order; a start never sits
        inside the packet before it; 16-byte starts are the first free
        boundary (4.1)."""
        out = []
        sb, eb = self.start_bytes(cfg), self.end_bytes()
        ends = list(eb)
        cursor = 0                      # first byte not yet claimed
        if open_before:
            if not ends:
                return out              # continues through the whole flit
            cursor = ends.pop(0) + 1
        for k, s in enumerate(sb):
            if s < cursor:
                out.append(f"START{k}PTR byte {s} overlaps the previous packet (ends at {cursor - 1})")
            elif cfg.start_align == 16 and s != ((cursor + 15) // 16) * 16:
                out.append(f"START{k}PTR byte {s} is not the first free 16-byte boundary "
                           f"after byte {cursor}")
            if ends:
                e = ends.pop(0)
                if e < s + 3:
                    out.append(f"packet {k} ends (byte {e}) before it starts (byte {s})")
                cursor = e + 1
            else:
                cursor = cfg.flit_bytes        # left open
                if k != len(sb) - 1:
                    out.append(f"START{k}PTR packet has no END but is not the last start")
        if ends:
            out.append(f"{len(ends)} END(s) match no open or started packet")
        return out
