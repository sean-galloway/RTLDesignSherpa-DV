# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL4 randomization manager
# Purpose: One handle over protocol and timing randomization for AXI4-Lite
#
# Subsystem: framework

"""AXI4-Lite randomization manager.

Mirrors ``axi4_randomization_manager``: one object owning both halves of
randomization, so a testbench configures field values and channel delays
through a single handle instead of wiring two unrelated objects together.

* protocol randomization -- ``AXIL4RandomizationConfig`` (what to put in the
  fields)
* timing randomization -- the named profiles in ``axil4_timing_config`` (when
  to assert valid and ready)

The channel list is all five. AXI4-Lite has the same channel set as AXI4, so
there is nothing to trim.
"""
import random
from typing import Any, Dict, List, Optional

from CocoTBFramework.components.axil4.axil4_randomization_config import (
    AXIL4RandomizationConfig,
)
from CocoTBFramework.components.axil4.axil4_timing_config import (
    DEFAULT_PROFILE,
    create_axil4_timing_from_profile,
    get_axil4_timing_profiles,
)

#: AXI4-Lite has the same five channels as AXI4.
ALL_CHANNELS = ['AW', 'W', 'B', 'AR', 'R']


class AXIL4RandomizationManager:
    """Protocol and timing randomization behind one handle."""

    CONFIG_CLASS = AXIL4RandomizationConfig
    TIMING_FACTORY = staticmethod(create_axil4_timing_from_profile)
    TIMING_PROFILES = staticmethod(get_axil4_timing_profiles)
    DEFAULT_TIMING_PROFILE = DEFAULT_PROFILE

    def __init__(self,
                 protocol_config: Optional[AXIL4RandomizationConfig] = None,
                 timing_profile: Optional[str] = None,
                 channels: Optional[List[str]] = None,
                 data_width: int = 32,
                 seed: Optional[int] = None):
        self.channels = list(channels) if channels else list(ALL_CHANNELS)
        self.data_width = data_width
        self.protocol = protocol_config or self.CONFIG_CLASS(data_width=data_width)

        profile = timing_profile or self.DEFAULT_TIMING_PROFILE
        if profile not in self.TIMING_PROFILES():
            raise ValueError(
                f"unknown timing profile {profile!r}; available: "
                f"{self.TIMING_PROFILES()}"
            )
        self.timing_profile = profile
        self.timing = self.TIMING_FACTORY(profile)

        # A manager-local Random, seeded explicitly, rather than the module
        # global. Two managers in one testbench must not consume each other's
        # sequence, and a run has to be reproducible from its seed alone.
        self.random = random.Random(seed)
        self.seed = seed

        self.stats = {'protocol_calls': 0, 'timing_calls': 0}

    # -- protocol --------------------------------------------------------

    def next_address(self) -> int:
        """An address inside the constraint window, correctly aligned."""
        self.stats['protocol_calls'] += 1
        c = self.protocol.get_constraints()
        lo, hi = c.aligned_addr_range()
        a = c.addr_alignment
        span = max(0, (hi - lo) // a)
        return lo + self.random.randint(0, span) * a

    def next_prot(self) -> int:
        self.stats['protocol_calls'] += 1
        return self.random.choice(self.protocol.get_constraints().prot_values)

    def should_inject_error(self) -> bool:
        self.stats['protocol_calls'] += 1
        return self.random.random() < self.protocol.get_constraints().error_injection_rate

    def next_strobe(self, data_width: Optional[int] = None) -> int:
        """A WSTRB following the configured strobe patterns.

        'all' is the AXI default when a DUT omits WSTRB entirely, which is why
        the compliance profile pins this to 'all' -- see the optional-fields
        rule in signal_mapping_helper.
        """
        self.stats['protocol_calls'] += 1
        width = (data_width or self.data_width) // 8
        full = (1 << width) - 1
        pattern = self.random.choice(self.protocol.get_constraints().strobe_patterns)
        if pattern == 'all':
            return full
        if pattern == 'partial':
            return full & ~(1 << self.random.randrange(width))
        return 1 << self.random.randrange(width)      # 'sparse'

    # -- timing ----------------------------------------------------------

    def get_timing_delays(self, channels: Optional[List[str]] = None) -> Dict[str, Any]:
        """The delay constraints for the requested channels.

        Keys are the ``{ch}_{valid,ready}_delay`` names the timing profiles
        use, lower-cased, so the result drops straight into a FlexRandomizer.
        """
        self.stats['timing_calls'] += 1
        wanted = [c.lower() for c in (channels or self.channels)]
        return {
            k: v for k, v in self.timing['constraints'].items()
            if k.split('_', 1)[0] in wanted
        }

    def set_timing_profile(self, profile: str) -> None:
        if profile not in self.TIMING_PROFILES():
            raise ValueError(
                f"unknown timing profile {profile!r}; available: "
                f"{self.TIMING_PROFILES()}"
            )
        self.timing_profile = profile
        self.timing = self.TIMING_FACTORY(profile)

    # -- reporting -------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self.stats,
            'timing_profile': self.timing_profile,
            'channels': list(self.channels),
            'data_width': self.data_width,
            'seed': self.seed,
        }
