"""Inheritance structure tests for issues #6, #7, #15.

These tests pin down the class hierarchy that the refactors established.
Catching MRO regressions here is much cheaper than catching them in a
real cocotb simulation.
"""

from __future__ import annotations

import pytest


# ----------------------------------------------------------------------
# #6: FIFOComponentBase is a deprecated alias for GAXIComponentBase
# ----------------------------------------------------------------------


def test_fifo_component_base_inherits_gaxi_component_base():
    from CocoTBFramework.components.fifo.fifo_component_base import FIFOComponentBase
    from CocoTBFramework.components.gaxi.gaxi_component_base import GAXIComponentBase

    assert issubclass(FIFOComponentBase, GAXIComponentBase)


def test_fifo_master_still_resolves_via_fifo_component_base():
    """FIFOMaster import path unchanged — back-compat preserved."""
    from CocoTBFramework.components.fifo.fifo_component_base import FIFOComponentBase
    from CocoTBFramework.components.fifo.fifo_master import FIFOMaster

    assert issubclass(FIFOMaster, FIFOComponentBase)


# ----------------------------------------------------------------------
# #7: AXISSlave inherits GAXISlave (not GAXIMonitorBase directly)
# ----------------------------------------------------------------------


def test_axis_slave_inherits_gaxi_slave():
    """AXIS is a ready/valid protocol — must use GAXISlave's chassis."""
    from CocoTBFramework.components.axis4.axis_slave import AXISSlave
    from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave

    assert issubclass(AXISSlave, GAXISlave)


def test_axis5_slave_picks_up_change_transitively():
    """AXIS5Slave inherits AXISSlave → so it's also a GAXISlave now."""
    from CocoTBFramework.components.axis5.axis5_slave import AXIS5Slave
    from CocoTBFramework.components.gaxi.gaxi_slave import GAXISlave

    assert issubclass(AXIS5Slave, GAXISlave)


# ----------------------------------------------------------------------
# #15: APB5 classes inherit APB classes
# ----------------------------------------------------------------------


def test_apb5_monitor_inherits_apb_monitor():
    from CocoTBFramework.components.apb.apb_components import APBMonitor
    from CocoTBFramework.components.apb5.apb5_components import APB5Monitor

    assert issubclass(APB5Monitor, APBMonitor)


def test_apb5_master_inherits_apb_master():
    from CocoTBFramework.components.apb.apb_components import APBMaster
    from CocoTBFramework.components.apb5.apb5_components import APB5Master

    assert issubclass(APB5Master, APBMaster)


def test_apb5_slave_inherits_apb_slave():
    """Phase B of #15: APB5Slave now uses APBSlave's unified state machine."""
    from CocoTBFramework.components.apb.apb_components import APBSlave
    from CocoTBFramework.components.apb5.apb5_components import APB5Slave

    assert issubclass(APB5Slave, APBSlave)


# ----------------------------------------------------------------------
# Type annotations (#11) — verify the aliases are exported
# ----------------------------------------------------------------------


def test_gaxi_component_base_exports_type_aliases():
    """Issue #11: DutHandle / ClockSignal / FieldConfigInput should be importable."""
    from CocoTBFramework.components.gaxi.gaxi_component_base import (
        ClockSignal,
        DutHandle,
        FieldConfigInput,
    )
    # They're type aliases — just verify they're importable
    assert DutHandle is not None
    assert ClockSignal is not None
    assert FieldConfigInput is not None
