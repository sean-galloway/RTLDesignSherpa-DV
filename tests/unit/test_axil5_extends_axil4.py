# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""AXI5-Lite is AXI4-Lite plus optional groups -- and must stay that way.

AXI5-Lite changes no channel's handshake, ordering or response semantics; it
only adds optional signal groups. So AXIL5 subclasses the AXIL4 interfaces and
swaps the field-config helper instead of copying ~950 lines of channel logic.

The risk that design takes on is drift: a later edit to one protocol that does
not reach the other, leaving two implementations of the same thing with nothing
comparing them. These tests are the comparison. The central one is
``test_axil5_with_no_features_is_axil4`` -- with every switch off the two must
produce identical field configs, which is the property that makes "AXIL5 is
AXIL4 plus options" true rather than aspirational.
"""

import pytest

from CocoTBFramework.components.axil4.axil4_field_configs import (
    AXIL4FieldConfigHelper,
)
from CocoTBFramework.components.axil4.axil4_interfaces import (
    AXIL4MasterRead,
    AXIL4MasterWrite,
    AXIL4SlaveRead,
    AXIL4SlaveWrite,
)
from CocoTBFramework.components.axil5 import (
    AXIL5_FEATURE_KWARGS,
    AXIL5FieldConfigHelper,
    AXIL5MasterRead,
    AXIL5MasterWrite,
    AXIL5SlaveRead,
    AXIL5SlaveWrite,
)

CHANNELS = ['AW', 'W', 'B', 'AR', 'R']

INTERFACE_PAIRS = [
    (AXIL5MasterRead, AXIL4MasterRead),
    (AXIL5MasterWrite, AXIL4MasterWrite),
    (AXIL5SlaveRead, AXIL4SlaveRead),
    (AXIL5SlaveWrite, AXIL4SlaveWrite),
]


def _names(cfg):
    return list(cfg.field_names())


# ---------------------------------------------------------------------------
# The core equivalence
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("channel", CHANNELS)
def test_axil5_with_no_features_is_axil4(channel):
    """Every switch off => field-for-field AXI4-Lite, same order.

    This is what lets an AXIL5 BFM drive an AXI4-Lite DUT, and what would break
    first if someone edited one helper without the other.
    """
    a4 = AXIL4FieldConfigHelper.create_all_field_configs(32, 32)[channel]
    a5 = AXIL5FieldConfigHelper.create_all_field_configs(32, 32)[channel]
    assert _names(a5) == _names(a4), (
        f"{channel}: AXIL5 with no features declares {_names(a5)} but "
        f"AXI4-Lite declares {_names(a4)} -- the two have drifted apart"
    )


@pytest.mark.parametrize("channel", CHANNELS)
def test_axil5_field_widths_match_axil4_for_shared_fields(channel):
    """Shared fields keep identical widths and defaults, not just names."""
    a4 = AXIL4FieldConfigHelper.create_all_field_configs(64, 64)[channel]
    a5 = AXIL5FieldConfigHelper.create_all_field_configs(
        64, 64, user_width=4, trace=True)[channel]
    for name in _names(a4):
        f4, f5 = a4.get_field(name), a5.get_field(name)
        assert (f5.bits, f5.default) == (f4.bits, f4.default), (
            f"{channel}.{name}: AXIL5 has bits={f5.bits} default={f5.default}, "
            f"AXI4-Lite has bits={f4.bits} default={f4.default}"
        )


@pytest.mark.parametrize("axil5_cls,axil4_cls", INTERFACE_PAIRS)
def test_interfaces_subclass_rather_than_fork(axil5_cls, axil4_cls):
    """AXIL5 interfaces inherit the AXIL4 transaction logic.

    If this fails someone has re-implemented a channel, and every fix to one
    protocol from then on reaches only half the framework.
    """
    assert issubclass(axil5_cls, axil4_cls)
    assert axil5_cls.FIELD_CONFIG_HELPER is AXIL5FieldConfigHelper
    assert axil4_cls.FIELD_CONFIG_HELPER is AXIL4FieldConfigHelper


@pytest.mark.parametrize("axil5_cls,axil4_cls", INTERFACE_PAIRS)
def test_axil5_adds_no_transaction_methods_of_its_own(axil5_cls, axil4_cls):
    """AXIL5 contributes configuration, never behaviour.

    A public method defined on the AXIL5 class is a second implementation of
    something AXIL4 already does. Configuration hooks are the allowed exception.
    """
    ALLOWED = {'FIELD_CONFIG_HELPER', '_build_field_config_options'}
    own = {
        n for cls in axil5_cls.__mro__
        if cls.__module__.endswith('axil5_interfaces')
        for n in vars(cls)
        if not n.startswith('__')
    } - ALLOWED
    assert not own, (
        f"{axil5_cls.__name__} defines {sorted(own)} of its own; AXI5-Lite "
        "differs from AXI4-Lite only in which optional fields exist, so "
        "behaviour belongs in the shared AXIL4 implementation"
    )


# ---------------------------------------------------------------------------
# The optional groups themselves
# ---------------------------------------------------------------------------
def test_every_axil4_channel_builds_through_the_hook():
    """No AXIL4 channel bypasses FIELD_CONFIG_HELPER.

    The extension works only because every channel's field config is built
    through the class hook. A call site left pointing straight at
    ``AXIL4FieldConfigHelper`` would still pass all the AXI4-Lite tests while
    silently giving an AXIL5 component an AXI4-Lite channel -- the DUT's
    optional signals then go undriven and unchecked, with nothing reporting it.
    """
    import inspect

    from CocoTBFramework.components.axil4 import axil4_interfaces

    src = inspect.getsource(axil4_interfaces)
    direct = src.count("field_config=AXIL4FieldConfigHelper.")
    hooked = src.count("field_config=self.FIELD_CONFIG_HELPER.")
    assert direct == 0, (
        f"{direct} channel(s) build their field config directly from "
        "AXIL4FieldConfigHelper, bypassing the hook AXIL5 overrides"
    )
    assert hooked == 10, (
        f"expected all 10 channel field configs to route through the hook, "
        f"found {hooked}"
    )


def test_feature_kwargs_all_reach_a_channel():
    """Every switch in AXIL5_FEATURE_KWARGS actually adds a field somewhere.

    A switch nobody honours is worse than a missing one: the caller believes
    the signal is being driven and checked when nothing touches it.
    """
    base = {ch: set(_names(cfg)) for ch, cfg in
            AXIL5FieldConfigHelper.create_all_field_configs(64, 64).items()}
    VALUES = {'trace': True, 'poison': True, 'exclusive': True}
    inert = []
    for kw in AXIL5_FEATURE_KWARGS:
        opts = {kw: VALUES.get(kw, 4)}
        cfgs = AXIL5FieldConfigHelper.create_all_field_configs(64, 64, **opts)
        if not any(set(_names(cfgs[ch])) - base[ch] for ch in CHANNELS):
            inert.append(kw)
    assert not inert, f"feature switches that add no field anywhere: {inert}"


def test_optional_groups_land_on_the_right_channels():
    """Each group appears only where AXI5-Lite defines it.

    Write data carries no trace, loop or MPAM -- those ride the address and
    response channels. A BFM driving them on W would be inventing signals the
    DUT has no port for, which under the strict bind rule is a fatal error
    rather than a quiet one.
    """
    cfgs = AXIL5FieldConfigHelper.create_all_field_configs(
        64, 64, user_width=4, trace=True, loop_width=3, mpam_width=11,
        mecid_width=16, nsaid_width=4, poison=True, exclusive=True)
    got = {ch: set(_names(cfgs[ch])) for ch in CHANNELS}

    expected = {
        'AW': {'addr', 'prot', 'user', 'trace', 'loop', 'mpam', 'mecid',
               'nsaid', 'lock'},
        'AR': {'addr', 'prot', 'user', 'trace', 'loop', 'mpam', 'mecid',
               'nsaid', 'lock'},
        'W':  {'data', 'strb', 'user', 'poison'},
        'R':  {'data', 'resp', 'user', 'trace', 'loop', 'poison'},
        'B':  {'resp', 'user', 'trace', 'loop'},
    }
    assert got == expected


@pytest.mark.parametrize("channel", CHANNELS)
def test_every_optional_group_field_defaults_to_zero(channel):
    """The zero-default rule, applied to the fields AXIL5 introduces.

    An unbound field reads 0, so an optional field is only safe when 0 is also
    its "feature not in use" value -- the rule stated above
    PROTOCOL_SIGNAL_CONFIGS in shared/signal_mapping_helper.py. Every group
    added here must satisfy it, or omitting the port would mean something
    other than "the DUT does not implement this".
    """
    base = set(_names(
        AXIL4FieldConfigHelper.create_all_field_configs(64, 64)[channel]))
    cfg = AXIL5FieldConfigHelper.create_all_field_configs(
        64, 64, user_width=4, trace=True, loop_width=3, mpam_width=11,
        mecid_width=16, nsaid_width=4, poison=True, exclusive=True)[channel]
    for name in set(_names(cfg)) - base:
        assert cfg.get_field(name).default == 0, (
            f"{channel}.{name} defaults to {cfg.get_field(name).default}, not "
            "0; an omitted port reads 0, so a non-zero default would make "
            "'absent' mean something other than 'feature not in use'"
        )


def test_poison_width_tracks_the_data_width():
    """One poison bit per 64 data bits, and never zero on a narrow bus."""
    for data_width, expected in ((32, 1), (64, 1), (128, 2), (512, 8)):
        cfg = AXIL5FieldConfigHelper.create_w_field_config(
            data_width, poison=True)
        assert cfg.get_field('poison').bits == expected, (
            f"{data_width}-bit bus should carry {expected} poison bit(s)")


def test_unset_switches_are_not_forwarded_as_zero():
    """An absent switch stays absent instead of becoming an explicit 0.

    The helper's signature is the single statement of what "off" means; a
    constructor that forwarded zeros would duplicate that statement and could
    contradict it later.
    """
    opts = AXIL5MasterRead._build_field_config_options(
        {'data_width': 64, 'trace': True})
    assert opts == {'trace': True}, (
        f"expected only the switches the caller passed, got {opts}")


def test_axil5_does_not_strip_user_width_the_way_axil4_does():
    """AXIL4's factories drop user_width; AXIL5's must not.

    On AXI4-Lite there are no USER signals, so discarding the argument is
    correct. On AXI5-Lite the group is real, and silently dropping it would
    leave the BFM blind to signals the DUT drives.
    """
    import inspect

    from CocoTBFramework.components.axil5 import axil5_factories

    src = inspect.getsource(axil5_factories)
    assert "pop('user_width'" not in src and 'pop("user_width"' not in src, (
        "an AXIL5 factory strips user_width; USER is a supported AXI5-Lite "
        "group and the switch must reach the field config"
    )


# ---------------------------------------------------------------------------
# Factory contract parity
# ---------------------------------------------------------------------------
class _MockInterface:
    """Stand-in for a constructed AXIL interface.

    The factory return dicts are built purely from interface attributes, so
    they can be exercised without cocotb, a DUT or a simulator -- which is what
    makes this parity check cheap enough to run on every commit.
    """

    def __init__(self):
        for chan in ('aw_channel', 'w_channel', 'b_channel',
                     'ar_channel', 'r_channel'):
            setattr(self, chan, object())
        self.compliance_checker = object()
        for meth in ('read_transaction', 'write_transaction',
                     'single_read', 'single_write',
                     'simple_read', 'simple_write',
                     'read_register', 'write_register'):
            setattr(self, meth, lambda *a, **k: None)


def test_axil5_factories_return_the_axil4_contract():
    """AXIL5 factory dicts carry exactly the AXIL4 keys.

    The returned dictionary IS the factory API -- callers index it by key. A
    key AXI4-Lite provides and AXI5-Lite omits is a KeyError in user code, not
    a type error in the framework, so nothing here would catch it except this.

    It has already happened: the first hand-written axil5_factories dropped
    'write', 'read', 'read_reg', 'write_reg', 'simple_read', 'simple_write',
    'memory_model' and both compliance checkers, and every other test in this
    file still passed.
    """
    from CocoTBFramework.components.axil4 import axil4_factories as f4

    w, r = _MockInterface(), _MockInterface()
    pairs = [
        ("master_rd", f4.build_master_rd_components(r)),
        ("master_wr", f4.build_master_wr_components(w)),
        ("slave_rd", f4.build_slave_rd_components(r)),
        ("slave_wr", f4.build_slave_wr_components(w)),
        ("master", f4.build_master_components(w, r)),
        ("slave", f4.build_slave_components(w, r, None)),
    ]
    # Every builder must produce a non-trivial dict; an empty one would make
    # the parity assertion below vacuously true.
    for name, d in pairs:
        assert len(d) >= 4, f"{name} builder returned only {sorted(d)}"

    # The AXIL5 factories are thin wrappers over these same builders, so
    # parity is structural. Assert the wiring rather than trusting it.
    import inspect

    from CocoTBFramework.components.axil5 import axil5_factories as f5

    src = inspect.getsource(f5)
    for builder in ('build_master_rd_components', 'build_master_wr_components',
                    'build_slave_rd_components', 'build_slave_wr_components',
                    'build_master_components', 'build_slave_components'):
        assert src.count(builder) >= 2, (
            f"axil5_factories does not use {builder}; a hand-built dict there "
            "will drift from the AXI4-Lite contract"
        )
    # The six per-direction factories must delegate; none may hand-build a
    # dict. create_axil5_system is deliberately excluded -- it composes a
    # master and a slave rather than wrapping one interface, exactly as
    # create_axil4_system does, so its dict has no shared builder to come from.
    for name in ('create_axil5_master_rd', 'create_axil5_master_wr',
                 'create_axil5_slave_rd', 'create_axil5_slave_wr',
                 'create_axil5_master', 'create_axil5_slave'):
        body = inspect.getsource(getattr(f5, name))
        assert "return {" not in body, (
            f"{name} hand-builds its return dict instead of using the shared "
            "builder -- that is how the contract drifted the first time"
        )


def test_axil5_factory_surface_matches_axil4():
    """Every AXIL4 factory has an AXIL5 counterpart.

    A missing factory sends a user back to the AXIL4 one, which constructs
    AXI4-Lite components and silently ignores the AXI5-Lite groups they asked
    for.
    """
    from CocoTBFramework.components.axil4 import axil4_factories as f4
    from CocoTBFramework.components.axil5 import axil5_factories as f5

    def factories(mod, tag):
        return {n.replace(tag, '') for n in dir(mod)
                if n.startswith('create_') and tag in n}

    missing = factories(f4, 'axil4') - factories(f5, 'axil5')
    assert not missing, f"AXIL5 has no counterpart for: {sorted(missing)}"


def test_axil5_reexports_the_shared_compliance_helpers():
    """The protocol-agnostic compliance helpers are shared, not re-implemented.

    They walk the component dictionaries and never touch a protocol type, so a
    fourth copy would be pure drift surface.
    """
    from CocoTBFramework.components.axil4 import axil4_factories as f4
    from CocoTBFramework.components.axil5 import axil5_factories as f5

    for name in ('get_unified_compliance_reports',
                 'print_unified_compliance_reports',
                 'is_unified_compliance_checking_enabled',
                 'print_all_compliance_reports_from_system',
                 'print_compliance_to_log'):
        assert getattr(f5, name) is getattr(f4, name), (
            f"{name} is a separate object in axil5_factories; it should be the "
            "same shared helper, not a copy"
        )
