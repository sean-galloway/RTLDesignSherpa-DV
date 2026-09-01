"""Unit tests for shared/protocol_types.py (issue #9)."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.shared.protocol_types import (
    PROTOCOL_TYPES,
    validate_protocol_type,
)


def test_protocol_types_is_frozenset():
    """The canonical set is immutable so it can't be accidentally mutated."""
    assert isinstance(PROTOCOL_TYPES, frozenset)


@pytest.mark.parametrize("protocol_type", [
    "fifo_master", "fifo_slave",
    "gaxi_master", "gaxi_slave",
    "axis_master", "axis_slave",
    "axi4_ar_master", "axi4_ar_slave",
    "axi4_r_master",  "axi4_r_slave",
    "axi4_aw_master", "axi4_aw_slave",
    "axi4_w_master",  "axi4_w_slave",
    "axi4_b_master",  "axi4_b_slave",
    "axi5_ar_master", "axi5_ar_slave",
    "axi5_r_master",  "axi5_r_slave",
    "axi5_aw_master", "axi5_aw_slave",
    "axi5_w_master",  "axi5_w_slave",
    "axi5_b_master",  "axi5_b_slave",
])
def test_validate_accepts_known_types(protocol_type):
    """Every expected identifier validates without error."""
    validate_protocol_type(protocol_type)


def test_validate_rejects_unknown_type():
    with pytest.raises(ValueError, match="protocol_type must be one of"):
        validate_protocol_type("not_a_real_type")


def test_validate_rejects_empty_string():
    with pytest.raises(ValueError):
        validate_protocol_type("")


def test_validate_rejects_typos():
    """Common typo guards."""
    with pytest.raises(ValueError):
        validate_protocol_type("fifo_msater")  # transposed letters
    with pytest.raises(ValueError):
        validate_protocol_type("AXI4_ar_master")  # uppercase


def test_set_contains_both_fifo_and_gaxi():
    """Issue #9 acceptance criterion: single source includes FIFO + GAXI."""
    assert "fifo_master" in PROTOCOL_TYPES
    assert "fifo_slave" in PROTOCOL_TYPES
    assert "gaxi_master" in PROTOCOL_TYPES
    assert "gaxi_slave" in PROTOCOL_TYPES


def test_set_size_matches_expected_channels():
    """Every identifier is accounted for, by CATEGORY rather than a bare total.

    This asserted ``== 26`` and broke when the twenty AXI4-Lite / AXI5-Lite
    channels landed -- correctly, since a bare total is exactly the guard that
    should fire on an unreviewed addition. But a bare total also cannot say
    WHICH group grew, so the failure reads as "the number changed" and the
    reviewer has to go and diff two sets by hand.

    Counting per family keeps the same protection and names the group instead.
    """
    fifo = {t for t in PROTOCOL_TYPES if t.startswith("fifo_")}
    gaxi = {t for t in PROTOCOL_TYPES if t.startswith("gaxi_")}
    axis = {t for t in PROTOCOL_TYPES if t.startswith("axis_")}
    # startswith("axi4_") does NOT match "axil4_" -- the fifth character is
    # 'l', not '_'. Matching the families loosely is how the Lite entries got
    # past a different guard in signal_mapping_helper's test.
    per_family = {
        fam: {t for t in PROTOCOL_TYPES if t.startswith(fam + "_")}
        for fam in ("axi4", "axi5", "axil4", "axil5")
    }

    assert len(fifo) == 2, sorted(fifo)
    assert len(gaxi) == 2, sorted(gaxi)
    assert len(axis) == 2, sorted(axis)
    for fam, members in per_family.items():
        assert len(members) == 10, f"{fam}: {sorted(members)}"

    counted = fifo | gaxi | axis | set().union(*per_family.values())
    assert counted == PROTOCOL_TYPES, (
        f"unaccounted identifiers: {sorted(PROTOCOL_TYPES - counted)}"
    )
