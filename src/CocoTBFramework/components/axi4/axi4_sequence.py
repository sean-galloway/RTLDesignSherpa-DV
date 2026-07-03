# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXI4Sequence
# Purpose: Canned + directed-random AXI4 burst sequences
#
# Documentation: see docs/AXI4_SEQUENCES.md (TODO)
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-06-22

"""AXI4 transaction sequences.

`AXI4Sequence` is a deferred-execution authoring layer above
`AXI4MasterWrite` / `AXI4MasterRead`. Author canned sequences once
(e.g. "random base, then row-hit follow-ons" or "spray across all
banks") in an include module; tests then run them and exclude broken
ones with `filter()` until bugs are fixed.

Design philosophy mirrors `GAXISequence`:

  - The sequence is **data**, not coroutines. Each entry is an
    `AXI4Burst` describing one bus transaction.
  - Execution is a single async function `run_axi4_sequence(seq, ...)`
    that walks the list. Sequences can be regenerated, shuffled, or
    composed without re-authoring the runner.

DDR/SDRAM-aware helpers built in:

  - `add_row_hit_burst` — random base then N follow-on column
    increments inside the same row.
  - `add_bank_spray` — N bursts across N banks at the same row.
  - `add_row_miss_pair` — back-to-back bursts to the same bank but
    different rows (forces PRE→ACT).
  - `add_random_workload` — RNG-driven mix using configurable
    W:R / size distributions (the standard "60/40 with 128B/256B/
    512B/1024B at 20/20/40/20" pattern).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "AXI4Burst",
    "AXI4Sequence",
    "run_axi4_sequence",
]


@dataclass
class AXI4Burst:
    """One AXI4 burst — write or read."""

    is_write: bool
    addr: int
    length: int                          # beats (1..256)
    axid: int = 0
    qos: int = 0
    size: int = 3                        # log2(bytes/beat); 3=8B (64-bit bus)
    burst_type: int = 1                  # 0=FIXED, 1=INCR (default), 2=WRAP
    data: Optional[List[int]] = None     # writes only
    strb: int = 0xFF                     # all bytes (64-bit default); add_write
                                         # sets it per data_width automatically
    delay_cycles: int = 0                # idle cycles before issuing
    tag: Optional[str] = None            # debug tag (which sequence it came from)


class AXI4Sequence:
    """Author once, run many times. Pair with `run_axi4_sequence`."""

    def __init__(self, name: str = "seq", *, data_width: int = 64,
                 id_width: int = 4, addr_width: int = 32,
                 seed: Optional[int] = None) -> None:
        self.name = name
        self.data_width = data_width
        self.id_width = id_width
        self.addr_width = addr_width
        self.bytes_per_beat = data_width // 8
        self._rng = random.Random(seed)
        self.bursts: List[AXI4Burst] = []
        self.stats: Dict[str, int] = {
            "writes": 0,
            "reads": 0,
            "row_hit_bursts": 0,
            "bank_spray_bursts": 0,
            "row_miss_pairs": 0,
            "random_bursts": 0,
        }

    # ---- Low-level primitives ---------------------------------------------

    def add_write(self, addr: int, data: Sequence[int], *, axid: int = 0,
                  qos: int = 0, delay: int = 0,
                  tag: Optional[str] = None) -> int:
        """Add one write burst with explicit data."""
        if not isinstance(data, (list, tuple)):
            data = [data]
        b = AXI4Burst(
            is_write=True, addr=addr, length=len(data), axid=axid,
            qos=qos, size=self._size_for_bus(), burst_type=1,
            data=list(data), strb=(1 << self.bytes_per_beat) - 1,
            delay_cycles=delay, tag=tag,
        )
        self.bursts.append(b)
        self.stats["writes"] += 1
        return len(self.bursts) - 1

    def add_read(self, addr: int, length: int = 1, *, axid: int = 0,
                 qos: int = 0, delay: int = 0,
                 tag: Optional[str] = None) -> int:
        """Add one read burst."""
        b = AXI4Burst(
            is_write=False, addr=addr, length=length, axid=axid,
            qos=qos, size=self._size_for_bus(), burst_type=1,
            delay_cycles=delay, tag=tag,
        )
        self.bursts.append(b)
        self.stats["reads"] += 1
        return len(self.bursts) - 1

    # ---- DDR/SDRAM-targeted patterns --------------------------------------

    def add_row_hit_burst(self, base_addr: int, n_followups: int, *,
                          burst_bytes: int = 64,
                          col_increment_bytes: Optional[int] = None,
                          is_write: bool = True, qos: int = 0,
                          axid: int = 0,
                          data_fn: Optional[Callable[[int, int], int]] = None,
                          tag: str = "row_hit") -> List[int]:
        """Random-ish base + N follow-on bursts that increment column only.

        `base_addr` should be aligned to `burst_bytes`. The follow-ups step
        by `col_increment_bytes` (defaults to `burst_bytes`). If the address
        map keeps row+bank fixed under that increment, every follow-up is a
        row-hit — the scheduler should NOT issue PRE/ACT between them.

        Returns the list of burst indices issued.
        """
        if col_increment_bytes is None:
            col_increment_bytes = burst_bytes
        length = max(1, burst_bytes // self.bytes_per_beat)
        indices: List[int] = []
        for i in range(n_followups + 1):
            addr = base_addr + i * col_increment_bytes
            if is_write:
                data = self._gen_data(length, base_addr, i, data_fn)
                indices.append(self.add_write(addr, data, axid=axid, qos=qos,
                                              tag=tag))
            else:
                indices.append(self.add_read(addr, length, axid=axid, qos=qos,
                                             tag=tag))
        self.stats["row_hit_bursts"] += len(indices)
        return indices

    def add_bank_spray(self, base_addr: int, num_banks: int = 8, *,
                       bank_stride_bytes: int = 0x400,
                       burst_bytes: int = 64,
                       is_write: bool = True, qos: int = 0,
                       axid: int = 0,
                       data_fn: Optional[Callable[[int, int], int]] = None,
                       tag: str = "bank_spray") -> List[int]:
        """N bursts across N banks at the same row.

        `bank_stride_bytes` is the address increment that moves to the
        next bank under the controller's address map (default 1 KB is
        typical for 64-bit-bus, 8-bank, no-interleave). With ROW_MAJOR,
        each burst hits a different bank so tFAW + tRRD windows engage.
        """
        length = max(1, burst_bytes // self.bytes_per_beat)
        indices: List[int] = []
        for b in range(num_banks):
            addr = base_addr + b * bank_stride_bytes
            if is_write:
                data = self._gen_data(length, base_addr, b, data_fn)
                indices.append(self.add_write(addr, data, axid=axid, qos=qos,
                                              tag=tag))
            else:
                indices.append(self.add_read(addr, length, axid=axid, qos=qos,
                                             tag=tag))
        self.stats["bank_spray_bursts"] += len(indices)
        return indices

    def add_row_miss_pair(self, base_addr: int, *,
                          row_stride_bytes: int = 0x2000,
                          burst_bytes: int = 64,
                          is_write_first: bool = True,
                          is_write_second: bool = True,
                          qos: int = 0, axid: int = 0,
                          data_fn: Optional[Callable[[int, int], int]] = None,
                          tag: str = "row_miss") -> Tuple[int, int]:
        """Back-to-back bursts to the same bank but different rows.

        Forces PRE → ACT between them, so the scheduler must drain the
        first column command before issuing the second's ACT.
        """
        length = max(1, burst_bytes // self.bytes_per_beat)
        addr0 = base_addr
        addr1 = base_addr + row_stride_bytes
        if is_write_first:
            i0 = self.add_write(addr0, self._gen_data(length, addr0, 0, data_fn),
                                axid=axid, qos=qos, tag=tag)
        else:
            i0 = self.add_read(addr0, length, axid=axid, qos=qos, tag=tag)
        if is_write_second:
            i1 = self.add_write(addr1, self._gen_data(length, addr1, 1, data_fn),
                                axid=axid, qos=qos, tag=tag)
        else:
            i1 = self.add_read(addr1, length, axid=axid, qos=qos, tag=tag)
        self.stats["row_miss_pairs"] += 1
        return (i0, i1)

    # ---- Random workload generator ----------------------------------------

    def add_random_workload(self, count: int, *,
                            addr_range: Tuple[int, int] = (0, 0x10000),
                            write_ratio: float = 0.6,
                            size_weights: Optional[Dict[int, float]] = None,
                            qos_choices: Optional[Sequence[int]] = None,
                            id_choices: Optional[Sequence[int]] = None,
                            align_to: Optional[int] = None,
                            data_fn: Optional[Callable[[int, int], int]] = None,
                            tag: str = "random") -> List[int]:
        """Append `count` random bursts under the given distribution.

        Defaults match the documented controller workload mix:
          - W:R = 60/40
          - sizes 128B/256B/512B/1024B at 20/20/40/20

        `size_weights` is `{burst_bytes: weight}`. `align_to` defaults
        to the largest size key so every burst starts aligned to its
        own length (matches typical AXI4 master behavior).
        """
        if size_weights is None:
            size_weights = {128: 0.2, 256: 0.2, 512: 0.4, 1024: 0.2}
        if qos_choices is None:
            qos_choices = [0]
        if id_choices is None:
            id_choices = [0]
        sizes = list(size_weights.keys())
        weights = [size_weights[s] for s in sizes]
        if align_to is None:
            align_to = max(sizes)

        rng = self._rng
        indices: List[int] = []
        for _ in range(count):
            burst_bytes = rng.choices(sizes, weights=weights, k=1)[0]
            length = max(1, burst_bytes // self.bytes_per_beat)
            # Pick an address that is (a) aligned, (b) within
            # [lo, hi - burst_bytes], and (c) does NOT cross a 4KB AXI boundary.
            # Aligning each burst to at least its own (power-of-two) size keeps it
            # inside one size block; for sizes <= 4096 that is inside one 4KB page.
            # Align the low bound UP and the high bound DOWN so masking a raw pick
            # can never underflow lo.
            lo, hi = addr_range
            eff_align = max(align_to, burst_bytes)
            aligned_lo = (lo + eff_align - 1) & ~(eff_align - 1)
            usable_hi = (hi - burst_bytes) & ~(eff_align - 1)
            if usable_hi < aligned_lo:
                raise ValueError(
                    f"addr_range {addr_range} too narrow for {burst_bytes}B "
                    f"aligned to {eff_align}")
            n_slots = (usable_hi - aligned_lo) // eff_align
            addr = aligned_lo + eff_align * rng.randrange(0, n_slots + 1)
            is_write = (rng.random() < write_ratio)
            qos = rng.choice(qos_choices)
            axid = rng.choice(id_choices)
            if is_write:
                data = self._gen_data(length, addr, 0, data_fn)
                indices.append(self.add_write(addr, data, axid=axid, qos=qos,
                                              tag=tag))
            else:
                indices.append(self.add_read(addr, length, axid=axid, qos=qos,
                                             tag=tag))
        self.stats["random_bursts"] += len(indices)
        return indices

    # ---- Sequence-level helpers -------------------------------------------

    def reset(self) -> None:
        self.bursts.clear()
        for k in self.stats:
            self.stats[k] = 0

    def _recompute_stats(self) -> None:
        """Rebuild stats from the current burst list (used after filter())."""
        for k in self.stats:
            self.stats[k] = 0
        for b in self.bursts:
            self.stats["writes" if b.is_write else "reads"] += 1
        # category counters are best-effort by the default helper tags
        self.stats["row_hit_bursts"] = sum(b.tag == "row_hit" for b in self.bursts)
        self.stats["bank_spray_bursts"] = sum(b.tag == "bank_spray" for b in self.bursts)
        self.stats["random_bursts"] = sum(b.tag == "random" for b in self.bursts)
        self.stats["row_miss_pairs"] = sum(b.tag == "row_miss" for b in self.bursts) // 2

    def filter(self, predicate: Callable[[AXI4Burst], bool]) -> "AXI4Sequence":
        """Return a new sequence with bursts matching `predicate`.

        Use case: exclude a buggy tag while a bug is being fixed.
        Example:
          seq2 = seq.filter(lambda b: b.tag != "row_miss")
        """
        out = AXI4Sequence(self.name + "_filtered",
                          data_width=self.data_width,
                          id_width=self.id_width,
                          addr_width=self.addr_width)
        out.bursts = [b for b in self.bursts if predicate(b)]
        out._recompute_stats()
        return out

    def shuffle(self) -> "AXI4Sequence":
        """In-place RNG shuffle of bursts (preserves seed reproducibility).

        Returns ``self`` so it can be chained (e.g. ``seq.shuffle()``).
        """
        self._rng.shuffle(self.bursts)
        return self

    def __len__(self) -> int:
        return len(self.bursts)

    def __iter__(self):
        return iter(self.bursts)

    def __repr__(self) -> str:
        return (f"AXI4Sequence({self.name!r}, n={len(self.bursts)}, "
                f"writes={self.stats['writes']}, reads={self.stats['reads']})")

    # ---- Internal ---------------------------------------------------------

    def _size_for_bus(self) -> int:
        # log2(bytes_per_beat). 64-bit → 8B → size=3.
        n = self.bytes_per_beat
        out = 0
        while (1 << out) < n:
            out += 1
        return out

    def _gen_data(self, length: int, base: int, seq_idx: int,
                  data_fn: Optional[Callable[[int, int], int]]) -> List[int]:
        if data_fn is not None:
            return [data_fn(base, seq_idx * length + i) for i in range(length)]
        # Default: address-derived pattern so writes are self-describing
        # when the address map echoes back through a memory model.
        mask = (1 << self.data_width) - 1
        return [((base + i * self.bytes_per_beat) ^ (seq_idx << 16)) & mask
                for i in range(length)]


# =============================================================================
# Runner
# =============================================================================

async def run_axi4_sequence(seq: AXI4Sequence, *, master_wr=None,
                            master_rd=None, log=None,
                            on_burst=None,
                            raise_on_error: bool = False) -> List[Dict]:
    """Execute every burst in `seq` against the provided masters.

    Returns one result dict per burst: `{is_write, addr, length, axid,
    qos, tag, data, error}`. For writes, `data` is the data written;
    for reads, it is the data read back.

    `on_burst(idx, burst, result)` is an optional callback after each
    burst — handy for memory-model bookkeeping.

    Raises if a write burst arrives while `master_wr` is None, or
    a read burst arrives while `master_rd` is None.

    If `raise_on_error=True`, any burst that raised (e.g. read
    TimeoutError, write BFM failure) will be re-raised as a
    RuntimeError with the sequence's per-burst error strings after
    the sequence completes. Recommended for tests that would
    otherwise silently discard `result["error"]` by reading only
    `result["data"]` — that pattern buries real BFM errors behind
    downstream NoneType-shaped exceptions (see the #31
    patho_bl256_n1 diagnosis for a worked example).
    """
    from cocotb.triggers import RisingEdge

    results: List[Dict] = []
    clock = (master_wr.clock if master_wr is not None
             else master_rd.clock if master_rd is not None
             else None)

    for idx, burst in enumerate(seq.bursts):
        # Fail fast on configuration errors (no master wired for this direction)
        # — these are programmer errors, not per-burst DUT failures, so they must
        # propagate rather than be swallowed into result["error"].
        if burst.is_write and master_wr is None:
            raise RuntimeError(
                f"sequence {seq.name!r} has write at idx {idx} but "
                f"no master_wr provided")
        if not burst.is_write and master_rd is None:
            raise RuntimeError(
                f"sequence {seq.name!r} has read at idx {idx} but "
                f"no master_rd provided")

        if burst.delay_cycles and clock is not None:
            for _ in range(burst.delay_cycles):
                await RisingEdge(clock)

        result: Dict = {
            "is_write": burst.is_write,
            "addr": burst.addr,
            "length": burst.length,
            "axid": burst.axid,
            "qos": burst.qos,
            "tag": burst.tag,
            "data": None,
            "error": None,
        }
        try:
            if burst.is_write:
                wr = await master_wr.write_transaction(
                    burst.addr, burst.data, burst_len=burst.length,
                    id=burst.axid, qos=burst.qos, size=burst.size,
                    burst_type=burst.burst_type, strb=burst.strb,
                )
                # write_transaction reports failure via a result dict (it does
                # NOT raise); surface it so the runner records the error too,
                # symmetric with read_transaction (which does raise).
                if isinstance(wr, dict) and wr.get("success") is False:
                    raise RuntimeError(
                        f"write_transaction failed: {wr.get('error', 'unknown')}")
                result["data"] = list(burst.data)
            else:
                data = await master_rd.read_transaction(
                    burst.addr, burst_len=burst.length,
                    id=burst.axid, qos=burst.qos, size=burst.size,
                    burst_type=burst.burst_type,
                )
                result["data"] = data
        except Exception as e:
            result["error"] = repr(e)
            if log is not None:
                log.error("burst %d (%s) failed: %s",
                          idx, burst.tag, repr(e))

        results.append(result)
        if on_burst is not None:
            # accept both sync and async callbacks
            maybe = on_burst(idx, burst, result)
            if maybe is not None and hasattr(maybe, "__await__"):
                await maybe

    if log is not None:
        n_err = sum(1 for r in results if r["error"])
        log.info("AXI4Sequence %r: %d bursts (%d errors)",
                 seq.name, len(results), n_err)

    if raise_on_error:
        errs = [(i, r["error"]) for i, r in enumerate(results)
                if r["error"] is not None]
        if errs:
            raise RuntimeError(
                f"AXI4Sequence {seq.name!r}: {len(errs)}/{len(results)} "
                f"burst(s) errored: {errs}"
            )

    return results


# ---------------------------------------------------------------------------
# Engine-style runner — bypasses write_transaction / read_transaction's
# per-burst lock + response-wait. Queues every AW back-to-back at the
# aw_channel level, every W beat at the w_channel level, and collects B
# / R responses asynchronously. Mirrors the bus behavior of
# axi4_master_wr_pattern_gen / axi4_master_rd_crc_check RTL engines:
# one AW per cycle, W beats streaming on a parallel channel,
# responses collected from the per-id callback queues.
# ---------------------------------------------------------------------------


async def run_axi4_sequence_engine(
    seq: AXI4Sequence, *, master_wr=None, master_rd=None, log=None,
    timeout_cycles: int = 1_000_000,
    raise_on_error: bool = False,
) -> List[Dict]:
    """Engine-style runner. Same return contract as ``run_axi4_sequence``.

    Use this when the test must reproduce engine RTL traffic exactly
    (e.g. NexysA7 kb4 / kb32 patterns). The default
    ``run_axi4_sequence`` walks bursts sequentially via
    ``write_transaction`` / ``read_transaction``, which acquires a
    per-instance AW+W lock and awaits the B response before the next
    burst — so consecutive AWs are separated by ~5-15 cycles. The
    engine RTL drives one AW per cycle regardless of W/B state. This
    runner drops the lock + response-wait and queues directly via
    ``aw_channel._driver_send`` (queue-and-go primitive that the
    GAXIMaster transmit pipeline drains back-to-back).

    Writes: all AW packets queued in order, all W beats queued, B
    responses awaited at the end.

    Reads: all AR packets queued in order, R beats per-id collected
    at the end.

    Reads and writes can coexist in one sequence (engine-style is
    write-first-then-read by default).
    """
    from cocotb.triggers import RisingEdge

    clock = (master_wr.clock if master_wr is not None
             else master_rd.clock if master_rd is not None
             else None)

    # Pre-build result skeleton in burst order so callers can index back.
    results: List[Dict] = []
    for burst in seq.bursts:
        results.append({
            "is_write": burst.is_write, "addr": burst.addr,
            "length": burst.length, "axid": burst.axid, "qos": burst.qos,
            "tag": burst.tag, "data": None, "error": None,
        })

    writes = [(i, b) for i, b in enumerate(seq.bursts) if b.is_write]
    reads  = [(i, b) for i, b in enumerate(seq.bursts) if not b.is_write]

    if writes and master_wr is None:
        raise RuntimeError(
            f"sequence {seq.name!r} has writes but master_wr is None")
    if reads and master_rd is None:
        raise RuntimeError(
            f"sequence {seq.name!r} has reads but master_rd is None")

    # --- WRITE PHASE ---
    if writes:
        # Build all AW + W packets up front.
        aw_to_send = []
        ws_to_send = []
        for idx, burst in writes:
            aw_pkt = master_wr.aw_channel.create_packet(
                addr=burst.addr,
                len=burst.length - 1,
                id=burst.axid,
                size=burst.size,
                burst=burst.burst_type,
                qos=burst.qos,
            )
            aw_to_send.append((idx, burst, aw_pkt))
            for k, d in enumerate(burst.data or []):
                w_pkt = master_wr.w_channel.create_packet(
                    data=d,
                    last=1 if k == burst.length - 1 else 0,
                    strb=burst.strb,
                )
                ws_to_send.append(w_pkt)

        # Queue every AW back-to-back. _driver_send is the underlying
        # queue-and-go (appends to transmit_queue, starts the pipeline if
        # not running, returns immediately). The pipeline drains as the
        # downstream's awready allows — one AW per cycle when ready.
        for _, _, aw in aw_to_send:
            await master_wr.aw_channel._driver_send(aw)
        # Same for W beats.
        for w in ws_to_send:
            await master_wr.w_channel._driver_send(w)

        # Wait for AW + W queues to fully drain.
        cycles_waited = 0
        while (master_wr.aw_channel.transmit_coroutine is not None or
               master_wr.w_channel.transmit_coroutine is not None):
            await RisingEdge(clock)
            cycles_waited += 1
            if cycles_waited > timeout_cycles:
                raise TimeoutError(
                    f"engine-style WR drain: AW/W queues not empty "
                    f"after {timeout_cycles} cycles")

        # Wait for all B responses (one per write burst, keyed by id).
        from collections import Counter
        expected_b_per_id = Counter(b.axid for _, b in writes)
        cycles_waited = 0
        while True:
            done = all(
                len(master_wr._response_by_id.get(axid, ())) >= expected
                for axid, expected in expected_b_per_id.items()
            )
            if done:
                break
            await RisingEdge(clock)
            cycles_waited += 1
            if cycles_waited > timeout_cycles:
                missing = {
                    axid: expected - len(master_wr._response_by_id.get(axid, ()))
                    for axid, expected in expected_b_per_id.items()
                    if len(master_wr._response_by_id.get(axid, ())) < expected
                }
                raise TimeoutError(
                    f"engine-style WR B-wait: {missing} short after "
                    f"{timeout_cycles} cycles")

        # Drain B responses + populate results
        for idx, burst in writes:
            b_pkt = master_wr._response_by_id[burst.axid].popleft()
            results[idx]["data"] = list(burst.data or [])
            if hasattr(b_pkt, "resp") and b_pkt.resp != 0:
                results[idx]["error"] = f"BRESP={b_pkt.resp}"

    # --- READ PHASE ---
    if reads:
        ar_to_send = []
        for idx, burst in reads:
            ar_pkt = master_rd.ar_channel.create_packet(
                addr=burst.addr,
                len=burst.length - 1,
                id=burst.axid,
                size=burst.size,
                burst=burst.burst_type,
                qos=burst.qos,
            )
            ar_to_send.append((idx, burst, ar_pkt))

        for _, _, ar in ar_to_send:
            await master_rd.ar_channel._driver_send(ar)

        cycles_waited = 0
        while master_rd.ar_channel.transmit_coroutine is not None:
            await RisingEdge(clock)
            cycles_waited += 1
            if cycles_waited > timeout_cycles:
                raise TimeoutError(
                    f"engine-style RD drain: AR queue not empty after "
                    f"{timeout_cycles} cycles")

        # Wait for all R beats (per AR's length, keyed by id).
        # AXI4 guarantees same-id R beats arrive in AR-issue order.
        from collections import defaultdict
        expected_r_per_id: Dict[int, int] = defaultdict(int)
        for _, burst in reads:
            expected_r_per_id[burst.axid] += burst.length

        cycles_waited = 0
        while True:
            done = all(
                len(master_rd._response_by_id.get(axid, ())) >= expected
                for axid, expected in expected_r_per_id.items()
            )
            if done:
                break
            await RisingEdge(clock)
            cycles_waited += 1
            if cycles_waited > timeout_cycles:
                missing = {
                    axid: expected - len(master_rd._response_by_id.get(axid, ()))
                    for axid, expected in expected_r_per_id.items()
                    if len(master_rd._response_by_id.get(axid, ())) < expected
                }
                raise TimeoutError(
                    f"engine-style RD R-wait: {missing} beats short "
                    f"after {timeout_cycles} cycles")

        # Pop beats per AR (same-id in-order), populate results.
        for idx, burst, _ in ar_to_send:
            id_queue = master_rd._response_by_id[burst.axid]
            beats = []
            for _ in range(burst.length):
                r_pkt = id_queue.popleft()
                beats.append(getattr(r_pkt, "data", 0))
                if hasattr(r_pkt, "resp") and r_pkt.resp != 0:
                    results[idx]["error"] = f"RRESP={r_pkt.resp}"
            results[idx]["data"] = beats

    if log is not None:
        n_err = sum(1 for r in results if r["error"])
        log.info("AXI4Sequence (engine) %r: %d bursts (%d errors)",
                 seq.name, len(results), n_err)

    if raise_on_error:
        errs = [(i, r["error"]) for i, r in enumerate(results)
                if r["error"] is not None]
        if errs:
            raise RuntimeError(
                f"AXI4Sequence (engine) {seq.name!r}: "
                f"{len(errs)}/{len(results)} burst(s) errored: {errs}"
            )

    return results
