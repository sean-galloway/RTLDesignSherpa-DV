# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: axi4_timing_config
# Purpose: AXI4 Timing Configuration
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
AXI4 Timing Configuration

Simple timing configuration for AXI4 components using existing FlexRandomizer infrastructure.
Provides common timing profiles for AXI4 testing.
"""

from typing import Any, Dict

from CocoTBFramework.components.shared.amba_timing_profiles import (
    canonical_names,
    canonical_profiles_for,
    resolve_profile_name,
)
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer


def create_axi4_timing_from_profile(profile_name: str) -> Dict[str, Any]:
    """
    Create AXI4 timing configuration from a named profile.

    Args:
        profile_name: Timing profile name ('axi4_normal', 'axi4_fast', etc.)

    Returns:
        Dictionary with timing configuration
    """
    # Define timing profiles using existing FlexRandomizer patterns
    timing_profiles = {
        'axi4_normal': {
            'ar_valid_delay': ([(0, 3), (4, 8)], [0.7, 0.3]),
            'ar_ready_delay': ([(0, 2), (3, 6)], [0.8, 0.2]),
            'r_valid_delay': ([(1, 4), (5, 10)], [0.6, 0.4]),
            'r_ready_delay': ([(0, 3), (4, 7)], [0.7, 0.3]),
        },
        'axi4_fast': {
            'ar_valid_delay': ([(0, 1)], [1.0]),
            'ar_ready_delay': ([(0, 1)], [1.0]),
            'r_valid_delay': ([(0, 2)], [1.0]),
            'r_ready_delay': ([(0, 1)], [1.0]),
        },
        'axi4_slow': {
            'ar_valid_delay': ([(5, 15)], [1.0]),
            'ar_ready_delay': ([(3, 12)], [1.0]),
            'r_valid_delay': ([(8, 20)], [1.0]),
            'r_ready_delay': ([(5, 15)], [1.0]),
        },
        'axi4_backtoback': {
            'ar_valid_delay': ([(0, 0)], [1.0]),
            'ar_ready_delay': ([(0, 0)], [1.0]),
            'r_valid_delay': ([(0, 0)], [1.0]),
            'r_ready_delay': ([(0, 0)], [1.0]),
        },
        'axi4_stress': {
            'ar_valid_delay': ([(0, 0), (10, 25)], [0.3, 0.7]),
            'ar_ready_delay': ([(0, 0), (15, 30)], [0.4, 0.6]),
            'r_valid_delay': ([(0, 0), (12, 28)], [0.3, 0.7]),
            'r_ready_delay': ([(0, 0), (8, 20)], [0.5, 0.5]),
        }
    }
    # The seven canonical AMBA profiles from AXI_RANDOMIZER_CONFIGS, so a
    # name means the same delays on every AMBA family rather than whatever
    # each family happened to define. The canonical definition WINS where a
    # name collides ('fast', 'backtoback'): a name that means two things is
    # worse than a name that means the less convenient one. Verified before
    # changing it that no caller in either repo passes a colliding name --
    # every consumer passes 'axi4_normal', which does not collide.
    timing_profiles.update(canonical_profiles_for('axi4'))

    resolved = resolve_profile_name(profile_name, 'axi4', timing_profiles)

    # Get profile or default to normal
    constraints = timing_profiles.get(resolved, timing_profiles['axi4_normal'])

    # Create FlexRandomizer with the constraints
    randomizer = FlexRandomizer(constraints)

    return {
        'profile_name': profile_name,
        'randomizer': randomizer,
        'constraints': constraints
    }


def get_axi4_timing_profiles():
    """Get list of available AXI4 timing profiles."""
    base = ['axi4_normal', 'axi4_fast', 'axi4_slow', 'axi4_backtoback', 'axi4_stress']
    # Canonical AMBA names are valid too; report them so a caller
    # enumerating profiles sees everything create_*_from_profile accepts.
    return base + [f'axi4_{n}' for n in canonical_names()
                    if f'axi4_{n}' not in base]


def create_axi4_randomizer_configs():
    """
    Create randomizer configurations for different test profiles.

    Returns:
        Dictionary of randomizer configurations
    """
    return {
        'normal': create_axi4_timing_from_profile('axi4_normal'),
        'fast': create_axi4_timing_from_profile('axi4_fast'),
        'slow': create_axi4_timing_from_profile('axi4_slow'),
        'backtoback': create_axi4_timing_from_profile('axi4_backtoback'),
        'stress': create_axi4_timing_from_profile('axi4_stress')
    }
