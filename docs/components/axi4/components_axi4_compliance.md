# AXI4 Compliance Checker

A passive AXI4 protocol checker that watches the bus and flags handshake violations, burst errors, ID ordering problems, and bad response codes. It bolts onto an existing testbench with zero code changes — you turn it on with an environment variable, and when it's off it never gets built.

## Overview

The `AXI4ComplianceChecker` gives you:

- **Environment-controlled activation** via `AXI4_COMPLIANCE_CHECK=1` -- no code changes required
- **Automatic signal monitoring** on all five AXI4 channels (AR, AW, W, R, B)
- **Handshake protocol validation** against the VALID/READY rules
- **Burst constraint checking** -- length, size, and the 4KB boundary
- **Response code validation** on the B and R channels
- **RLAST/WLAST matching** against the beat count the address phase promised
- **ID-based transaction tracking** for read and write ordering
- **Violation reports with per-cycle timestamps**
- **No measurable cost when disabled** -- the factory just returns `None`

Under the hood it's one `GAXIMonitor` per channel, plus a set of background coroutines doing the actual checking.

**Wiring:** the transaction-level checks (burst length/size, RLAST matching, response
codes) are fed by the `GAXIMonitorBase.get_completed_packets()` drain API.
`setup_monitors()` calls `enable_completed_packet_tracking()` on each channel monitor,
and the `monitor_transactions()` coroutine drains each monitor every clock cycle and
runs the `validate_*` checks on every observed packet. The drain queue is separate from
the cocotb `_recvQ`, so the documented `monitor._recvQ.popleft()` verification pattern
keeps working untouched.

The `monitor_handshakes()` coroutine checks the VALID/READY rule live on the DUT pins:
once VALID is asserted it must hold until the cycle where READY is also high
(AMBA AXI A3.2.1). A VALID that drops without a completed handshake is reported as
`VALID_DROPPED`; dropping after a completed handshake is legal and passes quietly.

Outstanding reads and writes are tracked as **per-ID FIFO queues**. AXI4 allows
multiple outstanding transactions on the same ID — they complete in order — so R beats
are matched against the oldest outstanding read for their ID, and each B response
retires the oldest outstanding write for its ID.

### WLAST validation and the write-data ordering rule

WLAST is checked against the beat count declared by the corresponding AW command. The
association between W beats and AW commands works because of something AXI4 took away:
**write data interleaving.** There is no `WID` signal (that was an AXI3 feature), so
write data bursts must appear on the W channel in exactly the order their AW commands
were issued -- a single strict FIFO across *all* IDs, not one per ID.

The checker therefore keeps one global queue, `aw_awaiting_w`, of AW commands waiting
for their data phase, in arrival order. Each W beat is counted against the head entry,
and the head pops when the data phase ends. The entries are the same objects held in
the per-ID `outstanding_writes` queues, so the beat bookkeeping is shared rather than
duplicated.

The two queues advance on **different protocol events and never pop each other**:

| Queue | Keyed by | Advanced by | Meaning |
|-------|----------|-------------|---------|
| `aw_awaiting_w` | global arrival order | WLAST | end of the write **data phase** |
| `outstanding_writes` | transaction ID | B response | end of the **transaction** |

Three conditions are reported as `WLAST_MISMATCH` on the `W` channel:

| Condition | Description |
|-----------|-------------|
| WLAST early | WLAST asserted before the AW's expected beat count is reached |
| WLAST missing | The final expected beat arrived without WLAST |
| No pending AW | A W beat arrived with no AW command awaiting write data |

When WLAST goes missing, the checker ends the data phase at the expected beat count
and resynchronizes on the next AW. That's deliberate: one malformed burst should
produce one violation, not a cascade of follow-on errors that buries the real one.

---

## Supporting Types

### AXI4ViolationType

```python
class AXI4ViolationType(Enum)
```

Every violation type the checker can raise.

| Value | Category | Description |
|-------|----------|-------------|
| `VALID_DROPPED` | Handshake | VALID deasserted before READY handshake |
| `READY_BEFORE_VALID` | Handshake | READY asserted before VALID (informational) |
| `VALID_UNSTABLE` | Handshake | VALID signal changed unexpectedly |
| `BURST_LENGTH_VIOLATION` | Burst | Burst length exceeds 256 |
| `BURST_SIZE_VIOLATION` | Burst | Burst size exceeds maximum (7) |
| `BURST_BOUNDARY_VIOLATION` | Burst | Burst crosses 4KB boundary |
| `WLAST_MISMATCH` | Burst | WLAST early, missing on the final beat, or a W beat with no pending AW |
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

One recorded violation: type, channel, cycle number, message, severity, plus an optional dict of extra context.

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

Factory method, and the recommended way in. It returns a live checker when the environment asks for one and `None` otherwise, so the same testbench code runs clean either way — just guard any use of the result with a truthiness check.

**Returns:** `AXI4ComplianceChecker` instance if `AXI4_COMPLIANCE_CHECK=1` is set, otherwise `None`.

```python
self.compliance_checker = AXI4ComplianceChecker.create_if_enabled(
    dut=dut, clock=clock, prefix="m_axi_", log=self.log,
    data_width=32, id_width=4
)
```

### `AXI4ComplianceChecker.is_enabled() -> bool`

Returns whether compliance checking is enabled, per the `AXI4_COMPLIANCE_CHECK` environment variable.

---

## Instance Methods

### `setup_monitors()`

Creates `GAXIMonitor` instances for every AXI4 channel that has valid/ready signals present on the DUT. Called automatically during initialization — you shouldn't need to call it yourself.

### `record_violation(violation_type, channel, message, **kwargs)`

Record a protocol violation by hand. Useful when your test has its own protocol expectations on top of the built-in ones.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `violation_type` | `AXI4ViolationType` | Type of violation | (required) |
| `channel` | `str` | Channel name (`'AR'`, `'AW'`, `'W'`, `'R'`, `'B'`) | (required) |
| `message` | `str` | Human-readable violation description | (required) |
| `severity` | `str` | Severity level (`'ERROR'`, `'WARNING'`, `'INFO'`) | `'ERROR'` |
| `additional_data` | `dict` | Extra context data | `{}` |

### `get_compliance_report() -> Dict[str, Any]`

The full compliance report as a dictionary.

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

Formats the report and writes it to the logger.

---

## Decorator

### `add_axi4_compliance_checking(testbench_class)`

Class decorator that wires compliance checking into an existing testbench class. It wraps `__init__` to create the checker and `finalize_test` to print the report.

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
