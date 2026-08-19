# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Passive DFI bus monitor (issue #16).

:class:`DFIMonitor` is a cocotb_bus.BusMonitor subclass that samples the
DFI command, write-data, and read-data sub-interfaces every clock and
dispatches captured packets to per-sub-interface queues. It can be
attached to either side of a :file:`tests/sim/rtl/dfi/dfi_shim.sv` —
the ``side`` argument selects the ``mc_dfi`` vs ``phy_dfi`` signal
prefix — so two monitor instances (one per side) can verify a packet
made it across the wire unchanged.

Design notes:
  - Unlike the single-channel BFMs (APB/GAXI) where one ``_recvQ`` is
    enough, DFI has three parallel sub-interface timelines that overlap
    (a write-data beat can land on the same cycle as a new ACT command),
    so the monitor exposes separate queues: ``command_q``,
    ``write_data_q``, ``read_data_q``.
  - Sampling is **falling edge** of ``dfi_clk`` (matching APB / cocotb
    convention) so values are stable post-rising-edge propagation.
  - Command capture is gated on ``cs_n == 0`` (CS active-low select).
    The captured packet's ``cmd`` field is the JEDEC decode of
    ``(ras_n, cas_n, we_n)`` per DFI v2.1 / JESD79-3F Table 67.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional

from cocotb.triggers import FallingEdge
from cocotb.utils import get_sim_time
from cocotb_bus.monitors import BusMonitor

from .dfi_packet import DFIControlPacket, DFIReadDataPacket, DFIWriteDataPacket, DRAMCommand

# Reverse-lookup table: (ras_n, cas_n, we_n) → DRAMCommand.
# Matches dfi_packet._DDR3_ENCODING. CS_n is checked separately; this
# table assumes the chip is already selected.
_CMD_DECODE = {
    (0, 1, 1): DRAMCommand.ACT,
    (1, 0, 1): DRAMCommand.RD,
    (1, 0, 0): DRAMCommand.WR,
    (0, 1, 0): DRAMCommand.PRE,
    (0, 0, 1): DRAMCommand.REF,
    (0, 0, 0): DRAMCommand.MRS,
    (1, 1, 1): DRAMCommand.NOP,
}


# Signal sets per sub-interface. Names match the dfi_signals catalog —
# no `dfi_` prefix here; the prefix comes from the BusMonitor `prefix`
# constructor argument so we resolve `<prefix>_<signal>` on the DUT.
_COMMAND_SIGNALS = ("address", "bank", "cas_n", "ras_n", "we_n", "cs_n",
                    "cke", "odt", "reset_n")
_WRITE_DATA_SIGNALS = ("wrdata", "wrdata_en", "wrdata_mask")
_READ_DATA_SIGNALS = ("rddata", "rddata_en", "rddata_valid")

# Error sub-interface (v3.0+): dfi_error + dfi_error_info. Present on
# the shim for all tests but only sampled when the BFM is configured
# for a version that defines it.
_ERROR_SIGNALS = ("error", "error_info")

# Alert wire (v3.0+): dfi_alert_n, ACTIVE LOW. Carries both DDR4
# write-CRC and CA-parity errors (they are indistinguishable at the
# DFI). Replaces the pre-spec-verification fabricated "crc_alert".
_ALERT_SIGNALS = ("alert_n",)

# Update interface — bidirectional since v2.1 (ctrlupd AND phyupd;
# phyupd_type selects one of up to 4 PHY-update duration modes).
_UPDATE_SIGNALS = ("ctrlupd_req", "ctrlupd_ack",
                   "phyupd_req", "phyupd_ack", "phyupd_type")

# Training interface (v2.1-v4.0; removed in v5.x). Wired subset:
# read-leveling / gate-training / write-leveling en+req+resp
# handshakes, which exist under these names from v2.1 through v4.0.
# CA/wdqlvl/DB training and the v2.1 delay-register wires are catalog-
# only until a test needs them.
_TRAINING_SIGNALS = ("rdlvl_en", "rdlvl_req", "rdlvl_resp",
                     "rdlvl_gate_en", "rdlvl_gate_req",
                     "wrlvl_en", "wrlvl_req", "wrlvl_resp")

# CA parity: MC drives dfi_parity_in (v2.1.1+); the PHY reports on
# dfi_parity_error in v2.1 (DDR3 DIMMs) and on dfi_alert_n from v3.0.
_CA_PARITY_SIGNALS = ("parity_in", "parity_error")

# Status interface: init handshake (doubles as the frequency-change
# protocol — there is no dedicated freq-change request wire in any
# DFI version), ratio, and the v4.0+ frequency indicator.
_STATUS_SIGNALS = ("init_start", "init_complete", "freq_ratio", "frequency")

# Low power control (v3.1-style split requests + shared ack/wakeup).
_LOW_POWER_SIGNALS = ("lp_ctrl_req", "lp_data_req", "lp_wakeup", "lp_ack")

# Disconnect Protocol (v4.0-v5.x): one MC-driven wire qualifying a
# handshake break as QOS (0) or error (1). Not a req/ack pair.
_DISCONNECT_SIGNALS = ("disconnect_error",)

# PHY Master Interface (v4.0; wires renamed dfi_phymngd_* in v5.2 —
# the shim models a v4.0/v5.1 PHY).
_PHY_MASTER_SIGNALS = ("phymstr_req", "phymstr_ack")


def _v(sig) -> int:
    """Read a cocotb signal as int, returning 0 if unresolvable (X/Z)."""
    v = sig.value
    return v.integer if v.is_resolvable else 0


class DFIMonitor(BusMonitor):
    """Per-sub-interface DFI bus monitor.

    Args:
        entity: The cocotb DUT handle.
        clock:  The DFI clock signal.
        side:   ``"mc"`` to attach to the MC-facing port of the shim,
                ``"phy"`` for the PHY-facing port. Determines the signal
                prefix (``mc_dfi`` vs ``phy_dfi``).
        title:  Optional title for log messages.
    """

    _signals = (
        list(_COMMAND_SIGNALS)
        + list(_WRITE_DATA_SIGNALS)
        + list(_READ_DATA_SIGNALS)
        + list(_ERROR_SIGNALS)
        + list(_ALERT_SIGNALS)
        + list(_UPDATE_SIGNALS)
        + list(_TRAINING_SIGNALS)
        + list(_CA_PARITY_SIGNALS)
        + list(_STATUS_SIGNALS)
        + list(_LOW_POWER_SIGNALS)
        + list(_DISCONNECT_SIGNALS)
        + list(_PHY_MASTER_SIGNALS)
    )
    _optional_signals: List[str] = []

    def __init__(
        self,
        entity,
        clock,
        side: str = "phy",
        title: Optional[str] = None,
        ca_map=None,
        ca_map_col=None,
        ca_width: Optional[int] = None,
        ca_sdr: bool = False,
        log=None,
        **kwargs,
    ):
        if side not in ("mc", "phy"):
            raise ValueError(f"side must be 'mc' or 'phy', got {side!r}")
        self.side = side
        self.title = title or f"DFIMonitor[{side}]"

        prefix = f"{side}_dfi"
        BusMonitor.__init__(self, entity, prefix, clock, **kwargs)
        self.clock = clock
        # Injectable like the AXI BFMs' `log=`; see DFISlavePHY.
        self.log = log if log is not None else self.entity._log

        # Per-sub-interface capture queues. The default _recvQ from
        # BusMonitor still works (every packet goes there too), but
        # consumers usually want them split.
        self.command_q: Deque[DFIControlPacket] = deque()
        self.write_data_q: Deque[DFIWriteDataPacket] = deque()
        self.read_data_q: Deque[DFIReadDataPacket] = deque()

        self.command_count = 0
        self.write_data_count = 0
        self.read_data_count = 0

        # ---- CA-bus command decode (opt-in) ----
        # DFI v5/v6 protocols (and LPDDR2/3 before them) carry the
        # command on an encoded CA bus, where ras/cas/we are held idle
        # and decode to NOP forever. Pass the device's CA map to decode
        # it; default None keeps the ras/cas/we path exactly as it was.
        #
        # strict=False, unlike the slave: a monitor can attach partway
        # through a command, so an orphan second half or an
        # unrecognised head edge must resync rather than raise. The
        # stream's `resyncs` counter records how often that happened.
        self._ca_streams = None
        if ca_map is not None:
            from .ca_stream import CAStream, HBM4CAStreams
            if ca_map_col is not None:
                self._ca_streams = HBM4CAStreams(ca_map, ca_map_col,
                                                 strict=False)
            else:
                if ca_width is None:
                    ca_width = ca_map.bus_width
                self._ca_streams = CAStream(ca_map, ca_width, sdr=ca_sdr,
                                            strict=False)

    # ----- Decoders -----

    def _decode_command(self) -> DRAMCommand:
        ras = _v(self.bus.ras_n)
        cas = _v(self.bus.cas_n)
        we  = _v(self.bus.we_n)
        return _CMD_DECODE.get((ras, cas, we), DRAMCommand.NOP)

    def _ca_bus_word(self) -> int:
        """This cycle's CA word. v6.0 renamed dfi_address to
        dfi_cmdaddr; accept whichever the bus exposes."""
        sig = getattr(self.bus, "cmdaddr", None)
        if sig is None:
            sig = self.bus.address
        return _v(sig)

    @property
    def _ca_in_flight(self) -> bool:
        """True while a CA command is mid-collection across cycles."""
        s = self._ca_streams
        if s is None:
            return False
        if hasattr(s, "row"):
            return s.row.partial or s.col.partial
        return s.partial

    def _decode_ca_commands(self) -> list:
        """Every command completed by this cycle's CA word, as
        ``(DRAMCommand, args)``. NOPs are filtered out."""
        word = self._ca_bus_word()
        if hasattr(self._ca_streams, "row"):
            rows, cols = self._ca_streams.feed_word(word)
            done = rows + cols
        else:
            done = self._ca_streams.feed_word(word)
        return [(c, a) for c, a in done if c != DRAMCommand.NOP]

    # ----- Sampling loop -----

    async def _monitor_recv(self):
        while True:
            await FallingEdge(self.clock)
            ts = get_sim_time("ns")

            # --- Command sub-interface: capture when CS is asserted ---
            cs_n = _v(self.bus.cs_n)
            if self._ca_streams is not None:
                # CA-bus protocols: feed the stream when CS selects a
                # new command, and keep feeding while one is in flight.
                # The second condition is not optional -- a multi-cycle
                # command deasserts CS on its continuation cycles by
                # design (DDR5 drives CS_n high on cycle 2), so gating
                # purely on CS would truncate every one of them. Idle
                # DES cycles are skipped so they cannot be mistaken for
                # a command pattern.
                if cs_n == 0 or self._ca_in_flight:
                    for cmd, args in self._decode_ca_commands():
                        pkt = DFIControlPacket(
                            address=self._ca_bus_word(),
                            cke=_v(self.bus.cke),
                            cs_n=cs_n,
                            bank=args.get("bank", 0),
                            odt=_v(self.bus.odt),
                            reset_n=_v(self.bus.reset_n),
                            cmd=cmd,
                            ca_args=args,
                            timestamp_ns=ts,
                        )
                        self.command_q.append(pkt)
                        self.command_count += 1
                        self._recv(pkt)
            elif cs_n == 0:
                cmd = self._decode_command()
                if cmd != DRAMCommand.NOP:
                    pkt = DFIControlPacket(
                        address=_v(self.bus.address),
                        cke=_v(self.bus.cke),
                        cs_n=cs_n,
                        bank=_v(self.bus.bank),
                        cas_n=_v(self.bus.cas_n),
                        ras_n=_v(self.bus.ras_n),
                        we_n=_v(self.bus.we_n),
                        odt=_v(self.bus.odt),
                        reset_n=_v(self.bus.reset_n),
                        cmd=cmd,
                        timestamp_ns=ts,
                    )
                    self.command_q.append(pkt)
                    self.command_count += 1
                    self._recv(pkt)

            # --- Write data sub-interface ---
            wrdata_en = _v(self.bus.wrdata_en)
            if wrdata_en:
                pkt = DFIWriteDataPacket(
                    wrdata=_v(self.bus.wrdata),
                    wrdata_en=wrdata_en,
                    wrdata_mask=_v(self.bus.wrdata_mask),
                    timestamp_ns=ts,
                )
                self.write_data_q.append(pkt)
                self.write_data_count += 1
                self._recv(pkt)

            # --- Read data sub-interface ---
            rddata_valid = _v(self.bus.rddata_valid)
            if rddata_valid:
                pkt = DFIReadDataPacket(
                    rddata=_v(self.bus.rddata),
                    rddata_valid=rddata_valid,
                    timestamp_ns=ts,
                )
                self.read_data_q.append(pkt)
                self.read_data_count += 1
                self._recv(pkt)

    # ----- Convenience helpers -----

    def clear_queues(self) -> None:
        self.command_q.clear()
        self.write_data_q.clear()
        self.read_data_q.clear()

    def __str__(self) -> str:
        return (
            f"{self.title}: cmd={self.command_count} "
            f"wr={self.write_data_count} rd={self.read_data_count}"
        )
