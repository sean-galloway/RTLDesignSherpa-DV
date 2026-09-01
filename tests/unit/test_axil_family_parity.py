# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: test_axil_family_parity
# Purpose: The Lite families carry the same modules as the full AXI families
#
# Subsystem: framework

"""AXI4-Lite / AXI5-Lite structural parity with AXI4 / AXI5.

The point of these checks is that a gap here is INVISIBLE. A missing module
does not fail; it just means a testbench reaching for the Lite equivalent of
something it uses on AXI4 finds nothing and hand-rolls a substitute. That is
how the two halves of a framework drift apart, and it is why the parity is
asserted rather than assumed.

What is deliberately NOT asserted is sameness of content. AXI4-Lite has no
bursts, no IDs and no exclusive access, so its constraint sets and profiles
are legitimately different -- see the module docstrings for each case.
"""
import importlib

import pytest

FAMILIES = ('axi4', 'axi5', 'axil4', 'axil5')

#: Modules every family is expected to carry.
CORE_MODULES = (
    'field_configs',
    'interfaces',
    'factories',
    'packet',
    'packet_utils',
    'transaction',
    'timing_config',
    'randomization_config',
    'randomization_manager',
    'compliance_checker',
)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("module", CORE_MODULES)
def test_every_family_carries_every_core_module(family, module):
    """axi4/axi5 set the bar; the Lite families must clear it."""
    name = f"CocoTBFramework.components.{family}.{family}_{module}"
    try:
        importlib.import_module(name)
    except ImportError as exc:                      # pragma: no cover
        pytest.fail(f"{name} is missing: {exc}")


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_exports_from_its_package_root(family):
    """axil4/__init__.py was empty once, so the package had no public surface
    and consumers reached into submodules. That is the state this pins shut."""
    pkg = importlib.import_module(f"CocoTBFramework.components.{family}")
    assert getattr(pkg, '__all__', None), f"{family} exposes no __all__"
    missing = [n for n in pkg.__all__ if not hasattr(pkg, n)]
    assert not missing, f"{family}.__all__ names unimportable symbols: {missing}"


@pytest.mark.parametrize("family,expected", [('axil4', 'axil4'), ('axil5', 'axil5')])
def test_lite_transaction_is_single_beat(family, expected):
    """AXI4-Lite has no AxLEN, so expected_beats is 1 by construction.

    The AXI4 tracker derives it from awlen/arlen; doing that here would read a
    field that does not exist and quietly settle on 1 anyway -- correct by
    accident is not the same as correct.
    """
    mod = importlib.import_module(
        f"CocoTBFramework.components.{family}.{family}_transaction")
    cls = getattr(mod, f"{family.upper()}Transaction")
    txn = cls(0, 'read')
    assert txn.expected_beats == 1


@pytest.mark.parametrize("family", ('axil4', 'axil5'))
def test_lite_read_completes_without_rlast(family):
    """AXI4 completes a read on RLAST. Lite has no RLAST, so waiting for one
    would hang forever -- a single R beat must complete the transaction."""
    mod = importlib.import_module(
        f"CocoTBFramework.components.{family}.{family}_transaction")
    cls = getattr(mod, f"{family.upper()}Transaction")
    txn = cls(0, 'read')

    class RBeat:
        rdata = 0xDEAD
        rresp = 0
    txn.add_response_packet(RBeat())
    assert txn.is_complete, "a Lite read must complete on its single R beat"


def test_axil5_transaction_subclasses_axil4():
    """AXI5-Lite changes no transaction semantics, so it must extend rather
    than restate -- the same rule test_axil5_extends_axil4 applies to the
    interfaces."""
    from CocoTBFramework.components.axil4.axil4_transaction import AXIL4Transaction
    from CocoTBFramework.components.axil5.axil5_transaction import AXIL5Transaction
    assert issubclass(AXIL5Transaction, AXIL4Transaction)


def test_axil5_records_absent_groups_as_absent():
    """A group the DUT was built without must not be recorded as 0.

    'MPAM is zero' and 'this DUT has no MPAM' mean different things, and
    collapsing them makes a build mismatch unreadable after the fact.
    """
    from CocoTBFramework.components.axil5.axil5_transaction import AXIL5Transaction
    txn = AXIL5Transaction(0, 'write')

    class AWNoMpam:
        awaddr = 0x100
        awuser = 3
    txn.add_address_packet(AWNoMpam())
    assert 'user' in txn.addr_sideband
    assert 'mpam' not in txn.addr_sideband


def test_axil4_constraints_omit_what_lite_does_not_have():
    """Burst, ID and exclusive-access constraints must be ABSENT, not pinned.

    A constraint that can only take one value is not a constraint; leaving it
    in invites a caller to set it and wonder why nothing changes.
    """
    from CocoTBFramework.components.axil4.axil4_randomization_config import (
        AXIL4ConstraintSet,
    )
    fields = set(vars(AXIL4ConstraintSet()))
    for absent in ('burst_len_min', 'burst_len_max', 'burst_types',
                   'burst_size_max', 'id_min', 'id_max',
                   'exclusive_access_rate', 'locked_access_rate'):
        assert absent not in fields, f"{absent} has no AXI4-Lite meaning"


def test_axil5_puts_exclusive_access_back():
    """AXI5-Lite adds AxLOCK, so the rate is meaningful again."""
    from CocoTBFramework.components.axil5.axil5_randomization_config import (
        AXIL5ConstraintSet,
    )
    assert 'exclusive_access_rate' in vars(AXIL5ConstraintSet())


def test_axil5_with_no_groups_configured_is_axil4_shaped():
    """The equivalence the whole family rests on, at the randomizer layer."""
    from CocoTBFramework.components.axil5.axil5_randomization_config import (
        AXIL5RandomizationConfig,
    )
    c = AXIL5RandomizationConfig(32, 'basic').get_constraints()
    assert not c.any_group_enabled()


def test_axil5_manager_never_draws_a_group_the_dut_lacks():
    """next_sideband is driven by the widths dict -- what the DUT carries --
    not by what the profile enables, mirroring the RTL's ENABLE_* asymmetry."""
    from CocoTBFramework.components.axil5.axil5_randomization_config import (
        AXIL5RandomizationConfig,
    )
    from CocoTBFramework.components.axil5.axil5_randomization_manager import (
        AXIL5RandomizationManager,
    )
    mgr = AXIL5RandomizationManager(
        protocol_config=AXIL5RandomizationConfig(32, 'stress'), seed=1)
    got = mgr.next_sideband('aw', {'user': 4})
    assert set(got) == {'user'}, "drew a group the DUT does not carry"


def test_lite_managers_are_reproducible_from_their_seed():
    """Two managers with one seed must agree; a shared global RNG would make
    a run depend on how many other components drew from it first."""
    from CocoTBFramework.components.axil4.axil4_randomization_manager import (
        AXIL4RandomizationManager,
    )
    a = AXIL4RandomizationManager(seed=42)
    b = AXIL4RandomizationManager(seed=42)
    assert [a.next_address() for _ in range(5)] == [b.next_address() for _ in range(5)]
