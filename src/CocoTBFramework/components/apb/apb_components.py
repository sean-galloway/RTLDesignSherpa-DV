# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: APBMonitor
# Purpose: APB Monitor, Master, and Slave BFM classes — extensible base for APB5
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""APB Monitor, Master, and Slave BFM classes.

These classes also serve as the base for the APB5 BFMs (`APB5Monitor`,
`APB5Master`, `APB5Slave`). Extension hooks for AMBA5 USER / WAKEUP /
parity fields are provided so APB5 can inherit cleanly. See issue #15
for the inheritance design.
"""

from collections import deque
from typing import Any

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb.utils import get_sim_time
from cocotb_bus.drivers import BusDriver
from cocotb_bus.monitors import BusMonitor

from ..shared.apb_common import (
    BASE_APB_OPTIONAL_SIGNALS,
    BASE_APB_SIGNALS,
    PWRITE_DIR,
)
from ..shared.flex_randomizer import FlexRandomizer
from ..shared.memory_model import MemoryModel
from .apb_packet import APBPacket

# Backward-compatible module-level names (preserved for any external imports).
# Canonical definitions live in components/shared/apb_common.py — see issue #8.
pwrite = list(PWRITE_DIR)
apb_signals = list(BASE_APB_SIGNALS)
apb_optional_signals = list(BASE_APB_OPTIONAL_SIGNALS)


class APBSignalMixin:
    """Required/optional signal-list handling shared by all APB BFMs.

    ``cocotb_bus`` treats ``_signals`` as *required* — bus binding raises if
    any of them is missing on the DUT — while ``_optional_signals`` are
    best-effort: missing ones are skipped and simply absent from
    ``self.bus``. Optional APB signals (PPROT / PSLVERR / PSTRB, plus the
    APB5 USER / WAKEUP / parity extensions) must therefore never appear in
    ``_signals``; otherwise a DUT without them can never bind and the
    :meth:`is_signal_present` guards are defeated.

    Subclasses (the APB5 BFMs) override the two class attributes to widen
    the optional set.
    """

    #: Required signals used when the caller doesn't pass ``signals``.
    _required_signal_defaults = tuple(BASE_APB_SIGNALS)
    #: Optional signals used when the caller doesn't pass ``signals``.
    _optional_signal_defaults = tuple(BASE_APB_OPTIONAL_SIGNALS)

    @classmethod
    def _resolve_signal_lists(cls, signals):
        """Return the ``(required, optional)`` signal lists for cocotb_bus.

        An explicit ``signals`` list is used verbatim as the required set
        with no optional signals — the caller takes full control, matching
        the historical behavior of the ``signals`` override parameter.
        """
        if signals:
            return list(signals), []
        return list(cls._required_signal_defaults), list(cls._optional_signal_defaults)

    @staticmethod
    def _match_optional_case(entity, prefix, optional):
        """Rebind optional signal names onto the DUT's ACTUAL casing.

        ``cocotb_bus`` is asymmetric here, and silently so. Required signals
        go through ``_add_signal(..., case_insensitive)``, but optional ones
        are gated on a bare, CASE-SENSITIVE ``hasattr(entity, signame)``
        before that lookup is ever reached::

            if hasattr(entity, signame):
                self._add_signal(attr_name, signame, array_idx, case_insensitive)
            else:
                ...  # "Ignoring optional missing signal", at DEBUG level

        So on a DUT whose ports are lowercase (``s_apb_pstrb``), PSEL/PADDR/
        PWDATA bind fine and PSTRB/PPROT/PSLVERR vanish. The failure mode is
        maximally quiet: the master then never drives PSTRB, every write goes
        out with zero byte-strobes, and a regblock correctly writes NOTHING
        while returning no error -- the register just reads back its reset
        value, exactly as if the write had been ignored.

        Found on axi4_intf_master_observer, whose APB ports are lowercase
        while every other APB block in that repo is uppercase; it was the only
        one without a component test, so nobody had ever issued an APB write
        to it in simulation.

        Returns a dict {canonical_name: actual_suffix} for cocotb_bus. Exact
        matches are returned unchanged, so uppercase DUTs are bit-identical to
        the previous behavior.
        """
        if not optional:
            return optional
        base = prefix.rstrip('_')
        resolved = {}
        for sig in optional:
            for cand in (sig, sig.lower(), sig.upper()):
                if hasattr(entity, f"{base}_{cand}"):
                    resolved[sig] = cand
                    break
        return resolved

    def is_signal_present(self, signal_name):
        """True if the (optional) signal was found on the bus at bind time."""
        return hasattr(self.bus, signal_name) and getattr(self.bus, signal_name) is not None


class APBMonitor(APBSignalMixin, BusMonitor):
    """APB Monitor.

    Class convention — Slave-via-BusMonitor and extension hooks:
        Inherits ``BusMonitor`` for its sampling chassis (see
        ``docs/components/components_overview.md``). Subclasses (notably
        ``APB5Monitor``) extend by:

        - Overriding ``_required_signal_defaults`` /
          ``_optional_signal_defaults`` (see :class:`APBSignalMixin`) to add
          extension signals (USER/WAKEUP/parity) to the *optional* set.
        - Overriding :meth:`_build_packet` to construct the protocol-specific
          packet class with extension fields.

        The edge-detection loop in :meth:`_monitor_recv` stays in this base —
        APB and APB5 share identical PSEL/PENABLE/PREADY semantics.
    """

    def __init__(self, entity, title, prefix, clock, signals=None,
                 bus_width=32, addr_width=12, log=None, **kwargs):

        self._signals, self._optional_signals = self._resolve_signal_lists(signals)

        self.count = 0

        # Normalize prefix: remove trailing underscore if present
        # BusMonitor adds underscore separator automatically
        prefix = prefix.rstrip('_')
        self._optional_signals = self._match_optional_case(
            entity, prefix, self._optional_signals)

        BusMonitor.__init__(self, entity, prefix, clock, **kwargs)
        self.clock = clock
        self.title = title
        self.log = log or self.entity._log
        self.bus_width = bus_width
        self.addr_width = addr_width
        self.strb_width = bus_width // 8

    def print(self, transaction):
        msg = f'{self.title} - APB Transaction #{self.count}: '
        msg += transaction.formatted(compact=True)
        self.log.debug(msg)

    # ---- Extension hooks (overridden by APB5Monitor) ----

    def _build_packet(self, *, start_time, count, pwrite, paddr,
                      pwdata, prdata, pstrb, pprot, pslverr,
                      direction: str) -> Any:
        """Construct the protocol-specific packet from the sampled bus values.

        APB4 returns an :class:`APBPacket`. APB5 overrides to add USER /
        WAKEUP / parity field capture and returns an ``APB5Packet``. The
        ``direction`` argument is the string from :data:`pwrite` (``'READ'``
        or ``'WRITE'``) so subclasses can branch on it without re-decoding
        ``pwrite``.
        """
        del direction  # APB4 doesn't use it; APB5 does
        return APBPacket(
            start_time=start_time,
            count=count,
            pwrite=pwrite,
            paddr=paddr,
            pwdata=pwdata,
            prdata=prdata,
            pstrb=pstrb,
            pprot=pprot,
            pslverr=pslverr,
        )

    async def _monitor_recv(self):
        # Track previous state to detect transaction boundaries
        # APB Protocol: PSEL -> PSEL+PENABLE -> PSEL+PENABLE+PREADY (completion)
        prev_penable = 0
        prev_pready = 0

        while True:
            await FallingEdge(self.clock)
            await Timer(200, units='ps')

            # Sample current bus state
            curr_psel = self.bus.PSEL.value.integer if self.bus.PSEL.value.is_resolvable else 0
            curr_penable = self.bus.PENABLE.value.integer
            curr_pready = self.bus.PREADY.value.integer if self.bus.PREADY.value.is_resolvable else 0

            # APB transaction completes when:
            # 1. PSEL & PENABLE & PREADY are ALL high (completion condition)
            # 2. In previous cycle, EITHER:
            #    a) PREADY was low (most common - PREADY asserted this cycle), OR
            #    b) PENABLE was low (back-to-back transactions where PREADY stays high)
            transaction_complete = curr_psel and curr_penable and curr_pready

            # Valid completion edges:
            # - PREADY 0->1 (normal case: slave responds)
            # - PENABLE 0->1 while PREADY already high (back-to-back with fast slave)
            valid_edge = transaction_complete and (not prev_pready or not prev_penable)

            if valid_edge:
                start_time = get_sim_time('ns')
                address    = self.bus.PADDR.value.integer
                direction  = pwrite[self.bus.PWRITE.value.integer]
                loc_pwrite = self.bus.PWRITE.value.integer
                error      = self.bus.PSLVERR.value.integer if self.is_signal_present('PSLVERR') else 0

                if direction == 'READ':
                    if self.bus.PRDATA.value.is_resolvable:
                        data = self.bus.PRDATA.value.integer
                    else:
                        data = self.bus.PRDATA.value
                else:
                    data = self.bus.PWDATA.value.integer
                strb = self.bus.PSTRB.value.integer if self.is_signal_present('PSTRB') else 0
                pprot = self.bus.PPROT.value.integer if self.is_signal_present('PPROT') else 0
                self.count += 1

                # Build the protocol-specific packet via the extension hook.
                # APB4 returns APBPacket; APB5 overrides to return APB5Packet
                # with USER/WAKEUP/parity fields populated.
                transaction = self._build_packet(
                    start_time=start_time,
                    count=self.count,
                    pwrite=loc_pwrite,
                    paddr=address,
                    pwdata=data if direction == 'WRITE' else 0,
                    prdata=data if direction == 'READ' else 0,
                    pstrb=strb,
                    pprot=pprot,
                    pslverr=error,
                    direction=direction,
                )

                # Dispatch immediately - APB data is stable when PREADY asserts
                self._recv(transaction)
                self.print(transaction)

            # Update previous state for next iteration
            prev_penable = curr_penable
            prev_pready = curr_pready


class APBSlave(APBSignalMixin, BusMonitor):
    """APB Slave BFM with extensible response pipeline.

    Class convention — Slave-via-BusMonitor:
        This class inherits from ``cocotb_bus.monitors.BusMonitor`` even though
        it is semantically a *responder* that drives output signals (``PREADY``,
        ``PRDATA``, ``PSLVERR``). ``cocotb_bus`` does not provide a "responder"
        base class — ``BusMonitor`` is reused for its passive signal-sampling
        coroutine, and the monitor loop overrides the sampled-edge handler to
        also drive responses. Every "Slave" BFM in this framework that inherits
        ``BusMonitor`` follows this convention.

    Extension hooks for APB5:
        Subclasses (notably :class:`APB5Slave`) extend by overriding:

        - :meth:`_default_randomizer_constraints` — add extension-field
          randomization keys (e.g. ``pruser``, ``pbuser``).
        - :meth:`_init_extension_signals` — zero APB5 output extensions
          (PRUSER/PBUSER/PWAKEUP) during ``__init__``.
        - :meth:`_capture_extension_input_fields` — sample PAUSER/PWUSER on
          each transaction.
        - :meth:`_drive_extension_response` — drive PRUSER/PBUSER alongside
          PREADY.
        - :meth:`_build_packet` — construct the protocol-specific packet
          (APB5 returns an :class:`APB5Packet` with USER fields).

        Each hook has a no-op default so the APB4 path is unchanged.
    """
    def __init__(self, entity, title, prefix, clock, registers, signals=None,
                    bus_width=32, addr_width=12, randomizer=None,
                    log=None, error_overflow=False, **kwargs):
        self._signals, self._optional_signals = self._resolve_signal_lists(signals)
        if randomizer is None:
            self.randomizer = FlexRandomizer(self._default_randomizer_constraints())
        else:
            self.randomizer = randomizer

        # Normalize prefix: remove trailing underscore if present
        # BusMonitor adds underscore separator automatically
        prefix = prefix.rstrip('_')
        self._optional_signals = self._match_optional_case(
            entity, prefix, self._optional_signals)

        BusMonitor.__init__(self, entity, prefix, clock, **kwargs)
        self.clock          = clock
        self.title          = title
        self.prefix         = prefix
        self.log = log or self.entity._log
        self.addr_width     = addr_width
        self.bus_width      = bus_width
        self.strb_bits      = bus_width // 8
        self.addr_mask      = (2**self.strb_bits - 1)
        self.num_lines      = len(registers) // self.strb_bits
        self.count          = 0
        self.error_overflow = error_overflow
        # Create the memory model
        self.mem = MemoryModel(num_lines=self.num_lines, bytes_per_line=self.strb_bits, log=self.log, preset_values=registers)
        self.sentQ = deque()

        # initialise all outputs to zero
        self.bus.PRDATA.setimmediatevalue(0)
        self.bus.PREADY.setimmediatevalue(0)
        if self.is_signal_present('PSLVERR'):
            self.bus.PSLVERR.setimmediatevalue(0)
        # Extension-signal init hook (no-op in APB4; APB5Slave overrides)
        self._init_extension_signals()
        if self.is_signal_present('PPROT'):
            msg = f'Slave {self.title} PPROT {dir(self.bus.PPROT)}'
            self.log.debug(msg)

    # ---- Extension hooks (overridden by APB5Slave) ----

    def _default_randomizer_constraints(self):
        """Default FlexRandomizer constraints. Subclasses extend the dict."""
        return {
            'ready': ([(0, 1), (2, 5), (6, 10)], [5, 2, 1]),
            'error': ([(0, 0), (1, 1)], [10, 0]),
        }

    def _init_extension_signals(self):
        """No-op default. APB5Slave zeroes PRUSER / PBUSER / PWAKEUP here."""
        return None

    def _capture_extension_input_fields(self):
        """Return a dict of master-driven extension fields sampled this transaction.

        APB5Slave overrides to return ``{'pauser': ..., 'pwuser': ...}``.
        Default returns an empty dict.
        """
        return {}

    def _drive_extension_response(self, rand_values):
        """No-op default. APB5Slave drives PRUSER/PBUSER from ``rand_values``."""
        return None

    def _build_packet(self, *, start_time, count, pwrite, paddr,
                      pwdata, prdata, pstrb, pprot, pslverr,
                      direction, extension_inputs, rand_values):
        """Construct the protocol-specific packet recorded for this transaction.

        APB4 returns an :class:`APBPacket`. APB5Slave overrides to return an
        :class:`APB5Packet` populated with USER fields. ``direction`` is the
        string ``'READ'`` or ``'WRITE'``. ``extension_inputs`` is whatever
        :meth:`_capture_extension_input_fields` returned. ``rand_values`` is
        the dict from :meth:`FlexRandomizer.next` for this transaction
        (subclasses can pull PRUSER/PBUSER values from it).
        """
        del direction, extension_inputs, rand_values  # APB4 doesn't use them
        return APBPacket(
            start_time=start_time,
            count=count,
            pwrite=pwrite,
            paddr=paddr,
            pwdata=pwdata,
            prdata=prdata,
            pstrb=pstrb,
            pprot=pprot,
            pslverr=pslverr,
        )

    def set_randomizer(self, randomizer):
        self.randomizer = randomizer
        self.log.info(f"Set new randomizer for APB Slave ({self.title})")

    def dump_registers(self):
        msg = f"APB Slave {self.title} - Register Dump:"
        self.log.info(msg)
        self.log.info(self.mem.dump())

    def print(self, transaction):
        """Debug-log a completed transaction. Subclasses can override the label."""
        msg = f'{self.title} - APB Slave Transaction #{self.count}: '
        msg += transaction.formatted(compact=True)
        self.log.debug(msg)

    async def reset_bus(self):
        msg = f'Resetting APB Bus {self.title}'
        self.log.info(msg)
        self.bus.PRDATA.value = 0
        self.bus.PREADY.value = 0
        if self.is_signal_present('PSLVERR'):
            self.bus.PSLVERR.value = 0

    def reset_registers(self):
        self.mem.reset(to_preset=True)

    async def _monitor_recv(self):
        """Unified APB slave state machine.

        Shared by APB4 and APB5. The flow per transaction:

        1. Detect ``PSEL`` (setup phase begins).
        2. Sample randomizer values (``ready_delay``, ``error``, extensions).
        3. Wait ``ready_delay`` cycles (matches the APB4 baseline timing —
           delay is measured from PSEL detection, not PENABLE rising).
        4. Sample address / direction / write-data / extension inputs.
        5. Perform the memory access (or set ``slv_error`` on overflow).
        6. Drive ``PREADY`` + ``PRDATA`` / ``PSLVERR`` + extension outputs.
        7. Wait for the master to assert ``PENABLE`` (access phase).
        8. Build the monitor packet via :meth:`_build_packet` and dispatch
           it through ``self._recv`` so downstream scoreboards see the
           transaction.

        Extension fields (USER/WAKEUP for APB5) are handled via the
        :meth:`_capture_extension_input_fields`,
        :meth:`_drive_extension_response`, and :meth:`_build_packet` hooks.
        """
        while True:
            await RisingEdge(self.clock)
            # Reset bus outputs each idle cycle
            self.bus.PREADY.value = 0
            if self.is_signal_present('PSLVERR'):
                self.bus.PSLVERR.value = 0

            await Timer(200, units='ps')

            if not (self.bus.PSEL.value.is_resolvable and self.bus.PSEL.value.integer):
                continue

            # PSEL detected — start a transaction.
            rand_dict = self.randomizer.next()
            ready_delay = int(rand_dict.get('ready', 0))
            slv_error = int(rand_dict.get('error', 0))

            # Apply randomized ready delay before driving the response.
            for _ in range(ready_delay):
                await RisingEdge(self.clock)

            # Sample address, direction, and inputs (data is stable through PREADY).
            address    = self.bus.PADDR.value.integer
            direction  = pwrite[self.bus.PWRITE.value.integer]
            loc_pwrite = self.bus.PWRITE.value.integer
            pprot      = (self.bus.PPROT.value.integer
                          if self.is_signal_present('PPROT') else 0)
            pstrb_in   = (self.bus.PSTRB.value.integer
                          if self.is_signal_present('PSTRB') else
                          (1 << self.strb_bits) - 1)
            pwdata_in  = (self.bus.PWDATA.value.integer
                          if direction == 'WRITE' else 0)
            extension_inputs = self._capture_extension_input_fields()

            # Memory access + overflow handling
            addr_bits_needed = (self.num_lines * self.strb_bits - 1).bit_length()
            memory_addr_mask = (1 << addr_bits_needed) - 1
            word_index = (address & memory_addr_mask) >> (self.strb_bits.bit_length() - 1)
            prdata = 0
            overflow_error = False

            if word_index >= self.num_lines:
                if self.error_overflow:
                    self.log.error(
                        f'APB {self.title} - Memory overflow error: {word_index}'
                    )
                    overflow_error = True
                    slv_error = 1
                else:
                    expand = word_index - self.num_lines + 10
                    self.log.warning(
                        f'APB {self.title} - Memory overflow expand: '
                        f'{self.num_lines=} {word_index=}'
                    )
                    self.mem.expand(expand)
                    self.num_lines += expand

            if not overflow_error:
                if direction == 'WRITE':
                    pwdata_ba = self.mem.integer_to_bytearray(pwdata_in, self.strb_bits)
                    self.mem.write(address & memory_addr_mask, pwdata_ba, pstrb_in)
                else:  # READ
                    prdata_ba = self.mem.read(address & memory_addr_mask, self.strb_bits)
                    prdata = self.mem.bytearray_to_integer(prdata_ba)

            # Drive the response
            self.bus.PREADY.value = 1
            if direction == 'READ':
                self.bus.PRDATA.value = prdata
            if slv_error and self.is_signal_present('PSLVERR'):
                self.bus.PSLVERR.value = 1
            # Extension response hook (no-op in APB4; APB5Slave drives PRUSER/PBUSER)
            self._drive_extension_response(rand_dict)

            await Timer(200, units='ps')

            # Wait for the master to assert PENABLE (access phase complete)
            while not self.bus.PENABLE.value.integer:
                await RisingEdge(self.clock)
                await Timer(200, units='ps')

            # Record and dispatch the transaction
            self.count += 1
            transaction = self._build_packet(
                start_time=get_sim_time('ns'),
                count=self.count,
                pwrite=loc_pwrite,
                paddr=address,
                pwdata=pwdata_in,
                prdata=prdata,
                pstrb=pstrb_in,
                pprot=pprot,
                pslverr=slv_error,
                direction=direction,
                extension_inputs=extension_inputs,
                rand_values=rand_dict,
            )
            self.sentQ.append(transaction)
            self._recv(transaction)
            self.print(transaction)


class APBMaster(APBSignalMixin, BusDriver):
    """APB Master BFM with queued + randomized transmit pipeline.

    Extension hooks for APB5:
        Subclasses (notably :class:`APB5Master`) extend by overriding:

        - :meth:`_default_randomizer_constraints` to add extension-field
          randomization.
        - :meth:`_init_extension_signals` to zero APB5 output extensions
          (PAUSER/PWUSER) during ``__init__``.
        - :meth:`_drive_extension_setup_phase` to drive USER / WAKEUP signals
          during the setup phase of ``_finish_xmit`` (per AMBA APB5,
          PWAKEUP is requester-driven and asserts with PSEL).
        - :meth:`_capture_extension_response` to sample USER signals
          alongside PRDATA / PSLVERR.
        - :meth:`_clear_extension_signals` to deassert extension outputs
          whenever the master clears the bus.

        Each hook has a no-op default so the APB4 path is unchanged.
    """
    def __init__(self, entity, title, prefix, clock, signals=None,
                    bus_width=32, addr_width=12, randomizer=None,
                    log=None, **kwargs):
        self._signals, self._optional_signals = self._resolve_signal_lists(signals)
        if randomizer is None:
            self.randomizer = FlexRandomizer(self._default_randomizer_constraints())
        else:
            self.randomizer = randomizer

        # Normalize prefix: remove trailing underscore if present
        # BusDriver adds underscore separator automatically
        prefix = prefix.rstrip('_')
        self._optional_signals = self._match_optional_case(
            entity, prefix, self._optional_signals)

        BusDriver.__init__(self, entity, prefix, clock, **kwargs)
        self.title = title
        self.prefix = prefix
        self.log = log or self.entity._log
        self.clock          = clock
        self.addr_width     = addr_width
        self.bus_width      = bus_width
        self.strb_bits      = bus_width // 8
        self.addr_mask      = (2**self.strb_bits - 1)
        self.sentQ = deque()

        # initialise all outputs to zero
        self.bus.PADDR.setimmediatevalue(0)
        self.bus.PWRITE.setimmediatevalue(0)
        self.bus.PSEL.setimmediatevalue(0)
        self.bus.PENABLE.setimmediatevalue(0)
        self.bus.PWDATA.setimmediatevalue(0)
        if self.is_signal_present('PSTRB'):
            self.bus.PSTRB.setimmediatevalue(0)
        # Extension-signal init hook (no-op in APB4; APB5Master overrides)
        self._init_extension_signals()
        self.transmit_queue = deque()
        self.transmit_coroutine = None
        self.transfer_busy = False

    # ---- Extension hooks (overridden by APB5Master) ----

    def _default_randomizer_constraints(self):
        """Default FlexRandomizer constraints. Subclasses extend the dict.

        Note: bin ranges MUST be tuples, not lists — FlexRandomizer's
        validator rejects list bins (see ConstraintValidationError).
        """
        return {
            'psel':    ([(0, 0), (1, 5), (6, 10)], [5, 2, 1]),
            'penable': ([(0, 0), (1, 2)], [4, 1]),
        }

    def _init_extension_signals(self):
        """No-op default. APB5Master zeroes PAUSER / PWUSER here."""
        return None

    def _drive_extension_setup_phase(self, transaction):
        """No-op default. APB5Master drives PAUSER / PWUSER during setup phase."""
        return None

    def _capture_extension_response(self, transaction):
        """No-op default. APB5Master samples PRUSER / PBUSER here."""
        return None

    def _clear_extension_signals(self):
        """No-op default. Called whenever the master clears the bus (between
        queued transactions, at pipeline completion, and on ``reset_bus``).

        APB5Master overrides this to deassert master-driven extensions
        (PWAKEUP / PAUSER / PWUSER) together with PSEL.
        """
        return None

    def set_randomizer(self, randomizer):
        self.randomizer = randomizer
        self.log.info(f"Set new randomizer for APB Master ({self.title})")

    async def reset_bus(self):
        # initialise the transmit queue
        self.transmit_queue     = deque()
        self.transmit_coroutine = None  # Use None, not 0, for proper Task checking
        self.transfer_busy      = False
        self.bus.PSEL.value     = 0
        self.bus.PENABLE.value  = 0
        self.bus.PWRITE.value   = 0
        self.bus.PADDR.value    = 0
        self.bus.PWDATA.value   = 0
        if self.is_signal_present('PSTRB'):
            self.bus.PSTRB.value = 0
        if self.is_signal_present('PPROT'):
            self.bus.PPROT.value    = 0
        # Extension clear hook (no-op in APB4; APB5Master deasserts PWAKEUP etc.)
        self._clear_extension_signals()

    async def busy_send(self, transaction):
        '''
            Provide a send method that waits for the transaction to complete.
        '''
        await self.send(transaction)
        while (self.transfer_busy):
            await RisingEdge(self.clock)

    async def _driver_send(self, transaction, sync=True, hold=False, **kwargs):
        '''
            Append a new transaction to be transmitted
        '''
        # add new transaction
        self.transmit_queue.append(transaction)
        msg = f'Adding to the transmit_queue: {transaction.formatted(compact=True)}'
        self.log.debug(msg)

        # launch new transmit pipeline coroutine if aren't holding for and the
        #   the coroutine isn't already running.
        #   If it is running it will just collect the transactions in the
        #   queue once it gets to them.
        # Use .done() method to properly check if Task is complete (CocoTB 1.8+)
        if not hold and (self.transmit_coroutine is None or self.transmit_coroutine.done()):
            # Set transfer_busy BEFORE starting pipeline to avoid race condition
            # with busy_send() checking the flag
            self.transfer_busy = True
            self.transmit_coroutine = cocotb.start_soon(self._transmit_pipeline())


    async def _transmit_pipeline(self):
        """Internal function to transmit queued transactions."""
        # Wait for clock edge to ensure we're not in a read-only phase
        await RisingEdge(self.clock)

        # default values
        self.transfer_busy = True

        # while there's data in the queue keep transmitting
        while len(self.transmit_queue):
            # clear out the bus
            self.bus.PSEL.value     = 0
            self.bus.PENABLE.value  = 0
            self.bus.PWRITE.value   = 0
            self.bus.PADDR.value    = 0
            self.bus.PWDATA.value   = 0
            if self.is_signal_present('PPROT'):
                self.bus.PPROT.value = 0
            if self.is_signal_present('PSTRB'):
                self.bus.PSTRB.value = 0
            # Extension clear hook (no-op in APB4)
            self._clear_extension_signals()

            rand_dict = self.randomizer.next()
            psel_delay = rand_dict['psel']
            penable_delay = rand_dict['penable']

            transaction = self.transmit_queue.popleft()
            transaction.start_time = cocotb.utils.get_sim_time('ns')

            # finish the packet transmit
            await self._finish_xmit(transaction, psel_delay, penable_delay)

        # clear out the bus
        self.transfer_busy      = False
        self.bus.PSEL.value     = 0
        self.bus.PENABLE.value  = 0
        self.bus.PWRITE.value   = 0
        self.bus.PADDR.value    = 0
        self.bus.PWDATA.value   = 0
        if self.is_signal_present('PPROT'):
            self.bus.PPROT.value    = 0
        if self.is_signal_present('PSTRB'):
            self.bus.PSTRB.value = 0
        # Extension clear hook (no-op in APB4)
        self._clear_extension_signals()

    async def _finish_xmit(self, transaction, psel_delay, penable_delay):
        """Completes an APB transaction.

        This method sets the APB signals, waits for the ready signal,
        and handles the transaction data and error status. Extension
        hooks (`_drive_extension_setup_phase`, `_capture_extension_response`)
        let APB5Master add USER/WAKEUP/parity handling without forking the
        whole pipeline.
        """
        for _ in range(psel_delay):
            await RisingEdge(self.clock)

        self.bus.PSEL.value   = 1
        # Access fields dictionary for APBPacket
        self.bus.PWRITE.value = transaction.fields['pwrite']
        self.bus.PADDR.value  = transaction.fields['paddr']
        if self.is_signal_present('PPROT'):
            self.bus.PPROT.value = transaction.fields['pprot']
        if self.is_signal_present('PSTRB'):
            self.bus.PSTRB.value = transaction.fields['pstrb']
        # Check direction from packet
        if transaction.direction == 'WRITE':
            self.bus.PWDATA.value = transaction.fields['pwdata']
        # Extension setup hook (no-op in APB4; APB5Master drives PAUSER/PWUSER)
        self._drive_extension_setup_phase(transaction)

        await RisingEdge(self.clock)
        await Timer(200, units='ps')

        for _ in range(penable_delay):
            await RisingEdge(self.clock)

        self.bus.PENABLE.value = 1
        await FallingEdge(self.clock)

        while not self.bus.PREADY.value:
            await FallingEdge(self.clock)

        # Wait for signal values to settle before sampling (matches APBMonitor/APBSlave timing)
        await Timer(200, units='ps')

        # check if the slave is asserting an error
        if self.is_signal_present('PSLVERR') and self.bus.PSLVERR.value:
            transaction.fields['pslverr'] = self.bus.PSLVERR.value.integer

        # if this is a read we should sample the data
        if transaction.direction == 'READ':
            if self.bus.PRDATA.value.is_resolvable:
                transaction.fields['prdata'] = self.bus.PRDATA.value.integer
            else:
                transaction.fields['prdata'] = self.bus.PRDATA.value

        # Extension response hook (no-op in APB4; APB5Master captures PRUSER/PBUSER/PWAKEUP)
        self._capture_extension_response(transaction)

        self.sentQ.append(transaction)
        await RisingEdge(self.clock)
