# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI v5.x behavior (v5.0 editorial; v5.1 signal wave; v5.2 renames).

Spec-verified against the v5.2 book. The old assumption that "v5.2 is
v4.0 plus a chapter-title rename" is WRONG in two load-bearing ways:

  1. The **DFI training interface is gone** — dfi_rdlvl_* /
     dfi_wrlvl_* / dfi_calvl_* / dfi_wdqlvl_* / DB training no longer
     exist. "The DFI specification does not dictate any training
     methodology"; training runs PHY-internally via the PHY Managed
     interface (PHY Independent Mode). training_step() raises
     RemovedInThisVersionError.
  2. The PHY Master rename is a **wire rename**, not just a title:
     dfi_phymstr_* → dfi_phymngd_*. A v5.2 BFM must sample different
     signals than a v4.0/v5.1 one.

Also new at v5.x (5.1 proposals, in the 5.2 book): WCK control
(LPDDR5), MC-to-PHY messages (dfi_ctrlmsg*), DDR5 2N mode / CS
geardown, LPDDR5 Link ECC, split low-power ctrl/data ack + wakeup,
dfi_freq_fsp, and (5.2) the dfi_freq_ratio → dfi_cmd_freq_ratio +
dfi_data_freq_ratio split with 1:8 support and DDR5 MRDIMM Link DQ
CRC.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import _bus_value, _maybe
from .events import (
    FreqChangeEvent,
    FreqChangeProtocol,
    TrainingEvent,
)
from .exceptions import RemovedInThisVersionError
from .v4_0 import DFIv4_0Behavior


class DFIv5_2Behavior(DFIv4_0Behavior):
    """Strategy class for DFI v5.x semantics."""

    version_label: str = "v5.2"

    # v5.2 renamed the takeover wires; the v4.0 sampler logic is
    # inherited and just reads the new names.
    _takeover_prefix: str = "phymngd"
    _takeover_reason: str = "phy_managed"

    # ----- Training: interface REMOVED in v5.x -----

    def training_step(self, bus: Any, state: Any) -> Optional[TrainingEvent]:
        raise RemovedInThisVersionError(
            "DFI training interface (training is PHY-internal via the "
            "PHY Managed interface / PHY Independent Mode)",
            self.version_label, "v5.0",
        )

    # ----- Frequency change: split ratios + FSP -----

    def freq_change(self, bus: Any, state: Any) -> Optional[FreqChangeEvent]:
        """init_start/init_complete protocol unchanged; the v5.x event
        captures dfi_cmd_freq_ratio + dfi_data_freq_ratio (the v5.2
        split of dfi_freq_ratio; ratios to 1:8), dfi_freq_fsp, and the
        (now up to 6-bit) dfi_frequency indicator.
        """
        del state
        if not (_bus_value(bus.init_start) and _bus_value(bus.init_complete)):
            return None

        def _opt(name: str):
            sig = _maybe(bus, name)
            return _bus_value(sig) if sig is not None else None

        return FreqChangeEvent(
            protocol=FreqChangeProtocol.BASIC,
            frequency_code=_opt("frequency"),
            cmd_freq_ratio=_opt("cmd_freq_ratio"),
            data_freq_ratio=_opt("data_freq_ratio"),
            freq_fsp=_opt("freq_fsp"),
        )

    # PHY takeover/release: inherited (phymngd wires via the prefix).
    # Disconnect: inherited — v5.2 kept the protocol for ctrlupd /
    # phyupd / phymngd handshakes.
    # CRC (alert_n), Error, CA parity, Low power, Update: inherited.
    # (The 5.1 lp ack/wakeup ctrl/data split affects which wires the
    # BFM *drives*; the request sampling inherited from v3.1 already
    # reads the split request wires.)
