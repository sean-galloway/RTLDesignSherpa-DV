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

# apb_gaxi_scoreboard.py

An APB-to-GAXI bridge has three observable moments: the APB transaction goes in, a GAXI command comes out, and a GAXI response comes back. This scoreboard keeps a queue for each one and checks that they line up into complete, correct flows—which is the whole job when the DUT exists to convert one protocol into the other.

## Overview

What you get:
- **Three-Phase Transaction Matching**: follows each transfer through APB transaction → GAXI command → GAXI response
- **Protocol-Aware Verification**: understands APB and GAXI semantics rather than doing blind field comparison
- **Response Handling**: pairs both read and write responses with the right command
- **Enhanced Error Classification**: sorts failures by category and narrows them to the offending field
- **Timeout-Based Matching**: a transaction that never completes gets flagged, not quietly forgotten

## Classes

### APBGAXIScoreboard

Bridge verification built around three queues—one per phase.

```python
class APBGAXIScoreboard:
    def __init__(self, name, log=None)
```

**Parameters:**
- `name`: scoreboard name; shows up in report headers
- `log`: logger for the detailed blow-by-blow

**Key Features:**
- Separate queues for APB transactions, GAXI commands, and GAXI responses
- Matching runs automatically as transactions arrive, with a configurable timeout
- Full statistics on matches, mismatches, and errors
- Field-level error reporting through the transaction extractor

**Transaction Queues:**
- `apb_queue`: APB transactions seen on the master/slave interface
- `gaxi_cmd_queue`: GAXI commands
- `gaxi_rsp_queue`: GAXI responses

## Core Methods

### Transaction Management

#### `add_apb_transaction(transaction)`
Feed an APB transaction into the scoreboard.

**Parameters:**
- `transaction`: the APB transaction to match

**Behavior:**
- Pulls the fields out with `APBTransactionExtractor`
- Timestamps the transaction so the timeout logic has something to work with
- Bumps the APB transaction counter
- Immediately attempts a match

```python
# Add APB transaction
apb_transaction = create_apb4_write(addr=0x1000, data=0xDEADBEEF)
scoreboard.add_apb_transaction(apb_transaction)
```

#### `add_gaxi_transaction(transaction)`
One entry point for both halves of the GAXI side. The scoreboard looks at which
fields the packet carries, decides whether it's a command or a response, and
routes it to the matching internal queue—so your monitor wiring stays one
callback per interface.

**Parameters:**
- `transaction`: GAXI command or response

**Behavior:**
- Command vs. response is decided from the fields present on the packet
- Commands (address/write-data fields) go to the command queue
- Responses (read-data/status fields) go to the response queue
- Timestamped, counted, and matched on arrival

```python
# Add GAXI command and response — same entry point for both
gaxi_command = create_gaxi_command(addr=0x1000, data=0xDEADBEEF, cmd=1)
scoreboard.add_gaxi_transaction(gaxi_command)

gaxi_response = create_gaxi_response(data=0xDEADBEEF, status='OKAY')
scoreboard.add_gaxi_transaction(gaxi_response)
```

### Transaction Matching

#### `_match_transactions()`
The matching engine. It runs on every transaction arrival.

**Matching Logic:**
1. **APB-GAXI Command Matching**: an APB transaction and a GAXI command match on address and operation type
2. **Command-Response Pairing**: GAXI commands and responses get paired through their transaction identifiers
3. **End-to-End Verification**: a flow only counts when all three phases check out

**Timeout Handling:**
- `match_timeout_ns` sets how long a phase may dangle before it's declared stale
- Expired transactions are cleaned out of the queues automatically
- Timeouts are logged and counted in the statistics

```python
# Configure timeout (default: 10μs)
scoreboard.match_timeout_ns = 50000  # 50μs timeout
```

### Field Extraction and Formatting

Field access goes through `APBTransactionExtractor` rather than poking at attributes directly—packet layouts vary, and the extractor knows the variations.

#### APB Transaction Fields
- **Command Fields**: address, data, write enable, strobe
- **Response Fields**: read data, error status, completion status
- **Timing Fields**: start time, end time, duration

#### GAXI Transaction Fields
- **Command Fields**: address, data, command type, strobe
- **Response Fields**: response data, status codes, error indicators

```python
# Example field extraction
apb_fields = APBTransactionExtractor.extract_command_fields(apb_transaction)
# Returns: {'addr': 0x1000, 'data': 0xDEADBEEF, 'is_write': True, 'strb': 0xF}

gaxi_fields = APBTransactionExtractor.extract_response_fields(gaxi_response)
# Returns: {'data': 0xDEADBEEF, 'has_error': False, 'status': 'OKAY'}
```

## Statistics and Reporting

### Comprehensive Statistics Tracking

Everything the scoreboard counts, in one dictionary:

```python
stats = {
    'apb_transactions': 0,           # Total APB transactions
    'gaxi_cmd_transactions': 0,      # Total GAXI commands
    'gaxi_rsp_transactions': 0,      # Total GAXI responses
    'matched_pairs': 0,              # Successfully matched complete flows
    'matched_write_responses': 0,    # Matched write responses
    'matched_read_responses': 0,     # Matched read responses
    'unmatched_apb': 0,              # Unmatched APB transactions
    'unmatched_gaxi_cmd': 0,         # Unmatched GAXI commands
    'unmatched_gaxi_rsp': 0,         # Unmatched GAXI responses
    'error_transactions': 0,         # Transactions with errors
    'field_extraction_errors': 0,   # Field extraction failures
    'transaction_type_errors': 0     # Invalid transaction types
}
```

### Reporting Methods

#### `report()`
The whole picture as a formatted string.

**Returns:**
- `str`: report with every statistic and the analysis

**Report Contents:**
- Transaction counts for all three phases
- Match rates broken out for reads and writes
- Error analysis and unmatched counts
- Field-extraction and type-error statistics

```python
print(scoreboard.report())
# Output:
# === APB-GAXI Scoreboard Report (BridgeTest) ===
# APB Transactions: 150
# GAXI Commands: 148
# GAXI Responses: 147
# Matched Pairs: 145
#   - Write Responses: 85
#   - Read Responses: 60
# Error Transactions: 2
# Unmatched APB: 5
# Unmatched GAXI CMD: 3
# Unmatched GAXI RSP: 2
```

#### `get_stats()`
The same numbers as a dictionary, for when you'd rather assert on them than read them.

**Returns:**
- `dict`: the complete statistics dictionary

```python
stats = scoreboard.get_stats()
success_rate = stats['matched_pairs'] / stats['apb_transactions'] * 100
print(f"Bridge success rate: {success_rate:.2f}%")
```

### Utility Methods

#### `clear()`
Reset for the next test phase.

**Behavior:**
- Empties all three queues
- Zeroes the counters
- Leaves your configuration (including the timeout) alone

```python
# Reset between test phases
scoreboard.clear()
```

## Usage Examples

### Basic APB-GAXI Bridge Verification

The full write flow, end to end: APB write in, GAXI command and response out, all three matched.

```python
from CocoTBFramework.scoreboards.apb_gaxi_scoreboard import APBGAXIScoreboard
from CocoTBFramework.components.apb.apb_packet import APBPacket
from CocoTBFramework.components.gaxi.gaxi_packet import GAXIPacket

# Create bridge scoreboard
scoreboard = APBGAXIScoreboard("APB_GAXI_Bridge", log=logger)

# Configure timeout for bridge latency
scoreboard.match_timeout_ns = 1000  # 1μs timeout

# Test write transaction flow
apb_write = APBPacket()
apb_write.direction = 'WRITE'
apb_write.paddr = 0x2000
apb_write.pwdata = 0x12345678
apb_write.pstrb = 0xF

gaxi_cmd = GAXIPacket(field_config)
gaxi_cmd.fields['addr'] = 0x2000
gaxi_cmd.fields['data'] = 0x12345678
gaxi_cmd.fields['cmd'] = 1  # Write
gaxi_cmd.fields['strb'] = 0xF

gaxi_rsp = GAXIPacket(field_config)
gaxi_rsp.fields['data'] = 0x0  # Write response (no data)
gaxi_rsp.fields['status'] = 0  # OKAY

# Add transactions in sequence
scoreboard.add_apb_transaction(apb_write)
scoreboard.add_gaxi_transaction(gaxi_cmd)
scoreboard.add_gaxi_transaction(gaxi_rsp)

# Verify bridge operation
report = scoreboard.report()
print(report)

# Check success rate
stats = scoreboard.get_stats()
if stats['matched_pairs'] == stats['apb_transactions']:
    print("Bridge verification: PASS")
else:
    print(f"Bridge verification: FAIL ({stats['matched_pairs']}/{stats['apb_transactions']} matched)")
```

### Read Transaction Verification

Reads exercise the same three queues with the data flowing the other way.

```python
# Test read transaction flow
async def test_bridge_read_flow():
    scoreboard = APBGAXIScoreboard("Read_Bridge", log=logger)
    
    # APB read request
    apb_read = APBPacket()
    apb_read.direction = 'READ'
    apb_read.paddr = 0x3000
    apb_read.prdata = 0xABCDEF00  # Expected read data
    
    # Corresponding GAXI command
    gaxi_cmd = GAXIPacket(field_config)
    gaxi_cmd.fields['addr'] = 0x3000
    gaxi_cmd.fields['cmd'] = 0  # Read
    
    # GAXI response with read data
    gaxi_rsp = GAXIPacket(field_config)
    gaxi_rsp.fields['data'] = 0xABCDEF00
    gaxi_rsp.fields['status'] = 0  # OKAY
    
    # Simulate bridge operation timing
    scoreboard.add_apb_transaction(apb_read)
    await Timer(100, units='ns')  # Bridge processing delay
    
    scoreboard.add_gaxi_transaction(gaxi_cmd)
    await Timer(50, units='ns')   # Memory access delay
    
    scoreboard.add_gaxi_transaction(gaxi_rsp)
    
    # Verify read flow
    stats = scoreboard.get_stats()
    assert stats['matched_read_responses'] == 1, "Read response not matched"
    assert stats['error_transactions'] == 0, "Unexpected errors detected"
    
    print("Read bridge verification: PASS")
```

### High-Throughput Bridge Testing

A hundred transactions back to back, with small delays standing in for bridge and memory latency.

```python
# Test bridge with multiple concurrent transactions
async def test_high_throughput_bridge():
    scoreboard = APBGAXIScoreboard("HighThroughput", log=logger)
    scoreboard.match_timeout_ns = 10000  # 10μs for high throughput
    
    # Generate transaction patterns
    num_transactions = 100
    transaction_pairs = []
    
    for i in range(num_transactions):
        # Alternating read/write pattern
        is_write = (i % 2 == 0)
        addr = 0x10000 + (i * 4)
        data = 0xDEAD0000 + i
        
        # APB transaction
        apb_tx = APBPacket()
        apb_tx.direction = 'WRITE' if is_write else 'READ'
        apb_tx.paddr = addr
        if is_write:
            apb_tx.pwdata = data
            apb_tx.pstrb = 0xF
        else:
            apb_tx.prdata = data
        
        # GAXI command
        gaxi_cmd = GAXIPacket(field_config)
        gaxi_cmd.fields['addr'] = addr
        gaxi_cmd.fields['cmd'] = 1 if is_write else 0
        if is_write:
            gaxi_cmd.fields['data'] = data
            gaxi_cmd.fields['strb'] = 0xF
        
        # GAXI response
        gaxi_rsp = GAXIPacket(field_config)
        gaxi_rsp.fields['data'] = data if not is_write else 0
        gaxi_rsp.fields['status'] = 0  # OKAY
        
        transaction_pairs.append((apb_tx, gaxi_cmd, gaxi_rsp))
    
    # Simulate concurrent bridge operation
    for apb_tx, gaxi_cmd, gaxi_rsp in transaction_pairs:
        scoreboard.add_apb_transaction(apb_tx)
        
        # Small delay for bridge processing
        await Timer(10, units='ns')
        scoreboard.add_gaxi_transaction(gaxi_cmd)
        
        # Memory response delay
        await Timer(5, units='ns')
        scoreboard.add_gaxi_transaction(gaxi_rsp)
    
    # Wait for all matching to complete
    await Timer(1000, units='ns')
    
    # Analyze results
    stats = scoreboard.get_stats()
    print(f"High-throughput test results:")
    print(f"  APB transactions: {stats['apb_transactions']}")
    print(f"  Matched pairs: {stats['matched_pairs']}")
    print(f"  Success rate: {stats['matched_pairs']/stats['apb_transactions']*100:.1f}%")
    print(f"  Write responses: {stats['matched_write_responses']}")
    print(f"  Read responses: {stats['matched_read_responses']}")
    
    # Verify performance
    assert stats['matched_pairs'] >= num_transactions * 0.95, "Insufficient match rate"
    assert stats['error_transactions'] == 0, "Unexpected error transactions"
    
    print("High-throughput bridge verification: PASS")
```

### Error Injection and Recovery Testing

Three flavors of trouble in one test: a clean transaction, a SLVERR, and a command whose response never shows up.

```python
# Test bridge error handling
async def test_bridge_error_handling():
    scoreboard = APBGAXIScoreboard("ErrorTest", log=logger)
    
    # Normal transaction
    normal_apb = create_apb4_write(addr=0x1000, data=0x11111111)
    normal_cmd = create_gaxi_command(addr=0x1000, data=0x11111111, cmd=1)
    normal_rsp = create_gaxi_response(status='OKAY')
    
    # Error transaction
    error_apb = create_apb4_write(addr=0x2000, data=0x22222222)
    error_cmd = create_gaxi_command(addr=0x2000, data=0x22222222, cmd=1)
    error_rsp = create_gaxi_response(status='SLVERR')  # Slave error
    
    # Timeout transaction (no response)
    timeout_apb = create_apb4_write(addr=0x3000, data=0x33333333)
    timeout_cmd = create_gaxi_command(addr=0x3000, data=0x33333333, cmd=1)
    # No response - will timeout
    
    # Add transactions
    scoreboard.add_apb_transaction(normal_apb)
    scoreboard.add_gaxi_transaction(normal_cmd)
    scoreboard.add_gaxi_transaction(normal_rsp)
    
    scoreboard.add_apb_transaction(error_apb)
    scoreboard.add_gaxi_transaction(error_cmd)
    scoreboard.add_gaxi_transaction(error_rsp)
    
    scoreboard.add_apb_transaction(timeout_apb)
    scoreboard.add_gaxi_transaction(timeout_cmd)
    # No response added
    
    # Wait for timeout
    await Timer(scoreboard.match_timeout_ns + 1000, units='ns')
    
    # Analyze error handling
    stats = scoreboard.get_stats()
    print("Error handling test results:")
    print(f"  Total APB transactions: {stats['apb_transactions']}")
    print(f"  Matched pairs: {stats['matched_pairs']}")
    print(f"  Error transactions: {stats['error_transactions']}")
    print(f"  Unmatched responses: {stats['unmatched_gaxi_rsp']}")
    
    # Verify error detection
    assert stats['error_transactions'] >= 1, "Error transaction not detected"
    assert stats['unmatched_gaxi_rsp'] >= 1, "Timeout not detected"
    
    print("Error handling verification: PASS")
```

### Multi-Bridge System Verification

One scoreboard per bridge, rolled up into a system report at the end.

```python
# Test system with multiple APB-GAXI bridges
class MultiBridgeTestEnvironment:
    def __init__(self, num_bridges):
        self.scoreboards = {}
        for i in range(num_bridges):
            self.scoreboards[i] = APBGAXIScoreboard(f"Bridge_{i}", log=logger)
    
    def add_bridge_transaction(self, bridge_id, apb_tx, gaxi_cmd, gaxi_rsp):
        if bridge_id in self.scoreboards:
            sb = self.scoreboards[bridge_id]
            sb.add_apb_transaction(apb_tx)
            sb.add_gaxi_transaction(gaxi_cmd)
            sb.add_gaxi_transaction(gaxi_rsp)
    
    def generate_comprehensive_report(self):
        total_stats = {
            'apb_transactions': 0,
            'matched_pairs': 0,
            'error_transactions': 0
        }
        
        print("=== Multi-Bridge System Report ===")
        for bridge_id, scoreboard in self.scoreboards.items():
            stats = scoreboard.get_stats()
            total_stats['apb_transactions'] += stats['apb_transactions']
            total_stats['matched_pairs'] += stats['matched_pairs']
            total_stats['error_transactions'] += stats['error_transactions']
            
            success_rate = stats['matched_pairs'] / stats['apb_transactions'] * 100 if stats['apb_transactions'] > 0 else 0
            print(f"Bridge {bridge_id}: {stats['matched_pairs']}/{stats['apb_transactions']} ({success_rate:.1f}%)")
        
        overall_success = total_stats['matched_pairs'] / total_stats['apb_transactions'] * 100 if total_stats['apb_transactions'] > 0 else 0
        print(f"Overall System: {total_stats['matched_pairs']}/{total_stats['apb_transactions']} ({overall_success:.1f}%)")
        print(f"Total Errors: {total_stats['error_transactions']}")
        
        return total_stats

# Usage
async def test_multi_bridge_system():
    test_env = MultiBridgeTestEnvironment(num_bridges=4)
    
    # Generate transactions for each bridge
    for bridge_id in range(4):
        for addr_offset in range(10):
            addr = 0x10000 + (bridge_id * 0x1000) + (addr_offset * 4)
            data = 0xB0000000 + (bridge_id << 16) + addr_offset
            
            apb_tx = create_apb4_write(addr=addr, data=data)
            gaxi_cmd = create_gaxi_command(addr=addr, data=data, cmd=1)
            gaxi_rsp = create_gaxi_response(status='OKAY')
            
            test_env.add_bridge_transaction(bridge_id, apb_tx, gaxi_cmd, gaxi_rsp)
            
            await Timer(50, units='ns')
    
    # Generate system report
    system_stats = test_env.generate_comprehensive_report()
    
    # Verify system performance
    assert system_stats['error_transactions'] == 0, "System errors detected"
    assert system_stats['matched_pairs'] == system_stats['apb_transactions'], "Incomplete transaction matching"
    
    print("Multi-bridge system verification: PASS")
```

## Best Practices

### Timeout Configuration
- Set the timeout from actual bridge latency plus memory access time, with margin
- A low-latency bridge deserves a tight timeout so a hang fails fast instead of stalling the test

### Transaction Ordering
- Add transactions in the order they'd actually occur
- APB first, then the GAXI command, then the response
- Don't sit on responses—the timeout clock is running

### Error Analysis
- Turn logging up when chasing field-extraction problems; the extractor messages usually name the culprit
- Watch the timeout counters—they tell you about bridge performance, not just correctness
- Use the error classifications to debug systematically instead of one waveform at a time

### Performance Optimization
- `clear()` between major test phases so queues don't accumulate history
- Keep an eye on queue depth in high-throughput runs
- Pick timeouts that fail fast without tripping on legitimate latency

## Integration Points

### Monitor Integration

The GAXI command and response monitors can share one callback—the scoreboard sorts out which is which.

```python
# Connect monitors to scoreboard
def on_apb_transaction(packet):
    scoreboard.add_apb_transaction(packet)

def on_gaxi_command(packet):
    scoreboard.add_gaxi_transaction(packet)

def on_gaxi_response(packet):
    scoreboard.add_gaxi_transaction(packet)

apb_monitor.add_callback(on_apb_transaction)
gaxi_cmd_monitor.add_callback(on_gaxi_command)
gaxi_rsp_monitor.add_callback(on_gaxi_response)
```

### Test Environment Integration

```python
# Complete bridge test environment
class APBGAXIBridgeTestEnv:
    def __init__(self, dut, clock):
        self.scoreboard = APBGAXIScoreboard("BridgeEnv", log=logger)
        
        # Connect monitors
        self.apb_monitor = APBMonitor(dut.apb, clock)
        self.gaxi_cmd_monitor = GAXIMonitor(dut.gaxi_cmd, clock)
        self.gaxi_rsp_monitor = GAXIMonitor(dut.gaxi_rsp, clock)
        
        # Connect callbacks
        self.apb_monitor.add_callback(self.scoreboard.add_apb_transaction)
        self.gaxi_cmd_monitor.add_callback(self.scoreboard.add_gaxi_transaction)
        self.gaxi_rsp_monitor.add_callback(self.scoreboard.add_gaxi_transaction)
    
    def get_verification_results(self):
        return {
            'report': self.scoreboard.report(),
            'stats': self.scoreboard.get_stats()
        }
```

Three queues, automatic matching, and statistics detailed enough to tell you whether a failure lived in the command path, the response path, or the timing. That's the whole bridge story.
