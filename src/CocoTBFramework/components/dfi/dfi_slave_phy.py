# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""PHY-side DFI slave BFM (issue #16).

:class:`DFISlavePHY` is the responder side of a DFI link. It:

  - Captures the MC's command stream off the wire (Slave-via-BusMonitor
    pattern, see ``docs/components/components_overview.md``).
  - Maintains a per-bank :class:`DramStateModel` and reports JEDEC
    sequencing/timing violations as the MC drives commands.
  - Auto-commits write data: ``CWL`` cycles after a WR command, it
    captures the ``wrdata`` beat off the wire and writes it through
    ``AddressMapping`` to the numpy-backed :class:`MemoryModel`.
  - Queues read requests so any in-flight write commits first, then
    drives ``rddata`` / ``rddata_valid`` for one cycle when the
    response is due. (User chose queue-don't-collide semantics over
    "fire CL cycles later no matter what" — see project_dfi_address_mapping
    memory note.)

MVP scope: BL=1 conceptually — one DFI beat per WR / RD command. Real
DDR3 is BL8 minimum, but locking the BL=1 case down first proves the
address-decode + memory-binding mechanics. Multi-beat bursts are
Phase 2.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

from cocotb.triggers import FallingEdge
from cocotb_bus.monitors import BusMonitor

from ..shared.memory_model import MemoryModel
from .dfi_base import DFIBase
from .dfi_monitor import _CMD_DECODE, _COMMAND_SIGNALS, _READ_DATA_SIGNALS, _WRITE_DATA_SIGNALS, _v
from .dfi_packet import DRAMCommand


@dataclass
class _PendingOp:
    """One pending memory operation, due at ``due_cycle``."""
    due_cycle: int
    flat_addr: int


class DFISlavePHY(BusMonitor):
    """PHY-side DFI BFM with DRAM state model + memory backing.

    Args:
        entity:   The cocotb DUT handle.
        clock:    The DFI clock signal.
        base:     The :class:`DFIBase` chassis carrying version, memory
                  type, timings, and address mapping.
        memory:   The :class:`MemoryModel` backing this slave.
        side:     Currently only ``"phy"`` (the PHY drives the slave role).
        title:    Optional title for log messages.
    """

    _signals = list(_COMMAND_SIGNALS) + list(_WRITE_DATA_SIGNALS) + list(_READ_DATA_SIGNALS)
    _optional_signals: list = []

    def __init__(
        self,
        entity,
        clock,
        base: DFIBase,
        memory: MemoryModel,
        side: str = "phy",
        title: Optional[str] = None,
        **kwargs,
    ):
        if side != "phy":
            raise ValueError(
                f"DFISlavePHY drives the PHY side only, got side={side!r}"
            )
        self.side = side
        self.title = title or "DFISlavePHY"
        self.base = base
        self.memory = memory
        self.mapping = base.mapping
        # MemoryModel is byte-addressed; one DFI beat is data_width / 8 bytes.
        # The MVP envelope assumes a single beat per command (BL=1 conceptually).
        self.bytes_per_beat = max(1, memory.bytes_per_line)

        # Independent state model — caller's base might be shared with a
        # master and we want the slave's view to be fully self-contained.
        from .dram_state import DramStateModel  # local import to avoid cycle
        self.dram = DramStateModel(
            timings=base.timings,
            num_banks=base.mapping.num_banks,
        )

        BusMonitor.__init__(self, entity, f"{side}_dfi", clock, **kwargs)
        self.clock = clock
        self.log = self.entity._log

        # Pending operation queues. Reads serialize behind writes
        # already in flight — the user wants queue-don't-collide
        # semantics so the slave never produces stale data while a
        # write is still draining.
        self._pending_reads: Deque[_PendingOp] = deque()
        self._pending_writes: Deque[_PendingOp] = deque()

        # Statistics
        self.cmd_counts = {cmd: 0 for cmd in DRAMCommand}
        self.writes_committed = 0
        self.reads_served = 0

        # Initialize PHY-driven outputs
        self.bus.rddata.value = 0
        self.bus.rddata_valid.value = 0

    # ----- Address helpers -----

    @property
    def _col_mask(self) -> int:
        return (1 << self.mapping._widths["col"]) - 1

    def _flat_addr_for(self, bank: int, raw_address: int) -> int:
        """Build a flat column-unit address from bank + WR/RD address."""
        open_row = self.dram.banks[bank].row
        if open_row is None:
            # Will trip a no_act_before_rd/wr violation in DramStateModel;
            # use row=0 just to keep the math defined.
            open_row = 0
        col = raw_address & self._col_mask
        return self.mapping.tuple_to_flat(0, bank, open_row, col)

    def _byte_addr(self, flat: int) -> int:
        return flat * self.bytes_per_beat

    # ----- Command dispatch -----

    def _decode_command(self) -> DRAMCommand:
        ras = _v(self.bus.ras_n)
        cas = _v(self.bus.cas_n)
        we  = _v(self.bus.we_n)
        return _CMD_DECODE.get((ras, cas, we), DRAMCommand.NOP)

    def _handle_command(self, cmd: DRAMCommand) -> None:
        bank = _v(self.bus.bank)
        addr = _v(self.bus.address)
        cycle = self.dram.cycle  # cycle as the dram model sees it
        cwl = self.dram.timings.CWL
        cl  = self.dram.timings.CL

        self.cmd_counts[cmd] = self.cmd_counts.get(cmd, 0) + 1

        beats = self.base.beats_per_burst

        if cmd == DRAMCommand.ACT:
            self.dram.on_activate(bank_idx=bank, row=addr)
        elif cmd == DRAMCommand.RD:
            self.dram.on_read(bank_idx=bank)
            base_col = addr & self._col_mask
            open_row = self.dram.banks[bank].row or 0
            # Queue N consecutive beats at (col, col+1, …, col+N-1).
            # Each beat lands one DFI cycle after the previous.
            for k in range(beats):
                col_k = base_col + k
                if col_k >= self.mapping.num_cols:
                    break  # don't wrap past the row end for now
                flat = self.mapping.tuple_to_flat(0, bank, open_row, col_k)
                self._pending_reads.append(
                    _PendingOp(due_cycle=cycle + cl + k, flat_addr=flat)
                )
            if addr & (1 << 10):
                self._pending_auto_pre(bank)
        elif cmd == DRAMCommand.WR:
            self.dram.on_write(bank_idx=bank)
            base_col = addr & self._col_mask
            open_row = self.dram.banks[bank].row or 0
            for k in range(beats):
                col_k = base_col + k
                if col_k >= self.mapping.num_cols:
                    break
                flat = self.mapping.tuple_to_flat(0, bank, open_row, col_k)
                self._pending_writes.append(
                    _PendingOp(due_cycle=cycle + cwl + k, flat_addr=flat)
                )
            if addr & (1 << 10):
                self._pending_auto_pre(bank)
        elif cmd == DRAMCommand.PRE:
            all_banks = bool(addr & (1 << 10))
            self.dram.on_precharge(bank_idx=bank, all_banks=all_banks)
        elif cmd == DRAMCommand.REF:
            self.dram.on_refresh()
        # MRS / NOP: ignored for MVP (just kept in cmd_counts)

    def _pending_auto_pre(self, bank: int) -> None:
        # MVP: defer the auto-precharge accounting until the BFM grows a
        # proper post-data scheduler. For now log it so it's not silently
        # dropped — full handling lands when multi-beat bursts arrive.
        self.log.debug(f"{self.title}: auto-precharge requested for bank {bank}")

    # ----- Pending operation servicing -----

    def _serve_writes(self) -> None:
        """Commit any pending writes whose CWL has elapsed."""
        cycle = self.dram.cycle
        while self._pending_writes and self._pending_writes[0].due_cycle <= cycle:
            op = self._pending_writes.popleft()
            if _v(self.bus.wrdata_en) == 0:
                self.log.warning(
                    f"{self.title}: pending write at flat=0x{op.flat_addr:x} "
                    f"due cycle {op.due_cycle} but wrdata_en is deasserted — "
                    "did the MC forget the data beat?"
                )
                continue
            data = _v(self.bus.wrdata)
            mask = _v(self.bus.wrdata_mask)
            ba = self.memory.integer_to_bytearray(data, self.bytes_per_beat)
            # Strobe is 1 per byte unmasked. The DFI mask convention is
            # 1=*don't* write the byte, hence invert.
            strobe = (~mask) & ((1 << self.bytes_per_beat) - 1)
            self.memory.write(self._byte_addr(op.flat_addr), ba, strobe=strobe)
            self.writes_committed += 1

    def _serve_reads(self) -> None:
        """Drive rddata + rddata_valid for one cycle when a read is due.

        Reads serialize behind any pending writes — if a write at the
        same cycle hasn't committed yet, the read holds until the next
        servicing pass.
        """
        cycle = self.dram.cycle
        # Hold back if a write at <= this cycle is still pending — that
        # write commits first per the user's queue-don't-collide rule.
        if self._pending_writes and self._pending_writes[0].due_cycle <= cycle:
            self.bus.rddata_valid.value = 0
            return

        if self._pending_reads and self._pending_reads[0].due_cycle <= cycle:
            op = self._pending_reads.popleft()
            ba = self.memory.read(self._byte_addr(op.flat_addr), self.bytes_per_beat)
            self.bus.rddata.value = self.memory.bytearray_to_integer(ba)
            self.bus.rddata_valid.value = 1
            self.reads_served += 1
        else:
            self.bus.rddata_valid.value = 0

    # ----- Sampling loop -----

    async def _monitor_recv(self):
        while True:
            await FallingEdge(self.clock)

            self.dram.tick()
            self.base.tick()

            if _v(self.bus.cs_n) == 0:
                cmd = self._decode_command()
                if cmd != DRAMCommand.NOP:
                    self._handle_command(cmd)

            # Order matters: commit writes first, then serve reads. The
            # serve_reads helper double-checks so we never produce stale
            # data while a same-cycle write is still in flight.
            self._serve_writes()
            self._serve_reads()

    # ----- Convenience -----

    def __str__(self) -> str:
        return (
            f"{self.title}: writes_committed={self.writes_committed} "
            f"reads_served={self.reads_served} "
            f"cmd_counts={ {c.value: n for c, n in self.cmd_counts.items() if n} }"
        )
