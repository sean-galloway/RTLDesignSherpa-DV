# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Gear-ratio adapter for N-phase DFI sources.

Memory controllers commonly emit DFI signals at a 1:N gear ratio
relative to the DRAM clock — one MC cycle carries N phases of DFI
commands that the PHY serializes onto the DRAM bus. LiteDRAM DDR3
on Xilinx Series-7 is 1:4; LiteDRAM DDR3 on Lattice ECP5 is 1:2;
LiteDRAM DDR2 is 1:2. Standard gear ratios are 1, 2, 4, 8, 16.

:class:`DFIPhaseAdapter` bridges an N-phase source to a 1-phase
:class:`DFISlavePHY` consumer. It maintains an internal queue of
phase dicts; the test (or a future LiteDRAM RTL sampler) feeds it
N dicts per MC cycle; the adapter's coroutine drains one dict per
DFI clock cycle, driving the 1-phase shim signals.

Usage
-----

Pure Python feed (for proof-of-life and test driving)::

    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=4, dfi_clock=dut.dfi_clk,
    )
    cocotb.start_soon(adapter.run())

    # On each "MC cycle", feed 4 phase dicts
    adapter.feed([
        {"cs_n": 0, "ras_n": 0, "cas_n": 1, "we_n": 1,
         "bank": 1, "address": 0x100},   # phase 0: ACT
        {"cs_n": 1},                      # phase 1: NOP
        {"cs_n": 0, "ras_n": 1, "cas_n": 0, "we_n": 1,
         "bank": 1, "address": 0x04},    # phase 2: RD
        {"cs_n": 1},                      # phase 3: NOP
    ])

Future RTL-sampled mode (for LiteDRAM co-sim) — a separate coroutine
samples ``mc_dfi_<sig>_p{0..N-1}`` signals each MC clock and calls
:meth:`feed`; the adapter handles the demuxing.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, Iterable, Optional, Set

from cocotb.triggers import RisingEdge


# Valid gear ratios per the user spec; constrains the adapter to
# sensible values for DDR1-5 / LPDDR controllers.
VALID_PHASE_COUNTS: Set[int] = {1, 2, 4, 8, 16}


# Signals the adapter drives on the 1-phase shim. These are the
# MC-to-PHY direction signals on the command + write-data interfaces;
# read-data and update/training/error etc. are driven by the slave
# side and aren't relevant to this adapter.
_DRIVEN_SIGNALS = (
    # Command interface
    "address", "bank", "cas_n", "ras_n", "we_n", "cs_n",
    "cke", "odt", "reset_n",
    # Write data interface
    "wrdata", "wrdata_en", "wrdata_mask",
    # Read data hint (MC-side rddata_en)
    "rddata_en",
)


class DFIPhaseAdapter:
    """Gear-ratio adapter: N-phase DFI source → 1-phase DFI consumer.

    Args:
        dut:           cocotb DUT handle whose signals the adapter drives.
        dest_prefix:   signal prefix on the DUT for the 1-phase output
                       (e.g., ``"mc_dfi"`` to drive ``dut.mc_dfi_address``,
                       ``dut.mc_dfi_bank``, etc.).
        n_phases:      gear ratio. Must be one of {1, 2, 4, 8, 16}.
        dfi_clock:     the DFI clock signal — the adapter advances one
                       phase per rising edge.
        idle_values:   optional dict overriding the default
                       deselected-idle signal values driven between
                       fed phases.
    """

    def __init__(
        self,
        dut: Any,
        dest_prefix: str,
        n_phases: int,
        dfi_clock: Any,
        idle_values: Optional[Dict[str, int]] = None,
    ):
        if n_phases not in VALID_PHASE_COUNTS:
            raise ValueError(
                f"n_phases must be one of {sorted(VALID_PHASE_COUNTS)}, "
                f"got {n_phases}"
            )
        self.dut = dut
        self.dest_prefix = dest_prefix
        self.n_phases = n_phases
        self.dfi_clock = dfi_clock

        # Default idle: deselected (CS_n high), no data, no read hint.
        # Matches what the MasterMC._init_idle uses so the bus naturally
        # idles between fed phases.
        self._idle = {
            "address": 0, "bank": 0,
            "cs_n": 1, "ras_n": 1, "cas_n": 1, "we_n": 1,
            "cke": 1, "odt": 0, "reset_n": 1,
            "wrdata": 0, "wrdata_en": 0, "wrdata_mask": 0,
            "rddata_en": 0,
        }
        if idle_values:
            self._idle.update(idle_values)

        # Phase queue. Each entry is a dict; only keys present override
        # the idle defaults for that cycle.
        self._queue: Deque[Dict[str, int]] = deque()

        # Stats
        self.phases_driven = 0
        self.idle_cycles = 0

    # ----- Public API -----

    def feed(self, phases: Iterable[Dict[str, int]]) -> None:
        """Queue N phase dicts to be driven on subsequent DFI cycles.

        Each phase dict provides per-signal overrides against the
        adapter's idle defaults. Empty dicts produce idle cycles.

        Args:
            phases: iterable of dicts. Must have exactly ``n_phases``
                entries (we enforce this so callers don't accidentally
                drift the gear ratio mid-stream).
        """
        phases = list(phases)
        if len(phases) != self.n_phases:
            raise ValueError(
                f"feed() expects exactly {self.n_phases} phase dicts "
                f"(matches n_phases={self.n_phases}), got {len(phases)}"
            )
        self._queue.extend(phases)

    def feed_idle(self) -> None:
        """Queue ``n_phases`` empty dicts — useful for filling idle MC cycles."""
        self._queue.extend([{} for _ in range(self.n_phases)])

    @property
    def queued_phases(self) -> int:
        """Number of phase dicts waiting in the queue."""
        return len(self._queue)

    # ----- Run loop -----

    async def run(self) -> None:
        """Drive one phase per DFI clock edge forever.

        Spawns once per adapter; call::

            cocotb.start_soon(adapter.run())

        before any feed() calls (the adapter samples on rising edges
        only, so a few cycles of idle at start are fine).
        """
        # Initialize all outputs to idle on startup so the bus
        # has a known state before the first phase lands.
        self._drive(self._idle)

        while True:
            await RisingEdge(self.dfi_clock)
            if self._queue:
                phase = self._queue.popleft()
                self._drive_phase(phase)
                self.phases_driven += 1
            else:
                self._drive(self._idle)
                self.idle_cycles += 1

    # ----- Internal: signal drives -----

    def _drive_phase(self, phase: Dict[str, int]) -> None:
        """Drive idle values, then overlay phase overrides."""
        merged = {**self._idle, **phase}
        self._drive(merged)

    def _drive(self, values: Dict[str, int]) -> None:
        """Set every driven signal to its corresponding value."""
        for sig_name in _DRIVEN_SIGNALS:
            if sig_name not in values:
                continue
            handle = getattr(self.dut, f"{self.dest_prefix}_{sig_name}")
            handle.value = values[sig_name]

    # ----- Convenience -----

    def __str__(self) -> str:
        return (
            f"DFIPhaseAdapter(n_phases={self.n_phases}, "
            f"queued={self.queued_phases}, "
            f"phases_driven={self.phases_driven}, "
            f"idle_cycles={self.idle_cycles})"
        )
