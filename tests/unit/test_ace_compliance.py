# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for the ACE compliance checker."""

import pytest

from CocoTBFramework.components.ace.ace_compliance_checker import (
    ACEComplianceChecker,
    ACEViolationType,
)
from CocoTBFramework.components.ace.ace_transaction import CRRESP, SnoopType


@pytest.fixture
def checker():
    return ACEComplianceChecker()


# ---------------------------------------------------------------------------
# CR ordering (R1)
# ---------------------------------------------------------------------------

def test_cr_in_order_increments_expected_seq(checker):
    checker.check_cr_order(0)
    checker.check_cr_order(1)
    assert checker.violations == []


def test_cr_out_of_order_records_violation(checker):
    checker.check_cr_order(1)
    assert checker.violations[-1].violation_type == ACEViolationType.CR_ORDERING_VIOLATION


# ---------------------------------------------------------------------------
# CD ordering and CDLAST (R2)
# ---------------------------------------------------------------------------

def test_cd_beats_in_order_with_correct_last(checker):
    checker.set_expected_cd_beats(2)
    checker.check_cd_order(0, is_last=False)
    checker.check_cd_order(0, is_last=True)
    assert checker.violations == []


def test_cd_out_of_order_records_violation(checker):
    checker.check_cd_order(1, is_last=True)
    assert checker.violations[-1].violation_type == ACEViolationType.CD_ORDERING_VIOLATION


def test_cdlast_before_final_beat_records_violation(checker):
    checker.set_expected_cd_beats(3)
    checker.check_cd_order(0, is_last=False)
    checker.check_cd_order(0, is_last=True)  # only beat 2 of expected 3
    assert checker.violations[-1].violation_type == ACEViolationType.CDLAST_NOT_FINAL


# ---------------------------------------------------------------------------
# No snoop to requesting master (R3)
# ---------------------------------------------------------------------------

def test_allowed_snoop_does_not_record_violation(checker):
    checker.check_snoop_not_to_requester(0x1000, excluded=False)
    assert checker.violations == []


def test_excluded_snoop_records_violation(checker):
    checker.check_snoop_not_to_requester(0x1000, excluded=True)
    assert checker.violations[-1].violation_type == ACEViolationType.SNOOP_TO_REQUESTING_MASTER


# ---------------------------------------------------------------------------
# CRRESP validity (R4)
# ---------------------------------------------------------------------------

def test_valid_crresp_for_read_shared(checker):
    cr = CRRESP.from_bits(data_transfer=True, pass_dirty=True, is_shared=True)
    checker.check_crresp_validity(cr, SnoopType.READ_SHARED)
    assert checker.violations == []


def test_invalid_crresp_for_make_invalid(checker):
    cr = CRRESP.from_bits(data_transfer=True)
    checker.check_crresp_validity(cr, SnoopType.MAKE_INVALID)
    assert checker.violations[-1].violation_type == ACEViolationType.CRRESP_INVALID_FOR_SNOOP


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def test_report_status_passed_when_clean(checker):
    report = checker.get_compliance_report()
    assert report["compliance_status"] == "PASSED"
    assert report["total_violations"] == 0


def test_report_status_failed_after_violation(checker):
    checker.record_violation(ACEViolationType.CR_ORDERING_VIOLATION, "test")
    report = checker.get_compliance_report()
    assert report["compliance_status"] == "FAILED"
    assert report["total_violations"] == 1
    assert "cr_ordering_violation" in report["violation_summary"]
