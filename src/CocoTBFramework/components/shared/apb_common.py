# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa-DV
#
# Module: apb_common
# Purpose: Shared constants and helpers for APB (AMBA APB4) and APB5 BFMs
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway

"""Shared constants for APB and APB5 BFMs.

Scope note (issue #8 audit):
    The original methodology review claimed APB and APB5 share ~80% of code.
    On closer inspection the duplication is materially smaller:

    - **Master**: ``APBMaster`` uses a queued, randomized transmit pipeline
      with ``_transmit_pipeline`` / ``_finish_xmit``. ``APB5Master`` directly
      drives in ``_driver_send`` with no queue and no randomized PSEL/PENABLE
      delays. These are structurally different implementations, not a
      common-base candidate.
    - **Slave**: APBSlave and APB5Slave diverge because APB5 carries
      USER/WAKEUP/parity fields that change the slave's randomizer and
      response logic.
    - **Monitor**: edge-detection loops are heavily duplicated but APB5
      captures more fields. A clean common-base extraction is possible
      but defer to a follow-up PR — left siblings here to keep the diff focused.

    What this module factors out today:

    - ``BASE_APB_SIGNALS`` / ``BASE_APB_OPTIONAL_SIGNALS`` — the AMBA APB4
      common subset (APB5 extends this set).
    - ``PWRITE_DIR`` — ``("READ", "WRITE")`` direction mapping used by both
      Monitors.

    The next consolidation step is to extract a common ``_APBMonitorBase``
    with override hooks for protocol-specific field capture. Tracked as a
    follow-up; this module is the seed.
"""

from __future__ import annotations

from typing import Tuple


# AMBA APB4 signal sets — APB5 extends this set with USER/PARITY/WAKEUP signals.
BASE_APB_SIGNALS: Tuple[str, ...] = (
    "PSEL",
    "PWRITE",
    "PENABLE",
    "PADDR",
    "PWDATA",
    "PRDATA",
    "PREADY",
)

BASE_APB_OPTIONAL_SIGNALS: Tuple[str, ...] = (
    "PPROT",
    "PSLVERR",
    "PSTRB",
)

# Direction lookup: APB encodes write/read in PWRITE (0 = read, 1 = write).
PWRITE_DIR: Tuple[str, str] = ("READ", "WRITE")
