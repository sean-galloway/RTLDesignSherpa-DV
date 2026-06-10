"""Unit tests for tFAW windowing in DramStateModel (issue #16).

tFAW = Four-Activate Window: no more than 4 ACT commands may issue
within any rolling tFAW-cycle window. JEDEC enforces this to limit
peak current draw. The check is "soft" because it's a windowed
average — a single violation typically warns rather than halts.
"""

from __future__ import annotations

import logging

import pytest

from CocoTBFramework.components.dfi import (
    DramStateModel,
    ViolationPolicy,
    builtin_timings,
)


@pytest.fixture
def timings():
    return builtin_timings("ddr3-1600")  # tFAW = 24 cycles, tRRD = 5 cycles


@pytest.fixture
def model(timings):
    return DramStateModel(timings=timings, num_banks=8)


def _advance(m, n):
    for _ in range(n):
        m.tick()


# ---------------------------------------------------------------------
# tFAW happy-path: 4 ACTs spread across the window are OK
# ---------------------------------------------------------------------


def test_three_acts_does_not_trigger_tfaw(model, timings):
    """tFAW only fires on the *5th* ACT inside the window."""
    model.on_activate(0, 0x100)
    _advance(model, timings.tRRD_cycles)
    model.on_activate(1, 0x100)
    _advance(model, timings.tRRD_cycles)
    model.on_activate(2, 0x100)
    # 3 ACTs is fine — tFAW window only kicks in once 4 ACTs are in flight
    assert model.policy.soft_violation_counts.get("tFAW", 0) == 0


def test_four_acts_outside_window_does_not_warn(model, timings, caplog):
    """4 ACTs are fine if the 4th lands >= tFAW cycles after the 1st."""
    spacing = max(timings.tRRD_cycles, (timings.tFAW_cycles // 3) + 1)
    model.on_activate(0, 0x100)
    _advance(model, spacing)
    model.on_activate(1, 0x100)
    _advance(model, spacing)
    model.on_activate(2, 0x100)
    _advance(model, spacing)
    model.on_activate(3, 0x100)
    # 4th ACT is far enough out that the rolling tFAW window can hold it
    assert model.policy.soft_violation_counts.get("tFAW", 0) == 0


# ---------------------------------------------------------------------
# tFAW violation: 5th ACT inside the window
# ---------------------------------------------------------------------


def test_fifth_act_within_window_warns(timings, caplog):
    """Pack 5 ACTs tighter than tFAW — the 5th must trigger a soft warn."""
    # Use a logger so the warning is captured
    log = logging.getLogger("test_tfaw")
    model = DramStateModel(timings=timings, num_banks=8, log=log)
    with caplog.at_level(logging.WARNING):
        # ACT every tRRD cycles → 4 ACTs in 3 * tRRD cycles (well under tFAW)
        for b in range(4):
            model.on_activate(b, 0x100)
            _advance(model, timings.tRRD_cycles)
        # 5th ACT is still within the tFAW window of the 1st
        model.on_activate(4, 0x100)
    assert model.policy.soft_violation_counts.get("tFAW", 0) == 1
    assert any("tFAW" in r.getMessage() for r in caplog.records)


def test_fifth_act_after_window_is_silent(timings):
    """If the 5th ACT comes after tFAW from ACT #1, the window has rolled."""
    model = DramStateModel(timings=timings, num_banks=8)
    # 4 ACTs early
    for b in range(4):
        model.on_activate(b, 0x100)
        _advance(model, timings.tRRD_cycles)
    # Wait long enough that ACT #1 falls out of the window
    _advance(model, timings.tFAW_cycles)
    model.on_activate(5, 0x100)
    assert model.policy.soft_violation_counts.get("tFAW", 0) == 0


# ---------------------------------------------------------------------
# Policy override: caller can make tFAW hard
# ---------------------------------------------------------------------


def test_tfaw_can_be_promoted_to_hard(timings):
    """Caller can override the default and make tFAW fatal."""
    policy = ViolationPolicy(
        hard=frozenset({"tFAW"}),
        soft=frozenset(),
        ignore=frozenset(),
    )
    model = DramStateModel(timings=timings, num_banks=8, policy=policy)
    for b in range(4):
        model.on_activate(b, 0x100)
        _advance(model, timings.tRRD_cycles)
    with pytest.raises(AssertionError, match="tFAW"):
        model.on_activate(4, 0x100)
