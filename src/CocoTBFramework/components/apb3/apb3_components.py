# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: APB3Components
# Purpose: APB3 Monitor, Master and Slave BFM Classes — APB4 minus PPROT/PSTRB.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-10

"""APB3 Monitor, Master and Slave BFM classes.

APB3 is implemented as a subclass of the APB4 BFMs in
``components/apb/apb_components.py``.  The only signal-set difference is that
APB3 exposes only ``PSLVERR`` as optional; ``PPROT`` and ``PSTRB`` are not
part of the APB3 signal set.  The APB3 master rejects transactions that carry
those fields, and the monitor/slave build :class:`APB3Packet` instances that
omit them.
"""

from typing import Any

from cocotb.utils import get_sim_time

from ..apb.apb_components import APBMaster, APBMonitor, APBSlave
from ..shared.apb_common import BASE_APB_SIGNALS
from .apb3_packet import APB3Packet


class APB3Monitor(APBMonitor):
    """APB3 Monitor.

    Inherits the edge-detection loop from :class:`APBMonitor` and overrides
    only the packet hook to construct an :class:`APB3Packet`.
    """

    _required_signal_defaults = tuple(BASE_APB_SIGNALS)
    _optional_signal_defaults = ("PSLVERR",)

    def print(self, transaction):
        msg = f'{self.title} - APB3 Transaction #{self.count}: '
        msg += transaction.formatted(compact=True)
        self.log.debug(msg)

    def _build_packet(self, *, start_time, count, pwrite, paddr,
                      pwdata, prdata, pstrb, pprot, pslverr,
                      direction: str) -> Any:
        """Construct an APB3Packet (PSTRB/PPROT are ignored)."""
        del pstrb, pprot, direction
        return APB3Packet(
            data_width=self.bus_width,
            addr_width=self.addr_width,
            start_time=start_time,
            count=count,
            pwrite=pwrite,
            paddr=paddr,
            pwdata=pwdata,
            prdata=prdata,
            pslverr=pslverr,
        )


class APB3Master(APBMaster):
    """APB3 Master BFM.

    Inherits the queued + randomized transmit pipeline from :class:`APBMaster`.
    The APB3 signal set does not include ``PSTRB`` or ``PPROT``; the
    convenience :meth:`write` and :meth:`read` methods raise if a caller tries
    to pass them.
    """

    _required_signal_defaults = tuple(BASE_APB_SIGNALS)
    _optional_signal_defaults = ("PSLVERR",)

    async def write(self, address, data, strb=None, pprot=0):
        """Perform one APB3 write transaction.

        Raises:
            ValueError: If ``strb`` or ``pprot`` is supplied; neither signal
                exists in the APB3 signal set.
        """
        if strb is not None:
            raise ValueError("APB3 does not support PSTRB; do not pass strb")
        if pprot != 0:
            raise ValueError("APB3 does not support PPROT; do not pass pprot")

        transaction = APB3Packet(
            data_width=self.bus_width,
            addr_width=self.addr_width,
            pwrite=1,
            paddr=address,
            pwdata=data,
            start_time=get_sim_time('ns'),
        )
        await self.busy_send(transaction)
        return transaction

    async def read(self, address, pprot=0):
        """Perform one APB3 read transaction.

        Raises:
            ValueError: If ``pprot`` is supplied; PPROT does not exist in APB3.
        """
        if pprot != 0:
            raise ValueError("APB3 does not support PPROT; do not pass pprot")

        transaction = APB3Packet(
            data_width=self.bus_width,
            addr_width=self.addr_width,
            pwrite=0,
            paddr=address,
            start_time=get_sim_time('ns'),
        )
        await self.busy_send(transaction)
        return transaction


class APB3Slave(APBSlave):
    """APB3 Slave BFM.

    Inherits the unified APB slave state machine from :class:`APBSlave` and
    overrides only the packet hook to construct an :class:`APB3Packet`.
    """

    _required_signal_defaults = tuple(BASE_APB_SIGNALS)
    _optional_signal_defaults = ("PSLVERR",)

    def _build_packet(self, *, start_time, count, pwrite, paddr,
                      pwdata, prdata, pstrb, pprot, pslverr,
                      direction, extension_inputs, rand_values) -> Any:
        """Construct an APB3Packet (PSTRB/PPROT are ignored)."""
        del pstrb, pprot, direction, extension_inputs, rand_values
        return APB3Packet(
            data_width=self.bus_width,
            addr_width=self.addr_width,
            start_time=start_time,
            count=count,
            pwrite=pwrite,
            paddr=paddr,
            pwdata=pwdata,
            prdata=prdata,
            pslverr=pslverr,
        )

    def print(self, transaction):
        msg = f'{self.title} - APB3 Slave Transaction #{self.count}: '
        msg += transaction.formatted(compact=True)
        self.log.debug(msg)
