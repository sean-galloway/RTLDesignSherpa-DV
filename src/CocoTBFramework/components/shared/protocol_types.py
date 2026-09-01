# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: protocol_types
# Purpose: Canonical set of protocol_type identifiers used by component bases
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway

"""Canonical protocol_type identifiers.

Single source of truth for the ``protocol_type`` string accepted by
:class:`GAXIComponentBase` and :class:`FIFOComponentBase` (and any future
ready/valid base). Both bases previously hard-coded their own copies of this
list, which drifted over time — see issue #9.

Add a new identifier here when introducing a new ready/valid channel type,
then register the matching signal pattern in
``signal_mapping_helper.PROTOCOL_SIGNAL_CONFIGS``.

**Both halves, or the failure is late and confusing.** Registering only the
signal pattern gets you past import and past every unit test, then fails at
BFM construction inside a simulation with "protocol_type must be one of ..."
-- a list that looks authoritative and does not mention the name you just
added two files away. That happened with the twenty AXI4-Lite / AXI5-Lite
entries. ``tests/unit/test_protocol_registry_parity.py`` now asserts the two
sets agree, so the omission fails at unit-test time instead.
"""

from __future__ import annotations

from typing import FrozenSet

# GAXI / AXIS / FIFO channel types. These are validated at base-class
# construction time; SignalResolver consumes the same strings to pick a
# signal-pattern table.
PROTOCOL_TYPES: FrozenSet[str] = frozenset({
    # FIFO
    "fifo_master",
    "fifo_slave",
    # Generic AXI-like (ready/valid)
    "gaxi_master",
    "gaxi_slave",
    # AXI-Stream
    "axis_master",
    "axis_slave",
    # AXI4 per-channel
    "axi4_ar_master", "axi4_ar_slave",
    "axi4_r_master",  "axi4_r_slave",
    "axi4_aw_master", "axi4_aw_slave",
    "axi4_w_master",  "axi4_w_slave",
    "axi4_b_master",  "axi4_b_slave",
    # AXI5 per-channel
    "axi5_ar_master", "axi5_ar_slave",
    "axi5_r_master",  "axi5_r_slave",
    "axi5_aw_master", "axi5_aw_slave",
    "axi5_w_master",  "axi5_w_slave",
    "axi5_b_master",  "axi5_b_slave",
    # AXI4-Lite per-channel
    "axil4_ar_master", "axil4_ar_slave",
    "axil4_r_master",  "axil4_r_slave",
    "axil4_aw_master", "axil4_aw_slave",
    "axil4_w_master",  "axil4_w_slave",
    "axil4_b_master",  "axil4_b_slave",
    # AXI5-Lite per-channel
    "axil5_ar_master", "axil5_ar_slave",
    "axil5_r_master",  "axil5_r_slave",
    "axil5_aw_master", "axil5_aw_slave",
    "axil5_w_master",  "axil5_w_slave",
    "axil5_b_master",  "axil5_b_slave",
})


def validate_protocol_type(protocol_type: str) -> None:
    """Raise ``ValueError`` if ``protocol_type`` is not a known identifier."""
    if protocol_type not in PROTOCOL_TYPES:
        raise ValueError(
            f"protocol_type must be one of {sorted(PROTOCOL_TYPES)}, "
            f"got: {protocol_type!r}"
        )
