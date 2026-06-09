# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: APB5Components
# Purpose: APB5 Monitor, Master and Slave BFM Classes — inherit from APB where practical
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-12-21

"""APB5 Monitor, Master and Slave BFM Classes with AMBA5 extensions.

Inheritance design (issue #15):
    - :class:`APB5Monitor` inherits :class:`APBMonitor` and overrides only
      the :meth:`_build_packet` hook to construct an :class:`APB5Packet`
      with USER / WAKEUP fields populated. The edge-detection loop is
      reused from APB unchanged.
    - :class:`APB5Master` inherits :class:`APBMaster` and overrides the
      extension hooks (``_default_randomizer_constraints``,
      ``_init_extension_signals``, ``_drive_extension_setup_phase``,
      ``_capture_extension_response``). It thereby gains APB4's queued +
      randomized transmit pipeline (``transmit_queue``,
      ``_transmit_pipeline``, ``_finish_xmit``, ``busy_send``,
      ``reset_bus``) for free. The legacy direct-drive ``_driver_send``
      from APB5Master is replaced by the inherited queued pipeline.
    - :class:`APB5Slave` keeps its own ``_monitor_recv`` for now. Its
      state machine (rising-edge PSEL+PENABLE detection, single-pass
      drive-then-deassert) diverges from APBSlave's clean two-phase
      (PSEL detect → ready_delay → PREADY assert → wait PENABLE → finish).
      Unifying the two requires deciding which state machine wins, which
      is a separate decision. Tracked as Phase B in issue #15.
"""

from collections import deque
from typing import Any

from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from cocotb_bus.monitors import BusMonitor

from ..apb.apb_components import APBMaster, APBMonitor
from ..shared.flex_randomizer import FlexRandomizer
from ..shared.memory_model import MemoryModel
from .apb5_packet import APB5Packet

# Direction mapping reused from APB convention
pwrite = ['READ', 'WRITE']

# APB5 signal sets — APB4 base + AMBA5 user / wakeup / parity extensions
apb5_signals = [
    "PSEL",
    "PWRITE",
    "PENABLE",
    "PADDR",
    "PWDATA",
    "PRDATA",
    "PREADY",
]

apb5_optional_signals = [
    "PPROT",
    "PSLVERR",
    "PSTRB",
    # APB5 extensions
    "PAUSER",
    "PWUSER",
    "PRUSER",
    "PBUSER",
    "PWAKEUP",
    # Parity signals (optional)
    "PWDATAPARITY",
    "PADDRPARITY",
    "PCTRLPARITY",
    "PRDATAPARITY",
    "PREADYPARITY",
    "PSLVERRPARITY",
]


# ----------------------------------------------------------------------
# APB5Monitor — inherits APBMonitor; overrides only the packet hook.
# ----------------------------------------------------------------------


class APB5Monitor(APBMonitor):
    """APB5 Monitor with AMBA5 extension support.

    Inherits the edge-detection loop from :class:`APBMonitor` and only
    overrides :meth:`_build_packet` to construct an :class:`APB5Packet`
    with USER / WAKEUP fields sampled from the bus.
    """

    def __init__(self, entity, title, prefix, clock, signals=None,
                 bus_width=32, addr_width=12,
                 auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
                 log=None, **kwargs):
        # APB5 has extended signal sets. If the caller didn't provide an
        # explicit override, supply the APB5 set before calling super().
        # APBMonitor's __init__ uses these as defaults when signals is None.
        if signals is None:
            self._signals = apb5_signals + apb5_optional_signals
            self._optional_signals = apb5_optional_signals
            # Pass `signals=self._signals` to ensure super() doesn't replace
            # them with the APB4 defaults.
            signals = self._signals

        # APB5-specific width parameters needed by the packet hook
        self.auser_width = auser_width
        self.wuser_width = wuser_width
        self.ruser_width = ruser_width
        self.buser_width = buser_width

        super().__init__(
            entity=entity, title=title, prefix=prefix, clock=clock,
            signals=signals, bus_width=bus_width, addr_width=addr_width,
            log=log, **kwargs,
        )

    def print(self, transaction):
        """Print transaction for debug (APB5 label)."""
        msg = f'{self.title} - APB5 Transaction #{self.count}: '
        msg += transaction.formatted(compact=True)
        self.log.debug(msg)

    def _build_packet(self, *, start_time, count, pwrite, paddr,
                      pwdata, prdata, pstrb, pprot, pslverr,
                      direction: str) -> Any:
        """Construct an APB5Packet with USER / WAKEUP fields sampled."""
        del direction  # APB5 doesn't need it; pwrite already carries direction
        pauser = (self.bus.PAUSER.value.integer
                  if self.is_signal_present('PAUSER') else 0)
        pwuser = (self.bus.PWUSER.value.integer
                  if self.is_signal_present('PWUSER') else 0)
        pruser = (self.bus.PRUSER.value.integer
                  if self.is_signal_present('PRUSER') else 0)
        pbuser = (self.bus.PBUSER.value.integer
                  if self.is_signal_present('PBUSER') else 0)
        wakeup = (self.bus.PWAKEUP.value.integer
                  if self.is_signal_present('PWAKEUP') else 0)

        return APB5Packet(
            data_width=self.bus_width,
            addr_width=self.addr_width,
            strb_width=self.strb_width,
            auser_width=self.auser_width,
            wuser_width=self.wuser_width,
            ruser_width=self.ruser_width,
            buser_width=self.buser_width,
            start_time=start_time,
            count=count,
            pwrite=pwrite,
            paddr=paddr,
            pwdata=pwdata,
            prdata=prdata,
            pstrb=pstrb,
            pprot=pprot,
            pslverr=pslverr,
            pauser=pauser,
            pwuser=pwuser,
            pruser=pruser,
            pbuser=pbuser,
            wakeup=wakeup,
        )


# ----------------------------------------------------------------------
# APB5Master — inherits APBMaster's queued+randomized pipeline.
# ----------------------------------------------------------------------


class APB5Master(APBMaster):
    """APB5 Master BFM.

    Inherits the queued + randomized transmit pipeline from
    :class:`APBMaster` (transmit_queue, _transmit_pipeline, _finish_xmit,
    busy_send, reset_bus, FlexRandomizer for PSEL/PENABLE delays). APB5
    extensions are layered in via the extension hooks:

    - :meth:`_init_extension_signals` zeroes PAUSER/PWUSER at construction.
    - :meth:`_drive_extension_setup_phase` drives PAUSER/PWUSER during the
      setup phase of every transaction.
    - :meth:`_capture_extension_response` samples PRUSER/PBUSER/PWAKEUP
      after PREADY rises.

    The convenience methods :meth:`write` and :meth:`read` build an
    :class:`APB5Packet` and forward to the inherited :meth:`send` (queued
    pipeline). Direct-drive callers should use :meth:`busy_send` if they
    need to wait for completion.
    """

    def __init__(self, entity, title, prefix, clock, signals=None,
                 bus_width=32, addr_width=12,
                 auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
                 randomizer=None, log=None, **kwargs):
        # Default to APB5 signal sets so APBMaster's __init__ picks them up.
        if signals is None:
            self._signals = apb5_signals + apb5_optional_signals
            self._optional_signals = apb5_optional_signals
            signals = self._signals

        # APB5 widths needed by extension hooks and packet construction
        self.auser_width = auser_width
        self.wuser_width = wuser_width
        self.ruser_width = ruser_width
        self.buser_width = buser_width
        self.count = 0

        super().__init__(
            entity=entity, title=title, prefix=prefix, clock=clock,
            signals=signals, bus_width=bus_width, addr_width=addr_width,
            randomizer=randomizer, log=log, **kwargs,
        )

    # ---- Extension hook overrides ----

    def _init_extension_signals(self):
        """Zero APB5 output extensions at construction time."""
        if self.is_signal_present('PPROT'):
            self.bus.PPROT.setimmediatevalue(0)
        if self.is_signal_present('PAUSER'):
            self.bus.PAUSER.setimmediatevalue(0)
        if self.is_signal_present('PWUSER'):
            self.bus.PWUSER.setimmediatevalue(0)

    def _drive_extension_setup_phase(self, transaction):
        """Drive PAUSER / PWUSER during the setup phase."""
        if self.is_signal_present('PAUSER'):
            self.bus.PAUSER.value = transaction.fields.get('pauser', 0)
        if self.is_signal_present('PWUSER'):
            self.bus.PWUSER.value = transaction.fields.get('pwuser', 0)

    def _capture_extension_response(self, transaction):
        """Sample PRUSER / PBUSER / PWAKEUP after PREADY rises."""
        if self.is_signal_present('PRUSER'):
            transaction.fields['pruser'] = self.bus.PRUSER.value.integer
        if self.is_signal_present('PBUSER'):
            transaction.fields['pbuser'] = self.bus.PBUSER.value.integer
        if self.is_signal_present('PWAKEUP'):
            transaction.fields['wakeup'] = self.bus.PWAKEUP.value.integer

    # ---- APB5-specific convenience methods ----

    async def write(self, address, data, strb=None, pprot=0, pauser=0, pwuser=0):
        """Perform an APB5 write transaction via the queued pipeline."""
        if strb is None:
            strb = (1 << self.strb_bits) - 1

        transaction = APB5Packet(
            data_width=self.bus_width,
            addr_width=self.addr_width,
            strb_width=self.strb_bits,
            auser_width=self.auser_width,
            wuser_width=self.wuser_width,
            ruser_width=self.ruser_width,
            buser_width=self.buser_width,
            pwrite=1,
            paddr=address,
            pwdata=data,
            pstrb=strb,
            pprot=pprot,
            pauser=pauser,
            pwuser=pwuser,
            start_time=get_sim_time('ns'),
        )

        await self.busy_send(transaction)
        return transaction

    async def read(self, address, pprot=0, pauser=0):
        """Perform an APB5 read transaction via the queued pipeline."""
        transaction = APB5Packet(
            data_width=self.bus_width,
            addr_width=self.addr_width,
            strb_width=self.strb_bits,
            auser_width=self.auser_width,
            wuser_width=self.wuser_width,
            ruser_width=self.ruser_width,
            buser_width=self.buser_width,
            pwrite=0,
            paddr=address,
            pprot=pprot,
            pauser=pauser,
            start_time=get_sim_time('ns'),
        )

        await self.busy_send(transaction)
        return transaction


# ----------------------------------------------------------------------
# APB5Slave — kept on its own state machine for now (see module docstring).
# ----------------------------------------------------------------------


class APB5Slave(BusMonitor):
    """APB5 Slave BFM with AMBA5 extension support.

    Class convention — Slave-via-BusMonitor:
        Inherits from ``cocotb_bus.monitors.BusMonitor`` even though this is a
        *responder* that drives output signals. ``cocotb_bus`` lacks a
        "responder" base class, so ``BusMonitor`` is reused as a chassis and
        the monitor loop is overridden to drive PREADY/PRDATA/PSLVERR (plus
        the APB5-specific PRUSER/PBUSER/error fields). Same pattern as
        ``APBSlave`` and ``GAXISlave``.

    Implementation note:
        Unlike :class:`APB5Monitor` and :class:`APB5Master`, this class does
        NOT inherit from :class:`APBSlave`. APBSlave and APB5Slave use
        structurally different ``_monitor_recv`` state machines (different
        edge detection, different drive-deassert cadence). Unifying them is
        tracked as Phase B in issue #15.
    """

    def __init__(self, entity, title, prefix, clock, registers, signals=None,
                 bus_width=32, addr_width=12,
                 auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
                 randomizer=None, log=None, error_overflow=False,
                 wakeup_generator=None, **kwargs):

        if signals:
            self._signals = signals
        else:
            self._signals = apb5_signals + apb5_optional_signals
            self._optional_signals = apb5_optional_signals

        if randomizer is None:
            self.randomizer = FlexRandomizer({
                'ready': ([(0, 1), (2, 5), (6, 10)], [5, 2, 1]),
                'error': ([(0, 0), (1, 1)], [10, 0]),
                'pruser': ([(0, (1 << ruser_width) - 1)], [1]),
                'pbuser': ([(0, (1 << buser_width) - 1)], [1]),
            })
        else:
            self.randomizer = randomizer

        prefix = prefix.rstrip('_')

        BusMonitor.__init__(self, entity, prefix, clock, **kwargs)
        self.clock = clock
        self.title = title
        self.prefix = prefix
        self.log = log or self.entity._log
        self.addr_width = addr_width
        self.bus_width = bus_width
        self.strb_bits = bus_width // 8
        self.addr_mask = (2**self.strb_bits - 1)
        self.num_lines = len(registers) // self.strb_bits
        self.count = 0
        self.error_overflow = error_overflow
        self.auser_width = auser_width
        self.wuser_width = wuser_width
        self.ruser_width = ruser_width
        self.buser_width = buser_width
        self.wakeup_generator = wakeup_generator

        # Create memory model
        self.mem = MemoryModel(
            num_lines=self.num_lines,
            bytes_per_line=self.strb_bits,
            log=self.log,
            preset_values=registers
        )
        self.sentQ = deque()

        # Initialize outputs
        self.bus.PRDATA.setimmediatevalue(0)
        self.bus.PREADY.setimmediatevalue(0)
        if self.is_signal_present('PSLVERR'):
            self.bus.PSLVERR.setimmediatevalue(0)
        if self.is_signal_present('PRUSER'):
            self.bus.PRUSER.setimmediatevalue(0)
        if self.is_signal_present('PBUSER'):
            self.bus.PBUSER.setimmediatevalue(0)
        if self.is_signal_present('PWAKEUP'):
            self.bus.PWAKEUP.setimmediatevalue(0)

        msg = f'APB5 Slave {self.title} initialized'
        self.log.debug(msg)

    def is_signal_present(self, signal_name):
        """Check if a signal is present on the bus."""
        return (hasattr(self.bus, signal_name) and
                getattr(self.bus, signal_name) is not None)

    def print(self, transaction):
        """Print transaction for debug."""
        msg = f'{self.title} - APB5 Transaction #{self.count}: '
        msg += transaction.formatted(compact=True)
        self.log.debug(msg)

    async def set_wakeup(self, value):
        """Set the PWAKEUP signal."""
        if self.is_signal_present('PWAKEUP'):
            self.bus.PWAKEUP.value = value

    async def _monitor_recv(self):
        """Handle APB5 slave transactions."""
        prev_penable = 0

        while True:
            await RisingEdge(self.clock)

            curr_psel = (self.bus.PSEL.value.integer
                         if self.bus.PSEL.value.is_resolvable else 0)
            curr_penable = (self.bus.PENABLE.value.integer
                            if self.bus.PENABLE.value.is_resolvable else 0)

            # Detect setup phase (PSEL without PENABLE)
            if curr_psel and not curr_penable:
                pass  # Setup phase - no action needed

            # Detect access phase start (PSEL + PENABLE rising)
            if curr_psel and curr_penable and not prev_penable:
                # Get random delays and user signal values
                rand_values = self.randomizer.next()
                ready_delay = rand_values.get('ready', 0)
                error_val = rand_values.get('error', 0)
                pruser = rand_values.get('pruser', 0)
                pbuser = rand_values.get('pbuser', 0)

                address = self.bus.PADDR.value.integer
                direction = pwrite[self.bus.PWRITE.value.integer]
                loc_pwrite = self.bus.PWRITE.value.integer

                # Calculate memory line
                line = (address & ~self.addr_mask) // self.strb_bits

                # Check for address overflow
                if line >= self.num_lines and self.error_overflow:
                    error_val = 1

                # Handle read/write
                if direction == 'WRITE':
                    wdata = self.bus.PWDATA.value.integer
                    strb = (self.bus.PSTRB.value.integer
                            if self.is_signal_present('PSTRB') else
                            (1 << self.strb_bits) - 1)

                    if line < self.num_lines:
                        self.mem.write(line, wdata, strb)
                    rdata = 0
                else:
                    if line < self.num_lines:
                        rdata = self.mem.read(line)
                    else:
                        rdata = 0
                    wdata = 0
                    strb = 0

                # Get APB5 input user signals
                pauser = (self.bus.PAUSER.value.integer
                          if self.is_signal_present('PAUSER') else 0)
                pwuser = (self.bus.PWUSER.value.integer
                          if self.is_signal_present('PWUSER') else 0)
                pprot = (self.bus.PPROT.value.integer
                         if self.is_signal_present('PPROT') else 0)

                # Apply ready delay
                for _ in range(ready_delay):
                    await RisingEdge(self.clock)

                # Set outputs
                self.bus.PRDATA.value = rdata
                self.bus.PREADY.value = 1
                if self.is_signal_present('PSLVERR'):
                    self.bus.PSLVERR.value = error_val
                if self.is_signal_present('PRUSER'):
                    self.bus.PRUSER.value = pruser
                if self.is_signal_present('PBUSER'):
                    self.bus.PBUSER.value = pbuser

                self.count += 1

                # Create transaction record
                transaction = APB5Packet(
                    data_width=self.bus_width,
                    addr_width=self.addr_width,
                    strb_width=self.strb_bits,
                    auser_width=self.auser_width,
                    wuser_width=self.wuser_width,
                    ruser_width=self.ruser_width,
                    buser_width=self.buser_width,
                    start_time=get_sim_time('ns'),
                    count=self.count,
                    pwrite=loc_pwrite,
                    paddr=address,
                    pwdata=wdata,
                    prdata=rdata,
                    pstrb=strb,
                    pprot=pprot,
                    pslverr=error_val,
                    pauser=pauser,
                    pwuser=pwuser,
                    pruser=pruser,
                    pbuser=pbuser,
                )

                self.sentQ.append(transaction)
                self._recv(transaction)
                self.print(transaction)

                # Wait for transaction completion
                await RisingEdge(self.clock)
                self.bus.PREADY.value = 0
                if self.is_signal_present('PSLVERR'):
                    self.bus.PSLVERR.value = 0

            prev_penable = curr_penable
