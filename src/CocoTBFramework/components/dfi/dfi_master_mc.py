# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""MC-side DFI driver — primitive API (issue #16).

:class:`DFIMasterMC` is a thin cocotb_bus.BusDriver subclass that
exposes one async primitive per DFI command (``activate``, ``read``,
``write``, ``precharge``, ``refresh``) plus a ``write_data`` beat
driver. Each primitive drives the wire for one clock cycle and then
returns the bus to deselected idle.

The MVP API is deliberately primitive — no transaction queue, no
randomizer, no auto-spacing for tRCD / CWL. The caller is expected
to insert delays via ``nop(cycles=…)`` between primitives. This makes
the BFM a faithful "what you drive is what hits the wire" model for
verifying MC RTL, and lets the slave-side timing checker
(:class:`DramStateModel`) catch any caller-induced violations.

For DDR3 / DDR2 / DDR1 the (ras_n, cas_n, we_n) encoding follows
JESD79-3F Table 67 — same table the monitor decodes against, so a
master + monitor pair round-trips cleanly across the shim.
"""

from __future__ import annotations

from typing import Optional

from cocotb.triggers import RisingEdge
from cocotb_bus.drivers import BusDriver

from .dfi_monitor import (
    _ALERT_SIGNALS,
    _CA_PARITY_SIGNALS,
    _COMMAND_SIGNALS,
    _DISCONNECT_SIGNALS,
    _ERROR_SIGNALS,
    _LOW_POWER_SIGNALS,
    _PHY_MASTER_SIGNALS,
    _READ_DATA_SIGNALS,
    _STATUS_SIGNALS,
    _TRAINING_SIGNALS,
    _UPDATE_SIGNALS,
    _WRITE_DATA_SIGNALS,
)


class DFIMasterMC(BusDriver):
    """MC-side DFI driver.

    Args:
        entity:   The cocotb DUT handle.
        clock:    The DFI clock signal.
        side:     Currently only ``"mc"`` (the MC drives the master role).
                  The argument exists for symmetry with :class:`DFIMonitor`.
        title:    Optional title for log messages.
        memory_type: Optional :class:`~.dfi_signals.MemoryType`; defaults
                  to DDR3. Pass LPDDR2/LPDDR3 so the primitives drive the
                  20-bit CA word on ``dfi_address`` instead of ras/cas/we.
    """

    _signals = (
        list(_COMMAND_SIGNALS)
        + list(_WRITE_DATA_SIGNALS)
        + list(_READ_DATA_SIGNALS)
        + list(_ERROR_SIGNALS)   # MC observes; PHY-driven
        + list(_ALERT_SIGNALS)   # MC observes dfi_alert_n; PHY-driven
        + list(_UPDATE_SIGNALS)  # MC drives ctrlupd_req/phyupd_ack
        + list(_TRAINING_SIGNALS)  # MC drives *_en; observes *_req/resp
        + list(_CA_PARITY_SIGNALS)  # MC drives parity_in; observes parity_error
        + list(_STATUS_SIGNALS)  # MC drives init_start/ratios; observes init_complete
        + list(_LOW_POWER_SIGNALS)  # MC drives lp_*_req/wakeup; observes lp_ack
        + list(_DISCONNECT_SIGNALS)  # MC drives disconnect_error
        + list(_PHY_MASTER_SIGNALS)  # MC drives phymstr_ack; observes req
    )
    _optional_signals: list = []

    def __init__(
        self,
        entity,
        clock,
        side: str = "mc",
        title: Optional[str] = None,
        memory_type=None,
        **kwargs,
    ):
        if side != "mc":
            raise ValueError(
                f"DFIMasterMC drives the MC side only, got side={side!r}"
            )
        self.side = side
        self.title = title or "DFIMasterMC"

        # memory_type defaults to a DDR-family member that uses the
        # ras/cas/we encoding. LPDDR2/3 callers should pass
        # MemoryType.LPDDR2 (or LPDDR3) so the primitives drive the
        # 20-bit CA word on dfi_address instead.
        from .dfi_signals import MemoryType
        self.memory_type = memory_type or MemoryType.DDR3

        BusDriver.__init__(self, entity, f"{side}_dfi", clock, **kwargs)
        self.clock = clock
        self.log = self.entity._log
        self._init_idle()

    # ----- Idle drive -----

    def _init_idle(self) -> None:
        """Drive all MC-side outputs to deselected idle.

        Called once at construction. The primitives below return signals
        to this state after each transaction so the bus naturally idles
        between commands.
        """
        self.bus.address.value = 0
        self.bus.bank.value = 0
        self.bus.cs_n.value = 1   # deselected (active low)
        self.bus.ras_n.value = 1
        self.bus.cas_n.value = 1
        self.bus.we_n.value = 1
        self.bus.cke.value = 1    # clock enabled
        self.bus.odt.value = 0
        self.bus.reset_n.value = 1
        self.bus.wrdata.value = 0
        self.bus.wrdata_en.value = 0
        self.bus.wrdata_mask.value = 0
        self.bus.rddata_en.value = 0
        # Update-interface MC-driven outputs
        self.bus.ctrlupd_req.value = 0
        self.bus.phyupd_ack.value = 0
        # CA parity MC-driven output
        self.bus.parity_in.value = 0
        # Status-interface MC-driven outputs. init_start low; the
        # frequency-change protocol is init_start asserted during
        # normal operation (there is no dedicated request wire).
        self.bus.init_start.value = 0
        self.bus.freq_ratio.value = 0    # 'b00 = 1:1 MC:PHY
        self.bus.frequency.value = 0
        # Training MC-driven enables
        self.bus.rdlvl_en.value = 0
        self.bus.rdlvl_gate_en.value = 0
        self.bus.wrlvl_en.value = 0
        # Low-power MC-driven requests + wakeup encoding
        self.bus.lp_ctrl_req.value = 0
        self.bus.lp_data_req.value = 0
        self.bus.lp_wakeup.value = 0
        # Disconnect flag + PHY-Master ack
        self.bus.disconnect_error.value = 0
        self.bus.phymstr_ack.value = 0

    # ----- Internal: family check -----

    def _is_lpddr2_family(self) -> bool:
        from .dfi_signals import MemoryType
        return self.memory_type in (MemoryType.LPDDR2, MemoryType.LPDDR3)

    # ----- Internal: drive a 1-cycle command pulse (DDR-style) -----

    async def _drive_command(
        self,
        *,
        ras_n: int,
        cas_n: int,
        we_n: int,
        bank: int = 0,
        address: int = 0,
    ) -> None:
        self.bus.cs_n.value = 0
        self.bus.ras_n.value = ras_n
        self.bus.cas_n.value = cas_n
        self.bus.we_n.value = we_n
        self.bus.bank.value = bank
        self.bus.address.value = address
        await RisingEdge(self.clock)
        # Return to deselected idle
        self.bus.cs_n.value = 1
        self.bus.ras_n.value = 1
        self.bus.cas_n.value = 1
        self.bus.we_n.value = 1

    # ----- Internal: drive a 1-cycle LPDDR2/3 CA command -----

    async def _drive_lpddr2_command(self, ca_word: int) -> None:
        """Drive the 20-bit CA word on dfi_address; hold ras/cas/we/bank
        at idle per DFI v2.1 Table 1 for LPDDR2 memory."""
        self.bus.cs_n.value = 0
        self.bus.address.value = ca_word
        # ras_n/cas_n/we_n/bank already idle from init_idle / return path
        self.bus.bank.value = 0
        self.bus.ras_n.value = 1
        self.bus.cas_n.value = 1
        self.bus.we_n.value = 1
        await RisingEdge(self.clock)
        self.bus.cs_n.value = 1
        self.bus.address.value = 0

    # ----- Command-interface primitives -----

    async def activate(self, bank: int, row: int) -> None:
        """ACT bank → row.

        DDR3-family: (ras_n=0, cas_n=1, we_n=1)
        LPDDR2/3:    CA opcode CA0r=0, CA1r=1 (JESD209-2F Table 60);
                     bank on CA9r:CA7r, row packed into dfi_address
        """
        if self._is_lpddr2_family():
            from .dfi_packet import DRAMCommand
            from .lpddr_ca import encode_lpddr2_ca
            ca = encode_lpddr2_ca(DRAMCommand.ACT, bank=bank, row=row)
            await self._drive_lpddr2_command(ca)
            return
        await self._drive_command(ras_n=0, cas_n=1, we_n=1, bank=bank, address=row)

    async def read(self, bank: int, col: int, auto_precharge: bool = False) -> None:
        """RD bank, col.

        DDR3-family: (ras_n=1, cas_n=0, we_n=1), addr[10]=AP
        LPDDR2/3:    CA opcode CA0r=1, CA1r=0, CA2r=1; AP on CA0f
        """
        if self._is_lpddr2_family():
            from .dfi_packet import DRAMCommand
            from .lpddr_ca import encode_lpddr2_ca
            ca = encode_lpddr2_ca(
                DRAMCommand.RD, bank=bank, col=col,
                auto_precharge=auto_precharge,
            )
            await self._drive_lpddr2_command(ca)
            return
        addr = col | (1 << 10) if auto_precharge else col
        await self._drive_command(ras_n=1, cas_n=0, we_n=1, bank=bank, address=addr)

    async def write(self, bank: int, col: int, auto_precharge: bool = False) -> None:
        """WR bank, col.

        DDR3-family: (ras_n=1, cas_n=0, we_n=0)
        LPDDR2/3:    CA opcode CA0r=1, CA1r=0, CA2r=0; AP on CA0f
        """
        if self._is_lpddr2_family():
            from .dfi_packet import DRAMCommand
            from .lpddr_ca import encode_lpddr2_ca
            ca = encode_lpddr2_ca(
                DRAMCommand.WR, bank=bank, col=col,
                auto_precharge=auto_precharge,
            )
            await self._drive_lpddr2_command(ca)
            return
        addr = col | (1 << 10) if auto_precharge else col
        await self._drive_command(ras_n=1, cas_n=0, we_n=0, bank=bank, address=addr)

    async def precharge(self, bank: int = 0, all_banks: bool = False) -> None:
        """PRE bank (or PREA all-banks).

        DDR3-family: (ras_n=0, cas_n=1, we_n=0)
        LPDDR2/3:    CA opcode CA0r=1, CA1r=1, CA2r=0, CA3r=1;
                     AB on CA4r, bank on CA9r:CA7r
        """
        if self._is_lpddr2_family():
            from .dfi_packet import DRAMCommand
            from .lpddr_ca import encode_lpddr2_ca
            ca = encode_lpddr2_ca(
                DRAMCommand.PRE, bank=bank, all_banks=all_banks,
            )
            await self._drive_lpddr2_command(ca)
            return
        addr = (1 << 10) if all_banks else 0
        await self._drive_command(ras_n=0, cas_n=1, we_n=0, bank=bank, address=addr)

    async def refresh(self) -> None:
        """REF (all-bank refresh).

        DDR3-family: (ras_n=0, cas_n=0, we_n=1)
        LPDDR2/3:    CA opcode CA0r=0, CA1r=0, CA2r=1; CA3r=1 (all-bank,
                     matching DFISlavePHY's REF -> all-bank handling; add
                     an ``all_banks=False`` arg here if per-bank REFpb is
                     ever needed)
        """
        if self._is_lpddr2_family():
            from .dfi_packet import DRAMCommand
            from .lpddr_ca import encode_lpddr2_ca
            ca = encode_lpddr2_ca(DRAMCommand.REF, all_banks=True)
            await self._drive_lpddr2_command(ca)
            return
        await self._drive_command(ras_n=0, cas_n=0, we_n=1)

    async def nop(self, cycles: int = 1) -> None:
        """Idle for ``cycles`` clocks.

        Use between primitives to satisfy tRCD / CWL / etc. — the master
        does not insert spacing automatically (the slave-side DramStateModel
        flags violations if the caller is too aggressive).
        """
        for _ in range(cycles):
            await RisingEdge(self.clock)

    # ----- Self-refresh / power-down primitives (CKE-edge commands) -----

    async def self_refresh_entry(self) -> None:
        """SRE: the REF encoding sampled with CKE falling. All banks
        must be precharged first (the slave's model checks)."""
        self.bus.cs_n.value = 0
        self.bus.ras_n.value = 0
        self.bus.cas_n.value = 0
        self.bus.we_n.value = 1
        self.bus.cke.value = 0
        await RisingEdge(self.clock)
        self.bus.cs_n.value = 1
        self.bus.ras_n.value = 1
        self.bus.cas_n.value = 1
        self.bus.we_n.value = 1
        # CKE stays low for the duration of self-refresh.

    async def self_refresh_exit(self) -> None:
        """SRX: CKE rising with the bus deselected. Row commands must
        then wait tXS = tRFC + 10 ns (the slave's model checks)."""
        self.bus.cs_n.value = 1
        self.bus.cke.value = 1
        await RisingEdge(self.clock)

    async def powerdown_entry(self) -> None:
        """PDE: CKE falling with the bus deselected/NOP. Legal with
        open rows (active power-down)."""
        self.bus.cs_n.value = 1
        self.bus.cke.value = 0
        await RisingEdge(self.clock)

    async def powerdown_exit(self) -> None:
        """PDX: CKE rising (bus deselected)."""
        self.bus.cs_n.value = 1
        self.bus.cke.value = 1
        await RisingEdge(self.clock)

    # ----- Write-data-interface primitives -----

    async def write_data(self, data: int, mask: int = 0) -> None:
        """Drive one beat of write data on the next clock edge."""
        self.bus.wrdata.value = data
        self.bus.wrdata_mask.value = mask
        self.bus.wrdata_en.value = 1
        await RisingEdge(self.clock)
        self.bus.wrdata_en.value = 0

    async def write_burst(self, beats, masks=None) -> None:
        """Drive a burst of consecutive write-data beats.

        For BL=8 with the canonical K=2 PHY ratio this is 4 beats; for
        BL=1 (the MVP-loopback case) it's just 1. The slave's
        DFISlavePHY queues writes at consecutive flat addresses
        (col, col+1, …, col+N-1) starting from the WR command's col.

        Args:
            beats: iterable of ints, one per DFI beat.
            masks: optional iterable of mask ints; defaults to 0 (no mask)
                   for every beat.
        """
        beats = list(beats)
        if masks is None:
            masks = [0] * len(beats)
        else:
            masks = list(masks)
            if len(masks) != len(beats):
                raise ValueError(
                    f"masks length {len(masks)} != beats length {len(beats)}"
                )
        for data, mask in zip(beats, masks):
            await self.write_data(data, mask)

    # ----- Read-data hint -----

    def set_rddata_en(self, value: int = 1) -> None:
        """Set the rddata_en hint (MC → PHY).

        Stays asserted until the caller flips it back. Doesn't wait —
        callers usually pair it with ``nop(cycles=CL)`` then assert/
        deassert around the expected read-data window.
        """
        self.bus.rddata_en.value = value

    # ----- Update-interface MC drives -----

    def set_ctrlupd_req(self, value: int = 1) -> None:
        """Drive the MC-initiated update request signal."""
        self.bus.ctrlupd_req.value = value

    def set_phyupd_ack(self, value: int = 1) -> None:
        """Drive the MC's grant of a PHY-initiated update."""
        self.bus.phyupd_ack.value = value

    def set_parity_in(self, value: int) -> None:
        """Drive the MC-computed CA parity bit (v2.1.1 DDR3 DIMM
        parity; DDR4 CA parity from v3.0)."""
        self.bus.parity_in.value = value

    # ----- Status interface: init + frequency change -----

    def set_init_start(self, value: int = 1) -> None:
        """Drive dfi_init_start.

        At initialization this validates freq_ratio (and friends);
        during normal operation (init_complete high) asserting it IS
        the frequency-change request — the PHY accepts by de-asserting
        dfi_init_complete within tinit_start cycles, or the offer is
        withdrawn. There is no dedicated freq-change wire in any DFI
        version.
        """
        self.bus.init_start.value = value

    def set_freq_ratio(self, ratio: int) -> None:
        """Drive dfi_freq_ratio: 'b00=1:1, 'b01=1:2, 'b10=1:4.
        Must only change while dfi_init_start is low (or at init)."""
        self.bus.freq_ratio.value = ratio

    def set_frequency(self, code: int) -> None:
        """Drive the dfi_frequency indicator (v4.0+; up to 32 system-
        defined encodings, 64 from v5.x). Must be valid and stable
        while dfi_init_start is asserted."""
        self.bus.frequency.value = code

    def request_freq_change(self, frequency_code: int = 0,
                            freq_ratio: int = 0) -> None:
        """Convenience: drive the indicator wires then assert
        init_start (the spec's frequency-change request sequence)."""
        self.bus.frequency.value = frequency_code
        self.bus.freq_ratio.value = freq_ratio
        self.bus.init_start.value = 1

    # ----- Training MC-side enables (v2.1-v4.0) -----

    def set_rdlvl_en(self, value: int = 1) -> None:
        """Enable read-leveling training (dfi_rdlvl_en)."""
        self.bus.rdlvl_en.value = value

    def set_rdlvl_gate_en(self, value: int = 1) -> None:
        """Enable gate training (dfi_rdlvl_gate_en)."""
        self.bus.rdlvl_gate_en.value = value

    def set_wrlvl_en(self, value: int = 1) -> None:
        """Enable write-leveling training (dfi_wrlvl_en)."""
        self.bus.wrlvl_en.value = value

    # ----- Low power control -----

    def set_lp_ctrl_req(self, value: int = 1, wakeup: int = 0) -> None:
        """Offer a control-interface low-power window (v3.1+ split
        request); ``wakeup`` drives the shared dfi_lp_wakeup encoding."""
        self.bus.lp_wakeup.value = wakeup
        self.bus.lp_ctrl_req.value = value

    def set_lp_data_req(self, value: int = 1, wakeup: int = 0) -> None:
        """Offer a data-interface low-power window (v3.1+)."""
        self.bus.lp_wakeup.value = wakeup
        self.bus.lp_data_req.value = value

    # ----- Disconnect / PHY-Master -----

    def set_disconnect_error(self, active: int) -> None:
        """Drive dfi_disconnect_error (v4.0+): qualifies an in-flight
        handshake break as QOS (0) or error (1). The break itself is
        performed by de-asserting the handshake's request/ack wire."""
        self.bus.disconnect_error.value = active

    def set_phymstr_ack(self, active: int) -> None:
        """Drive the MC's grant of PHY bus takeover (dfi_phymstr_ack;
        the wire is named dfi_phymngd_ack from v5.2)."""
        self.bus.phymstr_ack.value = active
