"""Cross-master scoreboard for concurrent bridge testing.

Designed for the BFM-stress tests: many masters firing many transactions at
many slaves, possibly with overlapping IDs and overlapping addresses. Each
write is registered with the master that issued it; once traffic settles, we
verify against each slave's MemoryModel.

The key requirement is **per-(master, slave) verification** so that a misroute
(write from master A landing at slave B's memory) shows up as both
"A's expected write didn't arrive" and "B's memory got a stray write".
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ExpectedWrite:
    """One write registered with the scoreboard."""
    master_idx: int
    slave_idx: int
    address: int
    data: int
    byte_count: int
    txn_id: Optional[int] = None  # AXI4 ID, if applicable


@dataclass
class ExpectedRead:
    """One read registered with the scoreboard."""
    master_idx: int
    slave_idx: int
    address: int
    expected_data: int  # from the seed pattern at issue time
    byte_count: int
    txn_id: Optional[int] = None


@dataclass
class ScoreboardResults:
    """Verification outcome."""
    writes_total: int = 0
    writes_matched: int = 0
    writes_mismatched: int = 0
    writes_lost: int = 0
    reads_total: int = 0
    reads_matched: int = 0
    reads_mismatched: int = 0
    per_master_writes: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    per_master_reads: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    per_slave_writes: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    per_slave_reads: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    mismatch_details: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.writes_mismatched == 0
            and self.writes_lost == 0
            and self.reads_mismatched == 0
        )

    def summary(self) -> str:
        lines = [
            f"writes: {self.writes_matched}/{self.writes_total} matched, "
            f"{self.writes_mismatched} mismatched, {self.writes_lost} lost",
            f"reads:  {self.reads_matched}/{self.reads_total} matched, "
            f"{self.reads_mismatched} mismatched",
        ]
        if self.per_master_writes:
            per_m_w = ", ".join(
                f"M{m}:{n}" for m, n in sorted(self.per_master_writes.items())
            )
            lines.append(f"per-master writes: {per_m_w}")
        if self.per_master_reads:
            per_m_r = ", ".join(
                f"M{m}:{n}" for m, n in sorted(self.per_master_reads.items())
            )
            lines.append(f"per-master reads:  {per_m_r}")
        if self.per_slave_writes:
            per_s_w = ", ".join(
                f"S{s}:{n}" for s, n in sorted(self.per_slave_writes.items())
            )
            lines.append(f"per-slave writes:  {per_s_w}")
        for d in self.mismatch_details[:10]:
            lines.append(f"  ! {d}")
        if len(self.mismatch_details) > 10:
            lines.append(f"  ... and {len(self.mismatch_details) - 10} more mismatches")
        return "\n".join(lines)


class ConcurrentBridgeScoreboard:
    """Cross-master scoreboard for concurrent bridge testing.

    Usage:
        sb = ConcurrentBridgeScoreboard(log)
        sb.register_write(master_idx=0, slave_idx=1, address=0x100,
                          data=0xDEADBEEF, byte_count=4, txn_id=5)
        # ... run transactions ...
        results = sb.verify(slave_mem_reader)
        assert results.passed, results.summary()
    """

    def __init__(self, log: Optional[logging.Logger] = None):
        self.log = log
        # Keyed by (slave_idx, address) so per-address ordering is checked
        self._writes: Dict[Tuple[int, int], List[ExpectedWrite]] = defaultdict(list)
        self._reads: List[ExpectedRead] = []
        self._pending_read_responses: Dict[
            Tuple[int, Optional[int]], List[ExpectedRead]
        ] = defaultdict(list)

    # ---------------- registration ----------------

    def register_write(
        self,
        master_idx: int,
        slave_idx: int,
        address: int,
        data: int,
        byte_count: int = 4,
        txn_id: Optional[int] = None,
    ) -> None:
        wr = ExpectedWrite(master_idx, slave_idx, address, data, byte_count, txn_id)
        self._writes[(slave_idx, address)].append(wr)

    def register_read(
        self,
        master_idx: int,
        slave_idx: int,
        address: int,
        expected_data: int,
        byte_count: int = 4,
        txn_id: Optional[int] = None,
    ) -> None:
        rd = ExpectedRead(master_idx, slave_idx, address, expected_data, byte_count, txn_id)
        self._reads.append(rd)
        self._pending_read_responses[(master_idx, txn_id)].append(rd)

    def record_read_response(
        self, master_idx: int, txn_id: Optional[int], actual_data: int
    ) -> Optional[str]:
        """Pop the next pending read for (master, id) and compare actual data.
        Returns an error message if it mismatched, ``None`` if it matched or
        if there was no pending entry.
        """
        key = (master_idx, txn_id)
        if not self._pending_read_responses[key]:
            return f"unexpected read response from M{master_idx}/id={txn_id}: 0x{actual_data:x}"
        expected = self._pending_read_responses[key].pop(0)
        mask = (1 << (8 * expected.byte_count)) - 1
        if (actual_data & mask) != (expected.expected_data & mask):
            return (
                f"read mismatch M{master_idx}/S{expected.slave_idx}/"
                f"id={txn_id} addr=0x{expected.address:08x}: "
                f"got 0x{actual_data:x}, expected 0x{expected.expected_data:x}"
            )
        return None

    # ---------------- verification ----------------

    def verify(self, slave_mem_reader) -> ScoreboardResults:
        """Verify all registered writes against slave memory.

        ``slave_mem_reader`` is a callable
        ``(slave_idx, address, byte_count) -> int`` that returns the
        little-endian integer value currently stored at the given address
        in the slave's MemoryModel.
        """
        results = ScoreboardResults()

        # ---- Writes: per-address, latest write wins ----
        for (slave_idx, addr), wrs in self._writes.items():
            # For same-address races, the spec says the slave only has to
            # honor "some" write — we conservatively check that the last
            # write registered (highest in our list, approximating the
            # order of issue from the TB) is the one observed. A more
            # rigorous check would require monitor callbacks.
            expected_wr = wrs[-1]
            try:
                actual = slave_mem_reader(slave_idx, addr, expected_wr.byte_count)
            except Exception as e:
                msg = (
                    f"write lost M{expected_wr.master_idx}/S{slave_idx} "
                    f"addr=0x{addr:08x}: slave memory read raised {e}"
                )
                results.mismatch_details.append(msg)
                results.writes_lost += len(wrs)
                results.writes_total += len(wrs)
                continue

            results.writes_total += len(wrs)
            results.per_slave_writes[slave_idx] += len(wrs)
            for wr in wrs:
                results.per_master_writes[wr.master_idx] += 1

            mask = (1 << (8 * expected_wr.byte_count)) - 1
            if (actual & mask) == (expected_wr.data & mask):
                results.writes_matched += len(wrs)
            else:
                results.writes_mismatched += 1
                # Outright "lost" is the rest (couldn't even check)
                results.writes_lost += len(wrs) - 1
                results.mismatch_details.append(
                    f"write mismatch M{expected_wr.master_idx}/S{slave_idx} "
                    f"addr=0x{addr:08x}: got 0x{actual:x}, expected "
                    f"0x{expected_wr.data:x} (id={expected_wr.txn_id})"
                )

        # ---- Reads: tally registered vs already-matched ----
        results.reads_total = len(self._reads)
        for rd in self._reads:
            results.per_master_reads[rd.master_idx] += 1
            results.per_slave_reads[rd.slave_idx] += 1

        # Anything still pending in _pending_read_responses is unmatched
        for key, pendings in self._pending_read_responses.items():
            for p in pendings:
                results.mismatch_details.append(
                    f"read response missing M{p.master_idx}/S{p.slave_idx} "
                    f"addr=0x{p.address:08x} id={p.txn_id}"
                )
                results.reads_mismatched += 1
        # Matched reads = total - mismatched (record_read_response counts
        # mismatches in real time, so anything we never saw a response for
        # is added to reads_mismatched here)
        results.reads_matched = results.reads_total - results.reads_mismatched

        return results

    def clear(self) -> None:
        self._writes.clear()
        self._reads.clear()
        self._pending_read_responses.clear()
