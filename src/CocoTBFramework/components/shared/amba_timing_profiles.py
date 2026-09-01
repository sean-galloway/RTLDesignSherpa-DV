# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AMBA canonical timing profiles
# Purpose: The AXI_RANDOMIZER_CONFIGS profile set, shared by all AMBA families
#
# Subsystem: framework

"""The canonical AMBA timing profiles, in one place.

These are the seven profile names in ``bin/TBClasses/amba/amba_random_configs.py``
(``AXI_RANDOMIZER_CONFIGS``) -- the set every AMBA testbench in the repo already
selects from. Each AMBA family's ``*_timing_config`` builds its prefixed entries
from this table, so 'burst_pause' means the same delays on AXI4, AXI5, AXI4-Lite
and AXI5-Lite instead of meaning whatever each family happened to define.

**Why the values are duplicated rather than imported.** ``AXI_RANDOMIZER_CONFIGS``
lives in the main repo's ``bin/TBClasses``, which DEPENDS on this framework --
importing it here would invert the dependency and make the framework unusable
standalone. So the numbers are replicated, and the drift that invites is caught
by ``val/amba/test_amba_timing_profile_parity.py`` in the main repo, which is
the one place both are importable. If you change a value here, that test tells
you the two have diverged.

The AMBA table is keyed by ROLE (a master's ``valid_delay``, a slave's
``ready_delay``); the per-family timing configs are keyed by CHANNEL
(``aw_valid_delay`` ... ``r_ready_delay``). :func:`expand_to_channels` is that
translation, applied identically for every family, because a profile that
delayed only some channels would silently leave the others running flat out --
the bug ``axi4_timing_config`` already has by covering reads only.
"""
from typing import Any, Dict, List, Tuple

#: The five AMBA channels. Every AXI and AXI-Lite family has all five.
AMBA_CHANNELS = ('aw', 'w', 'b', 'ar', 'r')

#: profile name -> (master valid_delay, slave ready_delay), copied verbatim
#: from AXI_RANDOMIZER_CONFIGS.
CANONICAL_PROFILES: Dict[str, Tuple[Any, Any]] = {
    'fixed': (
        ([(1, 1)], [1]),
        ([(1, 1)], [1]),
    ),
    'constrained': (
        ([(0, 0), (1, 5), (6, 10)], [5, 3, 1]),
        ([(0, 0), (1, 5), (6, 10)], [5, 3, 1]),
    ),
    'fast': (
        ([(0, 0), (1, 5), (6, 10)], [5, 0, 0]),
        ([(0, 0), (1, 5), (6, 10)], [5, 0, 0]),
    ),
    'backtoback': (
        ([(0, 0)], [1]),
        ([(0, 0)], [1]),
    ),
    'burst_pause': (
        ([(0, 0), (10, 20)], [8, 1]),
        ([(0, 0), (12, 25)], [8, 1]),
    ),
    'slow_producer': (
        ([(8, 20)], [1]),
        ([(8, 20)], [1]),
    ),
    'high_throughput': (
        ([(0, 1)], [1]),
        ([(0, 1)], [1]),
    ),
}


def expand_to_channels(valid_delay: Any, ready_delay: Any,
                       channels=AMBA_CHANNELS) -> Dict[str, Any]:
    """Turn one (valid, ready) pair into per-channel delay constraints.

    Every channel gets the same constraint, which is what the role-keyed AMBA
    table means: a master's ``valid_delay`` applies wherever that master drives
    a VALID, and likewise for ready.
    """
    out: Dict[str, Any] = {}
    for ch in channels:
        out[f'{ch}_valid_delay'] = valid_delay
        out[f'{ch}_ready_delay'] = ready_delay
    return out


def canonical_profiles_for(prefix: str,
                           channels=AMBA_CHANNELS) -> Dict[str, Dict[str, Any]]:
    """The seven canonical profiles, named ``{prefix}_{profile}``.

    Args:
        prefix: family prefix, e.g. ``'axi4'`` or ``'axil5'``.
    """
    return {
        f'{prefix}_{name}': expand_to_channels(valid, ready, channels)
        for name, (valid, ready) in CANONICAL_PROFILES.items()
    }


def canonical_names() -> List[str]:
    """The seven profile names, unprefixed."""
    return list(CANONICAL_PROFILES)


def resolve_profile_name(name: str, prefix: str, available) -> str:
    """Accept either ``'burst_pause'`` or ``'axi4_burst_pause'``.

    A testbench that has been selecting profiles by the bare AMBA name for
    years should not have to learn a prefix to keep working, and a caller
    reading the family's own profile list should not have to strip one.
    """
    if name in available:
        return name
    prefixed = f'{prefix}_{name}'
    if prefixed in available:
        return prefixed
    return name
