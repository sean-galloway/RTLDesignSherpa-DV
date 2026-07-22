"""Unit tests for shared/apb_common.py (issue #8) and the
required/optional cocotb_bus signal split in the APB/APB5 BFMs."""

from __future__ import annotations

import pytest

from CocoTBFramework.components.apb.apb_components import (
    APBMaster,
    APBMonitor,
    APBSignalMixin,
    APBSlave,
)
from CocoTBFramework.components.apb5.apb5_components import (
    APB5Master,
    APB5Monitor,
    APB5Slave,
    apb5_optional_signals,
)
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


# ----------------------------------------------------------------------
# Required/optional signal split for cocotb_bus binding.
#
# cocotb_bus treats `_signals` as REQUIRED (binding fails on a DUT that
# lacks any of them) and `_optional_signals` as best-effort. Optional APB
# signals must therefore never appear in the required list — otherwise a
# DUT without PSTRB/PSLVERR/PPROT (or the APB5 extensions) can't bind.
# ----------------------------------------------------------------------

APB4_CLASSES = [APBMonitor, APBSlave, APBMaster]
APB5_CLASSES = [APB5Monitor, APB5Slave, APB5Master]


@pytest.mark.parametrize("cls", APB4_CLASSES)
def test_apb4_default_split_required_vs_optional(cls):
    """APB4 BFMs: required = mandatory APB4 set; optional = PPROT/PSLVERR/PSTRB."""
    required, optional = cls._resolve_signal_lists(None)
    assert set(required) == set(BASE_APB_SIGNALS)
    assert set(optional) == set(BASE_APB_OPTIONAL_SIGNALS)


@pytest.mark.parametrize("cls", APB5_CLASSES)
def test_apb5_default_split_required_vs_optional(cls):
    """APB5 BFMs: required stays the APB4 base; every AMBA5 extension is optional."""
    required, optional = cls._resolve_signal_lists(None)
    assert set(required) == set(BASE_APB_SIGNALS)
    assert set(optional) == set(apb5_optional_signals)


@pytest.mark.parametrize("cls", APB4_CLASSES + APB5_CLASSES)
def test_no_optional_signal_in_required_list(cls):
    """The high-severity bug: optional signals must not be required."""
    required, optional = cls._resolve_signal_lists(None)
    overlap = set(required) & set(optional)
    assert not overlap, f"{cls.__name__} requires optional signals: {overlap}"
    for sig in ("PPROT", "PSLVERR", "PSTRB"):
        assert sig not in required, f"{cls.__name__} must not require {sig}"


@pytest.mark.parametrize("cls", APB5_CLASSES)
def test_apb5_extensions_not_required(cls):
    required, _optional = cls._resolve_signal_lists(None)
    for sig in ("PAUSER", "PWUSER", "PRUSER", "PBUSER", "PWAKEUP",
                "PWDATAPARITY", "PREADYPARITY"):
        assert sig not in required, f"{cls.__name__} must not require {sig}"


@pytest.mark.parametrize("cls", APB4_CLASSES + APB5_CLASSES)
def test_explicit_signals_used_verbatim(cls):
    """A caller-supplied signal list takes full control (no optional set)."""
    custom = ["PSEL", "PENABLE", "PADDR"]
    required, optional = cls._resolve_signal_lists(custom)
    assert required == custom
    assert required is not custom, "must copy, not alias, the caller's list"
    assert optional == []


@pytest.mark.parametrize("cls", APB4_CLASSES + APB5_CLASSES)
def test_all_bfms_use_signal_mixin(cls):
    """Signal-list resolution and is_signal_present come from one place."""
    assert issubclass(cls, APBSignalMixin)
    assert hasattr(cls, "is_signal_present")
