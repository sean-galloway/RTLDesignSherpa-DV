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
    - :class:`APB5Slave` inherits :class:`APBSlave` and overrides the
      extension hooks (``_default_randomizer_constraints``,
      ``_init_extension_signals``, ``_capture_extension_input_fields``,
      ``_drive_extension_response``, ``_build_packet``). The unified
      ``_monitor_recv`` state machine lives in APBSlave. This **fixes
      latent bugs** in the previous APB5Slave: the old code called
      ``self.mem.write(line, wdata, strb)`` passing an int instead of a
      bytearray and a line index instead of a byte address (would have
      raised TypeError), and ``self.mem.read(line)`` was missing the
      required ``length`` argument.

PWAKEUP direction (AMBA APB5, IHI 0024E):
    PWAKEUP is driven by the *requester* — :class:`APB5Master` asserts it
    together with PSEL and holds it until the transfer completes
    (``wakeup_enable`` constructor parameter / :meth:`APB5Master.set_wakeup_enable`).
    :class:`APB5Slave` and :class:`APB5Monitor` only observe PWAKEUP and
    record its value in the captured packet's ``wakeup`` field. The old
    slave-driven model (``APB5Slave.set_wakeup`` and the never-invoked
    ``wakeup_generator`` parameter) is gone; ``wakeup_generator`` is still
    accepted for compatibility but ignored with a DeprecationWarning.
"""

import warnings
from typing import Any

from cocotb.utils import get_sim_time

from ..apb.apb_components import APBMaster, APBMonitor, APBSlave
from ..shared.apb_common import (
    BASE_APB_OPTIONAL_SIGNALS,
    BASE_APB_SIGNALS,
    PWRITE_DIR,
)
from .apb5_packet import APB5Packet

# Direction mapping (canonical definition in components/shared/apb_common.py)
pwrite = list(PWRITE_DIR)

# APB5 signal sets — APB4 base + AMBA5 user / wakeup / parity extensions
apb5_signals = list(BASE_APB_SIGNALS)

# APB5 extension signals layered on top of the APB4 optional set
_APB5_EXTENSION_OPTIONAL_SIGNALS = (
    # APB5 user-channel extensions
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
)
apb5_optional_signals = list(BASE_APB_OPTIONAL_SIGNALS) + list(
    _APB5_EXTENSION_OPTIONAL_SIGNALS
)


def _warn_ignored_wakeup_generator(wakeup_generator):
    """Deprecation shim for the removed slave-side wake-up generation.

    Per AMBA APB5 (IHI 0024E) PWAKEUP is driven by the *requester* (the
    master), asserted with PSEL and held until the transfer completes. The
    old ``wakeup_generator`` parameter modeled the wrong direction (and was
    never invoked). It is accepted for backward compatibility but ignored.

    Returns:
        None (always) — the stored ``wakeup_generator`` attribute value.
    """
    if wakeup_generator is not None:
        warnings.warn(
            "APB5Slave(wakeup_generator=...) is deprecated and ignored: "
            "PWAKEUP is driven by the requester (master) per AMBA APB5 "
            "(IHI 0024E). Use APB5Master(wakeup_enable=...) or "
            "APB5Master.set_wakeup_enable() to control PWAKEUP.",
            DeprecationWarning,
            stacklevel=3,
        )
    return None


# ----------------------------------------------------------------------
# APB5Monitor — inherits APBMonitor; overrides only the packet hook.
# ----------------------------------------------------------------------


class APB5Monitor(APBMonitor):
    """APB5 Monitor with AMBA5 extension support.

    Inherits the edge-detection loop from :class:`APBMonitor` and only
    overrides :meth:`_build_packet` to construct an :class:`APB5Packet`
    with USER / WAKEUP fields sampled from the bus.
    """

    # APB5 default signal sets for cocotb_bus binding (see APBSignalMixin):
    # required signals are the APB4 base; every AMBA5 extension is optional.
    _required_signal_defaults = tuple(apb5_signals)
    _optional_signal_defaults = tuple(apb5_optional_signals)

    def __init__(self, entity, title, prefix, clock, signals=None,
                 bus_width=32, addr_width=12,
                 auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
                 log=None, **kwargs):
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

    - :meth:`_init_extension_signals` zeroes PAUSER/PWUSER/PWAKEUP at
      construction.
    - :meth:`_drive_extension_setup_phase` drives PAUSER/PWUSER and (per
      AMBA APB5, IHI 0024E) PWAKEUP during the setup phase of every
      transaction — PWAKEUP is a *requester-driven* signal that asserts
      together with PSEL and holds until the transfer completes.
    - :meth:`_capture_extension_response` samples PRUSER/PBUSER after
      PREADY rises.
    - :meth:`_clear_extension_signals` deasserts PWAKEUP/PAUSER/PWUSER
      whenever the master clears the bus (so PWAKEUP falls with PSEL).

    Wake-up control:
        ``wakeup_enable`` (constructor parameter, default True) selects
        whether PWAKEUP is asserted for each transfer; it can be changed at
        runtime via :meth:`set_wakeup_enable`. The driven value is recorded
        in the transaction's ``wakeup`` field.

    The convenience methods :meth:`write` and :meth:`read` build an
    :class:`APB5Packet` and forward to the inherited :meth:`send` (queued
    pipeline). Direct-drive callers should use :meth:`busy_send` if they
    need to wait for completion.
    """

    # APB5 default signal sets for cocotb_bus binding (see APBSignalMixin).
    _required_signal_defaults = tuple(apb5_signals)
    _optional_signal_defaults = tuple(apb5_optional_signals)

    def __init__(self, entity, title, prefix, clock, signals=None,
                 bus_width=32, addr_width=12,
                 auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
                 randomizer=None, log=None, wakeup_enable=True, **kwargs):
        # APB5 widths needed by extension hooks and packet construction
        self.auser_width = auser_width
        self.wuser_width = wuser_width
        self.ruser_width = ruser_width
        self.buser_width = buser_width
        self.count = 0
        # PWAKEUP driving policy: per AMBA APB5 (IHI 0024E) PWAKEUP is
        # driven by the requester (this master). When enabled and the DUT
        # has a PWAKEUP wire, the master asserts it together with PSEL and
        # holds it until the transfer completes.
        self.wakeup_enable = bool(wakeup_enable)

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
        if self.is_signal_present('PWAKEUP'):
            self.bus.PWAKEUP.setimmediatevalue(0)

    def _drive_extension_setup_phase(self, transaction):
        """Drive PAUSER / PWUSER / PWAKEUP during the setup phase.

        PWAKEUP is requester-driven (AMBA APB5, IHI 0024E): it asserts
        together with PSEL and is held until the transfer completes
        (deassertion happens in :meth:`_clear_extension_signals`). The
        value actually driven is recorded in the transaction's ``wakeup``
        field so scoreboards see what went on the wire.
        """
        if self.is_signal_present('PAUSER'):
            self.bus.PAUSER.value = transaction.fields.get('pauser', 0)
        if self.is_signal_present('PWUSER'):
            self.bus.PWUSER.value = transaction.fields.get('pwuser', 0)
        if self.is_signal_present('PWAKEUP'):
            wakeup_value = 1 if self.wakeup_enable else 0
            self.bus.PWAKEUP.value = wakeup_value
            if 'wakeup' in transaction.fields:
                transaction.fields['wakeup'] = wakeup_value

    def _capture_extension_response(self, transaction):
        """Sample PRUSER / PBUSER after PREADY rises.

        PWAKEUP is *not* sampled here — it is driven by this master (see
        :meth:`_drive_extension_setup_phase`), not by the completer.
        """
        if self.is_signal_present('PRUSER'):
            transaction.fields['pruser'] = self.bus.PRUSER.value.integer
        if self.is_signal_present('PBUSER'):
            transaction.fields['pbuser'] = self.bus.PBUSER.value.integer

    def _clear_extension_signals(self):
        """Deassert master-driven APB5 extensions when the bus is cleared.

        PWAKEUP falls together with PSEL (it is held through the transfer
        per IHI 0024E); PAUSER / PWUSER return to zero between transfers.
        """
        if self.is_signal_present('PAUSER'):
            self.bus.PAUSER.value = 0
        if self.is_signal_present('PWUSER'):
            self.bus.PWUSER.value = 0
        if self.is_signal_present('PWAKEUP'):
            self.bus.PWAKEUP.value = 0

    # ---- Wake-up control API ----

    def set_wakeup_enable(self, enable):
        """Enable/disable PWAKEUP assertion for subsequent transfers.

        Per AMBA APB5 (IHI 0024E) PWAKEUP is driven by the requester and
        asserted with (or before) PSEL, held until the transfer completes.
        When enabled (the default), this master asserts PWAKEUP together
        with PSEL for every transfer and deasserts it when PSEL falls.

        Args:
            enable: Truthy to assert PWAKEUP on subsequent transfers.
        """
        self.wakeup_enable = bool(enable)
        self.log.info(
            f"APB5 Master ({self.title}): PWAKEUP driving "
            f"{'enabled' if self.wakeup_enable else 'disabled'}"
        )

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
# APB5Slave — inherits APBSlave's unified state machine.
# ----------------------------------------------------------------------


class APB5Slave(APBSlave):
    """APB5 Slave BFM.

    Inherits the unified APB slave state machine from :class:`APBSlave`
    (see :meth:`APBSlave._monitor_recv`) and adds AMBA5 USER handling via
    the extension hooks. PWAKEUP is requester-driven (see module
    docstring): this slave only observes it and records the sampled value
    in each captured packet's ``wakeup`` field.

    Behavior change from the previous APB5Slave (issue #15 Phase B):
        - **Memory access is now correct.** The previous implementation
          called ``self.mem.write(line, wdata, strb)`` passing an int for
          ``wdata`` and a line index for the address; ``MemoryModel.write``
          requires a *byte address* and a *bytearray* (would have raised
          TypeError). Similarly ``self.mem.read(line)`` was missing the
          required ``length`` argument. The unified state machine uses the
          correct byte-address + bytearray + length API.
        - **Memory overflow auto-expansion.** APB5's previous behavior was
          to silently fail on out-of-range addresses. The unified state
          machine auto-expands the memory (matching APB4Slave's behavior),
          or signals an error if ``error_overflow=True``.
        - **Transaction now dispatched via ``self._recv``.** This was
          already the case in the old APB5Slave; preserved.
        - **``ready_delay`` timing**: now measured from PSEL detection
          (APB4-compatible), previously measured from PENABLE rising edge.
          Observable timing difference is typically 1 cycle.
    """

    # APB5 default signal sets for cocotb_bus binding (see APBSignalMixin).
    _required_signal_defaults = tuple(apb5_signals)
    _optional_signal_defaults = tuple(apb5_optional_signals)

    def __init__(self, entity, title, prefix, clock, registers, signals=None,
                 bus_width=32, addr_width=12,
                 auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
                 randomizer=None, log=None, error_overflow=False,
                 wakeup_generator=None, **kwargs):
        # APB5 widths needed by extension hooks and packet construction.
        # Must be set before super().__init__ because _default_randomizer_constraints()
        # is called during init and references ruser_width / buser_width.
        self.auser_width = auser_width
        self.wuser_width = wuser_width
        self.ruser_width = ruser_width
        self.buser_width = buser_width
        # Deprecated: PWAKEUP is requester-driven, so slave-side wake-up
        # generation no longer exists. Accepted (with a DeprecationWarning)
        # so existing callers don't break; always stored as None.
        self.wakeup_generator = _warn_ignored_wakeup_generator(wakeup_generator)

        super().__init__(
            entity=entity, title=title, prefix=prefix, clock=clock,
            registers=registers, signals=signals,
            bus_width=bus_width, addr_width=addr_width,
            randomizer=randomizer, log=log, error_overflow=error_overflow,
            **kwargs,
        )

    # ---- Extension hook overrides ----

    def _default_randomizer_constraints(self):
        """Add PRUSER / PBUSER randomization on top of the APB4 defaults."""
        constraints = super()._default_randomizer_constraints()
        constraints['pruser'] = ([(0, (1 << self.ruser_width) - 1)], [1])
        constraints['pbuser'] = ([(0, (1 << self.buser_width) - 1)], [1])
        return constraints

    def _init_extension_signals(self):
        """Zero APB5 output extensions at construction.

        Note: PWAKEUP is *not* initialized here — it is a requester-driven
        signal (AMBA APB5, IHI 0024E) owned by :class:`APB5Master`; the
        slave only observes it.
        """
        if self.is_signal_present('PRUSER'):
            self.bus.PRUSER.setimmediatevalue(0)
        if self.is_signal_present('PBUSER'):
            self.bus.PBUSER.setimmediatevalue(0)

    def _capture_extension_input_fields(self):
        """Sample PAUSER / PWUSER from the bus."""
        return {
            'pauser': (self.bus.PAUSER.value.integer
                       if self.is_signal_present('PAUSER') else 0),
            'pwuser': (self.bus.PWUSER.value.integer
                       if self.is_signal_present('PWUSER') else 0),
        }

    def _drive_extension_response(self, rand_values):
        """Drive PRUSER / PBUSER from randomizer values."""
        if self.is_signal_present('PRUSER'):
            self.bus.PRUSER.value = rand_values.get('pruser', 0)
        if self.is_signal_present('PBUSER'):
            self.bus.PBUSER.value = rand_values.get('pbuser', 0)

    def _build_packet(self, *, start_time, count, pwrite, paddr,
                      pwdata, prdata, pstrb, pprot, pslverr,
                      direction, extension_inputs, rand_values) -> Any:
        """Construct an APB5Packet populated with USER / WAKEUP fields.

        PWAKEUP is observed (sampled) here — it is driven by the master.
        """
        del direction
        wakeup = (self.bus.PWAKEUP.value.integer
                  if self.is_signal_present('PWAKEUP') else 0)
        return APB5Packet(
            data_width=self.bus_width,
            addr_width=self.addr_width,
            strb_width=self.strb_bits,
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
            pauser=extension_inputs.get('pauser', 0),
            pwuser=extension_inputs.get('pwuser', 0),
            pruser=rand_values.get('pruser', 0),
            pbuser=rand_values.get('pbuser', 0),
            wakeup=wakeup,
        )

    def print(self, transaction):
        """Print transaction for debug (APB5 label)."""
        msg = f'{self.title} - APB5 Transaction #{self.count}: '
        msg += transaction.formatted(compact=True)
        self.log.debug(msg)
