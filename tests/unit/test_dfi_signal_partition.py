# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Unit tests for the version-aware DFI signal partition — issue #69.

Background:
    The spec-verification sweep (60da384) made the BFMs declare the
    union of the DFI 2.1-6.0 signal catalog with ``_optional_signals``
    empty — every wire mandatory. A DUT implementing DFI v2.1 (which
    has no dfi_alert_n, no dfi_reset_n on DDR2, none of the post-2.1
    interfaces) then died at TB construction on
    ``self.bus.alert_n.value = 1`` with an AttributeError on None.
    Measured blast radius in the RDS repo: the whole pumice top tier
    (55 tests) and the entire ddr2-char sim suite.

    The fix: ``partition_wired_signals(version, memory_type)`` splits
    the wired union into a REQUIRED core (command/write/read wires the
    catalog defines for that pair) and OPTIONAL everything-else, and
    every drive/sample of an optional wire is presence-guarded. These
    tests pin the partition so the regression cannot reappear.
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_monitor import (
    _AUX_SIGNALS,
    _CORE_SIGNALS,
    partition_wired_signals,
    signal_version_note,
)
from CocoTBFramework.components.dfi.dfi_signal_types import (
    DFIVersion,
    MemoryType,
)


WIRED_UNION = set(_CORE_SIGNALS) | set(_AUX_SIGNALS)


# ---------------------------------------------------------------------
# The v2.1 / DDR2 case — the reported regression (pumice, ddr2-char)
# ---------------------------------------------------------------------


def test_v21_ddr2_core_is_required():
    req, _ = partition_wired_signals(DFIVersion.V2_1, MemoryType.DDR2)
    assert set(req) == {
        "address", "bank", "cas_n", "ras_n", "we_n", "cs_n", "cke", "odt",
        "wrdata", "wrdata_en", "wrdata_mask",
        "rddata", "rddata_en", "rddata_valid",
    }


def test_v21_ddr2_post_21_wires_are_optional():
    """The exact wires whose mandatory binding broke every v2.1 bus."""
    req, opt = partition_wired_signals(DFIVersion.V2_1, MemoryType.DDR2)
    for name in ("alert_n", "error", "error_info", "lp_ctrl_req",
                 "lp_data_req", "disconnect_error", "phymstr_req",
                 "phymstr_ack", "frequency"):
        assert name in opt, f"dfi_{name} must be optional at v2.1/DDR2"
        assert name not in req


def test_v21_ddr2_reset_n_is_optional():
    """dfi_reset_n exists from v2.1 but only for DDR3+ — the memory
    axis must demote it, not just the version axis."""
    req, opt = partition_wired_signals(DFIVersion.V2_1, MemoryType.DDR2)
    assert "reset_n" in opt
    assert "reset_n" not in req


def test_v21_ddr2_aux_within_version_still_optional():
    """Wires the spec DOES define at v2.1 (freq_ratio, lp_wakeup,
    lp_ack, the update interface) stay optional: they are auxiliary —
    the BFM can do its job without them, and a v2.1 DUT that predates
    the catalog may legitimately not carry them."""
    _, opt = partition_wired_signals(DFIVersion.V2_1, MemoryType.DDR2)
    for name in ("freq_ratio", "lp_wakeup", "lp_ack",
                 "ctrlupd_req", "ctrlupd_ack", "init_start"):
        assert name in opt, f"dfi_{name} must be optional (auxiliary)"


# ---------------------------------------------------------------------
# Other (version, memory) points
# ---------------------------------------------------------------------


def test_v40_ddr4_reset_n_required():
    req, _ = partition_wired_signals(DFIVersion.V4_0, MemoryType.DDR4)
    assert "reset_n" in req


def test_lpddr5_command_encoding_wires_not_required():
    """LPDDR5 carries commands on the CA bus; ras/cas/we/bank/odt are
    scoped to the DDR command families in the catalog."""
    req, opt = partition_wired_signals(DFIVersion.V5_2, MemoryType.LPDDR5)
    for name in ("ras_n", "cas_n", "we_n", "bank", "odt"):
        assert name not in req, f"dfi_{name} must not be required for LPDDR5"
        assert name in opt


def test_none_none_requires_only_universal_core():
    """Callers that declare nothing may only be held to the wires every
    memory type carries: the memory-scoped core (reset_n is DDR3+,
    ras/cas/we/bank the DDR command families, odt the ODT families)
    joins the optional tier, everything auxiliary stays optional."""
    req, opt = partition_wired_signals(None, None)
    assert set(req) == {
        "address", "cs_n", "cke",
        "wrdata", "wrdata_en", "wrdata_mask",
        "rddata", "rddata_en", "rddata_valid",
    }
    assert set(opt) == (set(_CORE_SIGNALS) - set(req)) | set(_AUX_SIGNALS)


def test_undeclared_monitor_binds_pumice_style_bus():
    """The RDS pumice TBs construct DFIMonitor() with no declaration
    against a v2.1 bus with no dfi_reset_n — nothing memory-scoped may
    be required of them."""
    req, _ = partition_wired_signals(None, None)
    for name in ("reset_n", "odt", "bank", "ras_n", "cas_n", "we_n"):
        assert name not in req


# ---------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------


@pytest.mark.parametrize("version,memory", [
    (None, None),
    (DFIVersion.V2_1, MemoryType.DDR2),
    (DFIVersion.V2_1, MemoryType.LPDDR2),
    (DFIVersion.V3_1, MemoryType.DDR3),
    (DFIVersion.V4_0, MemoryType.DDR4),
    (DFIVersion.V5_2, MemoryType.DDR5),
    (DFIVersion.V5_2, MemoryType.LPDDR5),
])
def test_partition_covers_union_exactly(version, memory):
    """required ∪ optional == wired union, required ∩ optional == ∅ —
    a wire can move between tiers but never vanish or duplicate."""
    req, opt = partition_wired_signals(version, memory)
    assert set(req) | set(opt) == WIRED_UNION
    assert set(req) & set(opt) == set()
    assert len(req) == len(set(req)) and len(opt) == len(set(opt))


def test_every_wired_signal_is_cataloged():
    """partition_wired_signals raises on a wired name the catalog does
    not know — a drifted tuple must fail loudly, not silently bind."""
    # The real tuples must all resolve (no raise):
    partition_wired_signals(DFIVersion.V2_1, MemoryType.DDR2)


# ---------------------------------------------------------------------
# Error-message helper
# ---------------------------------------------------------------------


def test_version_note_names_lifecycle():
    note = signal_version_note("alert_n")
    assert "dfi_alert_n" in note
    assert "v3.1" in note      # introduced (as spec-verified) at v3.x
    assert "v5.2" in note      # renamed dfi_alert in v6.0


def test_version_note_open_ended():
    note = signal_version_note("rddata")
    assert "latest" in note


def test_version_note_unknown_name():
    assert "not in the spec catalog" in signal_version_note("no_such_wire")
