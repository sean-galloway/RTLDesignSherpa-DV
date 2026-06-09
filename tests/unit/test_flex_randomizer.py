"""Unit tests for shared/flex_randomizer.py.

Covers the constraint forms used by APB/GAXI/FIFO base classes'
_default_randomizer_constraints() hooks (#15).
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer


def test_constraints_must_be_dict():
    with pytest.raises(TypeError, match="must be a dictionary"):
        FlexRandomizer([("ready", ([(0, 5)], [1]))])  # list, not dict


def test_empty_constraints_dict_raises():
    with pytest.raises(ValueError, match="cannot be empty"):
        FlexRandomizer({})


def test_constrained_random_returns_value_in_range():
    """The basic constraint form used by all APB/GAXI hooks."""
    r = FlexRandomizer({
        "ready": ([(0, 1), (2, 5), (6, 10)], [5, 2, 1]),
    })
    for _ in range(50):
        v = r.next()["ready"]
        assert 0 <= v <= 10


def test_apb_slave_default_constraints_shape():
    """Exact shape returned by APBSlave._default_randomizer_constraints."""
    r = FlexRandomizer({
        "ready": ([(0, 1), (2, 5), (6, 10)], [5, 2, 1]),
        "error": ([(0, 0), (1, 1)], [10, 0]),
    })
    result = r.next()
    assert set(result.keys()) == {"ready", "error"}
    assert isinstance(result["ready"], int)
    assert isinstance(result["error"], int)


def test_apb5_slave_default_constraints_shape():
    """Exact shape returned by APB5Slave._default_randomizer_constraints —
    extends APB4's keys with pruser/pbuser per #15 Phase B.
    """
    ruser_width = 4
    buser_width = 4
    r = FlexRandomizer({
        "ready": ([(0, 1), (2, 5), (6, 10)], [5, 2, 1]),
        "error": ([(0, 0), (1, 1)], [10, 0]),
        "pruser": ([(0, (1 << ruser_width) - 1)], [1]),
        "pbuser": ([(0, (1 << buser_width) - 1)], [1]),
    })
    result = r.next()
    assert set(result.keys()) == {"ready", "error", "pruser", "pbuser"}
    assert 0 <= result["pruser"] <= 15
    assert 0 <= result["pbuser"] <= 15


def test_apb_master_default_constraints_shape():
    """Exact shape returned by APBMaster._default_randomizer_constraints.

    Bin pairs MUST be tuples, not lists — FlexRandomizer enforces this.
    See APBMaster._default_randomizer_constraints docstring.
    """
    r = FlexRandomizer({
        "psel":    ([(0, 0), (1, 5), (6, 10)], [5, 2, 1]),
        "penable": ([(0, 0), (1, 2)], [4, 1]),
    })
    result = r.next()
    assert set(result.keys()) == {"psel", "penable"}


def test_flex_randomizer_rejects_list_bins():
    """Regression guard: list bin pairs should be rejected with a helpful error.

    Prior to this test, APBMaster's default constraints used `[0, 0]` (list)
    pairs which FlexRandomizer rejects. The test pins the contract so future
    refactors don't reintroduce the bug.
    """
    with pytest.raises(Exception, match="tuple of \\(min, max\\)"):
        FlexRandomizer({"x": ([[0, 0], [1, 5]], [1, 1])})


def test_sequence_constraint_rotates():
    """List constraint form (used elsewhere) cycles through values."""
    r = FlexRandomizer({"seq": [10, 20, 30]})
    vals = [r.next()["seq"] for _ in range(6)]
    assert vals == [10, 20, 30, 10, 20, 30]
