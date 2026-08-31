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

Burst scope: ``base.beats_per_burst`` DFI beats are queued per WR / RD
command (BL=1 for the MVP-loopback case; BL8 with the canonical K=2
PHY ratio queues 4 beats). See :class:`~.dfi_base.DFIBase` for how the
beat count is derived from the JEDEC BL.
"""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Deque, Optional

if TYPE_CHECKING:
    from .ca_map import CAMap
    from .dfi_timing import DFITimingProfile

from cocotb.triggers import FallingEdge
from cocotb.utils import get_sim_time
from cocotb_bus.monitors import BusMonitor

from ..shared.memory_model import MemoryModel
from .behaviors.events import (
    CAParityEvent,
    CRCEvent,
    DisconnectEvent,
    ErrorEvent,
    FreqChangeEvent,
    LowPowerEvent,
    TakeoverEvent,
    TrainingEvent,
    UpdateEvent,
)
from .dfi_base import DFIBase
from .dfi_monitor import (
    _AUX_SIGNALS,
    _CMD_DECODE,
    _CORE_SIGNALS,
    _DFIBusAccessMixin,
    _v,
    partition_wired_signals,
)
from .dfi_packet import DRAMCommand

_WR_TRACE = os.environ.get("DFI_WR_TRACE", "0") == "1"
# DFI_CMD_TRACE=1: log every DECODED command with the bank's open row at
# decode time — the command-level view (the wave-decode you'd otherwise do by
# hand). Pairs with DFI_WR_TRACE (data commits).
_CMD_TRACE = os.environ.get("DFI_CMD_TRACE", "0") == "1"


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


def decode_all_phases(cs_n_bus: int, ras_n_bus: int, cas_n_bus: int,
                      we_n_bus: int, dfi_rate: int) -> list:
    """Decode a command at EVERY DFI phase whose cs_n is asserted.

    The real a7ddrphy accepts one DRAM command per phase per DFI cycle — up to
    ``dfi_rate`` commands are launched in a single cycle. This generalizes
    :func:`decode_phase0_cmd` (which only ever looked at phase 0) so the BFM can
    model the multi-command-per-cycle packing the sub-DFI-word BL4 fix issues
    (two BL4 RDs at phases {P, P+2} in ONE cycle -> one fully-packed DFI word).

    Args
    ----
    cs_n_bus/ras_n_bus/cas_n_bus/we_n_bus : the packed DFI control buses,
        ``{phase_{N-1}, …, phase_0}`` bit-packed (one control bit per phase for
        DFI_CTRL_WIDTH=1 / one cs_n bit per phase for NUM_RANKS=1).
    dfi_rate : number of DFI phases (>=1).

    Returns
    -------
    list of ``(phase, DRAMCommand)`` for each phase whose cs_n is asserted
    (active-low) AND decodes to a non-NOP command, in ascending phase order.

    DFI_RATE==1 / phase-0-only traffic collapses to at most a single
    ``[(0, cmd)]`` entry, bit-identical to the legacy ``decode_phase0_cmd``
    path (regression guard for the single-command decode).
    """
    out = []
    rate = max(1, dfi_rate)
    for p in range(rate):
        if ((cs_n_bus >> p) & 1) != 0:
            continue  # phase not selected (cs_n high)
        cmd = decode_phase0_cmd((ras_n_bus >> p) & 1,
                                (cas_n_bus >> p) & 1,
                                (we_n_bus >> p) & 1)
        if cmd != DRAMCommand.NOP:
            out.append((p, cmd))
    return out


def deinterleave_read_window(prev_window: list, bursts: list,
                             words_per_cycle: int, nphases: int,
                             words_per_beat: int) -> list:
    """Build ONE a7ddrphy de-interleave window from the reads issued in a cycle.

    This is the faithful phase-anchored de-interleaver, factored out as a pure
    function so :class:`DFISlavePHY` and its unit test share the SAME logic (no
    duplicated model). It reproduces BOTH the on-board BUG and the FIX purely
    from how many RD commands are in ``bursts``:

      * ONE burst (1 RD/cycle, the BUG): only its rd_phase-anchored slot run is
        written; every other slot HOLDS its previous (stale) value.
      * TWO bursts at phases {P, P+2} (the FIX): both anchored runs are written
        into the same window -> fully packed, zero stale.

    Args
    ----
    prev_window     : the previous cycle's window (device-word list); slots no
                      burst writes this cycle keep their value from here (STALE).
                      Shorter/None is zero-extended.
    bursts          : list of ``(anchor_phase, [device_words])`` — one entry per
                      RD command decoded this DFI cycle, in issue order.
    words_per_cycle : device-word slots one DFI cycle exposes
                      (== nphases * words_per_beat).
    nphases         : PHY phase count / DFI gear.
    words_per_beat  : device words per DFI phase (K).

    Returns
    -------
    The new window (device-word list of length ``words_per_cycle``). Each burst's
    anchored slot run is placed via the shared contract
    :func:`dfi_timing.bl_anchored_slot_mask`, so the RTL assertion mirrors the
    identical geometry.
    """
    from .dfi_timing import bl_anchored_slot_mask
    window = list(prev_window) if prev_window else []
    if len(window) < words_per_cycle:
        window += [0] * (words_per_cycle - len(window))
    else:
        window = window[:words_per_cycle]
    for anchor_phase, burst_words in bursts:
        bl_beats = len(burst_words)
        if bl_beats <= 0:
            continue
        if bl_beats >= words_per_cycle:
            first_slot, burst_slots = 0, words_per_cycle
        else:
            _wpc, first_slot, burst_slots = bl_anchored_slot_mask(
                bl=bl_beats, nphases=nphases,
                words_per_beat=words_per_beat, rd_phase=anchor_phase)
            assert _wpc == words_per_cycle, (
                f"contract words_per_cycle {_wpc} != {words_per_cycle}")
        for i in range(burst_slots):
            window[(first_slot + i) % words_per_cycle] = (
                burst_words[i] if i < len(burst_words) else 0)
    return window


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
    """One pending memory operation, due at ``due_cycle``.

    ``burst_id`` / ``anchor_phase`` are only used by the a7ddrphy BL-anchored
    read model (read_bl_anchored): they group device-words back into their
    originating RD command and record the rd_phase the PHY anchors that burst
    to. ``decode_cycle`` is the DFI cycle the RD command was decoded on — the
    faithful de-interleaver groups ALL reads decoded in the SAME DFI cycle into
    ONE de-interleave window (that is what lets two same-cycle BL4 RDs at phases
    {P, P+2} fully pack one 128b DFI word, zero stale). All default to 0 so
    every other path is unaffected.
    """
    due_cycle: int
    flat_addr: int
    burst_id: int = 0
    anchor_phase: int = 0
    decode_cycle: int = 0


class DFISlavePHY(_DFIBusAccessMixin, BusMonitor):
    """PHY-side DFI BFM with DRAM state model + memory backing.

    Args:
        entity:   The cocotb DUT handle.
        clock:    The DFI clock signal.
        base:     The :class:`DFIBase` chassis carrying version, memory
                  type, timings, and address mapping.
        memory:   The :class:`MemoryModel` backing this slave.
        side:     Currently only ``"phy"`` (the PHY drives the slave role).
        title:    Optional title for log messages.

    Signal binding (issue #69): only the command/write/read core wires
    that ``base``'s (dfi_version, memory_type) pair defines are
    required. Every other wire the BFM knows how to touch is optional —
    idled and acted on when the DUT carries it, skipped when it does
    not, so a DFI v2.1 bus (no dfi_alert_n, no training wires) binds
    cleanly.
    """

    # Class-level defaults; instances refine from base.dfi_version /
    # base.memory_type in __init__.
    _signals = list(_CORE_SIGNALS)
    _optional_signals: list = list(_AUX_SIGNALS)

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
        dfi_phase_bytes: Optional[int] = None,
        timing: "Optional[DFITimingProfile]" = None,
        read_device_word_offset: int = 0,
        violation_policy=None,
        ca_map: "Optional[CAMap]" = None,
        ca_map_col: "Optional[CAMap]" = None,
        ca_width: Optional[int] = None,
        ca_sdr: bool = False,
        log=None,
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
        # Two DISTINCT granularities (decoupled so the model can catch narrow-
        # device column bugs):
        #   device_bytes  = one PHYSICAL DRAM word (x16 => 2). MemoryModel lines
        #                   and DRAM columns are device-word granular.
        #   bytes_per_beat= one DFI PHASE's data slice (== the pumice DRAM beat,
        #                   e.g. 32b => 4). Drives DFI_RATE / rddata_valid width
        #                   and bus packing — MUST match the RTL DFI, so it is the
        #                   phase width, NOT the memory word width.
        # words_per_beat (K) = device words packed into one DFI phase (2 for a
        # x16 device on a 32b beat). Default: dfi_phase_bytes = memory line =>
        # K=1 => bit-identical to the legacy single-granularity behavior.
        self.device_bytes = max(1, memory.bytes_per_line)
        self.bytes_per_beat = max(1, dfi_phase_bytes) if dfi_phase_bytes \
            else self.device_bytes
        self.words_per_beat = max(1, self.bytes_per_beat // self.device_bytes)

        # Independent state model — caller's base might be shared with a
        # master and we want the slave's view to be fully self-contained.
        # ``violation_policy`` lets violation-injection tests demote hard
        # rules to soft so the checker's catches can be counted instead
        # of aborting the simulation.
        from .dram_state import DramStateModel  # local import to avoid cycle
        self.dram = DramStateModel(
            timings=base.timings,
            num_banks=base.mapping.num_banks,
            policy=violation_policy,
        )

        # Per-instance signal partition from the declared version/memory
        # pair — shadows the class attributes before BusMonitor.__init__
        # builds the Bus from them (issue #69).
        self._declared_version = base.dfi_version
        self._declared_memory = base.memory_type
        self._signals, self._optional_signals = partition_wired_signals(
            base.dfi_version, base.memory_type)

        BusMonitor.__init__(self, entity, f"{side}_dfi", clock, **kwargs)
        self._check_required_bound()
        self.clock = clock
        # Default to the entity's logger, but let a testbench inject its
        # own the way the AXI BFMs take `log=`. Without this the slave's
        # output goes to the cocotb entity logger while everything else
        # in the TB goes to TBBase's, so a DFI trace and the transactions
        # that caused it land in two different places.
        self.log = log if log is not None else self.entity._log

        # Pending operation queues. Reads serialize behind writes
        # already in flight — the user wants queue-don't-collide
        # semantics so the slave never produces stale data while a
        # write is still draining.
        self._pending_reads: Deque[_PendingOp] = deque()
        self._pending_writes: Deque[_PendingOp] = deque()

        # Decoded mode-register writes: {mr_index: mr_data}. Populated on each
        # MRW (MRS) command so tests can verify the controller's init sequence
        # programmed the expected registers (esp. LPDDR2 MR63/10/1/2/3).
        self.mode_regs: dict = {}

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
        # Model the a7ddrphy 4-phase read-window offset (issue #32): shift the
        # assembled read device-words by this many device-word slots, zero-filling
        # vacated slots. 0 = ideal/bit-exact (default, no behavior change). Non-zero
        # reproduces the nphases=4-PHY / DFI_RATE=2-controller device-word corruption.
        self._read_dw_offset = int(read_device_word_offset)
        self._strict_rd_addr: Deque[int] = deque()   # addrs awaiting rddata_en

        # ---- Resolve the PHY-agnostic timing profile (the hook surface) -------
        # Precedence: an explicit `timing` profile wins; otherwise synthesize one
        # from the legacy strict_*/latency kwargs so existing callers are
        # unchanged. All downstream scheduling reads ONLY the resolved fields
        # below, so adding a new hook is local to the profile + the one place it
        # is honored.
        from .dfi_timing import (
            READ_REF_COMMAND,
            READ_REF_RDDATA_EN,
            WRITE_REF_COMMAND,
            WRITE_REF_WRDATA_EN,
            DFITimingProfile,
        )
        if timing is None:
            timing = DFITimingProfile(
                name="legacy",
                read_ref=(READ_REF_RDDATA_EN if strict_read_timing
                          else READ_REF_COMMAND),
                read_latency=(int(read_latency) if strict_read_timing else None),
                read_en_gated=False,
                write_ref=(WRITE_REF_COMMAND if strict_write_timing
                           else WRITE_REF_WRDATA_EN),
                write_latency=(int(write_latency) if strict_write_timing else None),
            )
        self._timing = timing
        # Re-derive the internal switches from the profile so both paths agree.
        self._read_ref        = timing.read_ref
        self._read_en_gated   = bool(timing.read_en_gated)
        # Free-running ISERDES model (a7ddrphy-faithful, opt-in). DATA anchored
        # to the command; VALID = rddata_en delayed by read_valid_latency;
        # DQ bus HOLDS its last word. See DFITimingProfile.a7ddrphy_free_running.
        self._read_free_running = bool(getattr(timing, "read_free_running", False))
        # a7ddrphy fixed 8-slot de-interleave for a BL < 2*nphases read: the
        # burst fills only its rd_phase-anchored phases; the other phases hold
        # the PREVIOUS read's beats (stale). See DFITimingProfile.a7ddrphy_bl4.
        self._read_bl_anchored = bool(getattr(timing, "read_bl_anchored", False))
        # Faithful per-64b-beat READ SKEW (a7ddrphy: the two 64b beats of a 128b
        # DFI word return at DIFFERENT capture latencies). read_hi_skew/lo_skew =
        # extra DFI cycles the HIGH/LOW beat lags. Default 0 = OFF (bit-identical,
        # all existing tests unaffected). The controller's PHY_TIMING.deskew_hi/lo
        # must be trained to cancel it. Modelled as a 1-deep hold per beat.
        self._read_hi_skew = int(getattr(timing, "read_hi_skew", 0))
        self._read_lo_skew = int(getattr(timing, "read_lo_skew", 0))
        self._skew_hi_prev = 0
        self._skew_lo_prev = 0
        self._skew_cur = None   # ideal read word produced this cycle (None = idle)
        # Held device-words of the last-served read (the "stale" content the
        # a7ddrphy leaves on the phases a short burst did not drive). Indexed by
        # device-word slot within a full DFI cycle.
        self._rd_stale_words: list = []
        # Monotonic RD-command counter — tags each read burst so the anchored
        # model can group device-words back into their originating burst.
        self._rd_burst_seq = 0
        self._read_valid_latency = (
            int(timing.read_valid_latency)
            if getattr(timing, "read_valid_latency", None) is not None else 0)
        # Command-anchored data pipeline: list of (due_cycle, flat_addr) that
        # will land on the (held) DQ bus at due_cycle. Separate rddata_en->valid
        # strobe pipeline holds the cycles a valid must be driven.
        self._rd_data_pipe: Deque[_PendingOp] = deque()
        self._rd_valid_pipe: Deque[int] = deque()   # cycles to drive valid
        # The current held DQ bus contents (device-word list) — free-running:
        # holds its last value until a newer command-anchored word overwrites it.
        self._dq_hold_words: list = []
        # command-anchored read latency: explicit hook, else JEDEC CL (applied
        # where `cl` is read in the RD-command scheduler).
        self._read_cmd_latency = timing.read_latency   # None => use CL
        self._strict_read_timing = (timing.read_ref == READ_REF_RDDATA_EN)
        if self._strict_read_timing and timing.read_latency is not None:
            self._read_latency = int(timing.read_latency)
        self._write_ref          = timing.write_ref
        self._strict_write_timing = (timing.write_ref == WRITE_REF_COMMAND)
        if self._strict_write_timing and timing.write_latency is not None:
            self._write_latency = int(timing.write_latency)
        self.log.info("DFISlavePHY timing profile '%s': read_ref=%s lat=%s "
                      "en_gated=%s write_ref=%s wlat=%s",
                      timing.name, self._read_ref, self._read_cmd_latency,
                      self._read_en_gated, self._write_ref, self._write_latency)

        # Error-interface event queue. Populated by the per-version
        # behavior class when bus.error indicates a PHY-driven error.
        self.error_events: Deque[ErrorEvent] = deque()

        # CRC/alert event queue. Populated by behavior.crc() when
        # bus.alert_n goes low (v3.0+; carries CRC and CA-parity).
        self.crc_events: Deque[CRCEvent] = deque()

        # Update-interface event queue. Populated by
        # behavior.update_request() when MC- or PHY-initiated requests
        # appear on the wire.
        self.update_events: Deque[UpdateEvent] = deque()

        # Training event queue. Populated by behavior.training_step()
        # when a leveling enable/request wire asserts (v2.1-v4.0;
        # raises RemovedInThisVersionError from v5.x).
        self.training_events: Deque[TrainingEvent] = deque()

        # CA parity event queue. Populated by behavior.ca_parity_check()
        # when bus.parity_error asserts (v2.1 DDR3-DIMM wire; from
        # v3.0 parity errors ride dfi_alert_n into crc_events).
        self.ca_parity_events: Deque[CAParityEvent] = deque()

        # Frequency-change event queue. Populated by behavior.freq_change()
        # when init_start asserts during normal operation.
        self.freq_change_events: Deque[FreqChangeEvent] = deque()

        # Low-power event queue. Populated by behavior.low_power()
        # when an lp request wire asserts.
        self.low_power_events: Deque[LowPowerEvent] = deque()

        # CKE-edge decode state for self-refresh / power-down: a
        # falling CKE with the REF encoding is SRE, with NOP/deselect
        # is PDE; a rising CKE exits whichever state we're in. The
        # v4.0+ rule that a ctrlupd handshake must precede SRX is
        # tracked via _sr_ctrlupd_seen while in self-refresh.
        self._prev_cke = 1
        self._sr_ctrlupd_seen = False

        # Disconnect-protocol event queue (v4.0+).
        self.disconnect_events: Deque[DisconnectEvent] = deque()

        # PHY-Master/Managed takeover event queue (v4.0+).
        self.takeover_events: Deque[TakeoverEvent] = deque()

        # ---- CA-bus command decode (opt-in) ----
        # DFI v5/v6 protocols carry the command on an encoded CA bus
        # (dfi_cmdaddr) instead of ras/cas/we. Pass the device's CA map
        # to decode it; default None keeps the ras/cas/we and LPDDR2
        # paths exactly as they were. The map is explicit rather than
        # inferred because it is not derivable from the DFI signals —
        # LPDDR5's bank organization, for one, is a device property.
        self._ca_streams = None
        self._ca_args = None
        if ca_map is not None:
            from .ca_stream import CAStream, HBM4CAStreams
            if ca_map_col is not None:
                # HBM4: independent row/column streams in one word.
                self._ca_streams = HBM4CAStreams(ca_map, ca_map_col)
            else:
                if ca_width is None:
                    ca_width = ca_map.bus_width
                self._ca_streams = CAStream(ca_map, ca_width, sdr=ca_sdr)

        # Statistics
        self.cmd_counts = {cmd: 0 for cmd in DRAMCommand}
        self.writes_committed = 0
        self.reads_served = 0

        # Initialize PHY-driven outputs. The read-data wires are core
        # (guaranteed bound by _check_required_bound); every auxiliary
        # wire is idled only if the DUT carries it (issue #69 — a v2.1
        # bus has no dfi_alert_n to idle).
        self.bus.rddata.value = 0
        self.bus.rddata_valid.value = 0
        self._set("error", 0)
        self._set("error_info", 0)
        self._set("alert_n", 1)      # ACTIVE LOW — idles high
        self._set("parity_error", 0)  # v2.1 DDR3-DIMM parity wire
        # PHY-driven update-interface signals
        self._set("ctrlupd_ack", 0)
        self._set("phyupd_req", 0)
        self._set("phyupd_type", 0)
        # PHY-driven training responses/requests (v2.1-v4.0 wires)
        self._set("rdlvl_req", 0)
        self._set("rdlvl_gate_req", 0)
        self._set("rdlvl_resp", 0)
        self._set("wrlvl_req", 0)
        self._set("wrlvl_resp", 0)
        # PHY-driven status: dfi_init_complete is DELIBERATELY not
        # driven here (#70). Asserting it at construction is a protocol
        # EVENT, not an idle tie-off — it releases any DUT init FSM
        # waiting in its dfi-init state, and a testbench that owns the
        # bring-up choreography (hold low through reset, assert N
        # cycles later) gets stomped: the 0.6.3 regression launched
        # pumice's LPDDR2 MR walk early enough to scramble its CA
        # framing. A test that wants this BFM to own readiness calls
        # ``set_init_complete(1)`` explicitly after construction.
        # PHY-driven low-power ack
        self._set("lp_ack", 0)
        # PHY-driven takeover request (dfi_phymngd_req from v5.2)
        self._set("phymstr_req", 0)

    # ----- Address helpers -----

    @property
    def _col_mask(self) -> int:
        return (1 << self.mapping._widths["col"]) - 1

    def _byte_addr(self, flat: int) -> int:
        # `flat` is a COLUMN index, and a DRAM column addresses one DEVICE
        # word -- so it scales by device_bytes, not by bytes_per_beat (one DFI
        # phase's slice). The two are equal in the default single-granularity
        # setup (dfi_phase_bytes defaults to the memory line = device word),
        # which is why this was invisible: it only diverges once a narrow
        # device sits behind a wider beat, e.g. an x16 part (2 B) with a 32-bit
        # pumice beat (4 B), where it doubled every address.
        #
        # A round-trip test cannot see it either -- writes and reads go through
        # the same scale, so a consistent error cancels. It shows up only when
        # a test checks memory at an ABSOLUTE address, i.e. asserts that an AXI
        # write to 0x2000 is readable at 0x2000.
        return flat * self.device_bytes

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

    def _uses_ca_bus(self) -> bool:
        """True when commands ride an encoded CA bus rather than
        ras/cas/we — either the LPDDR2 CA decoder or a CA map."""
        return self._ca_streams is not None or self._is_lpddr2_family()

    def _ca_bus_word(self) -> int:
        """This cycle's CA word. v6.0 renamed dfi_address to
        dfi_cmdaddr; accept whichever the bus exposes."""
        sig = getattr(self.bus, "cmdaddr", None)
        if sig is None:
            sig = self.bus.address
        return _v(sig)

    def _decode_command(self) -> DRAMCommand:
        if self._ca_streams is not None:
            # Cycle-driven: a command may span several DFI cycles, so
            # most cycles legitimately yield nothing (NOP). When more
            # than one completes in a cycle, the extras are handled
            # here and only the last is returned to the caller — which
            # then calls _handle_command once for it.
            word = self._ca_bus_word()
            if hasattr(self._ca_streams, "row"):
                rows, cols = self._ca_streams.feed_word(word)
                done = rows + cols
            else:
                done = self._ca_streams.feed_word(word)
            done = [(c, a) for c, a in done if c != DRAMCommand.NOP]
            if not done:
                self._ca_args = None
                return DRAMCommand.NOP
            for cmd, args in done[:-1]:
                self._ca_args = args
                self._handle_command(cmd)
            self._ca_args = done[-1][1]
            return done[-1][0]
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

    @staticmethod
    def _sim_time_ns() -> str:
        """Simulation time for a log line, or '-' when no simulator is
        attached. Logging must never be the thing that kills a run, and
        get_sim_time() raises outside a simulation context."""
        try:
            return f"{get_sim_time('ns')}"
        except Exception:
            return "-"

    def _log_command(self, cmd: DRAMCommand, bank: int, addr: int,
                     cycle: int) -> None:
        """One line per accepted command, in the shape the AXI BFMs use.

        The AXI slaves log a transaction with every field that decides
        what it does (id, addr, len, size, resp). The DFI equivalent is
        the DRAM command plus the bank state it acts on -- and, when the
        command arrived on an encoded CA bus, the decoded fields, which
        the legacy (bank, addr) fold throws away. Without them a trace
        of an HBM4 or LPDDR5 run cannot tell you which pseudo-channel,
        sub-channel or stack ID a command targeted, which is exactly
        what you need when a burst lands in the wrong place.

        Gated on DFI_CMD_TRACE=1 so normal runs stay quiet.
        """
        row = (self.dram.banks[bank].row
               if bank < len(self.dram.banks) else None)
        open_row = f"0x{row:X}" if row is not None else "closed"

        fields = ""
        args = self._ca_args if self._ca_streams is not None else \
            getattr(self, "_lpddr_args", None)
        if args:
            # Order the interesting ones first, then any protocol
            # selectors the map carried through (pc/sid/sc/cid/...).
            shown = []
            for key in ("row", "col", "ap", "auto_precharge", "all_banks"):
                if key in args:
                    v = args[key]
                    shown.append(f"{key}={v if isinstance(v, bool) else f'0x{v:X}'}")
            for key in sorted(k for k in args
                              if k not in ("row", "col", "ap", "bank",
                                           "auto_precharge", "all_banks")):
                shown.append(f"{key}={args[key]}")
            if shown:
                fields = " " + " ".join(shown)

        self.log.info(
            f"@ {self._sim_time_ns()}ns: DFISlavePHY: {cmd.name} "
            f"cyc={cycle} bank={bank} addr=0x{addr:X} "
            f"open_row={open_row}{fields}")

    def _handle_command(self, cmd: DRAMCommand,
                        phase_override: Optional[int] = None) -> None:
        # phase_override: when the faithful multi-command decoder handles several
        # commands issued in ONE DFI cycle, each carries its own DFI phase (its
        # rd/wr-phase anchor). None => fall back to _active_phase() (the single-
        # command legacy path), so existing callers are unchanged.
        if self._uses_ca_bus():
            # Pull bank/row/col/etc. from the decoded CA args, not the
            # raw bus fields (which are held idle when the command
            # rides the CA bus). Both decoders — the LPDDR2 one and the
            # CA-map path — produce the same args shape.
            args = (self._ca_args if self._ca_streams is not None
                    else getattr(self, "_lpddr_args", {})) or {}
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
            p = self._active_phase() if phase_override is None else phase_override
            dfi_rate = self._infer_dfi_rate()
            aw = max(1, len(self.bus.address) // dfi_rate)
            bw = max(1, len(self.bus.bank) // dfi_rate)
            bank = (_v(self.bus.bank)    >> (p * bw)) & ((1 << bw) - 1)
            addr = (_v(self.bus.address) >> (p * aw)) & ((1 << aw) - 1)
        cycle = self.dram.cycle  # cycle as the dram model sees it
        cwl = self.dram.timings.CWL
        cl  = self.dram.timings.CL

        self.cmd_counts[cmd] = self.cmd_counts.get(cmd, 0) + 1

        if _CMD_TRACE:
            self._log_command(cmd, bank, addr, cycle)

        beats = self.base.beats_per_burst

        if cmd == DRAMCommand.ACT:
            self.dram.on_activate(bank_idx=bank, row=addr)
        elif cmd in (DRAMCommand.RD, DRAMCommand.RDA):
            # RDA == RD with auto-precharge. The LPDDR2 CA decoder returns a
            # distinct RDA command (AP folded into the opcode); DDR2 returns RD
            # and carries AP in addr bit 10. Handle both: auto-precharge below
            # keys on addr bit 10, which the LPDDR2 path sets for RDA.
            self.dram.on_read(bank_idx=bank)
            base_col = addr & self._col_mask
            open_row = self.dram.banks[bank].row or 0
            # Queue N consecutive beats at (col, col+1, …, col+N-1).
            # With DFI_RATE > 1 the MC packs DFI_RATE DRAM beats per DFI
            # cycle, so beats in the same group share a due_cycle. Use
            # the rddata bus width to derive DFI_RATE without a new ctor
            # parameter.
            words_per_cycle = self._infer_dfi_rate() * self.words_per_beat
            # Tag this RD command: burst id (for anchored grouping) + the
            # rd_phase the PHY anchors the returned burst to (a7ddrphy BL-anchored
            # model only). _active_phase() follows the phase carrying the RD cmd.
            self._rd_burst_seq += 1
            _burst_id = self._rd_burst_seq
            _anchor_phase = (self._active_phase() if phase_override is None
                             else phase_override)
            _decode_cycle = cycle
            for k in range(beats):
                col_k = base_col + k
                if col_k >= self.mapping.num_cols:
                    break  # don't wrap past the row end for now
                flat = self.mapping.tuple_to_flat(0, bank, open_row, col_k)
                if self._read_free_running:
                    # a7ddrphy ISERDES: the read DATA for this command lands on
                    # the (held) DQ bus at command + read_latency, INDEPENDENT of
                    # rddata_en. The valid strobe is scheduled separately off
                    # rddata_en (see _monitor_recv). Data/valid decoupled => a
                    # slipped enable samples stale/zero data.
                    _rl = self._read_cmd_latency if self._read_cmd_latency \
                        is not None else cl
                    self._rd_data_pipe.append(
                        _PendingOp(due_cycle=cycle + _rl + (k // words_per_cycle),
                                   flat_addr=flat))
                elif self._strict_read_timing:
                    # read_ref = rddata_en: defer until the controller asserts
                    # dfi_rddata_en; the return is timed off THAT (+read_latency).
                    # Carry burst id + anchor phase for the BL-anchored model.
                    self._strict_rd_addr.append(
                        (flat, _burst_id, _anchor_phase))
                else:
                    # read_ref = command: schedule at command + the profile's
                    # read_latency hook (None => JEDEC CL). read_en_gated (if set)
                    # additionally holds rddata_valid until dfi_rddata_en — see
                    # _serve_reads. burst_id/anchor_phase are carried so the
                    # BL-anchored server (read_bl_anchored) can group a burst's
                    # device words and place them in the rd_phase-anchored slots;
                    # the plain _serve_reads path ignores them (K=1 => no-op).
                    _rl = self._read_cmd_latency if self._read_cmd_latency \
                        is not None else cl
                    self._pending_reads.append(
                        _PendingOp(due_cycle=cycle + _rl + (k // words_per_cycle),
                                   flat_addr=flat, burst_id=_burst_id,
                                   anchor_phase=_anchor_phase,
                                   decode_cycle=_decode_cycle)
                    )
            if addr & (1 << 10):
                self._pending_auto_pre(bank)
        elif cmd in (DRAMCommand.WR, DRAMCommand.WRA):
            # WRA == WR with auto-precharge (see the RD/RDA note above). Without
            # this, LPDDR2 close-page writes (HAPPY_HYBRID row-miss -> WRA) hit no
            # branch, queued no pending write, and their wrdata_en became "stray
            # data beats" -> the write was silently dropped.
            self.dram.on_write(bank_idx=bank)
            base_col = addr & self._col_mask
            open_row = self.dram.banks[bank].row or 0
            words_per_cycle = self._infer_dfi_rate() * self.words_per_beat
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
                                   + (k // words_per_cycle), flat_addr=flat)
                    )
                else:
                    self._pending_writes.append(
                        _PendingOp(due_cycle=cycle + cwl + (k // words_per_cycle),
                                   flat_addr=flat)
                    )
            if addr & (1 << 10):
                self._pending_auto_pre(bank)
        elif cmd == DRAMCommand.PRE:
            all_banks = bool(addr & (1 << 10))
            self.dram.on_precharge(bank_idx=bank, all_banks=all_banks)
        elif cmd == DRAMCommand.REF:
            # CA-bus protocols carry all_banks in the decoded args
            # (LPDDR2 Table 60: CA3r distinguishes REFab/REFpb). An
            # explicit False routes to the per-bank model; absent or
            # True is the broadcast REFab every other protocol means.
            _a = (self._ca_args if self._ca_streams is not None
                  else getattr(self, "_lpddr_args", {})) or {}
            if self._uses_ca_bus() and _a.get("all_banks") is False:
                self.dram.on_refresh_bank()
            else:
                self.dram.on_refresh()
        elif cmd == DRAMCommand.MRS:
            # Record MRW {index: data} for init verification. CA-bus
            # protocols carry mr_addr/mr_data in the decoded args; skip
            # MRR (a read, which writes nothing).
            if self._uses_ca_bus():
                _a = (self._ca_args if self._ca_streams is not None
                      else getattr(self, "_lpddr_args", {})) or {}
                if not _a.get("is_mrr"):
                    self.mode_regs[_a.get("mr_addr", 0)] = _a.get("mr_data", 0)
        # NOP: ignored (just kept in cmd_counts)

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
        # Each DFI phase carries K = words_per_beat DEVICE words (K=2 for an x16
        # device on a 32b beat). Pending writes are queued per device-word column
        # (one _PendingOp per column), so commit K of them per phase — otherwise
        # K-1 columns per phase stay queued forever and later stall reads (which
        # serialize behind pending writes). K=1 => device word == phase == legacy.
        dev_bytes = self.device_bytes
        dev_bits  = dev_bytes * 8
        K = self.words_per_beat
        for phase, data, mask in slices:
            for w in range(K):
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
                # slice device word w out of this phase's beat_bytes payload
                wd = (data >> (w * dev_bits)) & ((1 << dev_bits) - 1)
                wm = (mask >> (w * dev_bytes)) & ((1 << dev_bytes) - 1)
                ba = self.memory.integer_to_bytearray(wd, dev_bytes)
                # DFI mask convention: 1 means *don't* write that byte.
                strobe = (~wm) & ((1 << dev_bytes) - 1)
                _ba_addr = self._byte_addr(op.flat_addr)
                if _WR_TRACE:
                    self.log.info(
                        f"[WRTRACE] cyc={cycle} phase={phase} w={w} "
                        f"byte_addr=0x{_ba_addr:X} data=0x{wd:0{dev_bytes*2}X} "
                        f"strobe=0x{strobe:X} en={_v(self.bus.wrdata_en):b} "
                        f"pend_left={len(self._pending_writes)}")
                self.memory.write(_ba_addr, ba, strobe=strobe)
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
        # Commit at DEVICE-WORD granularity: each queued capture is one device
        # word; slice it from its position in the packed DFI cycle (device word w
        # -> bits [w*dev_bits +: dev_bits]). K=1 => device word == DFI phase =>
        # legacy behavior.
        dev_bytes = self.device_bytes
        dev_bits = dev_bytes * 8
        full_wrdata = _v(self.bus.wrdata)
        full_mask = _v(self.bus.wrdata_mask)
        w = 0
        while (self._write_captures
               and self._write_captures[0].due_cycle == cycle):
            op = self._write_captures.popleft()
            data = (full_wrdata >> (w * dev_bits)) & ((1 << dev_bits) - 1)
            mask = (full_mask >> (w * dev_bytes)) & ((1 << dev_bytes) - 1)
            # DFI mask convention: 1 means *don't* write that byte.
            strobe = (~mask) & ((1 << dev_bytes) - 1)
            ba = self.memory.integer_to_bytearray(data, dev_bytes)
            self.memory.write(self._byte_addr(op.flat_addr), ba, strobe=strobe)
            self.writes_committed += 1
            w += 1

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
        # read_en_gated hook: a PHY that only presents read data while the
        # controller holds dfi_rddata_en (a7ddrphy capture window). Data is
        # scheduled DUE at command+read_latency but held here until the enable
        # is asserted — so a controller that mis-cadences rddata_en gets no /
        # shifted read data, which the ungated self-timed model cannot expose.
        if self._read_en_gated and (_v(self.bus.rddata_en) == 0):
            self.bus.rddata_valid.value = 0
            return

        # Pack pending reads into one DFI cycle at DEVICE-WORD granularity. The
        # rddata bus holds words_per_cycle = rddata_bits / device_bits device
        # words; K=words_per_beat of them make up one DFI phase. rddata_valid is
        # per PHASE (one bit per bytes_per_beat slice), NOT per device word — so
        # its width stays DFI_RATE. (K=1 => device word == phase => legacy.)
        dev_bits = self.device_bytes * 8
        K = self.words_per_beat
        try:
            rddata_total_bits = len(self.bus.rddata)
        except TypeError:
            rddata_total_bits = self.bytes_per_beat * 8
        words_per_cycle = max(1, rddata_total_bits // dev_bits)

        packed_data = 0
        packed_valid = 0
        for w in range(words_per_cycle):
            if not (self._pending_reads
                    and self._pending_reads[0].due_cycle <= cycle):
                break
            op = self._pending_reads.popleft()
            ba = self.memory.read(self._byte_addr(op.flat_addr),
                                  self.device_bytes)
            word_data = self.memory.bytearray_to_integer(ba)
            packed_data |= (word_data & ((1 << dev_bits) - 1)) << (w * dev_bits)
            packed_valid |= (1 << (w // K))   # valid is per DFI phase
            self.reads_served += 1

        # a7ddrphy 4-phase read-window offset (issue #32): the controller reads
        # {p1,p0}=slots[0:4] but a read-latency misalignment puts the real data at
        # slots[offset:offset+4], so it grabs shifted device-words + zeros. Model
        # it by shifting the assembled device-words by `offset` slots, zero-filling.
        if packed_valid and self._read_dw_offset:
            span = words_per_cycle * dev_bits
            m = (1 << span) - 1
            off = self._read_dw_offset
            packed_data = ((packed_data << (off * dev_bits)) & m) if off > 0 \
                else (packed_data >> ((-off) * dev_bits))

        if packed_valid:
            self.bus.rddata.value = packed_data
            self.bus.rddata_valid.value = packed_valid
        else:
            self.bus.rddata_valid.value = 0

    def _serve_reads_free_running(self) -> None:
        """a7ddrphy-faithful read: DATA free-runs off the command; VALID is
        rddata_en delayed. Data and valid are DECOUPLED.

        Each cycle we (1) advance the free-running DQ bus from the command-
        anchored data pipeline (words that have become available OVERWRITE the
        held bus; the bus HOLDS its last value across gaps, like a real ISERDES
        continuously shifting out the last captured word), then (2) if a valid
        strobe (rddata_en delayed by read_valid_latency) is due this cycle,
        present whatever the DQ bus currently holds.

        The one-read shift falls out mechanically: if the controller fires
        rddata_en a cycle EARLY relative to its command-anchored data, the
        strobe samples the PREVIOUS read's held words (or ZERO before any data
        has landed) — exactly the on-silicon beats_mismatched == 2*txn."""
        cycle = self.dram.cycle
        dev_bits = self.device_bytes * 8
        try:
            rddata_total_bits = len(self.bus.rddata)
        except TypeError:
            rddata_total_bits = self.bytes_per_beat * 8
        words_per_cycle = max(1, rddata_total_bits // dev_bits)

        # (1) Advance the free-running DQ bus. Every command-anchored word whose
        # data-cycle has arrived overwrites the held bus, one DFI cycle's worth
        # (words_per_cycle device words) at a time — the newest wins and HOLDS.
        while (self._rd_data_pipe
               and self._rd_data_pipe[0].due_cycle <= cycle):
            new_words = []
            for _ in range(words_per_cycle):
                if not (self._rd_data_pipe
                        and self._rd_data_pipe[0].due_cycle <= cycle):
                    break
                op = self._rd_data_pipe.popleft()
                ba = self.memory.read(self._byte_addr(op.flat_addr),
                                      self.device_bytes)
                new_words.append(self.memory.bytearray_to_integer(ba)
                                 & ((1 << dev_bits) - 1))
            if new_words:
                self._dq_hold_words = new_words   # newest word set HELD on bus

        # (2) Drive a valid strobe if one is due this cycle. rddata_valid is a
        # pure function of the (delayed) rddata_en — NOT of data availability.
        valid_due = bool(self._rd_valid_pipe
                         and self._rd_valid_pipe[0] <= cycle)
        if not valid_due:
            self.bus.rddata_valid.value = 0
            return
        # Consume all strobes due this cycle (one DFI cycle each).
        while (self._rd_valid_pipe and self._rd_valid_pipe[0] <= cycle):
            self._rd_valid_pipe.popleft()

        # Sample the CURRENTLY held DQ bus. If no command data has landed yet,
        # the bus reads ZERO (first-read leading-zero signature).
        held = list(self._dq_hold_words)
        packed_data = 0
        packed_valid = 0
        K = self.words_per_beat
        for w in range(words_per_cycle):
            word = held[w] if w < len(held) else 0
            packed_data |= (word & ((1 << dev_bits) - 1)) << (w * dev_bits)
            packed_valid |= (1 << (w // K))
            self.reads_served += 1
        self.bus.rddata.value = packed_data
        self.bus.rddata_valid.value = packed_valid

    def _serve_reads_bl_anchored(self) -> None:
        """Faithful a7ddrphy phase-anchored read DE-INTERLEAVER.

        The Artix-7 a7ddrphy exposes ONE fixed words_per_cycle-slot DFI word per
        DFI cycle (8 slots for nphases=4 x16). This ONE model reproduces BOTH the
        board BUG and the FIX, keyed only on how many RD commands the controller
        issues per DFI cycle:

          * ONE RD/cycle (the on-board BUG): a BL4 read drives ONLY its
            rd_phase-ANCHORED contiguous slot run (4 slots); the slots it does NOT
            drive HOLD THE PREVIOUS READ'S device words (STALE) — the fixed 8-slot
            deserializer keeps the last word on the phases this short burst did not
            drive. A controller that captures the whole DFI word takes the anchored
            run correct and the rest STALE -> 4 real + 4 stale.

          * TWO RDs/cycle at phases {P, P+2} (the FIX): both anchored runs are
            written in the SAME de-interleave window -> {slots[0:4], slots[4:8]}
            fully populated -> 8 real, 0 stale.

        Reads decoded in the SAME DFI cycle (op.decode_cycle) belong to ONE
        window: each contributes its BL device words at its own anchor phase's
        slots. Slots no RD in the group drove hold the previous window's value.
        The anchored slot run is derived by the shared contract helper
        (dfi_timing.bl_anchored_slot_mask) so the RTL assertion mirrors the
        IDENTICAL rule. Stale-previous (not zero) is the faithful, bug-exposing
        fill — zeros would accidentally pass some data patterns.
        """
        cycle = self.dram.cycle
        # Queue-don't-collide: a same-or-earlier pending WRITE commits first.
        if self._pending_writes and self._pending_writes[0].due_cycle <= cycle:
            self.bus.rddata_valid.value = 0
            return
        # read_en_gated hook (a7ddrphy capture window): hold rddata_valid until
        # the controller asserts dfi_rddata_en.
        if self._read_en_gated and (_v(self.bus.rddata_en) == 0):
            self.bus.rddata_valid.value = 0
            return

        dev_bits = self.device_bytes * 8
        K = self.words_per_beat
        try:
            rddata_total_bits = len(self.bus.rddata)
        except TypeError:
            rddata_total_bits = self.bytes_per_beat * 8
        words_per_cycle = max(1, rddata_total_bits // dev_bits)
        nphases = self._infer_dfi_rate()

        # Nothing due this cycle -> keep valid low; the DQ hold state persists.
        if not (self._pending_reads
                and self._pending_reads[0].due_cycle <= cycle):
            self.bus.rddata_valid.value = 0
            return

        # Gather EVERY burst decoded in the same DFI cycle as the head (they pack
        # into ONE de-interleave window). Group each burst's device words by its
        # burst_id, recording its anchor_phase. This is the ONLY place the BUG vs
        # FIX diverge: one RD in the group -> half the window stays stale; two RDs
        # at {P,P+2} -> the whole window is real.
        group_decode = self._pending_reads[0].decode_cycle
        # Preserve first-seen order of bursts so a deterministic anchor layout.
        group_order: list = []
        group_words: dict = {}      # burst_id -> list[int]
        group_anchor: dict = {}     # burst_id -> anchor_phase
        while (self._pending_reads
               and self._pending_reads[0].due_cycle <= cycle
               and self._pending_reads[0].decode_cycle == group_decode):
            op = self._pending_reads.popleft()
            if op.burst_id not in group_words:
                group_order.append(op.burst_id)
                group_words[op.burst_id] = []
                group_anchor[op.burst_id] = op.anchor_phase
            ba = self.memory.read(self._byte_addr(op.flat_addr),
                                  self.device_bytes)
            group_words[op.burst_id].append(
                self.memory.bytearray_to_integer(ba) & ((1 << dev_bits) - 1))

        if not group_order:
            self.bus.rddata_valid.value = 0
            return

        # Build the FULL de-interleave window via the SHARED pure helper (same
        # logic the unit test drives): start from the previous window (STALE
        # hold), write each burst's device words into its anchored slots. Slots no
        # burst wrote keep the stale value.
        bursts = [(group_anchor[bid], group_words[bid]) for bid in group_order]
        total_words = sum(len(group_words[bid]) for bid in group_order)
        window = deinterleave_read_window(
            prev_window=self._rd_stale_words, bursts=bursts,
            words_per_cycle=words_per_cycle, nphases=nphases,
            words_per_beat=K)
        # This window becomes the NEXT window's stale fill.
        self._rd_stale_words = list(window)

        slots = window
        packed_data = 0
        packed_valid = 0
        for w in range(words_per_cycle):
            packed_data |= (slots[w] & ((1 << dev_bits) - 1)) << (w * dev_bits)
            packed_valid |= (1 << (w // K))   # valid is per DFI phase
        self.reads_served += total_words
        self.bus.rddata.value = packed_data
        self.bus.rddata_valid.value = packed_valid
        self._skew_cur = packed_data   # this cycle's ideal word for the skew step

    def _skew_post(self) -> None:
        """Faithful per-64b-beat read skew, run EVERY dfi cycle. Delays the HIGH
        (and/or LOW) 64b beat by one cycle relative to the other, so read N's high
        half lands on cycle N+1 (a trailing-cycle drive) — the a7ddrphy defect the
        controller's deskew_lo/hi cancel. Runs on idle cycles too, so the trailing
        high beat is driven even when no new read is due. `_skew_cur` is the ideal
        word the serve step produced this cycle (None = idle)."""
        try:
            total = len(self.bus.rddata)
        except TypeError:
            total = self.bytes_per_beat * 8
        hw   = total // 2
        mask = (1 << hw) - 1
        cur  = self._skew_cur
        cur_lo = (cur & mask) if cur is not None else 0
        cur_hi = ((cur >> hw) & mask) if cur is not None else 0
        out_lo = self._skew_lo_prev if self._read_lo_skew else cur_lo
        out_hi = self._skew_hi_prev if self._read_hi_skew else cur_hi
        self._skew_lo_prev = cur_lo
        self._skew_hi_prev = cur_hi
        self.bus.rddata.value = (out_hi << hw) | out_lo
        self._skew_cur = None

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

            # ----- CKE-edge decode: self-refresh / power-down -----
            cke_now = _v(self.bus.cke) & 1
            if self._prev_cke == 1 and cke_now == 0:
                selected = (cs_all & cs_sel_mask) != cs_sel_mask
                cmd_at_edge = self._decode_command() if selected \
                    else DRAMCommand.NOP
                if selected and cmd_at_edge == DRAMCommand.REF:
                    self.cmd_counts[DRAMCommand.SRE] = \
                        self.cmd_counts.get(DRAMCommand.SRE, 0) + 1
                    self.dram.on_self_refresh_entry()
                    self._sr_ctrlupd_seen = False
                else:
                    self.cmd_counts[DRAMCommand.PDE] = \
                        self.cmd_counts.get(DRAMCommand.PDE, 0) + 1
                    self.dram.on_powerdown_entry()
            elif self._prev_cke == 0 and cke_now == 1:
                if self.dram.in_self_refresh:
                    self.cmd_counts[DRAMCommand.SRX] = \
                        self.cmd_counts.get(DRAMCommand.SRX, 0) + 1
                    # v4.0+: a ctrlupd handshake is REQUIRED
                    # immediately before self-refresh exit.
                    from .dfi_signal_types import DFIVersion, version_rank
                    if (version_rank(self.base.dfi_version)
                            >= version_rank(DFIVersion.V4_0)
                            and not self._sr_ctrlupd_seen):
                        self.dram.policy.report(
                            "srx_without_ctrlupd",
                            "self-refresh exit without the required "
                            "ctrlupd handshake (DFI v4.0+ rule)",
                            self.log,
                        )
                    self.dram.on_self_refresh_exit()
                else:
                    self.cmd_counts[DRAMCommand.PDX] = \
                        self.cmd_counts.get(DRAMCommand.PDX, 0) + 1
                    self.dram.on_powerdown_exit()
            self._prev_cke = cke_now

            # Track the v4.0 pre-SRX ctrlupd handshake while in SR.
            # (Update wires are optional — absent reads as 0.)
            if (self.dram.in_self_refresh
                    and self._vopt("ctrlupd_req")
                    and self._vopt("ctrlupd_ack")):
                self._sr_ctrlupd_seen = True

            # Normal command dispatch only while CKE is high and we
            # didn't just consume the wire state as an entry command.
            if cke_now == 1 and (cs_all & cs_sel_mask) != cs_sel_mask:
                # Faithful a7ddrphy: decode a command at EVERY selected phase, so
                # multiple commands issued in ONE DFI cycle (the sub-DFI-word BL4
                # fix: two RDs at phases {P, P+2}) are all handled and pack into
                # one de-interleave window. Each command carries its own DFI phase
                # as its anchor. LPDDR2 rides the CA bus (one cmd/cycle) so it
                # keeps the single-decode path. The plain models also keep single
                # decode (bit-identical to before).
                if self._read_bl_anchored and not self._uses_ca_bus():
                    for _p, _cmd in decode_all_phases(
                            cs_all, _v(self.bus.ras_n), _v(self.bus.cas_n),
                            _v(self.bus.we_n), dfi_rate):
                        self._handle_command(_cmd, phase_override=_p)
                else:
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
                # One asserted rddata_en cycle returns one DFI cycle = DFI_RATE
                # phases x K device words = words_per_cycle device words.
                words_per_cycle = self._infer_dfi_rate() * self.words_per_beat
                for _ in range(words_per_cycle):
                    if not self._strict_rd_addr:
                        break
                    # _strict_rd_addr entries carry (flat, burst_id, anchor_phase)
                    # for the BL-anchored model. Unpack robustly so the legacy
                    # (bare-int flat) form still works if ever queued that way.
                    _entry = self._strict_rd_addr.popleft()
                    if isinstance(_entry, tuple):
                        flat, _bid, _aphase = _entry
                    else:
                        flat, _bid, _aphase = _entry, 0, 0
                    self._pending_reads.append(
                        _PendingOp(due_cycle=cycle + self._read_latency,
                                   flat_addr=flat, burst_id=_bid,
                                   anchor_phase=_aphase))

            # Free-running ISERDES: sample rddata_en into the valid-strobe
            # pipeline (valid = enable delayed read_valid_latency), INDEPENDENT
            # of the command-anchored data pipeline. This is where the real
            # a7ddrphy decouples the two: dfi_rddata_valid is purely the
            # controller's rddata_en delayed a fixed count; the data is whatever
            # the free-running DQ bus happens to hold at that instant.
            if self._read_free_running and (_v(self.bus.rddata_en) != 0):
                cycle = self.dram.cycle
                self._rd_valid_pipe.append(cycle + self._read_valid_latency)

            # Order matters: commit writes first, then serve reads. The
            # serve_reads helper double-checks so we never produce stale
            # data while a same-cycle write is still in flight.
            if self._strict_write_timing:
                self._serve_writes_strict()
            else:
                self._serve_writes()
            self._skew_cur = None   # serve sets it when it drives an ideal word
            if self._read_free_running:
                self._serve_reads_free_running()
            elif self._read_bl_anchored:
                self._serve_reads_bl_anchored()
            else:
                self._serve_reads()
            # Per-beat read skew: a 1-deep pipeline on the DQ bus, applied EVERY
            # cycle (idle included) so read N's high beat lands on cycle N+1.
            if self._read_hi_skew or self._read_lo_skew:
                self._skew_post()

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
            self._dispatch_behavior_low_power()

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

    def _dispatch_behavior_low_power(self) -> None:
        """Call the per-version behavior.low_power() and queue any event."""
        try:
            evt = self.base.behavior.low_power(self.bus, None)
        except NotImplementedError:
            return
        if evt is not None:
            self.low_power_events.append(evt)

    # ----- Error-interface drive (PHY → MC) -----

    def set_error(self, active: int, info: int = 0) -> None:
        """Drive the error sub-interface signals.

        Pulse the test sequence: ``slave.set_error(1, info=0x42)`` to
        assert; ``slave.set_error(0)`` to deassert. The on-the-wire
        edge is what the behavior class samples.
        """
        self._api_sig("error").value = active
        self._api_sig("error_info").value = info

    def set_alert_n(self, active: int) -> None:
        """Drive dfi_alert_n (PHY→MC, v3.0+, ACTIVE LOW).

        ``active=1`` pulls the wire LOW (error reported); ``active=0``
        returns it to its idle-high state. DDR4+ report both write-CRC
        and CA-parity errors on this wire.
        """
        self._api_sig("alert_n").value = 0 if active else 1

    def set_parity_error(self, active: int) -> None:
        """Drive dfi_parity_error (PHY→MC, v2.1.1 DDR3 registered-DIMM
        parity interface; renamed dfi_alert_n in v3.0)."""
        self._api_sig("parity_error").value = active

    def set_phyupd_req(self, active: int, update_type: int = 0) -> None:
        """Drive the PHY-initiated update request (PHY→MC, v2.1
        baseline). ``update_type`` drives dfi_phyupd_type (selects the
        tphyupd_typeX duration class, 0-3)."""
        self._api_sig("phyupd_type").value = update_type
        self._api_sig("phyupd_req").value = active

    def set_ctrlupd_ack(self, active: int) -> None:
        """Drive the PHY's ack of an MC-initiated update."""
        self._api_sig("ctrlupd_ack").value = active

    def set_rdlvl_req(self, active: int) -> None:
        """Drive the PHY's read-leveling training request (v2.1-v4.0)."""
        self._api_sig("rdlvl_req").value = active

    def set_rdlvl_gate_req(self, active: int) -> None:
        """Drive the PHY's gate-training request (v2.1-v4.0)."""
        self._api_sig("rdlvl_gate_req").value = active

    def set_wrlvl_req(self, active: int) -> None:
        """Drive the PHY's write-leveling training request (v2.1-v4.0)."""
        self._api_sig("wrlvl_req").value = active

    def set_rdlvl_resp(self, value: int) -> None:
        """Drive the read-leveling response bits (v2.1-v4.0)."""
        self._api_sig("rdlvl_resp").value = value

    def set_wrlvl_resp(self, value: int) -> None:
        """Drive the write-leveling sample response (v2.1-v4.0)."""
        self._api_sig("wrlvl_resp").value = value

    def set_init_complete(self, active: int) -> None:
        """Drive dfi_init_complete (PHY→MC).

        High = PHY ready for DFI transactions. De-asserting while the
        MC holds dfi_init_start high ACCEPTS a frequency-change
        request; re-assert after re-initializing at the new frequency.
        """
        self._api_sig("init_complete").value = active

    def accept_freq_change(self) -> None:
        """Acknowledge a frequency-change request the spec way: de-
        assert dfi_init_complete (must happen within tinit_start
        cycles of the MC's init_start assertion)."""
        self._api_sig("init_complete").value = 0

    def set_lp_ack(self, active: int) -> None:
        """Drive the PHY's low-power acknowledge (dfi_lp_ack; split
        into ctrl/data acks from v5.1)."""
        self._api_sig("lp_ack").value = active

    def set_phymstr_req(self, active: int) -> None:
        """Drive the PHY Master takeover request (dfi_phymstr_req,
        v4.0; the wire is named dfi_phymngd_req from v5.2)."""
        self._api_sig("phymstr_req").value = active

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
