# AXIL4 Compliance Checker

Non-intrusive AXIL4 (AXI4-Lite) protocol compliance checker that validates handshake rules, address alignment, write strobe patterns, response codes, and concurrent transaction restrictions. Designed for optional integration into existing testbenches without requiring code changes.

## Overview

The `AXIL4ComplianceChecker` provides:

- **Environment-controlled activation** via `AXIL4_COMPLIANCE_CHECK=1` or `AXI4_COMPLIANCE_CHECK=1` -- zero code changes required
- **Automatic signal monitoring** on all five AXIL4 channels (AR, AW, W, R, B)
- **Handshake protocol validation** (VALID must stay asserted until handshake)
- **Data/address stability checking** (signals must not change while VALID is asserted)
- **Address alignment validation** (must be aligned to data width boundary)
- **Write strobe validation** (must be valid and non-zero)
- **Response code validation** (must be 0-3)
- **Concurrent transaction detection** (AXIL4 does not support simultaneous read/write)
- **PROT field validation** (must be 3-bit value)
- **Detailed violation reporting** with per-cycle timestamps

Key differences from the AXI4 compliance checker:
- No burst checking (single transfer only)
- No ID tracking or ordering checks
- Simplified transaction flow validation
- Register access pattern validation
- Concurrent transaction detection (not supported in AXIL4)

---

## Supporting Types

### AXIL4ViolationType

```python
class AXIL4ViolationType(Enum)
```

Enumeration of all violation types the checker can detect.

| Value | Category | Description |
|-------|----------|-------------|
| `VALID_DROPPED` | Handshake | VALID deasserted before READY handshake |
| `READY_BEFORE_VALID` | Handshake | READY asserted before VALID |
| `VALID_UNSTABLE` | Handshake | VALID signal changed unexpectedly |
| `DATA_UNSTABLE` | Handshake | Data/address changed while VALID asserted |
| `ADDRESS_ALIGNMENT_VIOLATION` | Address | Address not aligned to data width boundary |
| `ADDRESS_WIDTH_VIOLATION` | Address | Address exceeds configured width |
| `RESPONSE_CODE_VIOLATION` | Response | Invalid response code (>3) |
| `INVALID_RESPONSE_TIMING` | Response | Response timing issue |
| `DATA_WIDTH_VIOLATION` | Data | Data exceeds configured width |
| `STROBE_VIOLATION` | Data | Invalid write strobe pattern |
| `STROBE_DATA_CONSISTENCY` | Data | Strobe/data consistency issue |
| `CONCURRENT_TRANSACTIONS` | Protocol | Simultaneous read and write (not allowed) |
| `BURST_ATTEMPT` | Protocol | Burst transaction attempted (single transfer only) |
| `RESET_VIOLATION` | Timing | Signals not properly reset |
| `CLOCK_VIOLATION` | Timing | Clock domain issue |
| `PROT_FIELD_VIOLATION` | PROT | Invalid PROT value (>7) |

### AXIL4Violation

```python
@dataclass
class AXIL4Violation:
    violation_type: AXIL4ViolationType
    channel: str
    cycle: int
    message: str
    severity: str = 'ERROR'
    additional_data: Dict[str, Any] = field(default_factory=dict)
```

Represents a single protocol violation with its type, channel, cycle number, descriptive message, severity level, and optional additional context.

---

## Class

### AXIL4ComplianceChecker

```python
class AXIL4ComplianceChecker:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix (e.g., `"m_axil_"`) | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `data_width` | `int` | Data bus width in bits | `32` |
| `addr_width` | `int` | Address bus width in bits | `32` |
| `user_width` | `int` | User signal width (usually 0 for AXIL4) | `0` |
| `multi_sig` | `bool` | Whether DUT uses individual signal mode | `True` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `violations` | `List[AXIL4Violation]` | All recorded violations |
| `violation_counts` | `Dict[AXIL4ViolationType, int]` | Count per violation type |
| `cycle_count` | `int` | Current simulation cycle |
| `stats` | `Dict[str, Any]` | Transaction and check statistics |
| `monitors` | `Dict[str, GAXIMonitor]` | Per-channel monitor instances |
| `enabled` | `bool` | Whether the checker is active |
| `outstanding_read` | `AXIL4Packet` or `None` | Currently outstanding read transaction |
| `outstanding_write` | `AXIL4Packet` or `None` | Currently outstanding write transaction |

---

## Class Methods

### `AXIL4ComplianceChecker.create_if_enabled(dut, clock, prefix="", log=None, **kwargs) -> Optional[AXIL4ComplianceChecker]`

Factory method that returns `None` when compliance checking is disabled.

**Returns:** `AXIL4ComplianceChecker` instance if compliance checking is enabled, otherwise `None`.

The checker is enabled when either `AXIL4_COMPLIANCE_CHECK=1` or `AXI4_COMPLIANCE_CHECK=1` is set in the environment.

```python
self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
    dut=dut, clock=clock, prefix="m_axil_", log=self.log,
    data_width=32, addr_width=32
)
```

### `AXIL4ComplianceChecker.is_enabled() -> bool`

Check if compliance checking is enabled via the `AXIL4_COMPLIANCE_CHECK` or `AXI4_COMPLIANCE_CHECK` environment variables.

---

## Instance Methods

### `setup_monitors()`

Set up `GAXIMonitor` instances for all AXIL4 channels that have valid/ready signals present on the DUT. Called automatically during initialization.

### `check_address_alignment(addr) -> bool`

Check if an address is properly aligned for the configured data width.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `addr` | `int` | Address to validate |

**Returns:** `True` if aligned, `False` otherwise.

### `check_write_strobes(strb, data) -> bool`

Check write strobe validity: must not exceed data width byte count, and must not be zero.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `strb` | `int` | Write strobe pattern |
| `data` | `int` | Write data value |

**Returns:** `True` if valid, `False` otherwise.

### `record_violation(violation_type, channel, message, **kwargs)`

Record a protocol violation.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `violation_type` | `AXIL4ViolationType` | Type of violation | (required) |
| `channel` | `str` | Channel name (`'AR'`, `'AW'`, `'W'`, `'R'`, `'B'`, `'SYSTEM'`) | (required) |
| `message` | `str` | Human-readable violation description | (required) |
| `severity` | `str` | Severity level | `'ERROR'` |
| `additional_data` | `dict` | Extra context data | `{}` |

### `get_compliance_report() -> Dict[str, Any]`

Get a comprehensive compliance report.

**Returns:** Dictionary with the following keys:

| Key | Type | Description |
|-----|------|-------------|
| `protocol` | `str` | Always `'AXIL4'` |
| `compliance_checking` | `str` | `'enabled'` or `'disabled'` |
| `total_violations` | `int` | Total number of violations recorded |
| `violation_summary` | `Dict[str, int]` | Count per violation type (non-zero only) |
| `statistics` | `Dict[str, Any]` | Transaction, check, and AXIL4-specific statistics |
| `violations` | `List[Dict]` | Last 10 violations with details |
| `compliance_status` | `str` | `'PASSED'` or `'FAILED'` |

**Statistics dictionary keys:**

| Key | Type | Description |
|-----|------|-------------|
| `total_ar_transactions` | `int` | Number of AR transactions observed |
| `total_aw_transactions` | `int` | Number of AW transactions observed |
| `total_w_transactions` | `int` | Number of W transactions observed |
| `total_r_responses` | `int` | Number of R responses observed |
| `total_b_responses` | `int` | Number of B responses observed |
| `total_violations` | `int` | Total violations |
| `checks_performed` | `int` | Total checks performed |
| `address_alignment_checks` | `int` | Number of alignment checks |
| `strobe_checks` | `int` | Number of strobe checks |

### `print_compliance_report()`

Print a formatted compliance report to the logger, including AXIL4-specific check counts.

---

## Decorator

### `add_axil4_compliance_checking(testbench_class)`

Class decorator that adds automatic AXIL4 compliance checking to an existing testbench class.

```python
@add_axil4_compliance_checking
class MyAXIL4Testbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)
        # Compliance checker automatically added as self.axil4_compliance_checker
```

---

## Usage Examples

### Conditional Integration in Testbench

```python
from CocoTBFramework.components.axil4.axil4_compliance_checker import AXIL4ComplianceChecker

class MyTestbench:
    def __init__(self, dut, clock):
        self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
            dut=dut,
            clock=clock,
            prefix="s_axil_",
            log=self.log,
            data_width=32,
            addr_width=32
        )

    def finalize_test(self):
        if self.compliance_checker:
            self.compliance_checker.print_compliance_report()
```

### Running Tests with Compliance Checking

```bash
# Normal test run (compliance checking disabled)
make test

# Enable AXIL4 compliance checking
AXIL4_COMPLIANCE_CHECK=1 make test

# Enable for both AXI4 and AXIL4 components
AXI4_COMPLIANCE_CHECK=1 make test
```

### Inspecting the Compliance Report

```python
if self.compliance_checker:
    report = self.compliance_checker.get_compliance_report()

    print(f"Protocol: {report['protocol']}")
    print(f"Status: {report['compliance_status']}")
    print(f"Total violations: {report['total_violations']}")
    print(f"AR transactions: {report['statistics']['total_ar_transactions']}")
    print(f"Address alignment checks: {report['statistics']['address_alignment_checks']}")
    print(f"Write strobe checks: {report['statistics']['strobe_checks']}")

    if report['violation_summary']:
        print("Violations:")
        for vtype, count in report['violation_summary'].items():
            print(f"  {vtype}: {count}")

    for v in report['violations']:
        print(f"  [{v['channel']}] cycle {v['cycle']}: {v['message']}")
```
