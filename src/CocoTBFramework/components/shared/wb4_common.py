# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: wb4_common
# Purpose: Shared constants for the Wishbone B4 (pipelined) BFMs
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-09-09
"""Shared constants for the Wishbone B4 BFMs.

Wishbone B4, PIPELINED mode. The request side is STB/STALL (an inverted
ready) with WE/ADR/DAT/SEL under a CYC envelope; the response side is one of
ACK/ERR/RTY per clock with DAT, terminating accepted requests IN ORDER.

- ``WB4_MASTER_DRIVEN`` / ``WB4_SLAVE_DRIVEN`` -- which side drives which
  signal; the BFMs use these to decide what to bind as an output.
- ``WB4_DATA_ALIASES`` -- the two names the spec's DAT_O/DAT_I get on a port.
  A master's DAT_O is the slave's DAT_I, so a DUT named from the master's
  view says ``DAT_W``/``DAT_O`` for write data and ``DAT_R``/``DAT_I`` for
  read data. Both are accepted, resolved at bind time.
- ``WB4_STATUS_*`` -- the 2-bit status the RTL's wb4_pkg encodes; mirrored
  here because cocotb cannot import an SV package.
"""

from __future__ import annotations

from typing import Tuple

# Required on every Wishbone B4 pipelined port (data names resolved via aliases).
WB4_MASTER_DRIVEN: Tuple[str, ...] = ("CYC", "STB", "WE", "ADR", "SEL")
WB4_SLAVE_DRIVEN: Tuple[str, ...] = ("STALL", "ACK")
# Optional: a slave that never errors or retries may omit them.
WB4_OPTIONAL_SIGNALS: Tuple[str, ...] = ("ERR", "RTY")

# Canonical name -> accepted port suffixes, first match wins.
WB4_DATA_ALIASES = {
    "DAT_W": ("DAT_W", "DAT_O", "WDATA", "DATA_W"),   # master -> slave
    "DAT_R": ("DAT_R", "DAT_I", "RDATA", "DATA_R"),   # slave -> master
}

WB4_STATUS_ACK = 0
WB4_STATUS_ERR = 1
WB4_STATUS_RTY = 2
WB4_STATUS_NAMES: Tuple[str, ...] = ("ACK", "ERR", "RTY", "???")

WE_DIR: Tuple[str, ...] = ("READ", "WRITE")
