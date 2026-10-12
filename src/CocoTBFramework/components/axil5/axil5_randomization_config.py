# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL5 randomization configuration
# Purpose: AXIL4 constraints plus the AXI5-Lite optional groups
#
# Subsystem: framework

"""AXI5-Lite randomization configuration.

``axil4_randomization_config`` with the optional-signal groups added, the way
``axi5_randomization_config`` extends ``axi4``'s. Everything AXI4-Lite
constrains is inherited; what is added is how often each optional group is
exercised and with what values.

What AXI5-Lite adds over AXI4-Lite, per IHI 0022 Issue L Table B2.2:

* **The transaction ID.** AWID/BID and ARID/RID are present on AXI5-Lite
  (code YS), so ``id_rate`` / ``id_values`` vary them.
* **A SECURE protocol mode** that sweeps AxPROT. AXI5's enum also lists modes
  for atomics and cache coherence; Lite has neither, so those stay absent.

Deliberately NOT here: exclusive access, MPAM, MECID, NSAID and LOOP. Table
B2.2 marks AxLOCK, AxMPAM, AxMECID, AxNSAID and xLOOP "N" (not present) for
AXI5-Lite, and B2.1.5 states exclusive accesses are not supported.
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from CocoTBFramework.components.axil4.axil4_randomization_config import (
    AXIL4ConstraintSet,
    AXIL4RandomizationConfig,
    AXIL4RandomizationProfile,
)


class AXIL5RandomizationProfile(Enum):
    """AXI4-Lite's profiles plus one that exercises the security qualifiers."""
    BASIC = "basic"
    COMPLIANCE = "compliance"
    PERFORMANCE = "performance"
    STRESS = "stress"
    AUTOMOTIVE = "automotive"
    DATACENTER = "datacenter"
    MOBILE = "mobile"
    SECURE = "secure"
    CUSTOM = "custom"


class AXIL5ProtocolMode(Enum):
    """AXI5-Lite operating modes."""
    STANDARD = "standard"
    SECURE = "secure"
    LOW_POWER = "low_power"
    HIGH_PERFORMANCE = "high_performance"


@dataclass
class AXIL5ConstraintSet(AXIL4ConstraintSet):
    """AXI4-Lite constraints plus the optional-group rates.

    Every ``*_rate`` is the probability that the group carries a NON-DEFAULT
    value on a given transaction. All default to 0.0, so an AXIL5 constraint
    set with nothing configured produces AXI4-Lite-shaped traffic -- the same
    all-groups-off equivalence the RTL and the field configs hold to.
    """
    # ID and optional-group exercise rates
    id_rate: float = 0.0
    user_rate: float = 0.0
    trace_rate: float = 0.0
    poison_rate: float = 0.0

    # Value pools, used when a group fires
    id_values: Optional[List[int]] = None

    def any_group_enabled(self) -> bool:
        """True when at least one optional group will ever be exercised.

        Useful as a guard: with every rate at 0 an AXIL5 randomizer produces
        AXI4-Lite traffic, and a test believing it is exercising AXI5-Lite
        would be passing for the wrong reason.
        """
        return any((self.id_rate, self.user_rate, self.trace_rate,
                    self.poison_rate))


class AXIL5RandomizationConfig(AXIL4RandomizationConfig):
    """AXIL4 configuration on the AXI5-Lite constraint set."""

    CONSTRAINT_CLASS = AXIL5ConstraintSet
    PROFILE_ENUM = AXIL5RandomizationProfile

    def _constraints_for(self, profile) -> AXIL5ConstraintSet:
        # Start from the AXI4-Lite defaults for the shared profiles. SECURE
        # has no AXI4-Lite counterpart, so it starts from BASIC.
        P = self.PROFILE_ENUM
        base_profile = AXIL4RandomizationProfile.BASIC if profile is P.SECURE \
            else AXIL4RandomizationProfile(profile.value)
        c = super()._constraints_for(base_profile)

        if profile is P.SECURE:
            c.trace_rate = 0.2
            c.prot_values = [0, 1, 2, 3]
        elif profile is P.STRESS:
            # Everything on, so the groups are exercised alongside the
            # back-pressure and error injection STRESS already brings.
            for name in ('id_rate', 'user_rate', 'trace_rate', 'poison_rate'):
                setattr(c, name, 0.3)
        elif profile is P.COMPLIANCE:
            # Groups present but never poisoned: a poisoned beat is a legal
            # transfer of bad data, and mixing it into a compliance run makes
            # a protocol failure hard to tell from an intentional poison.
            c.id_rate = c.user_rate = c.trace_rate = 0.5
            c.poison_rate = 0.0
        return c
