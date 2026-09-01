# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL4 timing configuration
# Purpose: Named timing profiles for AXI4-Lite components
#
# Subsystem: framework

"""AXI4-Lite timing configuration.

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

from CocoTBFramework.components.shared.amba_timing_profiles import (
    canonical_profiles_for,
    resolve_profile_name,
)
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer

# All five channels. AXI4-Lite has the same channel set as AXI4 -- it drops
# bursts and IDs, not channels -- so nothing here is read- or write-only.
_TIMING_PROFILES: Dict[str, Dict[str, Any]] = {
    'axil4_normal': {
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
    'axil4_fast': {
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
    'axil4_slow': {
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
    'axil4_backtoback': {
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
    'axil4_stress': {
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
_TIMING_PROFILES.update(canonical_profiles_for('axil4'))

DEFAULT_PROFILE = 'axil4_normal'


def create_axil4_timing_from_profile(profile_name: str) -> Dict[str, Any]:
    """Build a FlexRandomizer timing configuration from a named profile.

    An unknown name falls back to ``axil4_normal``, matching the AXI4/AXI5
    behaviour. ``profile_name`` in the result is the name ASKED FOR, so a
    caller can see it was not honoured.
    """
    resolved = resolve_profile_name(profile_name, 'axil4', _TIMING_PROFILES)
    constraints = _TIMING_PROFILES.get(resolved, _TIMING_PROFILES[DEFAULT_PROFILE])
    return {
        'profile_name': profile_name,
        'randomizer': FlexRandomizer(constraints),
        'constraints': constraints,
    }


def get_axil4_timing_profiles() -> List[str]:
    """List the available AXI4-Lite timing profiles."""
    return list(_TIMING_PROFILES)


def create_axil4_randomizer_configs() -> Dict[str, Any]:
    """Every profile, keyed by its short name (the prefix stripped)."""
    return {
        name.split('_', 1)[1]: create_axil4_timing_from_profile(name)
        for name in _TIMING_PROFILES
    }
