# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: cxs_check
# Purpose: CXSCHECKTYPE = Odd_Byte_Parity (IHI 0079D 3.2)
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-15
"""CXS interface protection.

Odd_Byte_Parity: a check bit plus the bits it covers always hold an odd
number of ones; check bit [n] covers bits [8n+7:8n] and the top bit covers a
short remainder (a 27-bit CXSCNTL has CXSCNTLCHK[3] over CXSCNTL[26:24]); a
one-bit signal's check is its inversion. This is exactly the AXI5-Stream
Odd_Parity_Byte_All scheme, so the arithmetic is shared with axis5_check.

Check enables (Table 3-2): the payload checks (DATA, CNTL, LAST, PRCLTYPE,
SRCID, TGTID, USER) only while CXSVALID is high; VALID, CRDGNT, CRDRTN,
ACTIVEREQ and ACTIVEACK every cycle out of reset. CXSDEACTHINT has none.
CXSPRCLTYPECHK, CXSSRCIDCHK and CXSTGTIDCHK are one bit each (their signals
are at most 8 bits wide).
"""

from ..axis5.axis5_check import chk_width, is_odd_parity, odd_parity_chk

# Signals whose check is enabled by CXSVALID, in the BFM field naming
PAYLOAD_SIGNALS = ('data', 'cntl', 'last', 'prcltype', 'srcid', 'tgtid', 'user')

# Signals whose check is enabled every cycle out of reset, by direction
TX_CONTROL_SIGNALS = ('valid', 'crdrtn', 'activereq')
RX_CONTROL_SIGNALS = ('crdgnt', 'activeack')

__all__ = ['PAYLOAD_SIGNALS', 'TX_CONTROL_SIGNALS', 'RX_CONTROL_SIGNALS',
           'chk_width', 'odd_parity_chk', 'is_odd_parity', 'signal_width']


def signal_width(cfg, name):
    """Width in bits of CXS signal ``name`` on ``cfg`` (0 = absent)."""
    return {
        'data': cfg.data_width,
        'cntl': cfg.cntl_width,
        'last': 1 if cfg.has_last else 0,
        'prcltype': 3 if cfg.has_prcltype else 0,
        'srcid': cfg.srcid_width,
        'tgtid': cfg.tgtid_width,
        'user': cfg.user_width,
    }.get(name, 1)
