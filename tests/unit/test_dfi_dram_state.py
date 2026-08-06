"""Unit tests for the DRAM state model + JEDEC timing checker (issue #16)."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dram_state import (
    BankState,
    DramStateModel,
    ViolationCategory,
    ViolationPolicy,
)
from CocoTBFramework.components.dfi.jedec_timings import builtin_timings


@pytest.fixture
def timings():
    return builtin_timings("ddr3-1600")


@pytest.fixture
def model(timings):
    return DramStateModel(timings=timings, num_banks=8)


def _advance(m: DramStateModel, n: int) -> None:
    for _ in range(n):
        m.tick()


# ---------------------------------------------------------------------
# ViolationPolicy
# ---------------------------------------------------------------------


def test_policy_defaults_to_proposed_split():
    p = ViolationPolicy()
    assert p.category_of("tRCD") == ViolationCategory.HARD
    assert p.category_of("tFAW") == ViolationCategory.SOFT
    assert p.category_of("init_sequence") == ViolationCategory.IGNORE


def test_policy_unknown_name_defaults_to_soft():
    """Forward-compat: a violation we haven't categorized yet warns
    rather than crashing the sim or being silently dropped."""
    p = ViolationPolicy()
    assert p.category_of("tFutureNewTiming") == ViolationCategory.SOFT


def test_policy_hard_raises():
    p = ViolationPolicy()
    with pytest.raises(AssertionError, match="tRCD"):
        p.report("tRCD", "context here")


def test_policy_soft_logs_and_counts(caplog):
    p = ViolationPolicy()
    import logging
    log = logging.getLogger("test")
    with caplog.at_level(logging.WARNING):
        p.report("tFAW", "first context", log)
        p.report("tFAW", "second context", log)
    assert p.soft_violation_counts == {"tFAW": 2}


def test_policy_ignore_is_silent():
    p = ViolationPolicy()
    # Should not raise, should not count
    p.report("init_sequence", "irrelevant")
    assert "init_sequence" not in p.soft_violation_counts


def test_policy_override_hard_to_soft(caplog):
    """User can override defaults to make tRCD a warning instead of fatal."""
    p = ViolationPolicy(
        hard=frozenset(),                  # nothing is fatal
        soft=frozenset({"tRCD"}),
        ignore=frozenset(),
    )
    import logging
    with caplog.at_level(logging.WARNING):
        p.report("tRCD", "downgraded", logging.getLogger("test"))
    assert p.soft_violation_counts == {"tRCD": 1}


# ---------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------


def test_model_starts_all_idle(model):
    for b in model.banks:
        assert b.state == BankState.IDLE
        assert b.row is None


def test_model_rejects_zero_banks(timings):
    with pytest.raises(ValueError, match="num_banks"):
        DramStateModel(timings=timings, num_banks=0)


# ---------------------------------------------------------------------
# Bank-state transitions
# ---------------------------------------------------------------------


def test_activate_marks_bank_active(model):
    model.on_activate(bank_idx=2, row=0x100)
    assert model.banks[2].state == BankState.ACTIVE
    assert model.banks[2].row == 0x100


def test_activate_on_already_active_bank_is_hard(model):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, 50)  # past all relevant timings
    with pytest.raises(AssertionError, match="already ACTIVE"):
        model.on_activate(bank_idx=0, row=0x200)


def test_read_without_activate_is_hard(model):
    with pytest.raises(AssertionError, match="no_act_before_rd"):
        model.on_read(bank_idx=3)


def test_write_without_activate_is_hard(model):
    with pytest.raises(AssertionError, match="no_act_before_wr"):
        model.on_write(bank_idx=3)


def test_precharge_returns_bank_to_idle(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRAS_min_cycles)
    model.on_precharge(bank_idx=0)
    assert model.banks[0].state == BankState.IDLE
    assert model.banks[0].row is None


# ---------------------------------------------------------------------
# Per-bank timing checks
# ---------------------------------------------------------------------


def test_read_before_tRCD_is_hard(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRCD_cycles - 2)  # one short
    with pytest.raises(AssertionError, match="tRCD"):
        model.on_read(bank_idx=0)


def test_read_after_tRCD_succeeds(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRCD_cycles)  # exactly enough
    model.on_read(bank_idx=0)  # no raise


def test_write_before_tRCD_is_hard(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRCD_cycles - 2)
    with pytest.raises(AssertionError, match="tRCD"):
        model.on_write(bank_idx=0)


def test_precharge_before_tRAS_is_hard(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    # Don't wait long enough
    _advance(model, 5)
    with pytest.raises(AssertionError, match="tRAS_min"):
        model.on_precharge(bank_idx=0)


def test_act_after_pre_before_tRP_is_hard(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRAS_min_cycles)
    model.on_precharge(bank_idx=0)
    _advance(model, timings.tRP_cycles - 2)
    with pytest.raises(AssertionError, match="tRP"):
        model.on_activate(bank_idx=0, row=0x200)


def test_act_to_act_diff_bank_before_tRRD_is_hard(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRRD_cycles - 2)  # one short
    with pytest.raises(AssertionError, match="tRRD"):
        model.on_activate(bank_idx=1, row=0x100)


def test_act_to_act_diff_bank_at_tRRD_succeeds(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRRD_cycles)
    model.on_activate(bank_idx=1, row=0x100)  # no raise


# ---------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------


def test_refresh_with_open_row_is_hard(model, timings):
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRAS_min_cycles)
    with pytest.raises(AssertionError, match="ref_with_open_row"):
        model.on_refresh()


def test_refresh_after_all_pre_succeeds(model, timings):
    # Activate then precharge → all banks idle
    model.on_activate(bank_idx=0, row=0x100)
    _advance(model, timings.tRAS_min_cycles)
    model.on_precharge(bank_idx=0, all_banks=False)
    model.on_refresh()  # no raise
    assert all(b.state == BankState.REFRESHING for b in model.banks)


def test_cmd_during_refresh_is_hard(model, timings):
    model.on_refresh()
    # Try an ACT during refresh
    _advance(model, 5)
    with pytest.raises(AssertionError, match="cmd_during_refresh"):
        model.on_activate(bank_idx=0, row=0x100)


def test_refresh_completes_after_tRFC(model, timings):
    model.on_refresh()
    _advance(model, timings.tRFC_cycles)
    assert all(b.state == BankState.IDLE for b in model.banks)


# ---------------------------------------------------------------------
# Policy override at construction
# ---------------------------------------------------------------------


def test_constructor_accepts_custom_policy(timings, caplog):
    """Caller can downgrade tRCD to a warning."""
    custom = ViolationPolicy(
        hard=frozenset(),  # nothing fatal
        soft=frozenset({"tRCD"}),
        ignore=frozenset(),
    )
    m = DramStateModel(timings=timings, num_banks=8, policy=custom)
    m.on_activate(bank_idx=0, row=0x100)
    # Read way too soon — should warn, not raise
    m.on_read(bank_idx=0)
    assert custom.soft_violation_counts.get("tRCD", 0) >= 1


# ---------------------------------------------------------------------
# tREFI windowing (JEDEC 8-postpone limit → max 9 x tREFI between REFs)
# ---------------------------------------------------------------------


def test_refi_window_unarmed_until_first_command(model, timings):
    """A model that never sees traffic never flags refresh-overdue."""
    _advance(model, 10 * timings.tREFI_cycles)
    assert model.policy.soft_violation_counts.get("tREFI", 0) == 0


def test_refi_no_violation_when_ref_arrives_in_window(model, timings):
    model.on_activate(0, row=0x10)
    _advance(model, timings.tRAS_min_cycles + 1)
    model.on_precharge(0)
    _advance(model, timings.tRP_cycles + 1)
    # REF comfortably inside the 9 x tREFI window
    _advance(model, timings.tREFI_cycles)
    model.on_refresh()
    _advance(model, 9 * timings.tREFI_cycles - 1)
    assert model.policy.soft_violation_counts.get("tREFI", 0) == 0


def test_refi_overdue_reports_once_per_window(model, timings):
    model.on_activate(0, row=0x10)
    window = 9 * timings.tREFI_cycles
    # Exceed the first window with no REF: exactly one soft violation.
    _advance(model, window + 2)
    assert model.policy.soft_violation_counts.get("tREFI", 0) == 1
    # Still no REF: the NEXT window must elapse before a second report
    # (no per-cycle flooding).
    _advance(model, 10)
    assert model.policy.soft_violation_counts.get("tREFI", 0) == 1
    _advance(model, window)
    assert model.policy.soft_violation_counts.get("tREFI", 0) == 2


def test_refi_ref_resets_the_window(model, timings):
    model.on_activate(0, row=0x10)
    _advance(model, timings.tRAS_min_cycles + 1)
    model.on_precharge(0)
    window = 9 * timings.tREFI_cycles
    _advance(model, window - 5 - timings.tRAS_min_cycles - 1)  # almost overdue
    model.on_refresh()                        # REF lands just in time
    _advance(model, timings.tRFC_cycles + 1)  # walk out of REFRESHING
    # Deep into the NEW window (tRFC advance already consumed part of it)
    _advance(model, window - timings.tRFC_cycles - 10)
    assert model.policy.soft_violation_counts.get("tREFI", 0) == 0
    _advance(model, 20)                       # now the new window expires
    assert model.policy.soft_violation_counts.get("tREFI", 0) == 1
