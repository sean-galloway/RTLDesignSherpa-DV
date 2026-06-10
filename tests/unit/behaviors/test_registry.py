"""Unit tests for the version → behavior registry and DFIBase wire-up.

Verifies:
  - VERSION_BEHAVIOR has the expected mappings (v5.x collapses onto v4.0)
  - behavior_for() returns instances of the right class
  - Unknown versions raise KeyError with a helpful message
  - DFIBase auto-instantiates the right behavior
  - DFIBase accepts a custom behavior override
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from CocoTBFramework.components.dfi import (
    AddressMapping,
    DFIBase,
    DFIVersion,
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.behaviors import (
    VERSION_BEHAVIOR,
    DFIv2_1Behavior,
    DFIv3_1Behavior,
    DFIv4_0Behavior,
    behavior_for,
)


@pytest.fixture
def timings():
    return builtin_timings("ddr3-1600")


@pytest.fixture
def mapping():
    return AddressMapping(num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024)


# ---------------------------------------------------------------------
# Registry contents
# ---------------------------------------------------------------------


def test_registry_has_all_active_versions():
    """Every DFI version we support should map to a behavior class."""
    expected_versions = {
        DFIVersion.V2_1, DFIVersion.V3_1, DFIVersion.V4_0, DFIVersion.V5_2,
    }
    assert set(VERSION_BEHAVIOR.keys()) == expected_versions


def test_v5_2_collapses_to_v4_0_behavior():
    """Per the catalog: v5.2 is a rename of PHY Master → PHY Managed
    with no behavior change, so v5.2 reuses DFIv4_0Behavior."""
    assert VERSION_BEHAVIOR[DFIVersion.V5_2] is DFIv4_0Behavior


def test_v2_1_maps_to_base():
    assert VERSION_BEHAVIOR[DFIVersion.V2_1] is DFIv2_1Behavior


def test_v3_1_maps_to_v3_1_class():
    assert VERSION_BEHAVIOR[DFIVersion.V3_1] is DFIv3_1Behavior


def test_v4_0_maps_to_v4_0_class():
    assert VERSION_BEHAVIOR[DFIVersion.V4_0] is DFIv4_0Behavior


# ---------------------------------------------------------------------
# behavior_for()
# ---------------------------------------------------------------------


def test_behavior_for_returns_instance():
    """Should return a fresh instance each call."""
    b1 = behavior_for(DFIVersion.V3_1)
    b2 = behavior_for(DFIVersion.V3_1)
    assert isinstance(b1, DFIv3_1Behavior)
    assert b1 is not b2


def test_behavior_for_unknown_version_raises():
    """A version absent from the registry must fail loudly at lookup."""
    with patch.dict(VERSION_BEHAVIOR, clear=True):
        VERSION_BEHAVIOR[DFIVersion.V2_1] = DFIv2_1Behavior
        with pytest.raises(KeyError, match="No behavior class registered"):
            behavior_for(DFIVersion.V4_0)


# ---------------------------------------------------------------------
# DFIBase wire-up
# ---------------------------------------------------------------------


def test_base_auto_selects_behavior(timings, mapping):
    """DFIBase should auto-select the behavior matching dfi_version."""
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
    )
    assert isinstance(base.behavior, DFIv2_1Behavior)
    # And the exact class, not just an ancestor
    assert type(base.behavior) is DFIv2_1Behavior


def test_base_accepts_custom_behavior(timings, mapping):
    """User can swap in a custom behavior instance."""
    class MyCustomBehavior(DFIv2_1Behavior):
        pass

    custom = MyCustomBehavior()
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
        behavior=custom,
    )
    assert base.behavior is custom


def test_base_custom_behavior_bypasses_registry(timings, mapping):
    """Even when version matches a registered class, an explicit
    behavior= overrides the lookup."""
    class WeirdBehavior(DFIv2_1Behavior):
        version_label = "weird"

    weird = WeirdBehavior()
    base = DFIBase(
        dfi_version=DFIVersion.V2_1,   # would normally pick DFIv2_1Behavior
        memory_type=MemoryType.DDR3,
        timings=timings,
        mapping=mapping,
        behavior=weird,
    )
    assert base.behavior is weird
    assert base.behavior.version_label == "weird"
