# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: ACEComplianceChecker
# Purpose: ACE protocol compliance checker for snoop-channel rules.
#
# Documentation: bin/CocoTBFramework/README.md
# Subsystem: framework
#
# Author: sean galloway
# Created: 2026-10-05

"""ACE protocol compliance checker.

Enforces the four ACE rules selected for the cache-ip family:

- R1: CR responses must return in AC-issue order per snoop-slave interface.
- R2: CD beats must return in AC-issue order and CDLAST only on the final beat.
- R3: No snoop is issued to the requesting master.
- R4: CRRESP must be valid for the snoop type.

The checker is intentionally lightweight: it records violations as they are
reported through a direct API, so it can be driven from unit tests without a
simulator.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .ace_transaction import CRRESP, SnoopType


class ACEViolationType(Enum):
    """Types of ACE protocol violations."""

    CR_ORDERING_VIOLATION = "cr_ordering_violation"
    CD_ORDERING_VIOLATION = "cd_ordering_violation"
    CDLAST_NOT_FINAL = "cdlast_not_final"
    SNOOP_TO_REQUESTING_MASTER = "snoop_to_requesting_master"
    CRRESP_INVALID_FOR_SNOOP = "crresp_invalid_for_snoop"


@dataclass
class ACEViolation:
    """Represents a single ACE protocol violation."""

    violation_type: ACEViolationType
    cycle: int
    message: str
    additional_data: Dict[str, Any] = field(default_factory=dict)
    severity: str = "ERROR"


class ACEComplianceChecker:
    """ACE snoop-channel compliance checker."""

    def __init__(self, log=None):
        """Initialize the ACE compliance checker."""
        self.log = log
        self.violations: List[ACEViolation] = []
        self.violation_counts: Dict[ACEViolationType, int] = {}
        self.cycle_count = 0

        # Per-snoop-slave state: expected sequence number for next CR and CD.
        # For CD, we also track how many beats have been seen for the current seq.
        self._next_cr_seq = 0
        self._next_cd_seq = 0
        self._current_cd_beats = 0
        self._current_cd_expected_beats: Optional[int] = None

        # Snoop-master side: hook results
        self._suppressed_snoops = 0
        self._issued_snoops = 0

    def record_violation(
        self,
        violation_type: ACEViolationType,
        message: str,
        severity: str = "ERROR",
        **additional_data,
    ) -> None:
        """Record a protocol violation."""
        violation = ACEViolation(
            violation_type=violation_type,
            cycle=self.cycle_count,
            message=message,
            severity=severity,
            additional_data=additional_data,
        )
        self.violations.append(violation)
        self.violation_counts[violation_type] = self.violation_counts.get(violation_type, 0) + 1

        if self.log:
            log_fn = self.log.warning if severity == "WARNING" else self.log.error
            log_fn(f"ACE Violation: {message}")

    def tick(self, cycles: int = 1) -> None:
        """Advance the internal cycle counter."""
        self.cycle_count += cycles

    def check_cr_order(
        self,
        snoop_seq: int,
        snoop_addr: int = 0,
        snoop_type: Optional[SnoopType] = None,
    ) -> None:
        """Validate that a CR response matches the expected issue order."""
        if snoop_seq != self._next_cr_seq:
            self.record_violation(
                ACEViolationType.CR_ORDERING_VIOLATION,
                f"CR out of order: expected seq {self._next_cr_seq}, got {snoop_seq}",
                snoop_addr=snoop_addr,
                snoop_type=snoop_type.name if snoop_type else None,
                expected_seq=self._next_cr_seq,
                got_seq=snoop_seq,
            )
        self._next_cr_seq = max(self._next_cr_seq, snoop_seq + 1)

    def check_cd_order(
        self,
        snoop_seq: int,
        is_last: bool,
        snoop_addr: int = 0,
        snoop_type: Optional[SnoopType] = None,
    ) -> None:
        """Validate CD beat ordering and CDLAST placement."""
        if snoop_seq != self._next_cd_seq:
            self.record_violation(
                ACEViolationType.CD_ORDERING_VIOLATION,
                f"CD beat out of order: expected seq {self._next_cd_seq}, got {snoop_seq}",
                snoop_addr=snoop_addr,
                snoop_type=snoop_type.name if snoop_type else None,
                expected_seq=self._next_cd_seq,
                got_seq=snoop_seq,
            )

        if is_last and self._current_cd_expected_beats is not None:
            if self._current_cd_beats + 1 != self._current_cd_expected_beats:
                self.record_violation(
                    ACEViolationType.CDLAST_NOT_FINAL,
                    "CDLAST asserted before the expected final beat",
                    snoop_addr=snoop_addr,
                    snoop_type=snoop_type.name if snoop_type else None,
                    expected_beats=self._current_cd_expected_beats,
                    got_beats=self._current_cd_beats + 1,
                )

        if is_last:
            self._next_cd_seq = max(self._next_cd_seq, snoop_seq + 1)
            self._current_cd_beats = 0
            self._current_cd_expected_beats = None
        else:
            self._current_cd_beats += 1

    def set_expected_cd_beats(self, beats: int) -> None:
        """Tell the checker how many CD beats the current snoop will produce."""
        self._current_cd_expected_beats = beats

    def check_crresp_validity(
        self,
        crresp: CRRESP,
        snoop_type: SnoopType,
        snoop_addr: int = 0,
    ) -> None:
        """Validate CRRESP for the given snoop type."""
        valid, msg = crresp.validate_for_snoop(snoop_type)
        if not valid:
            self.record_violation(
                ACEViolationType.CRRESP_INVALID_FOR_SNOOP,
                f"CRRESP invalid for {snoop_type.name}: {msg}",
                snoop_addr=snoop_addr,
                snoop_type=snoop_type.name,
                crresp=int(crresp),
            )

    def check_snoop_not_to_requester(
        self,
        addr: int,
        excluded: bool,
    ) -> None:
        """Record a violation if a snoop was issued to the requesting master."""
        self._issued_snoops += 1
        if not excluded:
            return
        self._suppressed_snoops += 1
        self.record_violation(
            ACEViolationType.SNOOP_TO_REQUESTING_MASTER,
            f"Snoop issued to requesting master at address 0x{addr:08X}",
            snoop_addr=addr,
        )

    def get_compliance_report(self) -> Dict[str, Any]:
        """Get a compliance report."""
        total = len(self.violations)
        summary = {}
        for vtype in ACEViolationType:
            count = self.violation_counts.get(vtype, 0)
            if count > 0:
                summary[vtype.value] = count

        return {
            "compliance_checking": "enabled",
            "total_violations": total,
            "violation_summary": summary,
            "statistics": {
                "issued_snoops": self._issued_snoops,
                "suppressed_snoops": self._suppressed_snoops,
                "checks_performed": sum(self.violation_counts.values()) + self._issued_snoops,
            },
            "violations": [
                {
                    "type": v.violation_type.value,
                    "cycle": v.cycle,
                    "message": v.message,
                    "severity": v.severity,
                }
                for v in self.violations[-10:]
            ],
            "compliance_status": "PASSED" if total == 0 else "FAILED",
        }

    def print_compliance_report(self) -> None:
        """Print a formatted compliance report."""
        report = self.get_compliance_report()
        if self.log:
            self.log.info("=" * 70)
            self.log.info("ACE PROTOCOL COMPLIANCE REPORT")
            self.log.info("=" * 70)
            self.log.info(f"Status: {report['compliance_status']}")
            self.log.info(f"Total Violations: {report['total_violations']}")
            if report["violation_summary"]:
                self.log.info("Violation Summary:")
                for vtype, count in report["violation_summary"].items():
                    self.log.info(f"  {vtype}: {count}")
            self.log.info("=" * 70)
        else:
            print("=" * 70)
            print("ACE PROTOCOL COMPLIANCE REPORT")
            print("=" * 70)
            print(f"Status: {report['compliance_status']}")
            print(f"Total Violations: {report['total_violations']}")
            if report["violation_summary"]:
                print("Violation Summary:")
                for vtype, count in report["violation_summary"].items():
                    print(f"  {vtype}: {count}")
            print("=" * 70)
