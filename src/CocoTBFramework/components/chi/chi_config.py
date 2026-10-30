# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_config
# Purpose: CHI (Arm IHI 0050 Issue H) interface properties, legality and
#          the derived flit widths
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI interface configuration.

One frozen :class:`CHIConfig` per port. The values are the B16.1 interface
properties and parameters that change a flit's layout or a link's
behaviour; everything else in the spec that only changes *which* opcodes a
node may use is a property of the BFM, not of the config.

Every width here is transcribed from IHI 0050H Tables B13.6 to B13.9 (flit
formats) and B16.10 to B16.12 (parameter ranges). ``validate()`` names the
rule a bad set breaks, the same way the CXS family and the RTL
``cxs_pkg::config_error`` do, so a test can assert on the number.

Scope of this first release (see the family docs for the list): Issue H
only, no Resource Planes (``Num_RP_* = 1``, no shared credits), no
replicated channels. The optional sideband buses (MPAM, PBHA, MECID,
StreamID, SecSID1, RSVDC, DataCheck, Poison) are *widths* so the flit
layout is exact for a DUT that has them; the BFMs carry them untouched.
"""

from dataclasses import dataclass, replace
from enum import Enum, IntEnum


class CHIIssue(IntEnum):
    """Spec issues. Only H has an on-disk spec in this family; the others
    exist so a config can say what it is NOT (field widths changed between
    F and G, so a G layout is not an H layout)."""
    E = 5
    F = 6
    G = 7
    H = 8

    @classmethod
    def coerce(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls[value.upper()]
        return cls(int(value))


class NodeType(str, Enum):
    """B13.6 node interfaces. Decides which channels a port has."""
    RN_F = "RN-F"   # all six: TXREQ RXRSP RXDAT RXSNP TXRSP TXDAT
    RN_D = "RN-D"   # as RN-F, SNP limited to DVM
    RN_I = "RN-I"   # no SNP channel
    HN_F = "HN-F"   # the interconnect side facing an RN-F (mirror of RN-F)
    HN_I = "HN-I"   # the interconnect side facing an RN-I
    SN_F = "SN-F"   # RXREQ TXRSP TXDAT RXDAT

    @classmethod
    def coerce(cls, value):
        if isinstance(value, cls):
            return value
        v = str(value).upper().replace('_', '-')
        for m in cls:
            if m.value == v or m.name == v.replace('-', '_'):
                return m
        raise ValueError(f"unknown CHI node type {value!r}")


# Channels a node TRANSMITS on and RECEIVES on, from the node's own
# perspective (B13.4 Table B13.1 and the B13.6 figures).
_TX_CHANNELS = {
    NodeType.RN_F: ('req', 'rsp', 'dat'),
    NodeType.RN_D: ('req', 'rsp', 'dat'),
    NodeType.RN_I: ('req', 'rsp', 'dat'),
    NodeType.HN_F: ('rsp', 'dat', 'snp'),
    NodeType.HN_I: ('rsp', 'dat'),
    NodeType.SN_F: ('rsp', 'dat'),
}
_RX_CHANNELS = {
    NodeType.RN_F: ('rsp', 'dat', 'snp'),
    NodeType.RN_D: ('rsp', 'dat', 'snp'),
    NodeType.RN_I: ('rsp', 'dat'),
    NodeType.HN_F: ('req', 'rsp', 'dat'),
    NodeType.HN_I: ('req', 'rsp', 'dat'),
    NodeType.SN_F: ('req', 'dat'),
}

CONFIG_RULES = {
    1: "issue must be H (the only issue with an on-disk spec; G flit widths differ)",
    2: "NodeID_Width must be 7 to 16 (Table B16.11)",
    3: "Req_Addr_Width must be 44 to 52 (Table B16.10)",
    4: "Data_Width must be 128, 256 or 512 (Table B16.12)",
    5: "Req_RSVDC_Width must be 0, 4, 8, 12, 16, 24 or 32 (Table B13.6)",
    6: "Dat_RSVDC_Width must be 0, 4, 8, 12, 16, 24 or 32 (Table B13.9)",
    7: "MPAM width must be 0, 12 or 15 (Table B13.6)",
    8: "PBHA width must be 0 or 4 (Table B13.6)",
    9: "MECID width must be 0 or 16 (Table B13.6)",
    10: "StreamID width must be 0 or 16 (Table B13.6)",
    11: "SecSID1 width must be 0 or 1 (Table B13.6)",
    12: "max L-Credits per channel must be 1 to 15 (B14.2.1.1)",
    13: "node_type must be one of RN-F, RN-D, RN-I, HN-F, HN-I, SN-F",
}

_RSVDC = (0, 4, 8, 12, 16, 24, 32)


@dataclass(frozen=True)
class CHIConfig:
    """One CHI port's properties (IHI 0050H chapter B16 and Table B13.6-9).

    ``node_type`` is the node the *BFM* plays, not the DUT: a
    ``CHIRequestNode`` with ``node_type=RN_F`` drives an HN-F-side DUT.
    """
    issue: CHIIssue = CHIIssue.H
    node_type: NodeType = NodeType.RN_F
    nodeid_width: int = 7          # B16.1.12 NodeID_Width
    addr_width: int = 44           # B16.1.11 Req_Addr_Width (RAW)
    data_width: int = 128          # B16.1.13 Data_Width (DW)
    req_rsvdc_width: int = 0       # B16.1.28
    dat_rsvdc_width: int = 0       # B16.1.29
    mpam_width: int = 0            # B16.1.9 MPAM_Support -> M = 0, 12, 15
    pbha_width: int = 0            # B16.1.19 PBHA_Support -> PB = 0, 4
    mecid_width: int = 0           # B16.1.26 MECID_Width -> E = 0, 16
    streamid_width: int = 0        # RME-CDA -> R = 0, 16 (shares bits with MECID)
    secsid1_width: int = 0         # RME-CDA -> S = 0, 1
    data_check: bool = False       # B16.1.6 Data_Check -> DC = DW/8
    poison: bool = False           # B16.1.4 Data_Poison -> P = DW/64
    max_lcredit: int = 15          # B14.2.1.1: 1 to 15 per channel
    link_control: bool = True      # LINKACTIVEREQ/ACK pair present
    sactive: bool = True           # TXSACTIVE/RXSACTIVE present

    def __post_init__(self):
        object.__setattr__(self, 'issue', CHIIssue.coerce(self.issue))
        object.__setattr__(self, 'node_type', NodeType.coerce(self.node_type))

    # ------------------------------------------------------------------
    # Legality
    # ------------------------------------------------------------------
    def config_error(self) -> int:
        """0 when legal, else the first broken rule number (CONFIG_RULES)."""
        if self.issue != CHIIssue.H:
            return 1
        if not 7 <= self.nodeid_width <= 16:
            return 2
        if not 44 <= self.addr_width <= 52:
            return 3
        if self.data_width not in (128, 256, 512):
            return 4
        if self.req_rsvdc_width not in _RSVDC:
            return 5
        if self.dat_rsvdc_width not in _RSVDC:
            return 6
        if self.mpam_width not in (0, 12, 15):
            return 7
        if self.pbha_width not in (0, 4):
            return 8
        if self.mecid_width not in (0, 16):
            return 9
        if self.streamid_width not in (0, 16):
            return 10
        if self.secsid1_width not in (0, 1):
            return 11
        if not 1 <= self.max_lcredit <= 15:
            return 12
        if not isinstance(self.node_type, NodeType):
            return 13
        return 0

    def validate(self):
        err = self.config_error()
        if err:
            raise ValueError(f"CHI Issue {self.issue.name}: rule {err}: {CONFIG_RULES[err]} ({self})")
        return self

    def with_(self, **changes):
        return replace(self, **changes)

    def short_name(self):
        return (f"CHI-{self.issue.name} {self.node_type.value} N{self.nodeid_width} "
                f"A{self.addr_width} DW{self.data_width}")

    # ------------------------------------------------------------------
    # Channel presence (B13.4 Table B13.1, B13.6)
    # ------------------------------------------------------------------
    @property
    def tx_channels(self):
        return _TX_CHANNELS[self.node_type]

    @property
    def rx_channels(self):
        return _RX_CHANNELS[self.node_type]

    @property
    def is_requester(self):
        return self.node_type in (NodeType.RN_F, NodeType.RN_D, NodeType.RN_I)

    @property
    def is_home(self):
        return self.node_type in (NodeType.HN_F, NodeType.HN_I)

    @property
    def has_snp(self):
        return 'snp' in self.tx_channels or 'snp' in self.rx_channels

    # ------------------------------------------------------------------
    # Derived widths (Tables B13.6 to B13.9)
    # ------------------------------------------------------------------
    @property
    def snp_addr_width(self):
        """SNP Addr is Req_Addr_Width - 3 (B13.10.20)."""
        return self.addr_width - 3

    @property
    def mecid_or_streamid_width(self):
        """The REQ flit carries Max(E, R) bits for MECID / StreamID."""
        return max(self.mecid_width, self.streamid_width)

    @property
    def data_check_width(self):
        return self.data_width // 8 if self.data_check else 0

    @property
    def poison_width(self):
        return self.data_width // 64 if self.poison else 0

    @property
    def be_width(self):
        return self.data_width // 8

    @property
    def tag_width(self):
        return self.data_width // 32

    @property
    def tu_width(self):
        return self.data_width // 128

    @property
    def req_flit_width(self):
        """Table B13.6: 93 + RAW + Y + M + PB + S + Max(E,R) at NodeID 7,
        plus (NodeID_Width - 7) for each of TgtID, SrcID, ReturnNID."""
        n = self.nodeid_width - 7
        return (93 + self.addr_width + self.req_rsvdc_width + self.mpam_width + self.pbha_width
                + self.secsid1_width + self.mecid_or_streamid_width + 3 * n)

    @property
    def rsp_flit_width(self):
        """Table B13.7: T = 71 at NodeID 7, plus TgtID and SrcID growth."""
        return 71 + 2 * (self.nodeid_width - 7)

    @property
    def snp_flit_width(self):
        """Table B13.8: S = 53 + SAW + M + E at NodeID 7, plus SrcID and
        FwdNID growth."""
        return (53 + self.snp_addr_width + self.mpam_width + self.mecid_width
                + 2 * (self.nodeid_width - 7))

    @property
    def dat_flit_width(self):
        """Table B13.9: D = 240 / 389 / 687 (DW 128 / 256 / 512) at NodeID 7
        and no optional buses, plus Y + DC + P + E and TgtID, SrcID, HomeNID
        growth."""
        base = {128: 240, 256: 389, 512: 687}[self.data_width]
        return (base + self.dat_rsvdc_width + self.data_check_width + self.poison_width
                + self.mecid_width + 3 * (self.nodeid_width - 7))

    def flit_width(self, channel: str) -> int:
        return {'req': self.req_flit_width, 'rsp': self.rsp_flit_width,
                'snp': self.snp_flit_width, 'dat': self.dat_flit_width}[channel]

    # ------------------------------------------------------------------
    # RTL parameter mirror
    # ------------------------------------------------------------------
    def rtl_parameters(self):
        """Parameter dict for a CHI RTL port in the RTLDesignSherpa style."""
        return {
            'NODEID_WIDTH': self.nodeid_width,
            'ADDR_WIDTH': self.addr_width,
            'DATA_WIDTH': self.data_width,
            'REQ_RSVDC_WIDTH': self.req_rsvdc_width,
            'DAT_RSVDC_WIDTH': self.dat_rsvdc_width,
            'MPAM_WIDTH': self.mpam_width,
            'PBHA_WIDTH': self.pbha_width,
            'MECID_WIDTH': self.mecid_width,
            'STREAMID_WIDTH': self.streamid_width,
            'SECSID1_WIDTH': self.secsid1_width,
            'DATA_CHECK': int(self.data_check),
            'POISON': int(self.poison),
            'MAX_LCREDIT': self.max_lcredit,
            'REQ_FLIT_WIDTH': self.req_flit_width,
            'RSP_FLIT_WIDTH': self.rsp_flit_width,
            'SNP_FLIT_WIDTH': self.snp_flit_width,
            'DAT_FLIT_WIDTH': self.dat_flit_width,
        }


__all__ = ['CHIConfig', 'CHIIssue', 'NodeType', 'CONFIG_RULES']
