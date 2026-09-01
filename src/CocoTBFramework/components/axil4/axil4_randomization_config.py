# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: AXIL4 randomization configuration
# Purpose: Constraint sets and profiles for randomized AXI4-Lite traffic
#
# Subsystem: framework

"""AXI4-Lite randomization configuration.

Mirrors ``axi4_randomization_config``. The profiles and the API are the same;
the CONSTRAINTS are not, and the differences are all cases where an AXI4
constraint has no AXI4-Lite counterpart rather than a different value:

* **No burst constraints.** AXI4-Lite has no AxLEN, AxSIZE or AxBURST, so
  ``burst_len_*``, ``burst_types`` and ``burst_size_max`` are absent rather
  than pinned to 1/INCR. A constraint that can only take one value is not a
  constraint, and leaving it in invites a caller to set it and wonder why
  nothing changes.
* **No ID constraints.** Lite has no AxID. ``id_min``/``id_max`` are gone for
  the same reason.
* **No exclusive or locked access.** AXI4-Lite has neither, so those rates are
  absent. (AXI5-Lite adds LOCK; ``axil5_randomization_config`` puts the
  exclusive rate back.)

What remains is what AXI4-Lite actually parameterises: where the address
lands, how it is aligned, what the data and strobe patterns look like, how
often to inject an error response, and the delay/ready behaviour.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class AXIL4RandomizationProfile(Enum):
    """Predefined profiles. Same names as AXI4's so a testbench that selects
    a profile by string keeps working across families."""
    BASIC = "basic"
    COMPLIANCE = "compliance"
    PERFORMANCE = "performance"
    STRESS = "stress"
    AUTOMOTIVE = "automotive"
    DATACENTER = "datacenter"
    MOBILE = "mobile"
    CUSTOM = "custom"


class AXIL4ProtocolMode(Enum):
    """AXI4-Lite operating modes.

    AXI4's enum also lists EXCLUSIVE_ACCESS, LOCKED_ACCESS and CACHE_COHERENT.
    AXI4-Lite has no exclusive access, no locking and no cache signalling, so
    those three are not offered here -- selecting one would name a mode the
    protocol cannot enter.
    """
    STANDARD = "standard"
    LOW_POWER = "low_power"
    HIGH_PERFORMANCE = "high_performance"


@dataclass
class AXIL4ConstraintSet:
    """Constraints for randomized AXI4-Lite traffic."""
    # Address
    addr_min: int = 0x1000
    addr_max: int = 0xFFFF000
    addr_alignment: int = 4
    addr_ranges: Optional[List[Tuple[int, int]]] = None

    # Protocol
    error_injection_rate: float = 0.0
    prot_values: List[int] = field(default_factory=lambda: [0])

    # Payload
    data_patterns: List[str] = field(default_factory=lambda: ['random', 'incremental', 'pattern'])
    strobe_patterns: List[str] = field(default_factory=lambda: ['all', 'partial', 'sparse'])

    # Timing
    min_delay_cycles: int = 0
    max_delay_cycles: int = 10
    ready_probability: float = 0.8

    def aligned_addr_range(self) -> Tuple[int, int]:
        """The address window, snapped outward to ``addr_alignment``."""
        a = self.addr_alignment
        return (self.addr_min - self.addr_min % a,
                self.addr_max - self.addr_max % a)


class AXIL4RandomizationConfig:
    """Holds a constraint set and the profile it came from."""

    CONSTRAINT_CLASS = AXIL4ConstraintSet
    PROFILE_ENUM = AXIL4RandomizationProfile

    def __init__(self, data_width: int = 32,
                 profile: "AXIL4RandomizationProfile | str" = AXIL4RandomizationProfile.BASIC,
                 constraints: Optional[AXIL4ConstraintSet] = None):
        self.data_width = data_width
        self.profile = self.PROFILE_ENUM(profile) if isinstance(profile, str) else profile
        self.constraints = constraints or self._constraints_for(self.profile)

    def _constraints_for(self, profile) -> AXIL4ConstraintSet:
        """Per-profile constraint defaults."""
        c = self.CONSTRAINT_CLASS()
        P = self.PROFILE_ENUM
        if profile is P.COMPLIANCE:
            c.error_injection_rate = 0.0
            c.strobe_patterns = ['all']
            c.ready_probability = 1.0
            c.max_delay_cycles = 0
        elif profile is P.PERFORMANCE:
            c.min_delay_cycles = 0
            c.max_delay_cycles = 0
            c.ready_probability = 1.0
        elif profile is P.STRESS:
            c.error_injection_rate = 0.05
            c.max_delay_cycles = 30
            c.ready_probability = 0.4
            c.strobe_patterns = ['all', 'partial', 'sparse']
        elif profile is P.AUTOMOTIVE:
            c.error_injection_rate = 0.01
            c.ready_probability = 0.9
            c.prot_values = [0, 1, 2, 3]     # privileged and secure mixes
        elif profile is P.DATACENTER:
            c.addr_max = 0xFFFFFF000
            c.ready_probability = 0.95
            c.max_delay_cycles = 4
        elif profile is P.MOBILE:
            c.max_delay_cycles = 20
            c.ready_probability = 0.6
        return c

    def get_constraints(self) -> AXIL4ConstraintSet:
        return self.constraints

    def to_dict(self) -> Dict[str, Any]:
        return {
            'data_width': self.data_width,
            'profile': self.profile.value,
            'constraints': vars(self.constraints),
        }


def create_compliance_randomization_config(data_width: int = 32) -> AXIL4RandomizationConfig:
    """Zero delays, full strobes, no injected errors -- for protocol checking."""
    return AXIL4RandomizationConfig(data_width, AXIL4RandomizationProfile.COMPLIANCE)


def create_automotive_randomization_config(data_width: int = 32) -> AXIL4RandomizationConfig:
    return AXIL4RandomizationConfig(data_width, AXIL4RandomizationProfile.AUTOMOTIVE)


def create_datacenter_randomization_config(data_width: int = 64) -> AXIL4RandomizationConfig:
    return AXIL4RandomizationConfig(data_width, AXIL4RandomizationProfile.DATACENTER)


def create_mobile_randomization_config(data_width: int = 32) -> AXIL4RandomizationConfig:
    return AXIL4RandomizationConfig(data_width, AXIL4RandomizationProfile.MOBILE)
