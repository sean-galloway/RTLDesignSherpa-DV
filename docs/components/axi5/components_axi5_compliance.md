# AXI5ComplianceChecker

The `AXI5ComplianceChecker` is a passive AXI5 protocol monitor. You don't rebuild your testbench to use it — you enable it (one environment variable), it hooks the channels that actually exist on the DUT, and it spends the rest of the simulation checking every transaction on all five channels against the AXI5 rules, including the rules for the features AXI5 adds over AXI4.

## Key Differences from AXI4 Compliance Checking

Everything the AXI4 checker covers, plus the AXI5-specific rule set:

- **Atomic operation validation**: ATOP encoding, the single-beat requirement, response matching
- **Memory Tagging Extension checks**: TAGOP encoding, TAGUPDATE/TAGMATCH consistency
- **Security context validation**: NSAID, MPAM, and MECID field rules
- **Chunked transfer validation**: CHUNKEN/CHUNKV consistency, data width requirements
- **Poison propagation tracking**: POISON indicator monitoring, with statistics
- **Trace consistency**: TRACE signal matching between request and response channels

Two coroutines do the checking, and they see the bus differently — worth understanding before you wire your own monitors into the same testbench.

The transaction-level checks (ATOP, MTE, chunking, response codes, RLAST matching) run on completed packets pulled from the `GAXIMonitorBase.get_completed_packets()` drain API. `setup_monitors()` calls `enable_completed_packet_tracking()` on each channel monitor, and the `monitor_transactions()` coroutine drains every monitor once per clock and runs the `validate_*` checks on each packet that comes out. The drain queue is separate from the cocotb `_recvQ`, so if your testbench already uses the `monitor._recvQ.popleft()` verification pattern, that keeps working untouched.

The handshake check can't wait for completed packets, so `monitor_handshakes()` watches the DUT signals directly and enforces the VALID/READY rule live (AMBA AXI A3.2.1): once VALID is asserted it must hold until the cycle where READY is also high. A VALID that drops without a completed handshake is reported as `VALID_DROPPED`; a drop after a completed handshake is legal and passes quietly.

Outstanding reads, writes, and atomics are tracked as **per-ID FIFO queues**. AXI5 permits multiple outstanding transactions with the same ID as long as they complete in order, so R beats and CHUNKV checks are matched against the oldest outstanding read for their ID, and each B response retires the oldest outstanding write or atomic for its ID — which is also where the TRACE consistency check happens.

### WLAST validation and the write-data ordering rule

WLAST is fully validated against the beat count declared by the corresponding AW command, using the same mechanism as the AXI4 checker. And as in AXI4, **AXI5 has no `WID` and no write-data interleaving** — interleaving was dropped after AXI3 — so write data bursts must appear on the W channel in exactly the order their AW commands arrived. One strict FIFO across *all* IDs, not one per ID. That trips people up, so the checker is explicit about it.

It keeps a single global queue, `aw_awaiting_w`, of AW commands still awaiting their data phase, in arrival order. Each W beat counts against the head entry, and the head pops when its data phase ends. The entries are the same objects held in the per-ID `outstanding_writes` queues, so beat bookkeeping is shared, not duplicated.

The two queues advance on **different protocol events and never pop each other**:

| Queue | Keyed by | Advanced by | Meaning |
|-------|----------|-------------|---------|
| `aw_awaiting_w` | global arrival order | WLAST | end of the write **data phase** |
| `outstanding_writes` | transaction ID | B response | end of the **transaction** (also TRACE check) |

Three conditions are reported as `WLAST_MISMATCH` on the `W` channel:

| Condition | Description |
|-----------|-------------|
| WLAST early | WLAST asserted before the AW's expected beat count is reached |
| WLAST missing | The final expected beat arrived without WLAST |
| No pending AW | A W beat arrived with no AW command awaiting write data |

When WLAST goes missing, the checker closes the data phase at the expected beat count and resynchronizes to the next AW. One malformed burst, one violation — not one per beat for the rest of the test. POISON statistics are still collected on every W beat, whatever happened with WLAST.

## Class Signature

```python
class AXI5ComplianceChecker:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `dut` | object | Device under test | (required) |
| `clock` | Signal | Clock signal | (required) |
| `prefix` | str | Signal name prefix (e.g., `"m_axi"`) | `""` |
| `log` | Logger | Logger instance | `None` |
| `data_width` | int | Data bus width in bits | `32` |
| `id_width` | int | ID field width in bits | `8` |
| `addr_width` | int | Address bus width in bits | `32` |
| `user_width` | int | User signal width in bits | `1` |
| `nsaid_width` | int | NSAID field width in bits | `4` |
| `mpam_width` | int | MPAM field width in bits | `11` |
| `mecid_width` | int | MECID field width in bits | `16` |
| `tag_width` | int | Single tag width in bits | `4` |
| `multi_sig` | bool | Use individual signals per field | `True` |

## Class Methods

Two ways in, depending on whether you want the environment to make the decision.

### `create_if_enabled(dut, clock, prefix, log, **kwargs) -> Optional[AXI5ComplianceChecker]`

The factory you should actually call. It returns `None` when compliance checking is disabled, so testbench code can hold the result and guard on truthiness. The switch is the `AXI5_COMPLIANCE_CHECK` environment variable:

```bash
export AXI5_COMPLIANCE_CHECK=1
```

### `is_enabled() -> bool`

Static method that reports whether `AXI5_COMPLIANCE_CHECK` is set. Handy when you need to know before you've built anything.

## Instance Methods

### `setup_monitors()`

Builds the signal monitors for all AXI5 channels. Called automatically during initialization. A `GAXIMonitor` is created for each channel (AR, AW, W, R, B) that has valid/ready signals present on the DUT — a partial interface gets partial monitoring.

### `get_compliance_report() -> Dict[str, Any]`

Returns the full compliance report as a dictionary.

**Returns**: Dictionary containing:

| Key | Type | Description |
|-----|------|-------------|
| `compliance_checking` | str | `'enabled'` or `'disabled'` |
| `total_violations` | int | Total number of violations detected |
| `violation_summary` | Dict | Counts per violation type |
| `statistics` | Dict | Transaction and check statistics |
| `axi5_feature_usage` | Dict | Counts of AXI5 feature activations |
| `violations` | List | Last 10 violation details |
| `compliance_status` | str | `'PASSED'` or `'FAILED'` |

### `print_compliance_report()`

Same report, formatted and sent to the logger. The one to call in your finalization path when a human will read the output.

### `record_violation(violation_type, channel, message, **kwargs)`

Records a protocol violation by hand. The checkers call this themselves; you'd call it only if your test enforces protocol rules of its own.

| Parameter | Type | Description |
|-----------|------|-------------|
| `violation_type` | AXI5ViolationType | Type of violation |
| `channel` | str | Channel where violation occurred (`'AR'`, `'AW'`, `'W'`, `'R'`, `'B'`) |
| `message` | str | Human-readable description |
| `severity` | str | `'ERROR'`, `'WARNING'`, or `'INFO'` (default `'ERROR'`) |

## Violation Types

What the checker can raise — first the standard AXI set, then the AXI5 additions.

### Standard AXI Violations

| Violation | Description |
|-----------|-------------|
| `VALID_DROPPED` | VALID signal dropped before handshake |
| `READY_BEFORE_VALID` | READY asserted before VALID |
| `VALID_UNSTABLE` | VALID signal unstable during handshake |
| `BURST_LENGTH_VIOLATION` | Burst length exceeds 256 |
| `BURST_SIZE_VIOLATION` | Burst size exceeds 7 |
| `BURST_BOUNDARY_VIOLATION` | Burst crosses 4KB boundary |
| `WLAST_MISMATCH` | WLAST early, missing on the final beat, or a W beat with no pending AW |
| `RLAST_MISMATCH` | RLAST does not match expected burst count |
| `ID_ORDERING_VIOLATION` | Out-of-order response for same ID |
| `RESPONSE_CODE_VIOLATION` | Invalid response code (> 3) |
| `DATA_STABILITY_VIOLATION` | Data changed while VALID asserted |
| `STROBE_VIOLATION` | Invalid write strobe pattern |

### AXI5-Specific Violations

| Violation | Description |
|-----------|-------------|
| `ATOP_BURST_LENGTH_VIOLATION` | Atomic operation with burst length > 1 |
| `ATOP_ENCODING_VIOLATION` | Invalid ATOP encoding |
| `ATOP_RESPONSE_VIOLATION` | Unexpected response for atomic operation |
| `TAGOP_ENCODING_VIOLATION` | TAGOP value out of range (must be 0-3) |
| `TAG_WIDTH_VIOLATION` | Tag width mismatch |
| `TAGUPDATE_MISMATCH` | TAGUPDATE inconsistent with TAGOP |
| `TAGMATCH_UNEXPECTED` | TAGMATCH set without matching TAGOP |
| `NSAID_VIOLATION` | Invalid NSAID value |
| `MPAM_VIOLATION` | Invalid MPAM value |
| `MECID_VIOLATION` | Invalid MECID value |
| `CHUNK_ENABLE_VIOLATION` | Chunking enabled with data_width < 128, or CHUNKV=1 without CHUNKEN |
| `CHUNKNUM_VIOLATION` | Invalid chunk number |
| `CHUNKSTRB_VIOLATION` | Invalid chunk strobe |
| `POISON_PROPAGATION_VIOLATION` | Poison indicator propagation error |
| `TRACE_CONSISTENCY_VIOLATION` | TRACE mismatch between request and response |

## AXI5Violation Dataclass

```python
@dataclass
class AXI5Violation:
    violation_type: AXI5ViolationType
    channel: str              # 'AR', 'AW', 'W', 'R', 'B'
    cycle: int                # Clock cycle when detected
    message: str              # Human-readable description
    severity: str = 'ERROR'   # 'ERROR', 'WARNING', 'INFO'
    additional_data: Dict[str, Any] = field(default_factory=dict)
```

## Statistics Tracked

Counters the checker maintains while the test runs:

| Statistic | Description |
|-----------|-------------|
| `total_ar_transactions` | Total AR transactions observed |
| `total_aw_transactions` | Total AW transactions observed |
| `total_w_beats` | Total W data beats observed |
| `total_r_beats` | Total R data beats observed |
| `total_b_responses` | Total B responses observed |
| `total_violations` | Total violations recorded |
| `checks_performed` | Total compliance checks executed |
| `atomic_operations` | Atomic operations detected |
| `mte_operations` | Memory tagging operations detected |
| `security_operations` | Security context operations detected |
| `chunked_transfers` | Chunked transfers detected |
| `poisoned_beats` | Data beats with POISON indicator |
| `traced_transactions` | Transactions with TRACE enabled |

## Decorator Integration

### `add_axi5_compliance_checking(testbench_class)`

The zero-touch option: a class decorator that wires compliance checking into an existing testbench without editing its body.

```python
from CocoTBFramework.components.axi5 import add_axi5_compliance_checking

@add_axi5_compliance_checking
class MyAXI5Testbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)
        # ... existing setup code ...
```

With `AXI5_COMPLIANCE_CHECK=1` set, the decorator creates an `AXI5ComplianceChecker` right after your `__init__` finishes and prints the compliance report during `finalize_test()`. With the variable unset it stays out of the way, so the same testbench runs in either mode unchanged.

## Usage Examples

### Example 1: Manual Integration

Build the checker through the factory and assert on the report when the test finishes:

```python
from CocoTBFramework.components.axi5 import AXI5ComplianceChecker

class MyTestbench:
    def __init__(self, dut):
        self.dut = dut
        self.clock = dut.aclk

        # Create compliance checker (returns None if disabled)
        self.compliance = AXI5ComplianceChecker.create_if_enabled(
            dut=self.dut,
            clock=self.clock,
            prefix='m_axi_',
            log=self.log,
            data_width=64,
            id_width=4
        )

    async def finalize(self):
        if self.compliance:
            report = self.compliance.get_compliance_report()
            assert report['compliance_status'] == 'PASSED', \
                f"AXI5 violations: {report['total_violations']}"
```

### Example 2: Environment-Controlled Checking

The usual setup — everything keyed off the environment, so CI decides whether checking runs:

```python
# Enable at runtime:
#   export AXI5_COMPLIANCE_CHECK=1
#   make sim

from CocoTBFramework.components.axi5 import AXI5ComplianceChecker

# In testbench
checker = AXI5ComplianceChecker.create_if_enabled(
    dut=dut, clock=clk, prefix='m_axi_', log=log
)

# Run test normally...

# At end of test, check results
if checker:
    checker.print_compliance_report()
    report = checker.get_compliance_report()

    # Check AXI5 feature coverage
    usage = report['axi5_feature_usage']
    log.info(f"Atomic ops: {usage['atomic_operations']}")
    log.info(f"MTE ops: {usage['mte_operations']}")
    log.info(f"Poisoned beats: {usage['poisoned_beats']}")
```

### Example 3: Decorator-Based Integration

Or skip the plumbing entirely and decorate the testbench class:

```python
from CocoTBFramework.components.axi5 import add_axi5_compliance_checking

@add_axi5_compliance_checking
class AXI5DMATestbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)
        self.aclk = dut.aclk
        # Standard setup -- compliance checker added automatically
        # by the decorator if AXI5_COMPLIANCE_CHECK=1

    async def run_test(self):
        # Run DMA transfer test
        await self.master.write_transaction(0x1000, [0xAA, 0xBB, 0xCC])
        await self.master.read_transaction(0x1000, burst_len=3)

    def finalize_test(self):
        # Compliance report printed automatically by decorator
        pass
```

---
