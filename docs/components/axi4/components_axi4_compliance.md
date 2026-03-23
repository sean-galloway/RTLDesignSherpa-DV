# AXI4 Compliance Checker

Non-intrusive AXI4 protocol compliance checker that validates handshake rules, burst constraints, ID ordering, and response codes. Designed for optional integration into existing testbenches without requiring code changes.

## Overview

The `AXI4ComplianceChecker` provides:

- **Environment-controlled activation** via `AXI4_COMPLIANCE_CHECK=1` -- zero code changes required
- **Automatic signal monitoring** on all five AXI4 channels (AR, AW, W, R, B)
- **Handshake protocol validation** (VALID/READY rules)
- **Burst constraint checking** (length, size, boundary)
- **Response code validation** for B and R channels
- **RLAST/WLAST matching** against expected beat counts
- **ID-based transaction tracking** for read and write ordering
- **Detailed violation reporting** with per-cycle timestamps
- **Minimal performance impact** when disabled

The checker uses `GAXIMonitor` instances to observe each channel and runs background coroutines for continuous protocol checking.

---

## Supporting Types

### AXI4ViolationType

```python
class AXI4ViolationType(Enum)
```

Enumeration of all violation types the checker can detect.

| Value | Category | Description |
|-------|----------|-------------|
| `VALID_DROPPED` | Handshake | VALID deasserted before READY handshake |
| `READY_BEFORE_VALID` | Handshake | READY asserted before VALID (informational) |
| `VALID_UNSTABLE` | Handshake | VALID signal changed unexpectedly |
| `BURST_LENGTH_VIOLATION` | Burst | Burst length exceeds 256 |
| `BURST_SIZE_VIOLATION` | Burst | Burst size exceeds maximum (7) |
| `BURST_BOUNDARY_VIOLATION` | Burst | Burst crosses 4KB boundary |
| `WLAST_MISMATCH` | Burst | WLAST does not match expected beat count |
| `RLAST_MISMATCH` | Burst | RLAST does not match expected beat count |
| `ID_ORDERING_VIOLATION` | ID | ID ordering rules violated |
| `ID_WIDTH_VIOLATION` | ID | ID value exceeds configured width |
| `RESPONSE_CODE_VIOLATION` | Response | Invalid response code (>3) |
| `RESET_VIOLATION` | Timing | Signals not properly reset |
| `CLOCK_VIOLATION` | Timing | Clock domain issue |
| `DATA_STABILITY_VIOLATION` | Data | Data changed while VALID asserted |
| `STROBE_VIOLATION` | Data | Invalid write strobe pattern |

### AXI4Violation

```python
@dataclass
class AXI4Violation:
    violation_type: AXI4ViolationType
    channel: str
    cycle: int
    message: str
    severity: str = 'ERROR'
    additional_data: Dict[str, Any] = field(default_factory=dict)
```

Represents a single protocol violation with its type, channel, cycle number, descriptive message, severity level, and optional additional context.

---

## Class

### AXI4ComplianceChecker

```python
class AXI4ComplianceChecker:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix (e.g., `"m_axi_"`) | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `data_width` | `int` | Data bus width in bits | `32` |
| `id_width` | `int` | ID field width in bits | `8` |
| `addr_width` | `int` | Address bus width in bits | `32` |
| `user_width` | `int` | User signal width in bits | `1` |
| `multi_sig` | `bool` | Whether DUT uses individual signal mode | `True` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `violations` | `List[AXI4Violation]` | All recorded violations |
| `violation_counts` | `Dict[AXI4ViolationType, int]` | Count per violation type |
| `cycle_count` | `int` | Current simulation cycle |
| `stats` | `Dict[str, Any]` | Transaction and check statistics |
| `monitors` | `Dict[str, GAXIMonitor]` | Per-channel monitor instances |
| `enabled` | `bool` | Whether the checker is active |

---

## Class Methods

### `AXI4ComplianceChecker.create_if_enabled(dut, clock, prefix="", log=None, **kwargs) -> Optional[AXI4ComplianceChecker]`

Factory method that returns `None` when compliance checking is disabled. This is the recommended way to integrate the checker.

**Returns:** `AXI4ComplianceChecker` instance if `AXI4_COMPLIANCE_CHECK=1` is set, otherwise `None`.

```python
self.compliance_checker = AXI4ComplianceChecker.create_if_enabled(
    dut=dut, clock=clock, prefix="m_axi_", log=self.log,
    data_width=32, id_width=4
)
```

### `AXI4ComplianceChecker.is_enabled() -> bool`

Check if compliance checking is enabled via the `AXI4_COMPLIANCE_CHECK` environment variable.

---

## Instance Methods

### `setup_monitors()`

Set up `GAXIMonitor` instances for all AXI4 channels that have valid/ready signals present on the DUT. Called automatically during initialization.

### `record_violation(violation_type, channel, message, **kwargs)`

Record a protocol violation.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `violation_type` | `AXI4ViolationType` | Type of violation | (required) |
| `channel` | `str` | Channel name (`'AR'`, `'AW'`, `'W'`, `'R'`, `'B'`) | (required) |
| `message` | `str` | Human-readable violation description | (required) |
| `severity` | `str` | Severity level (`'ERROR'`, `'WARNING'`, `'INFO'`) | `'ERROR'` |
| `additional_data` | `dict` | Extra context data | `{}` |

### `get_compliance_report() -> Dict[str, Any]`

Get a comprehensive compliance report.

**Returns:** Dictionary with the following keys:

| Key | Type | Description |
|-----|------|-------------|
| `compliance_checking` | `str` | `'enabled'` or `'disabled'` |
| `total_violations` | `int` | Total number of violations recorded |
| `violation_summary` | `Dict[str, int]` | Count per violation type (non-zero only) |
| `statistics` | `Dict[str, Any]` | Transaction and check statistics |
| `violations` | `List[Dict]` | Last 10 violations with details |
| `compliance_status` | `str` | `'PASSED'` or `'FAILED'` |

### `print_compliance_report()`

Print a formatted compliance report to the logger.

---

## Decorator

### `add_axi4_compliance_checking(testbench_class)`

Class decorator that adds automatic compliance checking to an existing testbench class. Modifies `__init__` to create a checker and `finalize_test` to print the report.

```python
@add_axi4_compliance_checking
class MyAXI4Testbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)
        # Compliance checker automatically added as self.axi4_compliance_checker
```

---

## Usage Examples

### Conditional Integration in Testbench

```python
from CocoTBFramework.components.axi4.axi4_compliance_checker import AXI4ComplianceChecker

class MyTestbench:
    def __init__(self, dut, clock):
        # Create compliance checker -- returns None if env var not set
        self.compliance_checker = AXI4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix="m_axi_",
            log=self.log,
            data_width=32,
            id_width=8
        )

    def finalize_test(self):
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
```

### Running Tests with Compliance Checking

```bash
# Normal test run (compliance checking disabled)
make test

# Enable compliance checking via environment variable
AXI4_COMPLIANCE_CHECK=1 make test
```

### Inspecting the Compliance Report

```python
if self.compliance_checker:
    report = self.compliance_checker.get_compliance_report()

    print(f"Status: {report['compliance_status']}")
    print(f"Total violations: {report['total_violations']}")
    print(f"AR transactions: {report['statistics']['total_ar_transactions']}")
    print(f"AW transactions: {report['statistics']['total_aw_transactions']}")
    print(f"Checks performed: {report['statistics']['checks_performed']}")

    for v in report['violations']:
        print(f"  [{v['channel']}] cycle {v['cycle']}: {v['message']}")
```
