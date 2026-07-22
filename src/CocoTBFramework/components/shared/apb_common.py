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

Scope note:
    Since the issue #15 unification, the APB5 BFMs (``APB5Monitor``,
    ``APB5Master``, ``APB5Slave``) inherit directly from the APB4 BFMs in
    ``components/apb/apb_components.py`` and extend them via override
    hooks (packet construction, extension-signal drive/capture, randomizer
    constraints). The BFM state machines therefore live in one place; this
    module holds only the protocol constants both layers share:

    - ``BASE_APB_SIGNALS`` — the mandatory AMBA APB4 signal set, used as
      the cocotb_bus *required* signal list by both APB and APB5 BFMs.
    - ``BASE_APB_OPTIONAL_SIGNALS`` — the APB4 optional signals
      (PPROT / PSLVERR / PSTRB), declared as cocotb_bus *optional* signals
      so DUTs without them still bind. APB5 layers its USER / WAKEUP /
      parity extensions on top of this optional set (see
      ``components/apb5/apb5_components.py``).
    - ``PWRITE_DIR`` — ``("READ", "WRITE")`` direction mapping used by all
      APB BFMs.
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
