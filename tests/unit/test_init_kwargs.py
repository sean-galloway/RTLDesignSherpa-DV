"""Unit tests for shared/init_kwargs.py (issue #10)."""

from __future__ import annotations

from CocoTBFramework.components.shared.init_kwargs import (
    FRAMEWORK_KWARGS,
    pop_framework_kwargs,
    strip_framework_kwargs,
)


def test_framework_kwargs_includes_canonical_set():
    """All known framework-only kwargs are in the canonical tuple."""
    expected = {
        "bus_name", "pkt_prefix", "memory_model", "randomizer",
        "signal_map", "super_debug", "pipeline_debug",
        "optional_fields",
    }
    assert set(FRAMEWORK_KWARGS) == expected


def test_strip_removes_framework_kwargs_in_place():
    kw = {
        "memory_model": object(),
        "super_debug": True,
        "bus_name": "u_dut",
        "user_thing": 42,
    }
    strip_framework_kwargs(kw)
    assert kw == {"user_thing": 42}


def test_strip_with_extras():
    """The `extra` arg lets callers strip prefix too (used by GAXIMaster)."""
    kw = {"memory_model": object(), "prefix": "u_", "user_thing": 42}
    strip_framework_kwargs(kw, extra=("prefix",))
    assert kw == {"user_thing": 42}


def test_strip_tolerates_missing_keys():
    """Stripping when kwargs don't contain the framework keys is a no-op."""
    kw = {"only_user_thing": 1}
    strip_framework_kwargs(kw)
    assert kw == {"only_user_thing": 1}


def test_pop_returns_dict_of_values():
    sentinel_mm = object()
    sentinel_rnd = object()
    kw = {
        "memory_model": sentinel_mm,
        "randomizer": sentinel_rnd,
        "user_thing": 42,
    }
    popped = pop_framework_kwargs(kw, names=("memory_model", "randomizer"))
    assert popped == {"memory_model": sentinel_mm, "randomizer": sentinel_rnd}
    assert kw == {"user_thing": 42}


def test_pop_default_uses_full_framework_set():
    """Default for names= is FRAMEWORK_KWARGS — pops all framework keys."""
    kw = {name: name for name in FRAMEWORK_KWARGS}
    kw["user_thing"] = 99
    popped = pop_framework_kwargs(kw)
    assert popped == {name: name for name in FRAMEWORK_KWARGS}
    assert kw == {"user_thing": 99}
