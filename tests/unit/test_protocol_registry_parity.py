# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: test_protocol_registry_parity
# Purpose: The two protocol registries must not drift apart
#
# Subsystem: framework

"""``PROTOCOL_TYPES`` and ``PROTOCOL_SIGNAL_CONFIGS`` must agree.

A protocol_type is validated in one file and resolved to signal patterns in
another. Registering it in only one is the failure this pins, and it is a
nasty one because of WHEN it surfaces:

* register the signal pattern only -> imports fine, every unit test passes,
  then BFM construction fails inside a simulation with "protocol_type must be
  one of ..." listing a set that looks authoritative and does not mention the
  name added two files away;
* register the type only -> construction succeeds and SignalResolver raises
  "Unknown protocol type" instead.

Both are late, and both point at the wrong file. protocol_types.py's own
header records that these lists drifted before (issue #9) and that the fix was
to centralise one of them -- which removed the duplication between the two
BASES but left this pair unchecked. This is that check.
"""
import pytest

from CocoTBFramework.components.shared.protocol_types import (
    PROTOCOL_TYPES,
    validate_protocol_type,
)
from CocoTBFramework.components.shared.signal_mapping_helper import (
    PROTOCOL_SIGNAL_CONFIGS,
)

#: Configs that are not ready/valid CHANNELS and so are not validated as
#: protocol_types: the wavedrom capture tables.
NON_CHANNEL = {k for k in PROTOCOL_SIGNAL_CONFIGS if k.endswith('_wavedrom')}
CHANNEL_CONFIGS = set(PROTOCOL_SIGNAL_CONFIGS) - NON_CHANNEL


def test_every_channel_config_is_an_accepted_protocol_type():
    """Otherwise the name resolves to patterns that construction rejects."""
    missing = sorted(CHANNEL_CONFIGS - PROTOCOL_TYPES)
    assert not missing, (
        f"{missing} have signal patterns but are not accepted protocol_types; "
        f"a BFM asking for one fails at construction, not at import"
    )


def test_every_protocol_type_has_signal_patterns():
    """Otherwise construction succeeds and SignalResolver raises instead."""
    missing = sorted(PROTOCOL_TYPES - set(PROTOCOL_SIGNAL_CONFIGS))
    assert not missing, (
        f"{missing} are accepted protocol_types with no entry in "
        f"PROTOCOL_SIGNAL_CONFIGS; SignalResolver raises on these"
    )


@pytest.mark.parametrize("family", ('axi4', 'axi5', 'axil4', 'axil5'))
@pytest.mark.parametrize("channel", ('aw', 'ar', 'w', 'b', 'r'))
@pytest.mark.parametrize("role", ('master', 'slave'))
def test_every_amba_channel_is_registered_in_both(family, channel, role):
    """The four AMBA families, all five channels, both roles -- 40 names.

    Enumerated rather than derived from either registry, so deleting an entry
    from BOTH still fails here instead of silently shrinking the contract.
    """
    key = f"{family}_{channel}_{role}"
    assert key in PROTOCOL_TYPES, f"{key} missing from PROTOCOL_TYPES"
    assert key in PROTOCOL_SIGNAL_CONFIGS, f"{key} missing from PROTOCOL_SIGNAL_CONFIGS"
    validate_protocol_type(key)          # must not raise


def test_validate_rejects_an_unregistered_name():
    """Guard the guard: if validation accepted anything, the checks above
    would pass while proving nothing."""
    with pytest.raises(ValueError):
        validate_protocol_type('axil9_zz_master')
