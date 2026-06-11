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

# Error sub-interface (v3.0+). Present on the shim for all tests but
# only sampled when the BFM is configured for a version that defines it.
_ERROR_SIGNALS = ("error", "error_info")

# CRC alert (v3.0+, DDR4). Present on the shim for all tests; samples
# only meaningful when memory_type=DDR4 and version >= V3_1.
_CRC_SIGNALS = ("crc_alert",)

# Update interface (v2.1+ for ctrlupd, v3.0+ for phyupd).
_UPDATE_SIGNALS = ("ctrlupd_req", "ctrlupd_ack", "phyupd_req", "phyupd_ack")

# Training interface (v3.0+). Single PHY-driven activity flag plus a
# phase code; per the LiteDRAM survey, training is by-circuit not by
# sequential phase, so the phase distinction lives in event data.
_TRAINING_SIGNALS = ("training_active", "training_phase")

# CA parity (v3.0+, DDR4 only). MC-driven parity bit, PHY-driven error
# check. Always-present on the shim regardless of memory type.
_CA_PARITY_SIGNALS = ("parity_in", "parity_check")

# Frequency-change handshake (v2.1+; v4.0 added protocol variants).
_FREQ_CHANGE_SIGNALS = ("freq_change_req", "freq_change_ack", "freq_change_protocol")


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
        + list(_CRC_SIGNALS)
        + list(_UPDATE_SIGNALS)
        + list(_TRAINING_SIGNALS)
        + list(_CA_PARITY_SIGNALS)
        + list(_FREQ_CHANGE_SIGNALS)
    )
    _optional_signals: List[str] = []

    def __init__(
        self,
        entity,
        clock,
        side: str = "phy",
        title: Optional[str] = None,
        **kwargs,
    ):
        if side not in ("mc", "phy"):
            raise ValueError(f"side must be 'mc' or 'phy', got {side!r}")
        self.side = side
        self.title = title or f"DFIMonitor[{side}]"

        prefix = f"{side}_dfi"
        BusMonitor.__init__(self, entity, prefix, clock, **kwargs)
        self.clock = clock
        self.log = self.entity._log

        # Per-sub-interface capture queues. The default _recvQ from
        # BusMonitor still works (every packet goes there too), but
        # consumers usually want them split.
        self.command_q: Deque[DFIControlPacket] = deque()
        self.write_data_q: Deque[DFIWriteDataPacket] = deque()
        self.read_data_q: Deque[DFIReadDataPacket] = deque()

        self.command_count = 0
        self.write_data_count = 0
        self.read_data_count = 0

    # ----- Decoders -----

    def _decode_command(self) -> DRAMCommand:
        ras = _v(self.bus.ras_n)
        cas = _v(self.bus.cas_n)
        we  = _v(self.bus.we_n)
        return _CMD_DECODE.get((ras, cas, we), DRAMCommand.NOP)

    # ----- Sampling loop -----

    async def _monitor_recv(self):
        while True:
            await FallingEdge(self.clock)
            ts = get_sim_time("ns")

            # --- Command sub-interface: capture when CS is asserted ---
            cs_n = _v(self.bus.cs_n)
            if cs_n == 0:
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
