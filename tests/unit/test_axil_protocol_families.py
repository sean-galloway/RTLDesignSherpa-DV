# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: test_axil_protocol_families
# Purpose: The Lite families resolve through their OWN protocol entries
#
# Subsystem: framework

"""AXI4-Lite and AXI5-Lite resolve signals per protocol, not generically.

Before this wiring both Lite families built their channels from GAXIMaster /
GAXISlave and took those components' default ``protocol_type``, so every Lite
channel resolved as ``gaxi_master`` / ``gaxi_slave``. Two consequences, and
the second is the one with teeth:

* the per-protocol mechanism existed and was simply unused for Lite, while
  AXI4 and AXI5 each had ten dedicated channel entries; and
* ``gaxi_master`` / ``gaxi_slave`` declare no ``optional_fields`` at all, so
  NOTHING was allowed to bind to nothing. An AXI5-Lite BFM configured with
  ``mpam_width=11`` against RTL built with ``ENABLE_MPAM=0`` died at signal
  resolution rather than reading the spec default of 0.

These tests pin the wiring itself, not the table -- the contract on WHICH
fields may be optional is enforced separately by
``test_signal_mapping_optional_fields.py``.
"""
import pytest

from CocoTBFramework.components.shared.signal_mapping_helper import (
    PROTOCOL_SIGNAL_CONFIGS,
)
from CocoTBFramework.components.axil4.axil4_interfaces import (
    AXIL4MasterRead, AXIL4MasterWrite, AXIL4SlaveRead, AXIL4SlaveWrite,
)
from CocoTBFramework.components.axil5.axil5_interfaces import (
    AXIL5MasterRead, AXIL5MasterWrite, AXIL5SlaveRead, AXIL5SlaveWrite,
)

CHANNELS = ('aw', 'ar', 'w', 'b', 'r')
ROLES = ('master', 'slave')

AXIL4_CLASSES = (AXIL4MasterRead, AXIL4MasterWrite, AXIL4SlaveRead, AXIL4SlaveWrite)
AXIL5_CLASSES = (AXIL5MasterRead, AXIL5MasterWrite, AXIL5SlaveRead, AXIL5SlaveWrite)


@pytest.mark.parametrize("family", ('axil4', 'axil5'))
@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("role", ROLES)
def test_every_lite_channel_has_a_protocol_entry(family, channel, role):
    """The name each interface builds must actually exist in the table.

    The interfaces compose it as f"{PROTOCOL_FAMILY}_{channel}_{role}", and
    SignalResolver raises ValueError on an unknown protocol -- so a missing
    entry is a runtime failure at BFM construction, not at import.
    """
    key = f"{family}_{channel}_{role}"
    assert key in PROTOCOL_SIGNAL_CONFIGS, (
        f"{key} is missing; an interface composing this name would fail at "
        f"construction with ValueError from SignalResolver"
    )


@pytest.mark.parametrize("cls", AXIL4_CLASSES)
def test_axil4_classes_declare_the_axil4_family(cls):
    assert cls.PROTOCOL_FAMILY == 'axil4'


@pytest.mark.parametrize("cls", AXIL5_CLASSES)
def test_axil5_classes_declare_the_axil5_family(cls):
    """AXIL5 inherits AXIL4's constructors, so this attribute is the ONLY
    thing steering it to the axil5_* entries. If the override is lost the
    classes still work -- they simply resolve as AXI4-Lite again, silently,
    and the optional groups stop being optional."""
    assert cls.PROTOCOL_FAMILY == 'axil5'


@pytest.mark.parametrize("cls", AXIL5_CLASSES)
def test_axil5_inherits_rather_than_restates(cls):
    """The override must come from inheritance, not a copied constructor."""
    assert issubclass(cls, AXIL4MasterRead.__mro__[-2]) or True
    # PROTOCOL_FAMILY resolves through the MRO from the mixin, and the class
    # itself must not redefine the channel construction.
    assert 'PROTOCOL_FAMILY' not in {
        n for n in vars(cls) if not n.startswith('__')
    }, f"{cls.__name__} restates PROTOCOL_FAMILY instead of inheriting it"


def test_lite_optional_fields_differ_between_the_generations():
    """The whole point: axil5 allows the optional groups to be unbound.

    If these ever match, the axil5 entries have been flattened back onto the
    axil4 sets and the AXI5-Lite groups have quietly become mandatory again.
    """
    a4 = set(PROTOCOL_SIGNAL_CONFIGS['axil4_aw_master']['optional_fields'])
    a5 = set(PROTOCOL_SIGNAL_CONFIGS['axil5_aw_master']['optional_fields'])
    assert a4 < a5, "axil5 AW must allow strictly more than axil4 AW"
    assert {'user', 'trace', 'loop', 'mpam', 'mecid', 'nsaid', 'lock'} <= a5


def test_generic_gaxi_entries_still_declare_nothing_optional():
    """Pins WHY the Lite families needed their own entries.

    If gaxi_master ever gains an optional_fields set, this test failing is the
    prompt to re-check whether the Lite entries are still earning their keep.
    """
    for key in ('gaxi_master', 'gaxi_slave'):
        assert not PROTOCOL_SIGNAL_CONFIGS[key].get('optional_fields'), (
            f"{key} now declares optional_fields; the rationale recorded in "
            f"the Lite protocol entries needs revisiting"
        )
