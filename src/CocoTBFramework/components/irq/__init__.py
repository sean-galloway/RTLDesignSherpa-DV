# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: IRQ Components Package
# Purpose: BFM for plain interrupt lines (level or pulse, scalar or vector)
#
# Documentation: docs/components/irq/index.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-09-28
# Promoted: 2026-10-04, bin/TBClasses/irq -> components/irq (release 1.0.0)

"""Interrupt-line BFM package.

    from CocoTBFramework.components.irq import IRQMonitor, IRQMonitorGroup, IRQPacket

    irqs = IRQMonitorGroup(dut, dut.pclk, {
        'gpio_irq':      None,     # width auto-detected
        'pic_int_out':   None,
        'pit_timer_irq': None,     # vector: one event per bit
        'rlb_irq_out':   None,
    }, title="RLB")
    irqs.start()
    ...
    ok, missing, unexpected = irqs.expect_only(['gpio_irq', 'pic_int_out',
                                                'rlb_irq_out'])

For a line WITH a handshake (valid/ready/retry) use GAXI instead — see
docs/components/gaxi/. This package is for plain interrupt wires.

PLACEMENT. This package was written in RTLDesignSherpa's bin/TBClasses on
2026-09-28 so it could be iterated without a package reinstall, with the
layout deliberately mirroring a framework component family to make promotion
a directory move. That promotion is what this file is: it landed here as
cocotb-framework 1.0.0. The RDS-side copy is gone; consumers import from
here. History before the move lives in the RTLDesignSherpa repo.
"""

from .irq_components import IRQMonitor, IRQMonitorGroup
from .irq_packet import IRQPacket

__all__ = [
    'IRQPacket',
    'IRQMonitor',
    'IRQMonitorGroup',
]
