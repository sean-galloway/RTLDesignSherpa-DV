# AXIL4 Compliance Checker

A passive protocol checker for AXIL4 (AXI4-Lite) that watches all five channels and flags handshake violations, misaligned addresses, bad write strobes, and out-of-range response codes. It attaches to an existing testbench with no code changes -- you enable it with an environment variable and read the report at the end of the run.

## Overview

The `AXIL4ComplianceChecker` gives you:

- **Environment-controlled activation** via `AXIL4_COMPLIANCE_CHECK=1` or `AXI4_COMPLIANCE_CHECK=1` -- flip it on for a run, no testbench edits required
- **Automatic monitoring** of all five AXIL4 channels (AR, AW, W, R, B)
- **Handshake validation** -- VALID must hold until the transfer completes; dropping VALID *after* a completed handshake is legal and is not flagged
- **Payload stability checking** -- address and data must not move while VALID is asserted and the transfer hasn't been accepted; legal back-to-back transfers with VALID held high are not flagged either
- **Address alignment validation** against the data width boundary
- **Write strobe validation** -- must be in range and non-zero
- **Response code validation** (0-3)
- **PROT field validation** (must fit in 3 bits)
- **Outstanding-depth statistics** (`max_outstanding_reads` / `max_outstanding_writes`)
- **Violation reports** with per-cycle timestamps

Because Lite drops most of what full AXI4 carries, this checker has much less to do than the AXI4 one:

- No burst checking -- every transaction is a single beat
- No ID tracking or ordering checks
- Simpler transaction-flow validation
- Checks tuned for register-access patterns

> **A note on concurrency:** driving reads and writes at the same time (ARVALID alongside
> AWVALID/WVALID) is **legal** in AXI4-Lite -- the read and write channels are
> independent -- and the protocol permits multiple outstanding transactions.
> The checker therefore does no cross-channel concurrency check and reports
> outstanding depth as an informational statistic only. The `CONCURRENT_TRANSACTIONS`
> violation type still exists for API compatibility but is never emitted.

**How it's wired:** the packet-level checks (address alignment, PROT, strobe, response
codes) are fed by the `GAXIMonitorBase.get_completed_packets()` drain API. `setup_monitors()`
calls `enable_completed_packet_tracking()` on each channel monitor, and the
`monitor_transactions()` coroutine drains each monitor every clock cycle and runs the
`validate_*` checks on every packet it sees. The drain queue is separate from the
cocotb `_recvQ`, so the usual `monitor._recvQ.popleft()` verification pattern keeps
working. The signal-level checks (VALID_DROPPED, DATA_UNSTABLE) run live against
DUT signals in the `monitor_handshakes()` coroutine.

---

## Supporting Types

### AXIL4ViolationType

```python
class AXIL4ViolationType(Enum)
```

Every violation type the checker knows about.

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
| `CONCURRENT_TRANSACTIONS` | Protocol | Retained for API compatibility; no longer emitted (concurrent read/write is legal in AXI4-Lite) |
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

One recorded violation: the type, the channel, the cycle it happened on, a message, and a severity (`'ERROR'` unless you say otherwise). `additional_data` carries whatever extra context helps you find the bug.

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
| `outstanding_reads` | `int` | Current outstanding read depth (informational) |
| `outstanding_writes` | `int` | Current outstanding write depth (informational) |

---

## Class Methods

### `AXIL4ComplianceChecker.create_if_enabled(dut, clock, prefix="", log=None, **kwargs) -> Optional[AXIL4ComplianceChecker]`

The intended way to instantiate the checker. Returns a live instance when the environment asks for one, `None` otherwise -- so the rest of the testbench can just guard with `if self.compliance_checker:`.

**Returns:** `AXIL4ComplianceChecker` instance if compliance checking is enabled, otherwise `None`.

Either `AXIL4_COMPLIANCE_CHECK=1` or `AXI4_COMPLIANCE_CHECK=1` in the environment turns it on.

```python
self.compliance_checker = AXIL4ComplianceChecker.create_if_enabled(
    dut=dut, clock=clock, prefix="m_axil_", log=self.log,
    data_width=32, addr_width=32
)
```

### `AXIL4ComplianceChecker.is_enabled() -> bool`

Reports whether compliance checking is enabled -- i.e., whether `AXIL4_COMPLIANCE_CHECK` or `AXI4_COMPLIANCE_CHECK` is set in the environment.

---

## Instance Methods

### `setup_monitors()`

Creates a `GAXIMonitor` for every AXIL4 channel whose valid/ready signals are present on the DUT. You don't call this yourself -- the constructor does.

### `check_address_alignment(addr) -> bool`

Returns whether an address is properly aligned for the configured data width.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `addr` | `int` | Address to validate |

**Returns:** `True` if aligned, `False` otherwise.

### `check_write_strobes(strb, data) -> bool`

A strobe is valid if it fits in the byte count implied by the data width and isn't zero.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `strb` | `int` | Write strobe pattern |
| `data` | `int` | Write data value |

**Returns:** `True` if valid, `False` otherwise.

### `record_violation(violation_type, channel, message, **kwargs)`

Adds a violation to the record. The built-in checks call this; call it from your own checks too if you add any.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `violation_type` | `AXIL4ViolationType` | Type of violation | (required) |
| `channel` | `str` | Channel name (`'AR'`, `'AW'`, `'W'`, `'R'`, `'B'`, `'SYSTEM'`) | (required) |
| `message` | `str` | Human-readable violation description | (required) |
| `severity` | `str` | Severity level | `'ERROR'` |
| `additional_data` | `dict` | Extra context data | `{}` |

### `get_compliance_report() -> Dict[str, Any]`

Returns the full compliance report as a dictionary.

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

Logs a formatted compliance report, including the AXIL4-specific check counts.

---

## Decorator

### `add_axil4_compliance_checking(testbench_class)`

Class decorator that bolts compliance checking onto an existing testbench class. The checker shows up as `self.axil4_compliance_checker`:

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

The pattern that makes the environment-variable switch work: always go through `create_if_enabled`, and guard every use of the result.

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

Nothing to rebuild -- same testbench, different environment:

```bash
# Normal test run (compliance checking disabled)
make test

# Enable AXIL4 compliance checking
AXIL4_COMPLIANCE_CHECK=1 make test

# Enable for both AXI4 and AXIL4 components
AXI4_COMPLIANCE_CHECK=1 make test
```

### Inspecting the Compliance Report

The report is plain data, so pull out whatever you need:

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

---
