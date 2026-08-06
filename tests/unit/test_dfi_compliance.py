# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Unit tests for the DFI latency-window compliance checker.

Every rule is tested in both directions: compliant traffic produces
zero violations, and each specific breach produces exactly the
matching violation (checker true positives — the referee itself is
under test here).
"""

from __future__ import annotations

import pytest

from CocoTBFramework.components.dfi.dfi_compliance import (
    ALL_RULES,
    CycleSample,
    DFIComplianceChecker,
    DFIComplianceParams,
    RULE_TCTRLUPD_MAX,
    RULE_TCTRLUPD_MIN,
    RULE_TPHY_RDLAT,
    RULE_TPHY_WRLAT,
    RULE_TPHYUPD_RESP,
    RULE_TRDDATA_EN,
)

IDLE = CycleSample()


@pytest.fixture
def params():
    return DFIComplianceParams(
        tphy_wrlat=2, trddata_en=2, tphy_rdlat=4,
        tctrlupd_min=2, tctrlupd_max=8, tphyupd_resp=4,
        tinit_start=4,
    )


@pytest.fixture
def chk(params):
    return DFIComplianceChecker(params)


def _run(chk, samples):
    for s in samples:
        chk.on_cycle(s)


# ---------------------------------------------------------------------
# Write path: tphy_wrlat
# ---------------------------------------------------------------------


def test_wrlat_compliant(chk):
    _run(chk, [
        CycleSample(wr_cmd=True),
        IDLE,
        CycleSample(wrdata_en=True),   # exactly wrlat=2 later
        IDLE,
    ])
    assert chk.report() == {}


def test_wrlat_missing_enable_flags(chk):
    _run(chk, [CycleSample(wr_cmd=True), IDLE, IDLE, IDLE])
    assert chk.report().get(RULE_TPHY_WRLAT) == 1


def test_wrlat_orphan_enable_flags(chk):
    _run(chk, [IDLE, CycleSample(wrdata_en=True), IDLE])
    assert chk.report().get(RULE_TPHY_WRLAT) == 1


def test_wrlat_zero_latency_profile():
    """wrlat=0: enable rides with the command; no orphan detection."""
    chk = DFIComplianceChecker(DFIComplianceParams(tphy_wrlat=0))
    _run(chk, [CycleSample(wr_cmd=True, wrdata_en=True), IDLE])
    assert chk.report().get(RULE_TPHY_WRLAT) is None


# ---------------------------------------------------------------------
# Read path: trddata_en and tphy_rdlat
# ---------------------------------------------------------------------


def test_rddata_en_compliant(chk):
    _run(chk, [
        CycleSample(rd_cmd=True),
        IDLE,
        CycleSample(rddata_en=True),
        CycleSample(rddata_en=True, rddata_valid=True),
        IDLE,
    ])
    assert chk.report() == {}


def test_rddata_en_missing_flags(chk):
    _run(chk, [CycleSample(rd_cmd=True), IDLE, IDLE, IDLE])
    assert chk.report().get(RULE_TRDDATA_EN) == 1


def test_rdlat_window_expiry_flags(chk):
    samples = [CycleSample(rddata_en=True)] + [IDLE] * 6
    _run(chk, samples)
    assert chk.report().get(RULE_TPHY_RDLAT) == 1


def test_rdlat_valid_inside_window_ok(chk):
    _run(chk, [
        CycleSample(rddata_en=True),
        IDLE,
        CycleSample(rddata_valid=True),   # within tphy_rdlat=4
        IDLE, IDLE, IDLE, IDLE,
    ])
    assert chk.report().get(RULE_TPHY_RDLAT) is None


# ---------------------------------------------------------------------
# Update: ctrlupd pulse width, phyupd response
# ---------------------------------------------------------------------


def test_ctrlupd_pulse_compliant(chk):
    _run(chk, [
        CycleSample(ctrlupd_req=True),
        CycleSample(ctrlupd_req=True),
        CycleSample(ctrlupd_req=True),
        IDLE,
    ])
    assert chk.report() == {}


def test_ctrlupd_too_short_flags(chk):
    _run(chk, [CycleSample(ctrlupd_req=True), IDLE])   # width 1 < min 2
    assert chk.report().get(RULE_TCTRLUPD_MIN) == 1


def test_ctrlupd_too_long_flags(chk):
    _run(chk, [CycleSample(ctrlupd_req=True)] * 12)    # > max 8
    assert chk.report().get(RULE_TCTRLUPD_MAX) == 1


def test_phyupd_acked_in_window_ok(chk):
    _run(chk, [
        CycleSample(phyupd_req=True),
        CycleSample(phyupd_req=True),
        CycleSample(phyupd_req=True, phyupd_ack=True),
        IDLE,
    ])
    assert chk.report() == {}


def test_phyupd_ack_timeout_flags(chk):
    _run(chk, [CycleSample(phyupd_req=True)] * 8)      # no ack, resp=4
    assert chk.report().get(RULE_TPHYUPD_RESP) == 1


# ---------------------------------------------------------------------
# Frequency change: outcome statistics, never violations
# ---------------------------------------------------------------------


def test_freq_change_acknowledged_stat(chk):
    _run(chk, [
        CycleSample(init_complete=True),
        CycleSample(init_start=True, init_complete=True),
        CycleSample(init_start=True, init_complete=True),
        CycleSample(init_start=True, init_complete=False),   # PHY accepts
        IDLE,
    ])
    assert chk.freq_change_acknowledged == 1
    assert chk.freq_change_not_acknowledged == 0
    assert chk.report() == {}


def test_freq_change_ignored_is_legal_not_violation(chk):
    samples = [CycleSample(init_complete=True)]
    samples += [CycleSample(init_start=True, init_complete=True)] * 8
    samples += [CycleSample(init_complete=True)]
    _run(chk, samples)
    assert chk.freq_change_not_acknowledged == 1
    assert chk.report() == {}                # legal per spec


# ---------------------------------------------------------------------
# Rule gating + report helpers
# ---------------------------------------------------------------------


def test_disabled_rule_not_flagged():
    p = DFIComplianceParams(
        tphy_wrlat=2,
        enabled_rules=frozenset(ALL_RULES - {RULE_TPHY_WRLAT}),
    )
    chk = DFIComplianceChecker(p)
    _run(chk, [CycleSample(wr_cmd=True), IDLE, IDLE, IDLE])
    assert chk.report() == {}


def test_assert_clean_raises_with_detail(chk):
    _run(chk, [CycleSample(wr_cmd=True), IDLE, IDLE, IDLE])
    with pytest.raises(AssertionError, match="tphy_wrlat"):
        chk.assert_clean()


def test_violation_records_carry_cycle_and_rule(chk):
    _run(chk, [CycleSample(wr_cmd=True), IDLE, IDLE, IDLE])
    v = chk.violations[0]
    assert v.rule == RULE_TPHY_WRLAT
    assert v.cycle == 3          # due cycle: cmd @1 + wrlat 2
