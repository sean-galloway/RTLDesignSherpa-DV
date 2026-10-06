# AXI4-ACE Compliance Checker

A lightweight ACE snoop-channel checker. It records violations through a direct API, so it can be driven from unit tests without a simulator. It does not monitor DUT pins directly; instead, the BFM or testbench calls its check methods as snoop transactions complete.

## Overview

The `ACEComplianceChecker` enforces the four ACE rules selected for the cache-ip family:

- **R1:** CR responses must return in AC-issue order per snoop-slave interface.
- **R2:** CD beats must return in AC-issue order and `CDLAST` must only be asserted on the final beat.
- **R3:** No snoop is issued to the requesting master.
- **R4:** CRRESP must be valid for the snoop type.

It is intentionally small: there is no environment-variable gate, no automatic monitor wiring, and no cost when it is not instantiated. Create it, call its check methods, and print the report.

---

## Supporting Types

### ACEViolationType

```python
class ACEViolationType(Enum)
```

Every violation type the checker can raise.

| Value | Description |
|-------|-------------|
| `CR_ORDERING_VIOLATION` | CR response returned out of AC-issue order |
| `CD_ORDERING_VIOLATION` | CD beat returned out of AC-issue order |
| `CDLAST_NOT_FINAL` | `CDLAST` asserted before the expected final beat |
| `SNOOP_TO_REQUESTING_MASTER` | A snoop was issued to the requesting master |
| `CRRESP_INVALID_FOR_SNOOP` | CRRESP violates the validity rules for the snoop type |

### ACEViolation

```python
@dataclass
class ACEViolation:
    violation_type: ACEViolationType
    cycle: int
    message: str
    additional_data: Dict[str, Any] = field(default_factory=dict)
    severity: str = "ERROR"
```

One recorded violation: type, cycle number, message, severity, and optional extra context.

---

## Class

### ACEComplianceChecker

```python
class ACEComplianceChecker:
    def __init__(self, log=None)
```

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `log` | `logging.Logger` | Logger instance | `None` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `violations` | `List[ACEViolation]` | All recorded violations |
| `violation_counts` | `Dict[ACEViolationType, int]` | Count per violation type |
| `cycle_count` | `int` | Internal cycle counter |
| `_next_cr_seq` | `int` | Expected sequence number for the next CR response |
| `_next_cd_seq` | `int` | Expected sequence number for the next CD beat |
| `_current_cd_beats` | `int` | Beats seen so far for the current CD transaction |
| `_current_cd_expected_beats` | `int` or `None` | Expected beat count for the current CD transaction |
| `_issued_snoops` | `int` | Counter for issued snoops |
| `_suppressed_snoops` | `int` | Counter for suppressed snoops |

---

## Instance Methods

### `record_violation(violation_type, message, severity="ERROR", **additional_data) -> None`

Record a protocol violation by hand. Useful when a test has its own protocol expectations on top of the built-in ones.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `violation_type` | `ACEViolationType` | Type of violation | (required) |
| `message` | `str` | Human-readable violation description | (required) |
| `severity` | `str` | Severity level (`'ERROR'`, `'WARNING'`, `'INFO'`) | `'ERROR'` |
| `**additional_data` | `Any` | Extra context data | — |

### `tick(cycles: int = 1) -> None`

Advance the internal cycle counter by `cycles`.

### `check_cr_order(snoop_seq, snoop_addr=0, snoop_type=None) -> None`

Validate that a CR response matches the expected AC-issue order.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `snoop_seq` | `int` | Sequence number of the snoop whose CR just arrived | (required) |
| `snoop_addr` | `int` | Snoop address for context | `0` |
| `snoop_type` | `SnoopType` or `None` | Snoop type for context | `None` |

If `snoop_seq` is not the next expected sequence number, a `CR_ORDERING_VIOLATION` is recorded.

### `check_cd_order(snoop_seq, is_last, snoop_addr=0, snoop_type=None) -> None`

Validate CD beat ordering and `CDLAST` placement.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `snoop_seq` | `int` | Sequence number of the snoop whose CD beat arrived | (required) |
| `is_last` | `bool` | Whether this beat has `CDLAST` asserted | (required) |
| `snoop_addr` | `int` | Snoop address for context | `0` |
| `snoop_type` | `SnoopType` or `None` | Snoop type for context | `None` |

Records a `CD_ORDERING_VIOLATION` if the beat is out of order, and a `CDLAST_NOT_FINAL` violation if `CDLAST` is asserted before the expected final beat.

### `set_expected_cd_beats(beats: int) -> None`

Tell the checker how many CD beats the current snoop will produce. Used by `check_cd_order` to validate `CDLAST` placement.

### `check_crresp_validity(crresp, snoop_type, snoop_addr=0) -> None`

Validate CRRESP for the given snoop type. Calls `CRRESP.validate_for_snoop` and records a `CRRESP_INVALID_FOR_SNOOP` violation if the result is invalid.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `crresp` | `CRRESP` | Snoop response to validate | (required) |
| `snoop_type` | `SnoopType` | Snoop type | (required) |
| `snoop_addr` | `int` | Snoop address for context | `0` |

### `check_snoop_not_to_requester(addr, excluded) -> None`

Record a violation if a snoop was issued to the requesting master.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `addr` | `int` | Snoop address |
| `excluded` | `bool` | `True` if the snoop was suppressed because it targeted the requester |

Increments `_issued_snoops` unconditionally and `_suppressed_snoops` when `excluded` is `True`. Records a `SNOOP_TO_REQUESTING_MASTER` violation when `excluded` is `True`.

### `get_compliance_report() -> Dict[str, Any]`

The full compliance report as a dictionary.

**Returns:** Dictionary with the following keys:

| Key | Type | Description |
|-----|------|-------------|
| `compliance_checking` | `str` | `'enabled'` |
| `total_violations` | `int` | Total number of violations recorded |
| `violation_summary` | `Dict[str, int]` | Count per violation type (non-zero only) |
| `statistics` | `Dict[str, Any]` | `issued_snoops`, `suppressed_snoops`, `checks_performed` |
| `violations` | `List[Dict]` | Last 10 violations with details |
| `compliance_status` | `str` | `'PASSED'` or `'FAILED'` |

### `print_compliance_report() -> None`

Formats the report and writes it to the logger if one is attached; otherwise prints to stdout.

---

## Usage Examples

### Checking CRRESP Validity

```python
from CocoTBFramework.components.ace import ACEComplianceChecker
from CocoTBFramework.components.ace.ace_transaction import (
    CRRESP, SnoopType,
)

checker = ACEComplianceChecker(log=log)

# A snoop master received this response
result = await snoop_master.issue_snoop(0x1000, SnoopType.READ_SHARED)
checker.check_crresp_validity(result.crresp, SnoopType.READ_SHARED, addr=0x1000)

checker.print_compliance_report()
```

### Checking Snoop Ordering

```python
checker = ACEComplianceChecker(log=log)

# As each CR response arrives, in the order they were issued
checker.check_cr_order(snoop_seq=0, snoop_addr=0x1000, snoop_type=SnoopType.READ_SHARED)
checker.check_cr_order(snoop_seq=1, snoop_addr=0x2000, snoop_type=SnoopType.READ_UNIQUE)
```

### Checking CD Beat Order and CDLAST

```python
checker = ACEComplianceChecker(log=log)

# A snoop with two data beats
checker.set_expected_cd_beats(2)
checker.check_cd_order(snoop_seq=0, is_last=False)
checker.check_cd_order(snoop_seq=0, is_last=True)

# Next snoop's single beat
checker.set_expected_cd_beats(1)
checker.check_cd_order(snoop_seq=1, is_last=True)
```

### Checking Snoop Suppression

```python
checker = ACEComplianceChecker(log=log)

# If the CCU suppressed a snoop because it targeted the requester:
checker.check_snoop_not_to_requester(addr=0x1000, excluded=True)
```

### Inspecting the Report

```python
report = checker.get_compliance_report()

print(f"Status: {report['compliance_status']}")
print(f"Total violations: {report['total_violations']}")
print(f"Issued snoops: {report['statistics']['issued_snoops']}")
print(f"Suppressed snoops: {report['statistics']['suppressed_snoops']}")

for v in report['violations']:
    print(f"  [{v['type']}] cycle {v['cycle']}: {v['message']}")
```

---

## Integration Pattern

Unlike the AXI4 checker, `ACEComplianceChecker` is not created through an environment variable or attached automatically. The typical pattern is to instantiate it in a testbench class, call its check methods as snoop results arrive, and print the report at the end of the test:

```python
class MyACETestbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)
        self.ace_checker = ACEComplianceChecker(log=self.log)
        # ... create snoop master/slave ...

    async def run_checks(self):
        result = await self.snoop_master.issue_snoop(0x1000, SnoopType.READ_SHARED)
        self.ace_checker.check_crresp_validity(
            result.crresp, SnoopType.READ_SHARED, addr=0x1000
        )

    def finalize_test(self):
        self.ace_checker.print_compliance_report()
```
