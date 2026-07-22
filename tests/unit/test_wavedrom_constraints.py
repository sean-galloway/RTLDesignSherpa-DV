"""Unit tests for wavedrom constraint_solver fixes.

Covers:
- TemporalConstraint dataclass fields (skip_boundary_detection, post_match_cycles, idle_signals)
- Late-bound signal windows created during sampling (no KeyError)
- Boundary constraints actually applied to the CP-SAT model
- Idle-boundary filtering: configured, derived, and explicit-skip behavior
- End-to-end solve using enumerate_all_solutions (ortools >= 9.x API)
- WaveJSONGenerator logger routing with print() fallback
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque

import pytest
from ortools.sat.python import cp_model

from CocoTBFramework.components.wavedrom.constraint_solver import (
    SignalStatic,
    SignalTransition,
    TemporalConstraint,
    TemporalConstraintSolver,
    TemporalEvent,
)
from CocoTBFramework.components.wavedrom.wavejson_gen import WaveJSONGenerator


class FakeSignal:
    """Minimal DUT signal stand-in: exposes .value like a cocotb handle."""

    def __init__(self, value: int = 0):
        self.value = value


class FakeDut:
    """Attribute bag standing in for a DUT handle."""


@pytest.fixture
def logger():
    return logging.getLogger("test_wavedrom_constraints")


@pytest.fixture
def dut():
    d = FakeDut()
    d.wr_valid = FakeSignal(0)
    d.wr_ready = FakeSignal(0)
    return d


@pytest.fixture
def solver(dut, logger):
    return TemporalConstraintSolver(dut=dut, log=logger, debug_level=0)


def make_constraint(name="write_handshake", **kwargs):
    defaults = dict(
        events=[
            TemporalEvent("valid_rise", SignalTransition("wr_valid", 0, 1)),
            TemporalEvent("ready_rise", SignalTransition("wr_ready", 0, 1)),
        ],
        max_window_size=10,
    )
    defaults.update(kwargs)
    return TemporalConstraint(name=name, **defaults)


# ---------------------------------------------------------------------------
# FIX 5: proper dataclass fields
# ---------------------------------------------------------------------------

def test_temporal_constraint_new_field_defaults():
    c = TemporalConstraint(name="c")
    assert c.skip_boundary_detection is False
    assert c.post_match_cycles == 0
    assert c.idle_signals == {}


def test_temporal_constraint_new_fields_configurable():
    c = TemporalConstraint(
        name="c",
        skip_boundary_detection=True,
        post_match_cycles=5,
        idle_signals={"wr_valid": 0, "rd_ready": 0},
    )
    assert c.skip_boundary_detection is True
    assert c.post_match_cycles == 5
    assert c.idle_signals == {"wr_valid": 0, "rd_ready": 0}


# ---------------------------------------------------------------------------
# FIX 1: signals bound after add_constraint() must not kill sampling
# ---------------------------------------------------------------------------

def test_late_bound_signal_gets_window_during_sampling(solver):
    # Constraint added BEFORE any signal is bound: windows dict starts empty
    constraint = make_constraint()
    solver.add_constraint(constraint)
    assert solver.constraint_windows[constraint.name] == {}

    # Bind signals AFTER add_constraint
    solver.add_signal_binding("wr_valid", "wr_valid")
    solver.add_signal_binding("wr_ready", "wr_ready")

    # Sampling must create windows on the fly instead of raising KeyError
    asyncio.run(solver._sample_signals_for_clock_group("default"))

    windows = solver.constraint_windows[constraint.name]
    assert set(windows.keys()) == {"wr_valid", "wr_ready"}
    assert list(windows["wr_valid"]) == [0]
    assert windows["wr_valid"].maxlen == constraint.max_window_size

    # A second sample appends normally
    solver.dut.wr_valid.value = 1
    asyncio.run(solver._sample_signals_for_clock_group("default"))
    assert list(windows["wr_valid"]) == [0, 1]


# ---------------------------------------------------------------------------
# FIX 2: boundary constraints are real CP-SAT constraints
# ---------------------------------------------------------------------------

class _PairCollector(cp_model.CpSolverSolutionCallback):
    def __init__(self, v1, v2):
        super().__init__()
        self.v1, self.v2 = v1, v2
        self.pairs = set()

    def on_solution_callback(self):
        self.pairs.add((self.Value(self.v1), self.Value(self.v2)))


def _enumerate_pairs(model, v1, v2):
    sat = cp_model.CpSolver()
    sat.parameters.enumerate_all_solutions = True
    collector = _PairCollector(v1, v2)
    sat.Solve(model, collector)
    return collector.pairs


def test_boundary_constraint_forbids_straddling_matches(solver):
    model = cp_model.CpModel()
    e1 = model.NewIntVar(0, 9, "e1")
    e2 = model.NewIntVar(0, 9, "e2")
    model.AddAllowedAssignments([e1], [[3], [6]])
    model.AddAllowedAssignments([e2], [[4], [7]])

    solver._apply_boundary_constraints_to_model(
        model, {"a": e1, "b": e2}, signal_data={}, boundary_cycle=5, reset_signals={}
    )

    # Without the boundary all 4 combos are feasible; the boundary at cycle 5
    # must eliminate the straddling pairs (3,7) and (6,4).
    assert _enumerate_pairs(model, e1, e2) == {(3, 4), (6, 7)}


def test_boundary_constraint_noop_without_event_vars(solver):
    model = cp_model.CpModel()
    # Must not raise even with no event variables
    solver._apply_boundary_constraints_to_model(
        model, {}, signal_data={}, boundary_cycle=5, reset_signals={"wr_valid": 0}
    )


def test_manual_boundary_makes_straddling_solve_infeasible(solver):
    """End-to-end: add_transaction_boundary now affects solving."""
    constraint = make_constraint("bounded_handshake")
    solver.add_signal_binding("wr_valid", "wr_valid")
    solver.add_signal_binding("wr_ready", "wr_ready")
    solver.add_constraint(constraint)
    solver.add_transaction_boundary("bounded_handshake", boundary_cycle=4, reset_signals={})

    # valid rises at cycle 2, ready rises at cycle 6 -> straddles boundary at 4
    windows = solver.constraint_windows["bounded_handshake"]
    windows["wr_valid"] = deque([0, 0, 1, 1, 1, 1, 1, 1, 1, 1], maxlen=10)
    windows["wr_ready"] = deque([0, 0, 0, 0, 0, 0, 1, 1, 1, 1], maxlen=10)

    asyncio.run(solver._solve_temporal_constraint("bounded_handshake", constraint))

    assert solver.solutions == []
    assert "bounded_handshake" not in solver.satisfied_constraints


# ---------------------------------------------------------------------------
# FIX 4: end-to-end solve with the non-deprecated enumerate API
# ---------------------------------------------------------------------------

def test_solve_finds_handshake_solution(solver, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # WaveJSON files land in tmp, not the repo

    constraint = make_constraint()
    solver.add_signal_binding("wr_valid", "wr_valid")
    solver.add_signal_binding("wr_ready", "wr_ready")
    solver.add_constraint(constraint)

    windows = solver.constraint_windows[constraint.name]
    windows["wr_valid"] = deque([0, 0, 1, 1, 1, 1, 1, 1, 1, 1], maxlen=10)
    windows["wr_ready"] = deque([0, 0, 0, 0, 0, 0, 1, 1, 1, 1], maxlen=10)

    asyncio.run(solver._solve_temporal_constraint(constraint.name, constraint))

    assert len(solver.solutions) == 1
    assert constraint.name in solver.satisfied_constraints
    timing = solver.solutions[0].temporal_solution["event_timing"]
    assert timing == {"valid_rise": 2, "ready_rise": 6}


# ---------------------------------------------------------------------------
# FIX 3: idle-boundary filter is configurable / derived, never vacuous
# ---------------------------------------------------------------------------

def test_idle_filter_with_configured_idle_signals(solver):
    constraint = make_constraint(
        "idle_cfg",
        boundary_min_idle_cycles=2,
        idle_signals={"wr_valid": 0},
    )
    solver.add_constraint(constraint)

    signal_data = {"wr_valid": [0, 1, 0, 0, 1, 1, 0, 0, 0, 1]}
    solutions = [
        {"sequence_start": 1},   # start < min_idle_cycles -> dropped
        {"sequence_start": 4},   # cycles 2,3 idle -> kept
        {"sequence_start": 5},   # cycle 4 busy -> dropped
        {"sequence_start": 9},   # cycles 7,8 idle -> kept
    ]

    filtered = solver._filter_solutions_by_idle_boundary(solutions, signal_data, 2, "idle_cfg")
    assert [s["sequence_start"] for s in filtered] == [4, 9]


def test_idle_filter_derives_signals_from_constraint_events(solver):
    constraint = TemporalConstraint(
        name="derived",
        events=[TemporalEvent("cmd_rise", SignalTransition("cmd_valid", 0, 1))],
        boundary_min_idle_cycles=2,
    )
    solver.add_constraint(constraint)

    signal_data = {"cmd_valid": [0, 1, 0, 0, 1, 0, 0, 0]}
    derived = solver._derive_idle_signals(constraint, signal_data)
    assert derived == {"cmd_valid": 0}

    solutions = [
        {"sequence_start": 2},   # cycle 1 busy -> dropped
        {"sequence_start": 4},   # cycles 2,3 idle -> kept
    ]
    filtered = solver._filter_solutions_by_idle_boundary(solutions, signal_data, 2, "derived")
    assert [s["sequence_start"] for s in filtered] == [4]


def test_idle_filter_skips_when_nothing_derivable(solver, caplog):
    """No configured or derivable idle signals: filter must skip with a log,
    returning all solutions instead of passing/failing vacuously."""
    constraint = TemporalConstraint(
        name="data_only",
        events=[TemporalEvent("data_stable", SignalStatic("cmd_data", 0xAB))],
        boundary_min_idle_cycles=3,
    )
    solver.add_constraint(constraint)

    signal_data = {"cmd_data": [0, 0xAB, 0xAB, 0, 0]}
    solutions = [{"sequence_start": 1}, {"sequence_start": 4}]

    with caplog.at_level(logging.INFO, logger="test_wavedrom_constraints"):
        filtered = solver._filter_solutions_by_idle_boundary(solutions, signal_data, 3, "data_only")

    assert filtered == solutions
    assert filtered is not solutions  # defensive copy, input untouched
    assert any("skipping idle-boundary filtering" in rec.message for rec in caplog.records)


def test_idle_filter_ignores_configured_signals_missing_from_data(solver, caplog):
    constraint = make_constraint(
        "partial_cfg",
        boundary_min_idle_cycles=1,
        idle_signals={"wr_valid": 0, "not_captured": 0},
    )
    solver.add_constraint(constraint)

    signal_data = {"wr_valid": [0, 0, 1, 1]}
    solutions = [{"sequence_start": 2}]  # cycle 1 idle -> kept

    with caplog.at_level(logging.WARNING, logger="test_wavedrom_constraints"):
        filtered = solver._filter_solutions_by_idle_boundary(solutions, signal_data, 1, "partial_cfg")

    assert [s["sequence_start"] for s in filtered] == [2]
    assert any("not_captured" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# WaveJSONGenerator diagnostics routing
# ---------------------------------------------------------------------------

def test_wavejson_generator_routes_diagnostics_through_logger(caplog):
    gen = WaveJSONGenerator(debug_level=1, log=logging.getLogger("wavejson_test"))
    with caplog.at_level(logging.INFO, logger="wavejson_test"):
        gen._emit("hello from generator")
    assert any("hello from generator" in rec.message for rec in caplog.records)


def test_wavejson_generator_falls_back_to_print(capsys):
    gen = WaveJSONGenerator(debug_level=1)  # no logger configured
    gen._emit("fallback message")
    assert "fallback message" in capsys.readouterr().out
