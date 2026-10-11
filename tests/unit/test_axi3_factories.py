# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for AXI3 factory functions."""

import inspect

import pytest

from CocoTBFramework.components.axi3 import axi3_factories
from CocoTBFramework.components.axi3.axi3_factories import (
    create_axi3_master_interface,
    create_axi3_master_rd,
    create_axi3_master_wr,
    create_axi3_slave_interface,
    create_axi3_slave_rd,
    create_axi3_slave_wr,
    create_complete_axi3_testbench_components,
)


def test_factory_functions_are_exported():
    names = {
        'create_axi3_master_rd',
        'create_axi3_master_wr',
        'create_axi3_slave_rd',
        'create_axi3_slave_wr',
        'create_axi3_master_interface',
        'create_axi3_slave_interface',
        'create_complete_axi3_testbench_components',
    }
    assert names <= set(dir(axi3_factories))


@pytest.mark.parametrize("func", [
    create_axi3_master_rd,
    create_axi3_master_wr,
    create_axi3_slave_rd,
    create_axi3_slave_wr,
])
def test_factory_functions_take_standard_args(func):
    sig = inspect.signature(func)
    params = list(sig.parameters)
    assert params[:4] == ['dut', 'clock', 'prefix', 'log']


def test_complete_testbench_components_returns_empty_for_empty_dut():
    """A DUT with no AXI3 signals yields no components without raising."""
    class EmptyDut:
        pass

    components = create_complete_axi3_testbench_components(
        EmptyDut(), None, master_prefix="m_axi_", slave_prefix="s_axi_"
    )
    assert components == {}
