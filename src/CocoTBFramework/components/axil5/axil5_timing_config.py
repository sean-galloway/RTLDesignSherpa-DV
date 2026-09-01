# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5 timing configuration
# Purpose: Named timing profiles for AXI5-Lite components
#
# Subsystem: framework

"""AXI5-Lite timing configuration.

The AXI4 and AXI5 equivalents of this module; the API is deliberately
identical so a testbench moves between families by changing the import and
the profile prefix.

One difference from ``axi4_timing_config`` is deliberate and worth naming: it
constrains only the READ channels (``ar_*``/``r_*``), yet
``bin/TBClasses/axi4/axi4_master_write_tb.py`` imports it -- so a write
testbench asking for 'axi4_slow' silently gets default timing on AW, W and B.
``axi5_timing_config`` constrains all five. This module follows AXI5.

Delays are FlexRandomizer constraints: a list of (min, max) ranges with a
weight per range.
"""
from typing import Any, Dict, List

from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer
from CocoTBFramework.components.shared.amba_timing_profiles import (
    canonical_names,
    canonical_profiles_for,
    resolve_profile_name,
)


# All five channels. AXI5-Lite has the same channel set as AXI4 -- it drops
# bursts and IDs, not channels -- so nothing here is read- or write-only.
_TIMING_PROFILES: Dict[str, Dict[str, Any]] = {
    'axil5_normal': {
        'aw_valid_delay': ([(0, 3), (4, 8)], [0.7, 0.3]),
        'aw_ready_delay': ([(0, 2), (3, 6)], [0.8, 0.2]),
        'w_valid_delay':  ([(0, 3), (4, 8)], [0.7, 0.3]),
        'w_ready_delay':  ([(0, 2), (3, 6)], [0.8, 0.2]),
        'b_valid_delay':  ([(1, 4), (5, 10)], [0.6, 0.4]),
        'b_ready_delay':  ([(0, 3), (4, 7)], [0.7, 0.3]),
        'ar_valid_delay': ([(0, 3), (4, 8)], [0.7, 0.3]),
        'ar_ready_delay': ([(0, 2), (3, 6)], [0.8, 0.2]),
        'r_valid_delay':  ([(1, 4), (5, 10)], [0.6, 0.4]),
        'r_ready_delay':  ([(0, 3), (4, 7)], [0.7, 0.3]),
    },
    'axil5_fast': {
        'aw_valid_delay': ([(0, 1)], [1.0]),
        'aw_ready_delay': ([(0, 1)], [1.0]),
        'w_valid_delay':  ([(0, 1)], [1.0]),
        'w_ready_delay':  ([(0, 1)], [1.0]),
        'b_valid_delay':  ([(0, 2)], [1.0]),
        'b_ready_delay':  ([(0, 1)], [1.0]),
        'ar_valid_delay': ([(0, 1)], [1.0]),
        'ar_ready_delay': ([(0, 1)], [1.0]),
        'r_valid_delay':  ([(0, 2)], [1.0]),
        'r_ready_delay':  ([(0, 1)], [1.0]),
    },
    'axil5_slow': {
        'aw_valid_delay': ([(5, 15)], [1.0]),
        'aw_ready_delay': ([(3, 12)], [1.0]),
        'w_valid_delay':  ([(5, 15)], [1.0]),
        'w_ready_delay':  ([(3, 12)], [1.0]),
        'b_valid_delay':  ([(8, 20)], [1.0]),
        'b_ready_delay':  ([(5, 15)], [1.0]),
        'ar_valid_delay': ([(5, 15)], [1.0]),
        'ar_ready_delay': ([(3, 12)], [1.0]),
        'r_valid_delay':  ([(8, 20)], [1.0]),
        'r_ready_delay':  ([(5, 15)], [1.0]),
    },
    'axil5_backtoback': {
        'aw_valid_delay': ([(0, 0)], [1.0]),
        'aw_ready_delay': ([(0, 0)], [1.0]),
        'w_valid_delay':  ([(0, 0)], [1.0]),
        'w_ready_delay':  ([(0, 0)], [1.0]),
        'b_valid_delay':  ([(0, 0)], [1.0]),
        'b_ready_delay':  ([(0, 0)], [1.0]),
        'ar_valid_delay': ([(0, 0)], [1.0]),
        'ar_ready_delay': ([(0, 0)], [1.0]),
        'r_valid_delay':  ([(0, 0)], [1.0]),
        'r_ready_delay':  ([(0, 0)], [1.0]),
    },
    'axil5_stress': {
        'aw_valid_delay': ([(0, 0), (10, 25)], [0.3, 0.7]),
        'aw_ready_delay': ([(0, 0), (15, 30)], [0.4, 0.6]),
        'w_valid_delay':  ([(0, 0), (10, 25)], [0.3, 0.7]),
        'w_ready_delay':  ([(0, 0), (15, 30)], [0.4, 0.6]),
        'b_valid_delay':  ([(0, 0), (12, 28)], [0.3, 0.7]),
        'b_ready_delay':  ([(0, 0), (8, 20)], [0.5, 0.5]),
        'ar_valid_delay': ([(0, 0), (10, 25)], [0.3, 0.7]),
        'ar_ready_delay': ([(0, 0), (15, 30)], [0.4, 0.6]),
        'r_valid_delay':  ([(0, 0), (12, 28)], [0.3, 0.7]),
        'r_ready_delay':  ([(0, 0), (8, 20)], [0.5, 0.5]),
    },
    # AXI5-Lite feature profiles. AXI5 has 'atomic', 'mte' and 'chunked'
    # alongside 'secure'; Lite has none of those three -- no atomics, no
    # memory tagging, no read-data chunking -- so only the secure profile
    # carries over, exercising the NSAID/MPAM/MECID qualifiers that DO exist.
    'axil5_secure': {
        'aw_valid_delay': ([(0, 2), (5, 12)], [0.6, 0.4]),
        'aw_ready_delay': ([(0, 2), (4, 10)], [0.7, 0.3]),
        'w_valid_delay':  ([(0, 2), (5, 12)], [0.6, 0.4]),
        'w_ready_delay':  ([(0, 2), (4, 10)], [0.7, 0.3]),
        'b_valid_delay':  ([(2, 6), (7, 14)], [0.6, 0.4]),
        'b_ready_delay':  ([(0, 3), (4, 9)], [0.7, 0.3]),
        'ar_valid_delay': ([(0, 2), (5, 12)], [0.6, 0.4]),
        'ar_ready_delay': ([(0, 2), (4, 10)], [0.7, 0.3]),
        'r_valid_delay':  ([(2, 6), (7, 14)], [0.6, 0.4]),
        'r_ready_delay':  ([(0, 3), (4, 9)], [0.7, 0.3]),
    },
}

# The seven canonical AMBA profiles (fixed, constrained, fast, backtoback,
# burst_pause, slow_producer, high_throughput) come from the shared table, so
# a profile name means the same delays on every AMBA family rather than
# whatever each family happened to define.
#
# The canonical definition WINS where a name collides. 'fast' meaning one set
# of delays on AXI4 and another on AXI4-Lite is precisely the confusion this
# table exists to remove, and a name that means two things is worse than a
# name that means the less convenient one. Family-specific profiles that do
# NOT collide -- normal, slow, stress, secure -- are untouched.
_TIMING_PROFILES.update(canonical_profiles_for('axil5'))

DEFAULT_PROFILE = 'axil5_normal'


def create_axil5_timing_from_profile(profile_name: str) -> Dict[str, Any]:
    """Build a FlexRandomizer timing configuration from a named profile.

    An unknown name falls back to ``axil5_normal``, matching the AXI4/AXI5
    behaviour. ``profile_name`` in the result is the name ASKED FOR, so a
    caller can see it was not honoured.
    """
    resolved = resolve_profile_name(profile_name, 'axil5', _TIMING_PROFILES)
    constraints = _TIMING_PROFILES.get(resolved, _TIMING_PROFILES[DEFAULT_PROFILE])
    return {
        'profile_name': profile_name,
        'randomizer': FlexRandomizer(constraints),
        'constraints': constraints,
    }


def get_axil5_timing_profiles() -> List[str]:
    """List the available AXI5-Lite timing profiles."""
    return list(_TIMING_PROFILES)


def create_axil5_randomizer_configs() -> Dict[str, Any]:
    """Every profile, keyed by its short name (the prefix stripped)."""
    return {
        name.split('_', 1)[1]: create_axil5_timing_from_profile(name)
        for name in _TIMING_PROFILES
    }


def get_timing_for_axil5_feature(feature: str) -> Dict[str, Any]:
    """Recommended profile for an AXI5-Lite optional-signal feature.

    AXI5's equivalent maps 'atomic', 'mte' and 'chunked' as well. AXI5-Lite has
    none of those, so an unknown feature falls back to the normal profile
    rather than pretending a mapping exists.
    """
    feature_mapping = {
        'secure': 'axil5_secure',
        'nsaid': 'axil5_secure',
        'mpam': 'axil5_secure',
        'mecid': 'axil5_secure',
    }
    return create_axil5_timing_from_profile(
        feature_mapping.get(feature, DEFAULT_PROFILE)
    )
