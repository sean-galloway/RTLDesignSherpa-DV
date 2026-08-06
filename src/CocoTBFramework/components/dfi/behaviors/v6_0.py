# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""DFI v6.0 behavior — new-generation baseline.

Spec-verified against the v6.0 book (Cadence, 8 May 2026). v6.0 is a
discontinuity: DDR1-4 and LPDDR1-4 support dropped (LPDDR5 / LPDDR6 /
DDR5 / HBM4 remain), the command bus repacked, and several interfaces
renamed or removed:

  - dfi_address → **dfi_cmdaddr** (encoded CA bus; per-protocol bit
    maps); unpacked command wires (bank/ras_n/cas_n/we_n/cke/odt/
    act_n/bg/cid) removed
  - dfi_alert_n → **dfi_alert** (polarity follows the memory signal);
    new dfi_data_alert for protocols with separate write-error paths
  - dfi_error / dfi_error_info → **dfi_phy_error / dfi_phy_error_info**
  - dfi_parity_in → **dfi_caparity**; dfi_reset_n → dfi_reset;
    dfi_wrdata_mask → dfi_wrdata_dbi_mask
  - **Disconnect protocol removed** (disconnect_request raises again)
  - new **sleep protocol** (dfi_sleep), command-bus enable
    (dfi_cmd_en), parity/ECC/severity data-path buses, 1:3 and 1:6
    frequency ratios

Training stays removed (PHY Managed / PHY Independent Mode), so the
v5.x raise is inherited.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import _bus_value, _maybe
from .events import (
    CRCEvent,
    CRCKind,
    DisconnectEvent,
    ErrorEvent,
    ErrorKind,
)
from .exceptions import RemovedInThisVersionError
from .v5_2 import DFIv5_2Behavior


class DFIv6_0Behavior(DFIv5_2Behavior):
    """Strategy class for DFI v6.0 semantics."""

    version_label: str = "v6.0"

    # ----- CRC / alert: dfi_alert (polarity per memory protocol) -----

    def crc(self, bus: Any, state: Any) -> Optional[CRCEvent]:
        """Sample dfi_alert (v6.0 rename of dfi_alert_n). Polarity now
        follows the memory signal; for DDR5 (ALERT_n) active means
        LOW, which this sampler assumes — override for protocols with
        active-high alerts.
        """
        del state
        alert = _maybe(bus, "alert")
        if alert is None:
            return None
        v = alert.value
        if v.is_resolvable and v.integer == 0:
            return CRCEvent(kind=CRCKind.DRAM_CRC, slice_idx=0)
        return None

    # ----- Error interface: dfi_phy_error rename -----

    def error_event(self, bus: Any, state: Any) -> Optional[ErrorEvent]:
        """Sample dfi_phy_error / dfi_phy_error_info (v6.0 rename of
        dfi_error / dfi_error_info; typically 1 bit + 4 info bits per
        data slice, not phased for frequency ratio).
        """
        del state
        err = _maybe(bus, "phy_error")
        if err is not None and _bus_value(err):
            info = _maybe(bus, "phy_error_info")
            return ErrorEvent(
                kind=ErrorKind.OTHER,
                code=_bus_value(info) if info is not None else 0,
            )
        return None

    # ----- Disconnect protocol: REMOVED in v6.0 -----

    def disconnect_request(self, bus: Any, state: Any) -> Optional[DisconnectEvent]:
        raise RemovedInThisVersionError(
            "Disconnect Protocol", self.version_label, "v6.0",
        )

    def disconnect_release(self, bus: Any, state: Any) -> None:
        raise RemovedInThisVersionError(
            "Disconnect Protocol", self.version_label, "v6.0",
        )

    # PHY Managed (phymngd wires), frequency change (init_start +
    # cmd/data ratios + FSP), low power, update: inherited from v5.x.
    # Training: inherited raise (still PHY-internal in v6.0).
