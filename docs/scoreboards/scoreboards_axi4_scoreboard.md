<!-- RTL Design Sherpa Documentation Header -->
<table>
<tr>
<td width="80">
  <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">
    <img src="https://raw.githubusercontent.com/sean-galloway/RTLDesignSherpa/main/docs/logos/Logo_200px.png" alt="RTL Design Sherpa" width="70">
  </a>
</td>
<td>
  <strong>CocoTB Framework</strong> · <em>Verification Infrastructure for RTL Testing</em><br>
  <sub>
    <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">GitHub</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/docs/DOCUMENTATION_INDEX.md">Documentation Index</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/LICENSE">MIT License</a>
  </sub>
</td>
</tr>
</table>

---

<!-- End Header -->

# axi4_scoreboard.py

AXI4 is where simple expected/actual queue matching runs out of road: multiple IDs, out-of-order completion, five channels. Transactions finish in whatever order the interconnect feels like. This scoreboard tracks each one by ID on both sides of the interface and pairs the master-side half with the slave-side half when both have arrived.

## Overview

- **ID-based Transaction Tracking**: a separate queue per AXI4 ID
- **Channel Separation**: reads and writes tracked independently
- **Master/Slave Monitoring**: both sides report; comparison fires when the two halves meet
- **Protocol Compliance**: AXI4 rule checking built in
- **Performance Analysis**: transaction counts, timing, and throughput data

## Classes

### AXI4Scoreboard

Full-protocol AXI4 verification.

```python
class AXI4Scoreboard(BaseScoreboard):
    def __init__(self, name, id_width=8, addr_width=32, data_width=32, user_width=1, log=None)
```

**Parameters:**
- `name`: scoreboard name; appears in reports
- `id_width`: width of ID fields in bits (default: 8)—size this for your system's ID space
- `addr_width`: width of address fields in bits (default: 32)
- `data_width`: width of data fields in bits (default: 32)
- `user_width`: width of user fields in bits (default: 1)
- `log`: logger for the detail

**Key Attributes:**
- `write_count`: writes processed
- `read_count`: reads processed
- `protocol_error_count`: protocol violations caught
- `master_writes`: master-side writes, keyed by ID
- `slave_writes`: slave-side writes, keyed by ID
- `master_reads`: master-side reads, keyed by ID
- `slave_reads`: slave-side reads, keyed by ID

## Monitor Integration

The scoreboard speaks two callback dialects and uses whichever the monitor offers:

1. **Custom monitors** exposing `set_write_callback(cb)` / `set_read_callback(cb)`.
   Callbacks are invoked with `(id_value, transaction)`. When a monitor provides
   both methods, they are preferred.
2. **Framework monitors** (`GAXIMonitor`, any `cocotb_bus` `Monitor`/`BusMonitor`
   subclass) exposing `add_callback(cb)`. Callbacks are invoked with
   `(transaction,)`; the scoreboard classifies each transaction as a read or a
   write from its composite keys (`aw_transaction`/`w_transactions`/
   `b_transaction` vs `ar_transaction`/`r_transactions`) and extracts the AXI4
   ID automatically (from an `id` key, or from the AW/B or AR/R packets).

A monitor offering neither raises `ValueError` when you connect it. A transaction that can't be classified as read or write gets logged and ignored.

### Transaction format

Transactions arrive as composite dictionaries—one per AXI4 transaction, holding the channel packets:

```python
write_tx = {
    'aw_transaction': aw_packet,      # AW channel packet
    'w_transactions': [w_packet, ...],  # W channel packets (one per beat)
    'b_transaction': b_packet,        # B channel packet
}
read_tx = {
    'ar_transaction': ar_packet,
    'r_transactions': [r_packet, ...],
}
```

Channel packets may use **either** naming dialect: AXI-prefixed (`awaddr`, `awlen`,
`wdata`, `bresp`, `rdata`, ...) **or** the framework's generic names
(`addr`, `len`, `data`, `resp`, ...). Field access tries both, so the master and
slave sides don't even have to agree on naming. Packets can be objects
(attribute access) or dictionaries (key access)—both work.

### Master Monitor Connection

#### `add_master_monitor(monitor)`
Hook up the monitor watching the master interface.

**Parameters:**
- `monitor`: monitor instance observing the master interface

**Behavior:**
- Registers write/read handlers via `set_write_callback`/`set_read_callback`
  when available, otherwise via `add_callback`
- From then on, master-side transactions flow in automatically

```python
# Connect master monitor
axi4_scoreboard.add_master_monitor(master_monitor)

# Monitor automatically feeds transactions to scoreboard
```

### Slave Monitor Connection

#### `add_slave_monitor(monitor)`
Same deal on the slave side.

**Parameters:**
- `monitor`: monitor instance observing the slave interface

**Behavior:**
- Registers write/read handlers via `set_write_callback`/`set_read_callback`
  when available, otherwise via `add_callback`
- From then on, slave-side transactions flow in automatically

```python
# Connect slave monitor
axi4_scoreboard.add_slave_monitor(slave_monitor)

# Complete master-slave verification setup
```

## Transaction Processing

### Write Transaction Handling

#### `_handle_master_write(id_value, transaction)`
A completed write showed up on the master side.

**Parameters:**
- `id_value`: AXI4 ID of the transaction
- `transaction`: the completed write

**Behavior:**
- Filed under `master_writes[id_value]`
- If the slave-side half is already waiting, comparison runs
- Write counters updated

#### `_handle_slave_write(id_value, transaction)`
A completed write showed up on the slave side.

**Parameters:**
- `id_value`: AXI4 ID of the transaction
- `transaction`: the completed write

**Behavior:**
- Filed under `slave_writes[id_value]`
- If the master-side half is already waiting, comparison runs
- Write response compliance validated

### Read Transaction Handling

#### `_handle_master_read(id_value, transaction)`
A completed read showed up on the master side.

**Parameters:**
- `id_value`: AXI4 ID of the transaction
- `transaction`: the completed read

**Behavior:**
- Filed under `master_reads[id_value]`
- If the slave-side half is already waiting, comparison runs
- Read counters updated

#### `_handle_slave_read(id_value, transaction)`
A completed read showed up on the slave side.

**Parameters:**
- `id_value`: AXI4 ID of the transaction
- `transaction`: the completed read

**Behavior:**
- Filed under `slave_reads[id_value]`
- If the master-side half is already waiting, comparison runs
- Read data and response codes validated

## Transaction Verification

### Write Transaction Matching

#### `_check_write_match(id_value, master_transaction, slave_transaction)`
What has to agree before a write counts as matched.

**Parameters:**
- `id_value`: transaction ID
- `master_transaction`: master-side write
- `slave_transaction`: slave-side write

**Verification Checks:**
- Address field consistency (`awaddr`/`addr`)
- Burst parameters (`awlen`/`len`, `awsize`/`size`, `awburst`/`burst`)
- Data payload, beat by beat (`wdata`/`data`)
- Response code (`bresp`/`resp`)
- A field present on only one side is reported as a mismatch; a field absent
  on both sides is skipped

```python
# Example write verification
# Master: AWADDR=0x1000, WDATA=[0xDEADBEEF, 0x12345678], WSTRB=[0xF, 0xF]
# Slave:  AWADDR=0x1000, WDATA=[0xDEADBEEF, 0x12345678], BRESP=OKAY
# Result: MATCH - addresses align, data matches, response is OKAY
```

### Read Transaction Matching

#### `_check_read_match(id_value, master_transaction, slave_transaction)`
Same idea for reads.

**Parameters:**
- `id_value`: transaction ID
- `master_transaction`: master-side read
- `slave_transaction`: slave-side read

**Verification Checks:**
- Address field consistency (`araddr`/`addr`)
- Burst parameters (`arlen`/`len`, `arsize`/`size`, `arburst`/`burst`)
- Read data, beat by beat (`rdata`/`data`)
- A field present on only one side is reported as a mismatch; a field absent
  on both sides is skipped

```python
# Example read verification
# Master: ARADDR=0x2000, ARLEN=3, ARID=5
# Slave:  ARADDR=0x2000, RDATA=[0x11, 0x22, 0x33, 0x44], RID=5, RRESP=OKAY
# Result: MATCH - address correct, data length matches, ID preserved
```

## Protocol Compliance Checking

### Built-in Validation

Checked automatically on every transaction:
- **ID Consistency**: response IDs match request IDs
- **Burst Alignment**: address alignment fits the burst size
- **Response Codes**: RESP values are legal (OKAY, EXOKAY, SLVERR, DECERR)
- **Outstanding Limits**: configurable caps on outstanding transactions per ID
- **Ordering Requirements**: the AXI4 ordering model

### Protocol Error Detection

Violations are logged as they happen:

```python
# Protocol errors automatically logged:
# - Mismatched transaction IDs
# - Invalid burst parameters
# - Out-of-order responses
# - Response timeout violations
# - Invalid response codes

if axi4_scoreboard.protocol_error_count > 0:
    print(f"Protocol violations detected: {axi4_scoreboard.protocol_error_count}")
```

## Performance Analysis

### Transaction Statistics

Tracked for you:
- **Transaction Counts**: read and write totals
- **ID Utilization**: how traffic spread across the ID space
- **Channel Efficiency**: bandwidth utilization analysis
- **Latency Metrics**: average response times by transaction type

### Performance Reporting

```python
# Access performance statistics
stats = {
    'total_transactions': axi4_scoreboard.transaction_count,
    'write_transactions': axi4_scoreboard.write_count,
    'read_transactions': axi4_scoreboard.read_count,
    'protocol_errors': axi4_scoreboard.protocol_error_count,
    'id_utilization': len(axi4_scoreboard.master_writes) + len(axi4_scoreboard.master_reads)
}

print(f"AXI4 Performance: {stats['total_transactions']} transactions")
print(f"Read/Write Ratio: {stats['read_transactions']}/{stats['write_transactions']}")
print(f"Protocol Compliance: {stats['protocol_errors']} violations")
```

## Usage Examples

### Basic AXI4 Verification Setup

The standard wiring: one monitor per side, then let transactions accumulate.

```python
from CocoTBFramework.scoreboards.axi4_scoreboard import AXI4Scoreboard

# NOTE: the framework does not ship an `AXI4Monitor` class. The monitors
# below are illustrative — any framework monitor with `add_callback()`
# (GAXIMonitor, cocotb_bus BusMonitor) or any custom object implementing
# `set_write_callback()` / `set_read_callback()` (called with
# `(id_value, transaction)`) can be connected via `add_master_monitor()` /
# `add_slave_monitor()`.

# Create scoreboard for 64-bit AXI4 with 4-bit IDs
scoreboard = AXI4Scoreboard(
    name="AXI4_Memory",
    id_width=4,
    addr_width=64,
    data_width=64,
    user_width=4,
    log=logger
)

# Create and connect monitors
master_monitor = AXI4Monitor(dut.master_axi, "Master", clock)
slave_monitor = AXI4Monitor(dut.slave_axi, "Slave", clock)

scoreboard.add_master_monitor(master_monitor)
scoreboard.add_slave_monitor(slave_monitor)

# Scoreboard automatically captures and verifies transactions
await Timer(1000, units='ns')  # Run test

# Generate verification report
error_count = scoreboard.report()
success_rate = scoreboard.result()
print(f"AXI4 Verification: {'PASS' if error_count == 0 else 'FAIL'} ({success_rate:.2%})")
```

### Advanced Multi-ID Verification

Sixteen IDs in flight at once—exactly the case per-ID tracking exists for.

```python
# Test with multiple outstanding transactions
async def test_multi_id_axi4():
    # Configure for high-performance testing
    scoreboard = AXI4Scoreboard(
        name="HighPerf_AXI4",
        id_width=8,  # 256 possible IDs
        addr_width=32,
        data_width=128,  # Wide data bus
        log=logger
    )
    
    # Connect monitors
    scoreboard.add_master_monitor(master_monitor)
    scoreboard.add_slave_monitor(slave_monitor)
    
    # Generate transactions with different IDs
    master = AXI4Master(dut.master_axi, clock)
    
    # Launch multiple concurrent transactions
    for i in range(16):
        write_transaction = master.create_write_transaction(
            addr=0x10000 + (i * 0x1000),
            data=[0xDEADBEEF + i],
            id=i,
            burst_len=4
        )
        await master.send_write(write_transaction)
    
    # Wait for completion and verify
    await Timer(5000, units='ns')
    
    # Analyze results by ID
    print(f"Write transactions: {scoreboard.write_count}")
    print(f"Active IDs: {len(scoreboard.master_writes)}")
    print(f"Protocol errors: {scoreboard.protocol_error_count}")
```

### Memory System Verification

A memory controller exercised with sequential, random, and burst traffic, checking protocol health between patterns.

```python
# Verify AXI4 memory controller
async def test_memory_controller():
    scoreboard = AXI4Scoreboard("MemCtrl", log=logger)
    
    # Connect to memory controller interfaces
    cpu_monitor = AXI4Monitor(dut.cpu_axi, "CPU", clock)
    ddr_monitor = AXI4Monitor(dut.ddr_axi, "DDR", clock)
    
    scoreboard.add_master_monitor(cpu_monitor)
    scoreboard.add_slave_monitor(ddr_monitor)
    
    # Generate realistic memory access patterns
    cpu_master = AXI4Master(dut.cpu_axi, clock)
    
    # Test different access patterns
    patterns = [
        # Sequential reads
        [(0x0000 + i*8, 'READ') for i in range(64)],
        # Random writes  
        [(random.randint(0x1000, 0x2000) & ~7, 'WRITE') for _ in range(32)],
        # Burst transfers
        [(0x3000 + i*64, 'BURST_READ', 8) for i in range(8)]
    ]
    
    for pattern in patterns:
        for access in pattern:
            if access[1] == 'READ':
                await cpu_master.read(access[0], id=random.randint(0, 15))
            elif access[1] == 'WRITE':
                await cpu_master.write(access[0], random.randint(0, 0xFFFFFFFF), id=random.randint(0, 15))
            elif access[1] == 'BURST_READ':
                await cpu_master.burst_read(access[0], access[2], id=random.randint(0, 15))
        
        # Check intermediate results
        if scoreboard.protocol_error_count > 0:
            print(f"Protocol errors after pattern: {scoreboard.protocol_error_count}")
            break
    
    # Final verification
    final_errors = scoreboard.report()
    print(f"Memory controller verification: {final_errors} errors")
```

### Cross-Clock Domain Verification

Clock crossings add latency the scoreboard can't see through; this pattern tracks transactions across the boundary and compares with CDC delay in mind.

```python
# Verify AXI4 clock domain crossing
async def test_clock_domain_crossing():
    # Separate scoreboards for each clock domain
    fast_scoreboard = AXI4Scoreboard("FastDomain", log=logger)
    slow_scoreboard = AXI4Scoreboard("SlowDomain", log=logger)
    
    # Connect monitors on both sides of CDC
    fast_monitor = AXI4Monitor(dut.fast_axi, "Fast", fast_clock)
    slow_monitor = AXI4Monitor(dut.slow_axi, "Slow", slow_clock)
    
    fast_scoreboard.add_master_monitor(fast_monitor)
    slow_scoreboard.add_slave_monitor(slow_monitor)
    
    # Create cross-domain transaction tracker
    class CDCTracker:
        def __init__(self):
            self.fast_transactions = {}
            self.slow_transactions = {}
        
        def on_fast_transaction(self, id_val, transaction):
            self.fast_transactions[id_val] = transaction
            self.check_matching()
        
        def on_slow_transaction(self, id_val, transaction):
            self.slow_transactions[id_val] = transaction
            self.check_matching()
        
        def check_matching(self):
            # Verify transactions cross domains correctly
            for id_val in self.fast_transactions:
                if id_val in self.slow_transactions:
                    fast_tx = self.fast_transactions[id_val]
                    slow_tx = self.slow_transactions[id_val]
                    # Compare transactions accounting for CDC latency
                    if not self.compare_cdc_transactions(fast_tx, slow_tx):
                        print(f"CDC mismatch for ID {id_val}")
    
    tracker = CDCTracker()
    
    # Connect tracker to monitors
    fast_monitor.add_callback(tracker.on_fast_transaction)
    slow_monitor.add_callback(tracker.on_slow_transaction)
    
    # Run test with clock domain crossing
    await Timer(10000, units='ns')
```

## Best Practices

### Monitor Configuration
- Connect both sides—one-sided verification only tells half the story
- Size `id_width` to the actual system, not the default
- Set timeouts that reflect your interconnect's real latency

### Performance Optimization
- Retire completed transactions in long tests
- Watch memory usage when transaction volume gets large
- Filter by ID when you're chasing something specific

### Error Analysis
- Detailed logging is worth it for protocol violations
- Timestamps turn "it failed" into "it failed 40 ns after the request"
- Keep failed transaction pairs for debugging

### Integration Guidelines
- Monitors connected before traffic starts, not after
- Scoreboard statistics double as coverage data
- Write custom callbacks for anything specialized

## Integration Points

### Test Environment Integration
```python
# Integration with test sequence
class AXI4TestEnvironment:
    def __init__(self, dut, clock):
        self.scoreboard = AXI4Scoreboard("TestEnv", log=logger)
        self.master_monitor = AXI4Monitor(dut.master, "Master", clock)
        self.slave_monitor = AXI4Monitor(dut.slave, "Slave", clock)
        
        self.scoreboard.add_master_monitor(self.master_monitor)
        self.scoreboard.add_slave_monitor(self.slave_monitor)
    
    def run_verification(self):
        return self.scoreboard.report()
```

### Coverage Integration

The ID dictionaries double as functional coverage:

```python
# Functional coverage with scoreboard
def calculate_id_coverage():
    used_ids = set(scoreboard.master_writes.keys()) | set(scoreboard.master_reads.keys())
    total_ids = 2 ** scoreboard.id_width
    coverage = len(used_ids) / total_ids * 100
    print(f"ID Coverage: {coverage:.1f}% ({len(used_ids)}/{total_ids})")
```

Per-ID queues, dual-side pairing, and protocol checks running the whole time—this is the scoreboard you want between a master and a slave that don't finish transactions in the order they started them.
