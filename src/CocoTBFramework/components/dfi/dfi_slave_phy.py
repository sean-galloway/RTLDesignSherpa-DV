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
from .behaviors.events import (
    CAParityEvent,
    CRCEvent,
    DisconnectEvent,
    ErrorEvent,
    FreqChangeEvent,
    TakeoverEvent,
    TrainingEvent,
    UpdateEvent,
)
from .dfi_base import DFIBase
from .dfi_monitor import (
    _CA_PARITY_SIGNALS,
    _CMD_DECODE,
    _COMMAND_SIGNALS,
    _CRC_SIGNALS,
    _DISCONNECT_SIGNALS,
    _ERROR_SIGNALS,
    _FREQ_CHANGE_SIGNALS,
    _PHY_MASTER_SIGNALS,
    _READ_DATA_SIGNALS,
    _TRAINING_SIGNALS,
    _UPDATE_SIGNALS,
    _WRITE_DATA_SIGNALS,
    _v,
)
from .dfi_packet import DRAMCommand


def decode_phase0_cmd(ras_n_bus: int, cas_n_bus: int,
                      we_n_bus: int) -> DRAMCommand:
    """Decode a single command from the DFI command bus's phase 0.

    The DDR2/DDR3 DFI bus carries ``{phase_{N-1}, …, phase_0}`` bit-
    packed when ``DFI_RATE>1``. The controller's MC drives the command
    on phase 0 and holds the upper phases as NOP for typical single-
    cmd-per-cycle traffic. ``_CMD_DECODE`` keys are single-bit
    ``(ras_n, cas_n, we_n)``, so mask each bus value to its LSB before
    lookup. Falls through to NOP for unknown encodings.

    Pulled out as a pure function so it can be unit-tested without a
    live cocotb bus. Regression guard for G-01a — the original BFM
    read ``cs_n / ras_n / cas_n / we_n`` as full integers and
    silently dropped every command on a multi-phase bus.
    """
    return _CMD_DECODE.get((ras_n_bus & 1, cas_n_bus & 1, we_n_bus & 1),
                           DRAMCommand.NOP)


def slice_phase_wrdata(full_wrdata: int, full_mask: int,
                       wrdata_en_bits: int,
                       beat_bytes: int) -> list:
    """Walk a packed ``wrdata`` / ``wrdata_mask`` bus phase-by-phase.

    Returns a list of ``(phase_idx, data, mask)`` tuples — one entry
    per asserted ``wrdata_en`` bit (LSB→MSB). For ``DFI_RATE=1`` this
    collapses to a single-entry list. Regression guard for G-01a's
    write-side counterpart — the original BFM read the full DFI-rate-
    wide ``wrdata`` as one beat and tried to fit it into ``beat_bytes``,
    throwing OverflowError once command decode started working.
    """
    if wrdata_en_bits == 0:
        return []
    beat_bits = beat_bytes * 8
    data_mask = (1 << beat_bits) - 1
    mask_mask = (1 << beat_bytes) - 1
    out = []
    for phase in range(wrdata_en_bits.bit_length()):
        if (wrdata_en_bits >> phase) & 1 == 0:
            continue
        data = (full_wrdata >> (phase * beat_bits)) & data_mask
        mask = (full_mask >> (phase * beat_bytes)) & mask_mask
        out.append((phase, data, mask))
    return out


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

    _signals = (
        list(_COMMAND_SIGNALS)
        + list(_WRITE_DATA_SIGNALS)
        + list(_READ_DATA_SIGNALS)
        + list(_ERROR_SIGNALS)
        + list(_CRC_SIGNALS)
        + list(_UPDATE_SIGNALS)
        + list(_TRAINING_SIGNALS)
        + list(_CA_PARITY_SIGNALS)
        + list(_FREQ_CHANGE_SIGNALS)
        + list(_DISCONNECT_SIGNALS)
        + list(_PHY_MASTER_SIGNALS)
    )
    _optional_signals: list = []

    def __init__(
        self,
        entity,
        clock,
        base: DFIBase,
        memory: MemoryModel,
        side: str = "phy",
        title: Optional[str] = None,
        strict_write_timing: bool = False,
        write_latency: int = 0,
        strict_read_timing: bool = False,
        read_latency: int = 0,
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

        # Strict write-timing mode (opt-in). The default BFM is lenient: it
        # FIFO-commits each write beat on ANY wrdata_en cycle, so a controller
        # that presents wrdata late still "writes" — hiding real DFI write-
        # timing bugs (the a7ddrphy requires wrdata CONCURRENT with the WR
        # command per write_latency; late data is dropped by real DRAM). In
        # strict mode we instead SAMPLE dfi_wrdata off the wire at exactly
        # command_cycle + write_latency (+ beat offset) — like real DRAM
        # latching its DQ window — regardless of wrdata_en. A controller whose
        # wrdata is late samples zeros/garbage there -> read-back mismatch,
        # faithfully reproducing on-silicon behavior.
        self._strict_write_timing = bool(strict_write_timing)
        self._write_latency = int(write_latency)
        self._write_captures: Deque[_PendingOp] = deque()

        # Strict read-timing mode (opt-in). Default BFM self-times reads off CL
        # and IGNORES dfi_rddata_en. Real DRAM/PHY returns rddata + rddata_valid
        # exactly read_latency sys-cycles after the controller asserts
        # dfi_rddata_en. In strict mode we queue each RD command's address and,
        # on each rddata_en cycle, schedule the corresponding DFI_RATE beats to
        # return read_latency cycles later. A controller that mis-cadences or
        # mis-times rddata_en gets misaligned/absent read data -> mismatch,
        # faithfully exercising the read gate the lenient BFM cannot see.
        self._strict_read_timing = bool(strict_read_timing)
        self._read_latency = int(read_latency)
        self._strict_rd_addr: Deque[int] = deque()   # addrs awaiting rddata_en

        # Error-interface event queue. Populated by the per-version
        # behavior class when bus.error indicates a PHY-driven error.
        self.error_events: Deque[ErrorEvent] = deque()

        # CRC-area event queue. Populated by behavior.crc() when
        # bus.crc_alert asserts (v3.0+ DDR4 path).
        self.crc_events: Deque[CRCEvent] = deque()

        # Update-interface event queue. Populated by
        # behavior.update_request() when MC- or PHY-initiated requests
        # appear on the wire.
        self.update_events: Deque[UpdateEvent] = deque()

        # Training event queue. Populated by behavior.training_step()
        # when bus.training_active is asserted.
        self.training_events: Deque[TrainingEvent] = deque()

        # CA parity event queue. Populated by behavior.ca_parity_check()
        # when bus.parity_check is asserted (DDR4 only).
        self.ca_parity_events: Deque[CAParityEvent] = deque()

        # Frequency-change event queue. Populated by behavior.freq_change()
        # when bus.freq_change_req is asserted.
        self.freq_change_events: Deque[FreqChangeEvent] = deque()

        # Disconnect-protocol event queue (v4.0+).
        self.disconnect_events: Deque[DisconnectEvent] = deque()

        # PHY-Master/Managed takeover event queue (v4.0+).
        self.takeover_events: Deque[TakeoverEvent] = deque()

        # Statistics
        self.cmd_counts = {cmd: 0 for cmd in DRAMCommand}
        self.writes_committed = 0
        self.reads_served = 0

        # Initialize PHY-driven outputs
        self.bus.rddata.value = 0
        self.bus.rddata_valid.value = 0
        self.bus.error.value = 0
        self.bus.error_info.value = 0
        self.bus.crc_alert.value = 0
        # PHY-driven update-interface signals
        self.bus.ctrlupd_ack.value = 0
        self.bus.phyupd_req.value = 0
        # PHY-driven training-interface signals
        self.bus.training_active.value = 0
        self.bus.training_phase.value = 0
        # PHY-driven CA parity check
        self.bus.parity_check.value = 0
        # PHY-driven freq-change ack
        self.bus.freq_change_ack.value = 0
        # PHY-driven disconnect / phymstr requests
        self.bus.disconnect_req.value = 0
        self.bus.phymstr_req.value = 0

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

    def _is_lpddr2_family(self) -> bool:
        from .dfi_signals import MemoryType
        return self.base.memory_type in (
            MemoryType.LPDDR2, MemoryType.LPDDR3,
        )

    def _active_phase(self) -> int:
        """DFI sub-phase carrying the issued command — the phase whose cs_n bit
        is asserted (active-low). Models a PHY that accepts the R/W command on
        whichever phase the MC placed it (its rdphase/wrphase), rather than a
        fixed phase-0. Falls back to phase 0 when nothing/ambiguous is selected,
        so legacy phase-0 traffic and DFI_RATE=1 buses are unaffected. This is
        what lets the oracle follow pumice's DFI_PHASE.rd_phase=1 placement."""
        dfi_rate = self._infer_dfi_rate()
        if dfi_rate <= 1:
            return 0
        cs = _v(self.bus.cs_n)   # 1 cs_n bit per phase for NUM_RANKS=1
        for p in range(dfi_rate):
            if ((cs >> p) & 1) == 0:
                return p
        return 0

    def _decode_command(self) -> DRAMCommand:
        if self._is_lpddr2_family():
            # LPDDR2/3 carry the command on the dfi_address CA bus;
            # ras_n/cas_n/we_n are held idle and useless for decode.
            from .lpddr_ca import decode_lpddr2_ca
            addr = _v(self.bus.address)
            cmd, _args = decode_lpddr2_ca(addr)
            # Stash the decoded args so _handle_command can use them
            # without re-decoding the address.
            self._lpddr_args = _args
            return cmd
        # Decode ras/cas/we from the phase that actually carries the command
        # (rdphase/wrphase-aware). One control bit per phase (DFI_CTRL_WIDTH=1).
        p = self._active_phase()
        return decode_phase0_cmd(
            (_v(self.bus.ras_n) >> p) & 1,
            (_v(self.bus.cas_n) >> p) & 1,
            (_v(self.bus.we_n)  >> p) & 1)

    def _handle_command(self, cmd: DRAMCommand) -> None:
        if self._is_lpddr2_family():
            # Pull bank/row/col/etc. from the decoded CA args, not the
            # raw bus fields (which are held idle for LPDDR2/3).
            args = getattr(self, "_lpddr_args", {}) or {}
            bank = args.get("bank", 0)
            if cmd == DRAMCommand.ACT:
                addr = args.get("row", 0)
            else:
                addr = args.get("col", 0)
                if args.get("auto_precharge"):
                    addr |= (1 << 10)
                if args.get("all_banks"):
                    addr |= (1 << 10)
        else:
            # Pull bank/addr from the phase that carries the command, matching
            # _decode_command's rdphase/wrphase-aware phase select. For phase 0
            # this is identical to the old full-bus read (upper phases NOP=0).
            p = self._active_phase()
            dfi_rate = self._infer_dfi_rate()
            aw = max(1, len(self.bus.address) // dfi_rate)
            bw = max(1, len(self.bus.bank) // dfi_rate)
            bank = (_v(self.bus.bank)    >> (p * bw)) & ((1 << bw) - 1)
            addr = (_v(self.bus.address) >> (p * aw)) & ((1 << aw) - 1)
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
            # With DFI_RATE > 1 the MC packs DFI_RATE DRAM beats per DFI
            # cycle, so beats in the same group share a due_cycle. Use
            # the rddata bus width to derive DFI_RATE without a new ctor
            # parameter.
            dfi_rate = self._infer_dfi_rate()
            for k in range(beats):
                col_k = base_col + k
                if col_k >= self.mapping.num_cols:
                    break  # don't wrap past the row end for now
                flat = self.mapping.tuple_to_flat(0, bank, open_row, col_k)
                if self._strict_read_timing:
                    # Defer scheduling until the controller asserts rddata_en;
                    # the return is timed off THAT (command_cycle + cl is the
                    # lenient self-timed model that ignores the read gate).
                    self._strict_rd_addr.append(flat)
                else:
                    self._pending_reads.append(
                        _PendingOp(due_cycle=cycle + cl + (k // dfi_rate),
                                   flat_addr=flat)
                    )
            if addr & (1 << 10):
                self._pending_auto_pre(bank)
        elif cmd == DRAMCommand.WR:
            self.dram.on_write(bank_idx=bank)
            base_col = addr & self._col_mask
            open_row = self.dram.banks[bank].row or 0
            dfi_rate = self._infer_dfi_rate()
            for k in range(beats):
                col_k = base_col + k
                if col_k >= self.mapping.num_cols:
                    break
                flat = self.mapping.tuple_to_flat(0, bank, open_row, col_k)
                if self._strict_write_timing:
                    # Real DRAM samples its DQ window at a fixed offset from the
                    # WR command (DFI write_latency), NOT whenever wrdata_en
                    # happens to fire. Schedule the capture cycle-exactly.
                    self._write_captures.append(
                        _PendingOp(due_cycle=cycle + self._write_latency
                                   + (k // dfi_rate), flat_addr=flat)
                    )
                else:
                    self._pending_writes.append(
                        _PendingOp(due_cycle=cycle + cwl + (k // dfi_rate),
                                   flat_addr=flat)
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
        """Auto-precharge: close the bank so a subsequent ACT to the same
        bank (different row) succeeds.

        Correct JEDEC semantics would defer the precharge until BL/2 cycles
        after the last data beat (WRITE) or CL cycles after the read data
        (READ). Since `_handle_command` captures `flat_addr` at CMD-time
        from the current `.row`, and `_pending_writes` / `_pending_reads`
        carry those flats forward independently of subsequent bank state,
        firing the precharge here (immediately after the command) is
        functionally equivalent: pending ops resolve against the row
        that was open at CMD-time, and the bank is now free to accept a
        fresh ACT — which is exactly what the controller expects from
        WRA / RDA.

        Prior behavior: this was a debug-log-only stub. Every same-bank
        different-row sequence stayed pinned on the first ACT'd row —
        the whole D-2 pathological pattern matrix tripped on this
        (RTLDesignSherpa#33).
        """
        self.dram.on_precharge(bank_idx=bank)
        self.log.debug(
            f"{self.title}: auto-precharge applied for bank {bank}"
        )

    # ----- Pending operation servicing -----

    def _serve_writes(self) -> None:
        """Commit one pending write per ``wrdata_en`` cycle (FIFO match).

        DFI semantics: the MC asserts ``wrdata_en`` for one cycle per
        wrdata beat it places on the bus. The slave latches each beat
        into the oldest pending write in FIFO order. The ``due_cycle``
        on each pending op is a *no-earlier-than* hint (CWL window),
        not a strict deadline — real MCs delay wrdata by CWL, while
        debug-path injectors (e.g. LiteDRAM's DFII) emit wrdata on the
        same cycle as the WR command. Both forms are valid; the slave
        accepts whichever arrives first.
        """
        beat_bytes = self.bytes_per_beat
        slices = slice_phase_wrdata(
            full_wrdata=_v(self.bus.wrdata),
            full_mask=_v(self.bus.wrdata_mask),
            wrdata_en_bits=_v(self.bus.wrdata_en),
            beat_bytes=beat_bytes,
        )
        for phase, data, mask in slices:
            if not self._pending_writes:
                self.log.warning(
                    f"{self.title}: wrdata_en asserted on phase {phase} "
                    "but no pending write — stray data beat?"
                )
                return
            cycle = self.dram.cycle
            op = self._pending_writes[0]
            if op.due_cycle > cycle:
                self.log.debug(
                    f"{self.title}: early wrdata at cycle {cycle} for op "
                    f"due {op.due_cycle} — committing immediately "
                    "(debug-injector path)"
                )
            self._pending_writes.popleft()
            ba = self.memory.integer_to_bytearray(data, beat_bytes)
            # DFI mask convention: 1 means *don't* write that byte.
            strobe = (~mask) & ((1 << beat_bytes) - 1)
            self.memory.write(self._byte_addr(op.flat_addr), ba,
                              strobe=strobe)
            self.writes_committed += 1

    def _serve_writes_strict(self) -> None:
        """Faithful write capture: sample dfi_wrdata off the wire at the
        cycle the DFI contract says it must be valid (command_cycle +
        write_latency + beat), regardless of wrdata_en. Beats due the same
        cycle occupy consecutive DFI phases (FIFO order). A controller that
        presents wrdata late samples zeros/masked here -> the target column
        keeps its prior value -> read-back mismatch, exactly as on silicon."""
        if not self._write_captures:
            return
        cycle = self.dram.cycle
        # Drop any stale (missed) captures — the DQ window already passed.
        while (self._write_captures
               and self._write_captures[0].due_cycle < cycle):
            self._write_captures.popleft()
        beat_bytes = self.bytes_per_beat
        beat_bits = beat_bytes * 8
        full_wrdata = _v(self.bus.wrdata)
        full_mask = _v(self.bus.wrdata_mask)
        phase = 0
        while (self._write_captures
               and self._write_captures[0].due_cycle == cycle):
            op = self._write_captures.popleft()
            data = (full_wrdata >> (phase * beat_bits)) & ((1 << beat_bits) - 1)
            mask = (full_mask >> (phase * beat_bytes)) & ((1 << beat_bytes) - 1)
            # DFI mask convention: 1 means *don't* write that byte.
            strobe = (~mask) & ((1 << beat_bytes) - 1)
            ba = self.memory.integer_to_bytearray(data, beat_bytes)
            self.memory.write(self._byte_addr(op.flat_addr), ba, strobe=strobe)
            self.writes_committed += 1
            phase += 1

    def _infer_dfi_rate(self) -> int:
        """Derive DFI_RATE from the rddata bus width. With one DRAM beat
        = bytes_per_beat bytes, the bus carries DFI_RATE such beats."""
        beat_bits = self.bytes_per_beat * 8
        try:
            rddata_total_bits = len(self.bus.rddata)
        except TypeError:
            rddata_total_bits = beat_bits
        return max(1, rddata_total_bits // beat_bits)

    def _serve_reads(self) -> None:
        """Drive rddata + rddata_valid for one cycle when a read is due.

        Packs up to DFI_RATE pending reads into one DFI cycle, mirroring
        how the MC packs wrdata: phase 0 in the low DRAM beat slot,
        phase 1 in the next, ..., with rddata_valid bit `k` set for
        each populated phase. Reads serialize behind any pending writes —
        if a write at the same cycle hasn't committed yet, the read
        holds until the next servicing pass.
        """
        cycle = self.dram.cycle
        # Hold back if a write at <= this cycle is still pending — that
        # write commits first per the user's queue-don't-collide rule.
        if self._pending_writes and self._pending_writes[0].due_cycle <= cycle:
            self.bus.rddata_valid.value = 0
            return

        # Derive DFI_RATE from the actual rddata bus width vs one DRAM
        # beat. The MC expects packed reads when DFI_RATE > 1, so we pop
        # that many pending reads (provided they're all due) per cycle.
        beat_bits = self.bytes_per_beat * 8
        try:
            rddata_total_bits = len(self.bus.rddata)
        except TypeError:
            rddata_total_bits = beat_bits
        dfi_rate = max(1, rddata_total_bits // beat_bits)

        packed_data = 0
        packed_valid = 0
        for phase in range(dfi_rate):
            if not (self._pending_reads
                    and self._pending_reads[0].due_cycle <= cycle):
                break
            op = self._pending_reads.popleft()
            ba = self.memory.read(self._byte_addr(op.flat_addr),
                                  self.bytes_per_beat)
            beat_data = self.memory.bytearray_to_integer(ba)
            packed_data |= (beat_data & ((1 << beat_bits) - 1)) << (phase * beat_bits)
            packed_valid |= (1 << phase)
            self.reads_served += 1

        if packed_valid:
            self.bus.rddata.value = packed_data
            self.bus.rddata_valid.value = packed_valid
        else:
            self.bus.rddata_valid.value = 0

    # ----- Sampling loop -----

    async def _monitor_recv(self):
        while True:
            await FallingEdge(self.clock)

            self.dram.tick()
            self.base.tick()

            # A command is present if the chip is selected on ANY DFI sub-phase
            # (cs_n active-low). The legacy gate only tested phase 0 (& 1), which
            # silently dropped commands the MC places on an upper phase to match
            # the PHY's rdphase/wrphase (e.g. a7ddrphy rdphase=1). Test the full
            # cs_n bus: any 0 bit within the DFI_RATE phases means "selected".
            dfi_rate = self._infer_dfi_rate()
            cs_all = _v(self.bus.cs_n)
            cs_sel_mask = (1 << dfi_rate) - 1   # 1 cs_n bit per phase (1 rank)
            if (cs_all & cs_sel_mask) != cs_sel_mask:
                cmd = self._decode_command()
                if cmd != DRAMCommand.NOP:
                    self._handle_command(cmd)

            # Strict read gate: the controller enables the read capture window
            # via dfi_rddata_en. On each cycle it is asserted, schedule one DFI
            # cycle's worth (DFI_RATE beats) of the queued read to return
            # exactly read_latency cycles later. Mirrors the real PHY, which
            # ignores the address on rddata_en (data is whatever the DRAM drives
            # for the RD command issued earlier — FIFO order here).
            if self._strict_read_timing and (_v(self.bus.rddata_en) != 0):
                cycle = self.dram.cycle
                dfi_rate = self._infer_dfi_rate()
                for _ in range(dfi_rate):
                    if not self._strict_rd_addr:
                        break
                    flat = self._strict_rd_addr.popleft()
                    self._pending_reads.append(
                        _PendingOp(due_cycle=cycle + self._read_latency,
                                   flat_addr=flat))

            # Order matters: commit writes first, then serve reads. The
            # serve_reads helper double-checks so we never produce stale
            # data while a same-cycle write is still in flight.
            if self._strict_write_timing:
                self._serve_writes_strict()
            else:
                self._serve_writes()
            self._serve_reads()

            # Per-version behavior dispatch. The behavior class returns
            # an Event when it sees something noteworthy on its sub-area;
            # we route those to per-area queues. Behavior calls are
            # try/except-wrapped because some areas raise
            # NotSupportedInThisVersionError on pre-introduction versions
            # — silently drop in that case (the version legitimately
            # doesn't define the area).
            self._dispatch_behavior_error()
            self._dispatch_behavior_crc()
            self._dispatch_behavior_update()
            self._dispatch_behavior_training()
            self._dispatch_behavior_ca_parity()
            self._dispatch_behavior_freq_change()
            self._dispatch_behavior_disconnect()
            self._dispatch_behavior_takeover()

    def _dispatch_behavior_error(self) -> None:
        """Call the per-version behavior.error_event() and queue any event."""
        try:
            evt = self.base.behavior.error_event(self.bus, None)
        except NotImplementedError:
            return  # version doesn't define an error interface
        if evt is not None:
            self.error_events.append(evt)

    def _dispatch_behavior_crc(self) -> None:
        """Call the per-version behavior.crc() and queue any event."""
        try:
            evt = self.base.behavior.crc(self.bus, None)
        except NotImplementedError:
            return  # version doesn't define CRC
        if evt is not None:
            self.crc_events.append(evt)

    def _dispatch_behavior_update(self) -> None:
        """Call the per-version behavior.update_request() and queue any event."""
        try:
            evt = self.base.behavior.update_request(self.bus, None)
        except NotImplementedError:
            return
        if evt is not None:
            self.update_events.append(evt)

    def _dispatch_behavior_training(self) -> None:
        """Call the per-version behavior.training_step() and queue any event."""
        try:
            evt = self.base.behavior.training_step(self.bus, None)
        except NotImplementedError:
            return
        if evt is not None:
            self.training_events.append(evt)

    def _dispatch_behavior_ca_parity(self) -> None:
        """Call the per-version behavior.ca_parity_check() and queue any event."""
        try:
            evt = self.base.behavior.ca_parity_check(self.bus, None)
        except NotImplementedError:
            return
        if evt is not None:
            self.ca_parity_events.append(evt)

    def _dispatch_behavior_freq_change(self) -> None:
        """Call the per-version behavior.freq_change() and queue any event."""
        try:
            evt = self.base.behavior.freq_change(self.bus, None)
        except NotImplementedError:
            return
        if evt is not None:
            self.freq_change_events.append(evt)

    def _dispatch_behavior_disconnect(self) -> None:
        """Call the per-version behavior.disconnect_request() and queue any event."""
        try:
            evt = self.base.behavior.disconnect_request(self.bus, None)
        except NotImplementedError:
            return
        if evt is not None:
            self.disconnect_events.append(evt)

    def _dispatch_behavior_takeover(self) -> None:
        """Call the per-version behavior.phy_takeover() and queue any event."""
        try:
            evt = self.base.behavior.phy_takeover(self.bus, None)
        except NotImplementedError:
            return
        if evt is not None:
            self.takeover_events.append(evt)

    # ----- Error-interface drive (PHY → MC) -----

    def set_error(self, active: int, info: int = 0) -> None:
        """Drive the error sub-interface signals.

        Pulse the test sequence: ``slave.set_error(1, code=0x42)`` to
        assert; ``slave.set_error(0)`` to deassert. The on-the-wire
        edge is what the behavior class samples.
        """
        self.bus.error.value = active
        self.bus.error_info.value = info

    def set_crc_alert(self, active: int) -> None:
        """Drive the CRC alert signal (PHY→MC, DDR4).

        Pulse the test sequence: ``slave.set_crc_alert(1)`` to assert;
        ``slave.set_crc_alert(0)`` to deassert.
        """
        self.bus.crc_alert.value = active

    def set_phyupd_req(self, active: int) -> None:
        """Drive the PHY-initiated update request (PHY→MC, v3.0+)."""
        self.bus.phyupd_req.value = active

    def set_ctrlupd_ack(self, active: int) -> None:
        """Drive the PHY's ack of an MC-initiated update."""
        self.bus.ctrlupd_ack.value = active

    def set_training(self, active: int, phase: int = 0) -> None:
        """Drive the training interface (PHY→MC).

        ``phase`` is the encoded TrainingPhase code:
        0=read_lvl, 1=write_lvl, 2=dq, 3=ca, 4=db.
        """
        self.bus.training_active.value = active
        self.bus.training_phase.value = phase

    def set_parity_check(self, active: int) -> None:
        """Drive the PHY's CA parity error indicator (DDR4)."""
        self.bus.parity_check.value = active

    def set_freq_change_ack(self, active: int) -> None:
        """Drive the PHY's frequency-change acknowledgement."""
        self.bus.freq_change_ack.value = active

    def set_disconnect_req(self, active: int) -> None:
        """Drive the PHY disconnect request (v4.0+)."""
        self.bus.disconnect_req.value = active

    def set_phymstr_req(self, active: int) -> None:
        """Drive the PHY Master/Managed takeover request (v4.0+)."""
        self.bus.phymstr_req.value = active

    # ----- Convenience -----

    def __str__(self) -> str:
        return (
            f"{self.title}: writes_committed={self.writes_committed} "
            f"reads_served={self.reads_served} "
            f"error_events={len(self.error_events)} "
            f"crc_events={len(self.crc_events)} "
            f"update_events={len(self.update_events)} "
            f"training_events={len(self.training_events)} "
            f"ca_parity_events={len(self.ca_parity_events)} "
            f"freq_change_events={len(self.freq_change_events)} "
            f"disconnect_events={len(self.disconnect_events)} "
            f"takeover_events={len(self.takeover_events)} "
            f"cmd_counts={ {c.value: n for c, n in self.cmd_counts.items() if n} }"
        )
