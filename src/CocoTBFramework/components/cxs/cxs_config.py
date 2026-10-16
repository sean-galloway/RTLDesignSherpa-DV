# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: cxs_config
# Purpose: CXS (Arm IHI 0079) interface properties, per-issue legality and
#          the CXSCNTL field layout
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-15
"""CXS interface properties.

CXS has four published issues and each is a strict superset of the one
before, so an issue is a set of legal property values rather than a separate
wire protocol. One :class:`CXSConfig` describes an interface; :meth:`validate`
says whether that property set is legal for the issue it names.

=====  ====  ===============================================================
Issue  Year  Adds
=====  ====  ===============================================================
A      2018  CXSDATAFLITWIDTH 256/512/1024, CXSMAXPKTPERFLIT 2..4,
             CXS_MAX_CREDIT <= 15, CXSCHECKTYPE, CXSLINKCONTROL
B      2020  CXSLAST (CXS_LAST), CXSPRCLTYPE (CXS_PROTOCOL_TYPE)
C      2023  CXSMAXPKTPERFLIT = 1 (no CXSCNTL, width 8..2048),
             CXS_MAX_CREDIT 1..63
D      2025  2048-bit multi-packet flits, CXS_START_ALIGNMENT = 4,
             CXSSRCID/CXSTGTID (0..8), CXSUSER (0..128), CXS-Lite
=====  ====  ===============================================================

The rules are the same, in the same order, as ``cxs_pkg::config_error`` in
the RTL, so a rule number reported by either side means the same thing.

CXSCNTL layout (IHI 0079D Tables 4-5 and 4-7), N = CXSMAXPKTPERFLIT, from
bit 0 upward: START[N] | START0..N-1PTR | END[N] | ENDERROR[N] |
END0..N-1PTR. A start pointer is log2(W/128) bits with 16-byte start
alignment, log2(W/32) with 4-byte; an end pointer is log2(W/32).
"""

from dataclasses import dataclass, replace
from enum import IntEnum


class CXSIssue(IntEnum):
    """Specification issue; the value is the RTL ``CXS_ISSUE`` code."""
    A = 1
    B = 2
    C = 3
    D = 4

    @classmethod
    def coerce(cls, value):
        """Accept a CXSIssue, its int code, or a letter ('A'..'D')."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls[value.strip().upper()]
        return cls(int(value))


# Rule number -> reason. Numbering matches cxs_pkg::config_error.
CONFIG_RULES = {
    1: "issue must be A..D",
    2: "CXSMAXPKTPERFLIT must be 1..4",
    3: "CXSMAXPKTPERFLIT = 1 needs Issue C or later",
    4: "with one packet per flit CXSDATAFLITWIDTH is 8..2048, a multiple of 8",
    5: "with one packet per flit CXS_LAST and CXS_PROTOCOL_TYPE must be False",
    6: "with several packets per flit CXSDATAFLITWIDTH is 256/512/1024 (and 2048 from Issue D)",
    7: "a 256-bit flit carries at most 2 packets unless start alignment is 4 (Issue D)",
    8: "CXS_START_ALIGNMENT must be 4 or 16",
    9: "CXS_START_ALIGNMENT = 4 needs Issue D",
    10: "CXSLAST / CXSPRCLTYPE need Issue B or later",
    11: "CXS_MAX_CREDIT must be >= 1",
    12: "CXS_MAX_CREDIT is at most 15 before Issue C, 63 from Issue C",
    13: "CXS_SRCID_WIDTH/CXS_TGTID_WIDTH are 0..8 and CXS_USER_WIDTH 0..128",
    14: "CXSSRCID / CXSTGTID / CXSUSER need Issue D",
}


def _clog2(value):
    return max(0, (int(value) - 1).bit_length())


def chk_width(width):
    """Odd_Byte_Parity check width for a ``width``-bit signal (0 if absent)."""
    return 0 if width <= 0 else (width + 7) // 8


@dataclass(frozen=True)
class CXSConfig:
    """One CXS interface's properties (IHI 0079D Table 2-2).

    ``max_credit`` is CXS_MAX_CREDIT; ``link_control`` is True for
    CXSLINKCONTROL = Explicit_Credit_Return; ``check`` is True for
    CXSCHECKTYPE = Odd_Byte_Parity; ``continuous`` is CXSCONTINUOUSDATA.
    """
    issue: CXSIssue = CXSIssue.D
    data_width: int = 256
    max_pkt_per_flit: int = 2
    start_align: int = 16
    has_last: bool = False
    has_prcltype: bool = False
    srcid_width: int = 0
    tgtid_width: int = 0
    user_width: int = 0
    max_credit: int = 15
    # The one sanctioned departure from the spec: a credit pool beyond
    # CXS_MAX_CREDIT's cap (a receiver whose buffer is a whole SRAM). Skips
    # rule 12 only; mirrors the RTL CXS_CREDIT_BEYOND_SPEC parameter.
    credit_beyond_spec: bool = False
    link_control: bool = True
    check: bool = False
    continuous: bool = False

    def __post_init__(self):
        object.__setattr__(self, 'issue', CXSIssue.coerce(self.issue))

    # ------------------------------------------------------------------
    # Legality
    # ------------------------------------------------------------------
    def config_error(self):
        """0 when legal, else the first broken rule (see CONFIG_RULES)."""
        i, dw, n, al = int(self.issue), self.data_width, self.max_pkt_per_flit, self.start_align
        if i < CXSIssue.A or i > CXSIssue.D:
            return 1
        if n < 1 or n > 4:
            return 2
        if n == 1 and i < CXSIssue.C:
            return 3
        if n == 1:
            if dw < 8 or dw > 2048 or dw % 8:
                return 4
            if self.has_last or self.has_prcltype:
                return 5
        else:
            if dw not in (256, 512, 1024) and not (dw == 2048 and i >= CXSIssue.D):
                return 6
            if dw == 256 and n > 2 and not (al == 4 and i >= CXSIssue.D):
                return 7
        if al not in (4, 16):
            return 8
        if al == 4 and i < CXSIssue.D:
            return 9
        if (self.has_last or self.has_prcltype) and i < CXSIssue.B:
            return 10
        if self.max_credit < 1:
            return 11
        if not self.credit_beyond_spec and self.max_credit > (63 if i >= CXSIssue.C else 15):
            return 12
        if not (0 <= self.srcid_width <= 8 and 0 <= self.tgtid_width <= 8
                and 0 <= self.user_width <= 128):
            return 13
        if (self.srcid_width or self.tgtid_width or self.user_width) and i < CXSIssue.D:
            return 14
        return 0

    def validate(self):
        """Raise ValueError naming the broken rule when the set is illegal."""
        err = self.config_error()
        if err:
            raise ValueError(f"CXS Issue {self.issue.name}: rule {err}: {CONFIG_RULES[err]} ({self})")
        return self

    def is_compatible_rx(self, rx):
        """IHI 0079D Table 2-3: can this transmitter drive receiver ``rx``?

        Returns a list of the requirements that fail (empty = compatible).
        """
        fails = []
        if self.check != rx.check:
            fails.append("CXSCHECKTYPE must match")
        if rx.has_last and not self.has_last:
            fails.append("RX CXS_LAST = True needs TX CXS_LAST = True")
        if self.max_credit < rx.max_credit:
            fails.append("TX CXS_MAX_CREDIT must be >= RX")
        if rx.continuous and not self.continuous:
            fails.append("RX CXSCONTINUOUSDATA = True needs TX True")
        if self.data_width != rx.data_width:
            fails.append("CXSDATAFLITWIDTH must match")
        if self.link_control != rx.link_control:
            fails.append("CXSLINKCONTROL must match")
        if 1 in (self.max_pkt_per_flit, rx.max_pkt_per_flit):
            if self.max_pkt_per_flit != rx.max_pkt_per_flit:
                fails.append("CXSMAXPKTPERFLIT = 1 on either side must match")
        elif self.max_pkt_per_flit > rx.max_pkt_per_flit:
            fails.append("TX CXSMAXPKTPERFLIT must be <= RX")
        if self.start_align == 4 and rx.start_align != 4:
            fails.append("TX start alignment 4 needs RX 4")
        return fails

    # ------------------------------------------------------------------
    # Derived widths and the CXSCNTL layout
    # ------------------------------------------------------------------
    @property
    def is_lite(self):
        """CXS-Lite: one packet per flit, no CXSCNTL (IHI 0079D chapter 7)."""
        return self.max_pkt_per_flit == 1

    @property
    def flit_bytes(self):
        return self.data_width // 8

    @property
    def start_ptr_width(self):
        return _clog2(self.data_width // 32) if self.start_align == 4 else _clog2(self.data_width // 128)

    @property
    def end_ptr_width(self):
        return _clog2(self.data_width // 32)

    @property
    def cntl_width(self):
        """CXSCNTLWIDTH; 0 for CXS-Lite."""
        n = self.max_pkt_per_flit
        if n <= 1:
            return 0
        return n * (3 + self.start_ptr_width + self.end_ptr_width)

    @property
    def end_lsb(self):
        n = self.max_pkt_per_flit
        return n + n * self.start_ptr_width

    @property
    def enderror_lsb(self):
        return self.end_lsb + self.max_pkt_per_flit

    @property
    def end_ptr_lsb(self):
        return self.enderror_lsb + self.max_pkt_per_flit

    def start_ptr_lsb(self, k):
        return self.max_pkt_per_flit + k * self.start_ptr_width

    def end_ptr_lsb_k(self, k):
        return self.end_ptr_lsb + k * self.end_ptr_width

    def cntl_fields(self):
        """[(name, lsb, width)] in bit order -- the rows of Table 4-5/4-7."""
        n = self.max_pkt_per_flit
        if n <= 1:
            return []
        rows = [("START", 0, n)]
        rows += [(f"START{k}PTR", self.start_ptr_lsb(k), self.start_ptr_width) for k in range(n)]
        rows += [("END", self.end_lsb, n), ("ENDERROR", self.enderror_lsb, n)]
        rows += [(f"END{k}PTR", self.end_ptr_lsb_k(k), self.end_ptr_width) for k in range(n)]
        return rows

    def check_widths(self):
        """Check-signal widths for the signals this interface has (Table 3-2)."""
        if not self.check:
            return {}
        w = {'valid': 1, 'data': chk_width(self.data_width), 'crdgnt': 1}
        if self.cntl_width:
            w['cntl'] = chk_width(self.cntl_width)
        if self.has_last:
            w['last'] = 1
        if self.has_prcltype:
            w['prcltype'] = 1
        if self.srcid_width:
            w['srcid'] = 1
        if self.tgtid_width:
            w['tgtid'] = 1
        if self.user_width:
            w['user'] = chk_width(self.user_width)
        if self.link_control:
            w.update({'crdrtn': 1, 'activereq': 1, 'activeack': 1})
        return w

    def rtl_parameters(self):
        """The cxs_master / cxs_slave parameter set for this configuration."""
        return {
            'CXS_ISSUE': int(self.issue),
            'CXS_DATA_WIDTH': self.data_width,
            'CXS_MAX_PKT_PER_FLIT': self.max_pkt_per_flit,
            'CXS_START_ALIGN': self.start_align,
            'CXS_HAS_LAST': int(self.has_last),
            'CXS_HAS_PRCLTYPE': int(self.has_prcltype),
            'CXS_SRCID_WIDTH': self.srcid_width,
            'CXS_TGTID_WIDTH': self.tgtid_width,
            'CXS_USER_WIDTH': self.user_width,
            'CXS_MAX_CREDIT': self.max_credit,
            'CXS_CREDIT_BEYOND_SPEC': int(self.credit_beyond_spec),
            'CXS_LINK_CTRL': int(self.link_control),
            'CXS_CHECK': int(self.check),
        }

    def with_(self, **changes):
        """A copy with some properties changed (the config is immutable)."""
        return replace(self, **changes)

    @classmethod
    def lite(cls, data_width=256, issue=CXSIssue.D, **kw):
        """A CXS-Lite interface (one packet per flit, Issue C or later)."""
        return cls(issue=issue, data_width=data_width, max_pkt_per_flit=1, **kw)

    def short_name(self):
        """Compact id for test names: iD_w256_n2_a16_..."""
        tags = [f"i{self.issue.name}", f"w{self.data_width}", f"n{self.max_pkt_per_flit}",
                f"a{self.start_align}", f"cr{self.max_credit}"]
        if self.has_last:
            tags.append("last")
        if self.has_prcltype:
            tags.append("prcl")
        if self.srcid_width or self.tgtid_width:
            tags.append(f"id{self.srcid_width}x{self.tgtid_width}")
        if self.user_width:
            tags.append(f"u{self.user_width}")
        tags.append("lc" if self.link_control else "nolc")
        if self.check:
            tags.append("chk")
        return "_".join(tags)
