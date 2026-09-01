# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5 randomization manager
# Purpose: One handle over protocol and timing randomization for AXI5-Lite
#
# Subsystem: framework

"""AXI5-Lite randomization manager.

Mirrors ``axi4_randomization_manager``: one object owning both halves of
randomization, so a testbench configures field values and channel delays
through a single handle instead of wiring two unrelated objects together.

* protocol randomization -- ``AXIL5RandomizationConfig`` (what to put in the
  fields)
* timing randomization -- the named profiles in ``axil5_timing_config`` (when
  to assert valid and ready)

The channel list is all five. AXI5-Lite has the same channel set as AXI4, so
there is nothing to trim.
"""
from typing import Any, Dict, Optional

from CocoTBFramework.components.axil4.axil4_randomization_manager import (
    AXIL4RandomizationManager,
)
from CocoTBFramework.components.axil5.axil5_randomization_config import (
    AXIL5RandomizationConfig,
)
from CocoTBFramework.components.axil5.axil5_timing_config import (
    DEFAULT_PROFILE,
    create_axil5_timing_from_profile,
    get_axil5_timing_profiles,
)

#: AXI5-Lite has the same five channels as AXI4.
ALL_CHANNELS = ['AW', 'W', 'B', 'AR', 'R']


class AXIL5RandomizationManager(AXIL4RandomizationManager):
    """AXIL4 manager on the AXI5-Lite config, plus optional-group draws."""

    CONFIG_CLASS = AXIL5RandomizationConfig
    TIMING_FACTORY = staticmethod(create_axil5_timing_from_profile)
    TIMING_PROFILES = staticmethod(get_axil5_timing_profiles)
    DEFAULT_TIMING_PROFILE = DEFAULT_PROFILE

    #: Group -> the constraint attribute holding its firing rate.
    GROUP_RATES = {
        'user': 'user_rate', 'trace': 'trace_rate', 'loop': 'loop_rate',
        'mpam': 'mpam_rate', 'mecid': 'mecid_rate', 'nsaid': 'nsaid_rate',
        'poison': 'poison_rate', 'lock': 'exclusive_access_rate',
    }

    def should_exercise(self, group: str) -> bool:
        """Whether this transaction should carry a non-default ``group``."""
        rate_attr = self.GROUP_RATES.get(group)
        if rate_attr is None:
            raise ValueError(
                f"unknown optional group {group!r}; known: {sorted(self.GROUP_RATES)}"
            )
        self.stats['protocol_calls'] += 1
        return self.random.random() < getattr(self.protocol.get_constraints(), rate_attr)

    def next_group_value(self, group: str, width: int) -> int:
        """A value for ``group``, from its configured pool when one exists.

        Returns 0 when the group is not firing this transaction, which is the
        spec default for every AXI5-Lite optional group -- so a caller can
        assign the result unconditionally.
        """
        if not self.should_exercise(group):
            return 0
        pool = getattr(self.protocol.get_constraints(), f"{group}_values", None)
        if pool:
            return self.random.choice(pool)
        return self.random.randrange(1 << width) if width > 0 else 0

    def next_sideband(self, channel: str, widths: Dict[str, int]) -> Dict[str, int]:
        """Draw every optional group valid on ``channel``.

        ``widths`` names which groups the DUT actually carries and how wide
        they are, so a group the RTL was built without is never drawn -- the
        same asymmetry the RTL's ENABLE_* parameters create.
        """
        valid = {
            'aw': ('user', 'trace', 'loop', 'mpam', 'mecid', 'nsaid', 'lock'),
            'ar': ('user', 'trace', 'loop', 'mpam', 'mecid', 'nsaid', 'lock'),
            'w':  ('user', 'poison'),
            'b':  ('user', 'trace', 'loop'),
            'r':  ('user', 'trace', 'loop', 'poison'),
        }.get(channel)
        if valid is None:
            raise ValueError(f"unknown channel {channel!r}")
        return {g: self.next_group_value(g, widths[g])
                for g in valid if g in widths}

    def get_statistics(self) -> Dict[str, Any]:
        stats = super().get_statistics()
        stats['groups_enabled'] = self.protocol.get_constraints().any_group_enabled()
        return stats
