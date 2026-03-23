# AXI5ComplianceChecker

The `AXI5ComplianceChecker` provides non-intrusive AXI5 protocol compliance checking that can be optionally enabled in existing testbenches without requiring code changes. It monitors all five AXI5 channels and validates transactions against AXI5 protocol rules, with dedicated checks for AXI5-specific features.

## Key Differences from AXI4 Compliance Checking

- **Atomic operation validation**: ATOP encoding, single-beat requirement, response matching
- **Memory Tagging Extension checks**: TAGOP encoding, TAGUPDATE/TAGMATCH consistency
- **Security context validation**: NSAID, MPAM, MECID field rules
- **Chunked transfer validation**: CHUNKEN/CHUNKV consistency, data width requirements
- **Poison propagation tracking**: POISON indicator monitoring and statistics
- **Trace consistency**: TRACE signal matching between request and response channels

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

### `create_if_enabled(dut, clock, prefix, log, **kwargs) -> Optional[AXI5ComplianceChecker]`

Factory method that returns `None` if compliance checking is disabled. Enable via the `AXI5_COMPLIANCE_CHECK` environment variable.

```bash
export AXI5_COMPLIANCE_CHECK=1
```

### `is_enabled() -> bool`

Static method that checks if compliance checking is enabled via the `AXI5_COMPLIANCE_CHECK` environment variable.

## Instance Methods

### `setup_monitors()`

Set up signal monitors for all AXI5 channels. Called automatically during initialization. Creates `GAXIMonitor` instances for each channel (AR, AW, W, R, B) that has valid/ready signals present on the DUT.

### `get_compliance_report() -> Dict[str, Any]`

Get a comprehensive compliance report.

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

Print a formatted compliance report to the logger.

### `record_violation(violation_type, channel, message, **kwargs)`

Record a protocol violation.

| Parameter | Type | Description |
|-----------|------|-------------|
| `violation_type` | AXI5ViolationType | Type of violation |
| `channel` | str | Channel where violation occurred (`'AR'`, `'AW'`, `'W'`, `'R'`, `'B'`) |
| `message` | str | Human-readable description |
| `severity` | str | `'ERROR'`, `'WARNING'`, or `'INFO'` (default `'ERROR'`) |

## Violation Types

### Standard AXI Violations

| Violation | Description |
|-----------|-------------|
| `VALID_DROPPED` | VALID signal dropped before handshake |
| `READY_BEFORE_VALID` | READY asserted before VALID |
| `VALID_UNSTABLE` | VALID signal unstable during handshake |
| `BURST_LENGTH_VIOLATION` | Burst length exceeds 256 |
| `BURST_SIZE_VIOLATION` | Burst size exceeds 7 |
| `BURST_BOUNDARY_VIOLATION` | Burst crosses 4KB boundary |
| `WLAST_MISMATCH` | WLAST does not match expected burst count |
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

The compliance checker maintains the following statistics:

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

Class decorator that adds AXI5 compliance checking to existing testbenches without modifying their code.

```python
from CocoTBFramework.components.axi5 import add_axi5_compliance_checking

@add_axi5_compliance_checking
class MyAXI5Testbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)
        # ... existing setup code ...
```

When the `AXI5_COMPLIANCE_CHECK=1` environment variable is set, the decorator automatically:
1. Creates an `AXI5ComplianceChecker` instance after `__init__`
2. Prints the compliance report during `finalize_test()`

## Usage Examples

### Example 1: Manual Integration

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
