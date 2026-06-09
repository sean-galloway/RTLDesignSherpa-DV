"""Unit tests for shared/apb_common.py (issue #8)."""

from __future__ import annotations

from CocoTBFramework.components.shared.apb_common import (
    BASE_APB_OPTIONAL_SIGNALS,
    BASE_APB_SIGNALS,
    PWRITE_DIR,
)


def test_constants_are_tuples_not_lists():
    """Tuples make accidental mutation impossible."""
    assert isinstance(BASE_APB_SIGNALS, tuple)
    assert isinstance(BASE_APB_OPTIONAL_SIGNALS, tuple)
    assert isinstance(PWRITE_DIR, tuple)


def test_base_signals_contain_apb4_required_set():
    """The 7 mandatory AMBA APB4 signals."""
    assert set(BASE_APB_SIGNALS) == {
        "PSEL", "PWRITE", "PENABLE", "PADDR", "PWDATA", "PRDATA", "PREADY",
    }


def test_base_optional_signals_are_apb4_optional_set():
    """APB4 optional signals."""
    assert set(BASE_APB_OPTIONAL_SIGNALS) == {"PPROT", "PSLVERR", "PSTRB"}


def test_pwrite_dir_matches_spec():
    """PWRITE=0 is READ, PWRITE=1 is WRITE per spec."""
    assert PWRITE_DIR == ("READ", "WRITE")


def test_apb4_module_level_lists_match_shared_constants():
    """`apb_signals` in apb_components.py is a list copy of BASE_APB_SIGNALS."""
    from CocoTBFramework.components.apb import apb_components

    assert apb_components.apb_signals == list(BASE_APB_SIGNALS)
    assert apb_components.apb_optional_signals == list(BASE_APB_OPTIONAL_SIGNALS)
    assert apb_components.pwrite == list(PWRITE_DIR)


def test_apb5_module_level_lists_extend_apb4():
    """APB5 base list is identical to APB4 base; optional is APB4 + extensions."""
    from CocoTBFramework.components.apb5 import apb5_components

    assert apb5_components.apb5_signals == list(BASE_APB_SIGNALS)
    # APB5 optional must be a strict superset of APB4 optional
    apb5_opt = set(apb5_components.apb5_optional_signals)
    apb4_opt = set(BASE_APB_OPTIONAL_SIGNALS)
    assert apb4_opt < apb5_opt, "APB5 optional must include APB4 optional"


def test_apb5_extensions_include_expected_user_signals():
    from CocoTBFramework.components.apb5 import apb5_components

    apb5_opt = set(apb5_components.apb5_optional_signals)
    for sig in ("PAUSER", "PWUSER", "PRUSER", "PBUSER", "PWAKEUP"):
        assert sig in apb5_opt, f"APB5 must expose {sig}"
