"""Unit tests for DFIPhaseAdapter — the gear-ratio adapter for 1/2/4/8/16-phase
DFI sources. Uses mock signal handles to verify queueing/feed semantics
without cocotb.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_phase_adapter import (
    DFIPhaseAdapter,
    VALID_PHASE_COUNTS,
)


class _MockSig:
    def __init__(self):
        self.value = 0


class _MockDut:
    """Auto-creates signal handles on attribute access (one per name)."""
    def __init__(self):
        self._sigs = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._sigs:
            self._sigs[name] = _MockSig()
        return self._sigs[name]


# ---------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------


@pytest.mark.parametrize("n", sorted(VALID_PHASE_COUNTS))
def test_accepts_each_valid_phase_count(n):
    dut = _MockDut()
    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=n, dfi_clock=object(),
    )
    assert adapter.n_phases == n


@pytest.mark.parametrize("bad_n", [0, 3, 5, 7, 32, -1])
def test_rejects_invalid_phase_counts(bad_n):
    dut = _MockDut()
    with pytest.raises(ValueError, match="n_phases must be one of"):
        DFIPhaseAdapter(
            dut, dest_prefix="mc_dfi", n_phases=bad_n, dfi_clock=object(),
        )


def test_default_idle_values():
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "mc_dfi", 4, object())
    # Sanity-check a few of the deselected-idle defaults
    assert a._idle["cs_n"] == 1
    assert a._idle["ras_n"] == 1
    assert a._idle["cke"] == 1
    assert a._idle["wrdata_en"] == 0


def test_idle_values_overridable():
    dut = _MockDut()
    a = DFIPhaseAdapter(
        dut, "mc_dfi", 4, object(),
        idle_values={"cke": 0, "odt": 1},
    )
    assert a._idle["cke"] == 0
    assert a._idle["odt"] == 1
    # Other defaults still present
    assert a._idle["cs_n"] == 1


# ---------------------------------------------------------------------
# feed() validation
# ---------------------------------------------------------------------


def test_feed_requires_exactly_n_phases():
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "mc_dfi", 4, object())

    a.feed([{}, {}, {}, {}])     # 4 dicts — OK
    assert a.queued_phases == 4

    with pytest.raises(ValueError, match="exactly 4 phase dicts"):
        a.feed([{}, {}, {}])      # 3 — wrong

    with pytest.raises(ValueError, match="exactly 4 phase dicts"):
        a.feed([{}, {}, {}, {}, {}])  # 5 — wrong


def test_feed_idle_queues_n_empty_dicts():
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "mc_dfi", 4, object())
    a.feed_idle()
    assert a.queued_phases == 4


def test_feed_accepts_arbitrary_partial_dicts():
    """Each phase dict only needs to set the signals it cares about;
    idle defaults fill the rest."""
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "mc_dfi", 2, object())
    a.feed([
        {"cs_n": 0, "bank": 5},  # partial — other signals default to idle
        {},                       # empty — full idle
    ])
    assert a.queued_phases == 2


# ---------------------------------------------------------------------
# 1-phase mode (degenerate gear ratio)
# ---------------------------------------------------------------------


def test_1_phase_mode_passes_through():
    """At n_phases=1, the adapter is a 1:1 passthrough — feed one
    dict per MC cycle."""
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "mc_dfi", 1, object())
    a.feed([{"cs_n": 0, "bank": 3}])
    assert a.queued_phases == 1


# ---------------------------------------------------------------------
# Signal name resolution
# ---------------------------------------------------------------------


def test_drive_resolves_signals_under_prefix():
    """The adapter's _drive helper should set DUT signals using the
    `<prefix>_<sig>` naming convention."""
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "myprefix_dfi", 4, object())
    a._drive({"cs_n": 0, "bank": 7, "address": 0x42})
    assert dut.myprefix_dfi_cs_n.value == 0
    assert dut.myprefix_dfi_bank.value == 7
    assert dut.myprefix_dfi_address.value == 0x42


def test_drive_phase_overlays_partial_dict_on_idle():
    """_drive_phase merges the partial dict on top of idle defaults."""
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "mc_dfi", 2, object())
    # Drive a phase with only cs_n=0 — other signals should use idle defaults
    a._drive_phase({"cs_n": 0, "bank": 2})
    assert dut.mc_dfi_cs_n.value == 0      # from phase override
    assert dut.mc_dfi_bank.value == 2      # from phase override
    assert dut.mc_dfi_ras_n.value == 1     # from idle default
    assert dut.mc_dfi_cke.value == 1       # from idle default


# ---------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------


def test_stats_start_at_zero():
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "mc_dfi", 4, object())
    assert a.phases_driven == 0
    assert a.idle_cycles == 0


def test_str_includes_n_phases_and_counts():
    dut = _MockDut()
    a = DFIPhaseAdapter(dut, "mc_dfi", 8, object())
    s = str(a)
    assert "n_phases=8" in s
    assert "queued=0" in s
