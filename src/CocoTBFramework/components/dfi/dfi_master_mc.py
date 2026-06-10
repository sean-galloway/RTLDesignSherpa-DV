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

from .dfi_monitor import _COMMAND_SIGNALS, _READ_DATA_SIGNALS, _WRITE_DATA_SIGNALS


class DFIMasterMC(BusDriver):
    """MC-side DFI driver.

    Args:
        entity:   The cocotb DUT handle.
        clock:    The DFI clock signal.
        side:     Currently only ``"mc"`` (the MC drives the master role).
                  The argument exists for symmetry with :class:`DFIMonitor`.
        title:    Optional title for log messages.
    """

    _signals = list(_COMMAND_SIGNALS) + list(_WRITE_DATA_SIGNALS) + list(_READ_DATA_SIGNALS)
    _optional_signals: list = []

    def __init__(
        self,
        entity,
        clock,
        side: str = "mc",
        title: Optional[str] = None,
        **kwargs,
    ):
        if side != "mc":
            raise ValueError(
                f"DFIMasterMC drives the MC side only, got side={side!r}"
            )
        self.side = side
        self.title = title or "DFIMasterMC"

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

    # ----- Internal: drive a 1-cycle command pulse -----

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

    # ----- Command-interface primitives -----

    async def activate(self, bank: int, row: int) -> None:
        """ACT bank → row. (ras_n=0, cas_n=1, we_n=1)"""
        await self._drive_command(ras_n=0, cas_n=1, we_n=1, bank=bank, address=row)

    async def read(self, bank: int, col: int, auto_precharge: bool = False) -> None:
        """RD bank, col. (ras_n=1, cas_n=0, we_n=1)

        ``auto_precharge`` sets address bit 10 per the JEDEC convention.
        """
        addr = col | (1 << 10) if auto_precharge else col
        await self._drive_command(ras_n=1, cas_n=0, we_n=1, bank=bank, address=addr)

    async def write(self, bank: int, col: int, auto_precharge: bool = False) -> None:
        """WR bank, col. (ras_n=1, cas_n=0, we_n=0)"""
        addr = col | (1 << 10) if auto_precharge else col
        await self._drive_command(ras_n=1, cas_n=0, we_n=0, bank=bank, address=addr)

    async def precharge(self, bank: int = 0, all_banks: bool = False) -> None:
        """PRE bank (or PREA all-banks). (ras_n=0, cas_n=1, we_n=0)"""
        addr = (1 << 10) if all_banks else 0
        await self._drive_command(ras_n=0, cas_n=1, we_n=0, bank=bank, address=addr)

    async def refresh(self) -> None:
        """REF (all-bank refresh). (ras_n=0, cas_n=0, we_n=1)"""
        await self._drive_command(ras_n=0, cas_n=0, we_n=1)

    async def nop(self, cycles: int = 1) -> None:
        """Idle for ``cycles`` clocks.

        Use between primitives to satisfy tRCD / CWL / etc. — the master
        does not insert spacing automatically (the slave-side DramStateModel
        flags violations if the caller is too aggressive).
        """
        for _ in range(cycles):
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
