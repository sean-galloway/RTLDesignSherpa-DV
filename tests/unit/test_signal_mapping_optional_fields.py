"""Only zero-default fields may be declared optional.

Companion to test_signal_mapping_required_fields.py. That file proves the
MECHANISM -- a declared field records itself as required, and opting out
works. This file polices the DATA: which fields the AXI4/AXI5 protocol
configs are allowed to put in 'optional_fields' at all.

The rule, stated once in signal_mapping_helper.py above PROTOCOL_SIGNAL_CONFIGS:
an unbound field reads 0 forever, so a field may be optional ONLY IF the
protocol default for the omitted signal is also 0. Where they agree, an absent
port and a port tied to its default are indistinguishable and the BFM still
models the spec. Where they disagree, silent-0 yields a DIFFERENT, LEGAL,
WRONG transaction -- AxSIZE=0 is 1 byte per beat where the spec default is the
full bus width; AxBURST=0 is FIXED where the default is INCR; WSTRB=0 writes
nothing where the default is all lanes; xLAST=0 never ends the burst.

That failure is on record one layer up: 55f9453 fixed AWSIZE/ARSIZE defaulting
to 2 (4 bytes) instead of the bus width, which made slaves mis-slice or
silently drop every write from a >32-bit master.

These are static table checks -- no DUT, no simulator, no resolver.
"""

import pytest

from CocoTBFramework.components.shared.signal_mapping_helper import (
    PROTOCOL_SIGNAL_CONFIGS,
)

# Signals whose default, when a DUT omits them, is NOT 0. Marking any of these
# optional converts an absent port into a valid-but-wrong transaction rather
# than an obviously missing one, so they may never appear in optional_fields.
NON_ZERO_DEFAULT_FIELDS = {
    'size':  'AxSIZE defaults to the full bus width; 0 means 1 byte per beat',
    'burst': 'AxBURST defaults to INCR (0b01); 0 means FIXED',
    'strb':  'WSTRB defaults to all lanes enabled; 0 writes no bytes',
    'last':  'xLAST defaults to 1; 0 means the burst never ends',
}

# Zero-default fields deliberately kept required anyway. An ID silently reading
# 0 collapses ID-reordering traffic to single-ID and still passes -- the exact
# silent-green the strict-bind rule was written to stop.
DELIBERATELY_STRICT_FIELDS = {
    'id':   'a silently-zero ID collapses ID reordering and still passes',
    'len':  'a silently-zero LEN turns every burst into a single beat',
    'addr': 'the address is the transaction; it is never inferable',
    'data': 'the payload is what the testbench exists to check',
    'resp': 'a silently-zero RESP reads as OKAY and hides every error',
}

# NOTE the prefixes are exact: 'axil4_aw_master'.startswith('axi4_') is False,
# because the fifth character is 'l', not '_'. The Lite families therefore need
# listing explicitly -- when they were first added they sat outside this guard
# entirely and the contract went unenforced for twenty configs.
AXI_CONFIG_KEYS = sorted(
    k for k in PROTOCOL_SIGNAL_CONFIGS
    if k.startswith(('axi4_', 'axi5_', 'axil4_', 'axil5_'))
    and k.endswith(('_master', '_slave'))
)


def test_axi_configs_are_present():
    """Guard the guard: if the table is empty these checks prove nothing."""
    assert len(AXI_CONFIG_KEYS) == 40, (
        f"expected 40 AXI4/AXI5/AXI4-Lite/AXI5-Lite channel configs, "
        f"found {len(AXI_CONFIG_KEYS)}: "
        f"{AXI_CONFIG_KEYS}"
    )


@pytest.mark.parametrize("key", AXI_CONFIG_KEYS)
def test_every_axi_channel_declares_optional_fields(key):
    """Each AXI channel config carries an optional_fields entry.

    The entry existing is what makes qualifier omission survivable without a
    per-call-site opt-out. It was absent for every channel once: the resolver
    read `self.config.get('optional_fields', ())`, no config defined the key,
    so AxUSER/AxREGION/AxQOS/AxLOCK/AxCACHE/AxPROT became mandatory on every
    DUT and each missing qualifier was a fatal construction error.
    """
    assert 'optional_fields' in PROTOCOL_SIGNAL_CONFIGS[key], (
        f"{key} declares no optional_fields, so every qualifier it names is "
        "mandatory and any DUT omitting one dies at construction"
    )


@pytest.mark.parametrize("key", AXI_CONFIG_KEYS)
def test_no_non_zero_default_field_is_optional(key):
    """The core rule: non-zero-default signals may never be optional."""
    optional = set(PROTOCOL_SIGNAL_CONFIGS[key].get('optional_fields', ()))
    violations = optional & set(NON_ZERO_DEFAULT_FIELDS)
    assert not violations, "\n".join(
        [f"{key} marks non-zero-default field(s) optional:"]
        + [f"  - {f}: {NON_ZERO_DEFAULT_FIELDS[f]}" for f in sorted(violations)]
        + ["An unbound field reads 0, so this silently produces a different, "
           "legal, wrong transaction instead of a missing one."]
    )


@pytest.mark.parametrize("key", AXI_CONFIG_KEYS)
def test_deliberately_strict_fields_stay_required(key):
    """Zero-default fields the rule permits but we keep strict on purpose."""
    optional = set(PROTOCOL_SIGNAL_CONFIGS[key].get('optional_fields', ()))
    violations = optional & set(DELIBERATELY_STRICT_FIELDS)
    assert not violations, "\n".join(
        [f"{key} relaxed a deliberately-strict field:"]
        + [f"  - {f}: {DELIBERATELY_STRICT_FIELDS[f]}" for f in sorted(violations)]
        + ["These default to 0, so the zero-default rule would allow them. "
           "They are excluded anyway: erring strict costs a loud construction "
           "error, erring loose costs a suite that cannot fail."]
    )


def test_axil4_default_optional_fields_obey_the_same_rule():
    """AXI-Lite's optional set lives elsewhere but answers to the same rule.

    AXIL4 has no per-channel entry in PROTOCOL_SIGNAL_CONFIGS -- its channels
    ride the generic gaxi_* configs -- so its config-level tier is the module
    constant AXIL4_DEFAULT_OPTIONAL_FIELDS instead. Being in a different file
    is not a reason to escape the check: WSTRB and xLAST have non-zero defaults
    on AXI-Lite exactly as they do on AXI4.
    """
    from CocoTBFramework.components.axil4.axil4_interfaces import (
        AXIL4_DEFAULT_OPTIONAL_FIELDS,
    )

    optional = set(AXIL4_DEFAULT_OPTIONAL_FIELDS)
    banned = (set(NON_ZERO_DEFAULT_FIELDS) | set(DELIBERATELY_STRICT_FIELDS))
    violations = optional & banned
    assert not violations, (
        f"AXIL4_DEFAULT_OPTIONAL_FIELDS marks {sorted(violations)} optional; "
        "an unbound field reads 0, which for these is a different, legal, "
        "wrong transfer rather than a missing one."
    )


def test_axil4_interfaces_apply_the_default_by_union_not_replacement():
    """A caller-supplied opt-out must not silently drop the built-in default.

    Each AXIL4 interface class unions kwargs['optional_fields'] with
    AXIL4_DEFAULT_OPTIONAL_FIELDS. Replacing instead of unioning would mean a
    TB opting one field out quietly re-armed the fatal rule on AxPROT, and the
    failure would surface as an unrelated construction error somewhere else.
    """
    import inspect

    from CocoTBFramework.components.axil4 import axil4_interfaces as axil

    src = inspect.getsource(axil)
    unions = src.count("| set(AXIL4_DEFAULT_OPTIONAL_FIELDS)")
    assert unions == 4, (
        f"expected all 4 AXIL4 interface classes to union the default, "
        f"found {unions} -- a class that assigns instead of unioning drops it"
    )


def test_declared_optional_fields_actually_exist_on_the_channel():
    """optional_fields naming a field the channel never declares is dead text.

    A stale name is not harmful at runtime -- the resolver only consults the
    set for fields it is already resolving -- but it misleads the next reader
    into thinking a field is handled when nothing references it. AxREGION on
    the AXI5 configs is the deliberate exception: AMBA5 removed the signal, and
    the entry is what lets an AXI4-shaped BFM bind against an AXI5 port.
    """
    from CocoTBFramework.components.axi4.axi4_field_configs import (
        get_axi4_field_configs,
    )
    from CocoTBFramework.components.axi5.axi5_field_configs import (
        get_axi5_field_configs,
    )

    ALLOWED_ABSENT = {'region'}   # AMBA5 removed it; kept for AXI4-shaped BFMs

    stale = {}
    for tag, cfgs in (('axi4', get_axi4_field_configs()),
                      ('axi5', get_axi5_field_configs())):
        for chan, cfg in cfgs.items():
            declared = set(cfg.field_names())
            for role in ('master', 'slave'):
                key = f"{tag}_{chan.lower()}_{role}"
                if key not in PROTOCOL_SIGNAL_CONFIGS:
                    continue
                optional = set(
                    PROTOCOL_SIGNAL_CONFIGS[key].get('optional_fields', ()))
                extra = optional - declared - ALLOWED_ABSENT
                if extra:
                    stale[key] = sorted(extra)

    assert not stale, (
        f"optional_fields naming fields the channel does not declare: {stale}. "
        "Either the field config lost a field or the name is a typo."
    )
