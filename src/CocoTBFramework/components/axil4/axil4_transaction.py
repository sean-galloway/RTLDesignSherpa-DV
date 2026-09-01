# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL4Transaction
# Purpose: Transaction record and tracker for AXI4-Lite
#
# Subsystem: framework

"""AXI4-Lite transaction record and tracker.

Mirrors ``axi4_transaction`` / ``axi5_transaction``, simplified where AXI4-Lite
genuinely is simpler rather than where it merely looks it:

* **Every transaction is exactly one beat.** AXI4-Lite has no AxLEN, so there
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

AXI5-Lite adds optional sideband but changes none of this, which is why
``AXIL5Transaction`` subclasses rather than restates it.
"""
import time
from typing import Any, Dict, Optional


class AXIL4Transaction:
    """A single AXI4-Lite transaction and the packets that made it up."""

    #: AXI4-Lite is single-beat by construction.
    EXPECTED_BEATS = 1

    def __init__(self, transaction_id: int, transaction_type: str):
        if transaction_type not in ('read', 'write'):
            raise ValueError(
                f"transaction_type must be 'read' or 'write', got {transaction_type!r}"
            )
        self.transaction_id = transaction_id
        self.transaction_type = transaction_type
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.is_complete = False

        self.address_packet: Any = None      # AW or AR
        self.data_packets: list = []         # W (writes only)
        self.response_packets: list = []     # B or R

        self.expected_beats = self.EXPECTED_BEATS
        self.received_beats = 0
        self.error_response: Optional[int] = None

    def add_address_packet(self, packet: Any) -> None:
        """Record the AW or AR packet.

        Unlike AXI4 there is no burst length to read back: ``expected_beats``
        stays 1 for every AXI4-Lite transaction.
        """
        self.address_packet = packet

    def add_data_packet(self, packet: Any) -> None:
        """Record the W packet."""
        self.data_packets.append(packet)

    def add_response_packet(self, packet: Any) -> None:
        """Record a B or R packet and settle completion.

        A Lite transaction completes on its first response either way: writes
        on B, reads on their single R beat. There is no RLAST to wait for.
        """
        self.response_packets.append(packet)
        self.received_beats += 1

        for field in ('bresp', 'rresp'):
            resp = getattr(packet, field, None)
            if resp:                       # non-zero == not OKAY
                self.error_response = resp
                break

        self.is_complete = True
        self.end_time = time.time()

    @property
    def duration(self) -> Optional[float]:
        """Wall-clock duration, or None while still in flight."""
        return None if self.end_time is None else self.end_time - self.start_time

    @property
    def has_error(self) -> bool:
        return self.error_response is not None

    @property
    def response_code(self) -> str:
        """The response as a name. Lite uses the same 2-bit encoding as AXI4,
        minus EXOKAY -- AXI4-Lite has no exclusive access, so a slave returning
        0b01 is out of spec rather than reporting an exclusive success."""
        names = {0: 'OKAY', 1: 'EXOKAY (not legal on AXI4-Lite)',
                 2: 'SLVERR', 3: 'DECERR'}
        return names.get(self.error_response or 0, 'UNKNOWN')

    def get_data_bytes(self) -> bytes:
        """Concatenate the payload of every data packet recorded."""
        out = bytearray()
        for pkt in self.data_packets:
            data = getattr(pkt, 'wdata', None)
            if data is None:
                data = getattr(pkt, 'rdata', None)
            if data is not None:
                out += int(data).to_bytes(8, 'little')
        return bytes(out)

    def __repr__(self) -> str:
        state = 'complete' if self.is_complete else 'in-flight'
        err = f" error={self.response_code}" if self.has_error else ""
        return (f"<{type(self).__name__} #{self.transaction_id} "
                f"{self.transaction_type} {state}{err}>")


class AXIL4TransactionTracker:
    """Creates, looks up and retires AXIL4 transactions.

    Mirrors ``AXI5TransactionTracker``. The handle is allocated here rather
    than taken from the bus, because AXI4-Lite has no ID to take.
    """

    TRANSACTION_CLASS = AXIL4Transaction

    def __init__(self):
        self.active: Dict[int, AXIL4Transaction] = {}
        self.completed: list = []
        self._next_id = 0

    def create_transaction(self, transaction_type: str,
                           transaction_id: Optional[int] = None) -> AXIL4Transaction:
        if transaction_id is None:
            transaction_id = self._next_id
            self._next_id += 1
        elif transaction_id in self.active:
            raise ValueError(f"transaction {transaction_id} is already in flight")
        txn = self.TRANSACTION_CLASS(transaction_id, transaction_type)
        self.active[transaction_id] = txn
        return txn

    def get_transaction(self, transaction_id: int) -> Optional[AXIL4Transaction]:
        return self.active.get(transaction_id)

    def complete_transaction(self, transaction_id: int) -> Optional[AXIL4Transaction]:
        txn = self.active.pop(transaction_id, None)
        if txn is not None:
            self.completed.append(txn)
        return txn

    def get_statistics(self) -> dict:
        durations = [t.duration for t in self.completed if t.duration is not None]
        errors = [t for t in self.completed if t.has_error]
        return {
            'active': len(self.active),
            'completed': len(self.completed),
            'errors': len(errors),
            'error_rate': (len(errors) / len(self.completed)) if self.completed else 0.0,
            'average_duration': (sum(durations) / len(durations)) if durations else None,
        }

    def clear(self) -> None:
        self.active.clear()
        self.completed.clear()
        self._next_id = 0
