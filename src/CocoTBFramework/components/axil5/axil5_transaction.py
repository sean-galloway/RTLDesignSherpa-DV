# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5Transaction
# Purpose: Transaction record and tracker for AXI5-Lite
#
# Subsystem: framework

"""AXI5-Lite transaction record and tracker.

``AXIL4Transaction`` with the AXI5-Lite sideband recorded alongside it. The
transaction MODEL is unchanged -- single beat, no RLAST, no bus ID -- because
AXI5-Lite adds optional signals to AXI4-Lite without changing a channel's
handshake, ordering or completion semantics. So these subclass rather than
restate, the same way the interfaces do.

Inherited from AXI4-Lite unchanged:

* **Every transaction is exactly one beat.** AXI5-Lite has no AxLEN, so there
  is no burst-length arithmetic and ``expected_beats`` is always 1. The AXI4
  version derives it from ``awlen``/``arlen``; here that would be dead code
  that reads a field which does not exist.
* **There is no RLAST.** AXI4 completes a read when a beat arrives with RLAST
  set. Lite has no such signal, so a read completes on its single R beat.
  Waiting for an RLAST that can never arrive would hang.
* **There is no ID.** ``transaction_id`` is a tracker-local handle for
  correlating packets, NOT an AxID off the bus -- Lite has none. The name is
  kept because the AXI4/AXI5 trackers use it and moving between them should
  not mean relearning the vocabulary.

"""
from typing import Any, Optional

from CocoTBFramework.components.axil4.axil4_transaction import (
    AXIL4Transaction,
    AXIL4TransactionTracker,
)


class AXIL5Transaction(AXIL4Transaction):
    """An AXI4-Lite transaction plus the AXI5-Lite optional sideband.

    The groups are recorded when the packet carries them and left None when it
    does not, which is the same thing the RTL does: a disabled group is absent,
    not zero-valued-and-meaningful.
    """

    #: Optional-group fields that may ride an address packet.
    ADDR_SIDEBAND = ('user', 'trace', 'loop', 'mpam', 'mecid', 'nsaid', 'lock')
    #: ...a data packet.
    DATA_SIDEBAND = ('user', 'poison')
    #: ...a response packet.
    RESP_SIDEBAND = ('user', 'trace', 'loop', 'poison')

    def __init__(self, transaction_id: int, transaction_type: str):
        super().__init__(transaction_id, transaction_type)
        self.addr_sideband: dict = {}
        self.data_sideband: list = []
        self.resp_sideband: list = []

    @staticmethod
    def _collect(packet: Any, prefix: str, fields) -> dict:
        """Pull {field: value} for whichever optional signals this packet has.

        Absent is recorded as absent. Writing 0 for a missing group would make
        "the DUT was built without MPAM" indistinguishable from "MPAM is 0",
        and those mean different things to anyone reading the record.
        """
        got = {}
        for f in fields:
            for name in (f"{prefix}{f}", f):
                if hasattr(packet, name):
                    got[f] = getattr(packet, name)
                    break
        return got

    def add_address_packet(self, packet: Any) -> None:
        super().add_address_packet(packet)
        pre = 'aw' if self.transaction_type == 'write' else 'ar'
        self.addr_sideband = self._collect(packet, pre, self.ADDR_SIDEBAND)

    def add_data_packet(self, packet: Any) -> None:
        super().add_data_packet(packet)
        self.data_sideband.append(self._collect(packet, 'w', self.DATA_SIDEBAND))

    def add_response_packet(self, packet: Any) -> None:
        super().add_response_packet(packet)
        pre = 'b' if self.transaction_type == 'write' else 'r'
        self.resp_sideband.append(self._collect(packet, pre, self.RESP_SIDEBAND))

    @property
    def is_poisoned(self) -> bool:
        """True if any recorded beat carried a non-zero POISON.

        Carried, never generated and never checked by the transport RTL -- this
        reports what arrived.
        """
        return any(sb.get('poison') for sb in self.data_sideband + self.resp_sideband)

    @property
    def response_code(self) -> str:
        """AXI5-Lite DOES have exclusive access, so 0b01 is a legal EXOKAY here
        where it is out of spec on AXI4-Lite."""
        names = {0: 'OKAY', 1: 'EXOKAY', 2: 'SLVERR', 3: 'DECERR'}
        return names.get(self.error_response or 0, 'UNKNOWN')


class AXIL5TransactionTracker(AXIL4TransactionTracker):
    """AXIL4 tracker, allocating AXIL5 transactions."""

    TRANSACTION_CLASS = AXIL5Transaction
