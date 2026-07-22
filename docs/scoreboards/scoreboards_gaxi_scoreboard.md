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

# gaxi_scoreboard.py

GAXI is the framework's generic AXI substrate—the layer the AXI4/AXI5/AXI-Lite pieces are built on—so this scoreboard ends up seeing more traffic than any other. It's built around the modern `FieldConfig`/`Packet` architecture, and it ships with two extras that matter in practice: a transform scoreboard for cross-protocol checks and a memory adapter for data-consistency checks.

## Overview

- **Modern Field Configuration**: native `FieldConfig` and `Packet` integration
- **Flexible Packet Handling**: legacy and modern packet formats both accepted
- **Protocol Transformation**: cross-protocol verification through transformers
- **Memory Model Integration**: adapter included
- **Transform Scoreboards**: verification in the target protocol's domain

## Classes

### GAXIScoreboard

GAXI verification on the modern architecture.

```python
class GAXIScoreboard(BaseScoreboard):
    def __init__(self, name, field_config, log=None)
```

**Parameters:**
- `name`: scoreboard name; shows up in reports
- `field_config`: field configuration (FieldConfig object or plain dictionary)
- `log`: logger for the detail

**Modern Features:**
- FieldConfig validation and conversion handled for you
- Works with the updated Packet class and its fields dictionary
- Field-by-field comparison logging
- Legacy packet formats still accepted

### Field Configuration Handling

Hand it a plain dictionary and it gets validated into a `FieldConfig` for you; hand it a `FieldConfig` and it's used as-is. Either way you end up in the same place.

```python
# Dictionary format (automatically converted)
field_dict = {'data': 32, 'addr': 32, 'cmd': 1}
scoreboard = GAXIScoreboard("Test", field_dict, log=logger)

# FieldConfig object (used directly)
field_config = FieldConfig.validate_and_create(field_dict)
scoreboard = GAXIScoreboard("Test", field_config, log=logger)
```

## Core Methods

### Transaction Comparison

#### `_compare_transactions(expected, actual)`
Comparison goes through the `Packet` class `__eq__`, which skips timing fields automatically. That's the part that saves you a debugging session: `start_time`/`end_time` are excluded, so two functionally identical packets captured at different sim times still match.

**Parameters:**
- `expected`: expected GAXI transaction (GAXIPacket)
- `actual`: actual GAXI transaction (GAXIPacket)

**Returns:**
- `bool`: True on match, False otherwise

**Modern Comparison Logic:**
- Both transactions must be GAXIPacket instances
- Uses the Packet class `__eq__` method, which skips timing fields on its own
- Compares every configured field using field_config
- Handles both legacy and modern packet formats

```python
# Automatic comparison with timing field exclusion
scoreboard.add_expected(expected_packet)  # start_time, end_time ignored
scoreboard.add_actual(actual_packet)      # Only functional fields compared
```

#### `_log_mismatch(expected, actual)`
Compact packet dumps, then the field-by-field walk in hex. The logger detects which packet format it's holding—modern or legacy—and formats accordingly.

**Parameters:**
- `expected`: expected GAXI packet
- `actual`: actual GAXI packet

**Enhanced Logging Features:**
- Uses the packet's `formatted(compact=True)` method for readable output
- Automatic packet-format detection (modern vs legacy)
- Field-by-field comparison using FieldConfig
- Hex display so values compare at a glance

```python
# Example modern mismatch log output:
# GAXI Packet mismatch:
#   Expected: addr=0x1000, data=0xDEADBEEF, cmd=1
#   Actual:   addr=0x1000, data=0xBEEFDEAD, cmd=1
#   Field 'data' mismatch: expected=0xDEADBEEF, actual=0xBEEFDEAD
```

## Advanced Scoreboards

### TransformScoreboard

When the two sides of your DUT speak different protocols, verify in the target protocol's domain. Source transactions arrive as expecteds, get transformed, and are forwarded to the target scoreboard; actuals are already in the target protocol and go straight there.

```python
class TransformScoreboard(BaseScoreboard):
    def __init__(self, name, transformer, target_scoreboard, log=None)
```

**Parameters:**
- `name`: scoreboard name
- `transformer`: protocol transformer instance
- `target_scoreboard`: the scoreboard that does the final comparison
- `log`: logger instance

**Transform Workflow:**
1. Source transactions arrive via `add_expected()`
2. The transformer converts them to the target protocol
3. Converted transactions are forwarded to the target scoreboard
4. Actual transactions go straight to the target scoreboard
5. Comparison happens in the target domain

```python
# Cross-protocol verification setup
apb_to_gaxi = APBtoGAXITransformer(gaxi_field_config)
gaxi_scoreboard = GAXIScoreboard("Target", gaxi_field_config)
transform_scoreboard = TransformScoreboard("Bridge", apb_to_gaxi, gaxi_scoreboard)

# APB input automatically transformed for GAXI comparison
transform_scoreboard.add_expected(apb_transaction)  # Transformed to GAXI
transform_scoreboard.add_actual(gaxi_packet)        # Direct comparison
```

### Memory Integration

### GAXItoMemoryAdapter

The memory adapter, GAXI-flavored. Writes honor the strobe field when one's configured.

```python
class GAXItoMemoryAdapter:
    def __init__(self, memory_model, field_map=None, log=None)
```

**Parameters:**
- `memory_model`: memory model instance for data storage
- `field_map`: field mapping for memory operations
- `log`: logger instance

**Default Field Mapping:**
- `'addr'`: address field for memory operations
- `'data'`: data field for read/write operations
- `'strb'`: strobe field for byte enables

#### Memory Operations

##### `write_to_memory(packet)`
Write a GAXI packet's data into the memory model.

**Parameters:**
- `packet`: GAXI packet carrying the write data

**Behavior:**
- Pulls address and data out of the packet fields
- Applies strobe-based byte enables when present
- Updates the memory model
- Logs the write for debugging

```python
# Memory write with strobe support
adapter = GAXItoMemoryAdapter(memory_model)
write_packet = create_gaxi_write(addr=0x1000, data=0xDEADBEEF, strb=0xF)
adapter.write_to_memory(write_packet)
```

##### `read_from_memory(packet)`
Check a read packet's data against memory contents.

**Parameters:**
- `packet`: GAXI packet carrying the expected read data

**Returns:**
- `bool`: True when packet data matches memory

**Verification Process:**
- Pulls the address out of the packet
- Reads current memory contents at that address
- Compares against the packet's data field
- Returns the verdict

```python
# Memory read verification
read_packet = create_gaxi_read(addr=0x1000, data=0xDEADBEEF)
match = adapter.read_from_memory(read_packet)
if not match:
    print("Memory read data mismatch")
```

## Usage Examples

### Basic GAXI Verification

The standard loop, with the timing-field exclusion doing quiet work in the background.

```python
from CocoTBFramework.scoreboards.gaxi_scoreboard import GAXIScoreboard
from CocoTBFramework.components.gaxi.gaxi_packet import GAXIPacket
from CocoTBFramework.components.shared.field_config import FieldConfig

# Modern field configuration
field_config = FieldConfig.from_dict({
    'addr': 32,
    'data': 32,
    'cmd': 1,
    'strb': 4
})

# Create scoreboard with modern field config
scoreboard = GAXIScoreboard("GAXI_Test", field_config, log=logger)

# Create test packets using modern Packet class
expected = GAXIPacket(field_config)
expected.fields['addr'] = 0x1000
expected.fields['data'] = 0xDEADBEEF
expected.fields['cmd'] = 1  # Write
expected.fields['strb'] = 0xF

actual = GAXIPacket(field_config)
actual.fields['addr'] = 0x1000
actual.fields['data'] = 0xDEADBEEF
actual.fields['cmd'] = 1
actual.fields['strb'] = 0xF

# Verify transactions (timing fields automatically ignored)
scoreboard.add_expected(expected)
scoreboard.add_actual(actual)

# Check results
error_count = scoreboard.report()
pass_rate = scoreboard.result()
print(f"GAXI Verification: {'PASS' if error_count == 0 else 'FAIL'} ({pass_rate:.2%})")
```

### Cross-Protocol Transformation Verification

APB in, GAXI out, compared in the GAXI domain—the transform scoreboard ties it together.

```python
from CocoTBFramework.scoreboards.gaxi_scoreboard import TransformScoreboard
from CocoTBFramework.scoreboards.apb_gaxi_transformer import APBtoGAXITransformer
from CocoTBFramework.components.apb.apb_packet import APBPacket

# Create transformation pipeline
transformer = APBtoGAXITransformer(gaxi_field_config, GAXIPacket, log=logger)
target_scoreboard = GAXIScoreboard("GAXI_Target", gaxi_field_config, log=logger)
bridge_scoreboard = TransformScoreboard("APB_GAXI_Bridge", transformer, target_scoreboard, log=logger)

# Create APB input transaction
apb_transaction = APBPacket()
apb_transaction.direction = 'WRITE'
apb_transaction.paddr = 0x2000
apb_transaction.pwdata = 0x12345678
apb_transaction.pstrb = 0xF

# Create expected GAXI output (from DUT)
gaxi_output = GAXIPacket(gaxi_field_config)
gaxi_output.fields['addr'] = 0x2000
gaxi_output.fields['data'] = 0x12345678
gaxi_output.fields['cmd'] = 1
gaxi_output.fields['strb'] = 0xF

# Verify transformation
bridge_scoreboard.add_expected(apb_transaction)  # Auto-transformed to GAXI
bridge_scoreboard.add_actual(gaxi_output)        # Direct GAXI comparison

# Analysis
errors = bridge_scoreboard.report()
if errors == 0:
    print("Bridge transformation verified successfully")
else:
    print(f"Bridge verification failed: {errors} errors")
```

### Memory-Backed GAXI System Verification

Writes update the model, reads check against it. The subclass below wires that in.

```python
from CocoTBFramework.scoreboards.gaxi_scoreboard import GAXItoMemoryAdapter
from CocoTBFramework.components.shared.memory_model import MemoryModel

# Create memory system
memory = MemoryModel(size=1024*1024, log=logger)
field_map = {
    'addr': 'addr',
    'data': 'data',
    'strb': 'strb'
}
adapter = GAXItoMemoryAdapter(memory, field_map, log=logger)

# Create memory-integrated verification environment
class MemoryGAXIScoreboard(GAXIScoreboard):
    def __init__(self, name, field_config, memory_adapter, log=None):
        super().__init__(name, field_config, log)
        self.memory_adapter = memory_adapter
    
    def add_expected(self, packet):
        # For write transactions, update memory
        if packet.fields.get('cmd') == 1:  # Write
            self.memory_adapter.write_to_memory(packet)
        super().add_expected(packet)
    
    def _compare_transactions(self, expected, actual):
        # Standard comparison
        basic_match = super()._compare_transactions(expected, actual)
        
        # Additional memory consistency check for reads
        if actual.fields.get('cmd') == 0:  # Read
            memory_match = self.memory_adapter.read_from_memory(actual)
            if not memory_match and self.log:
                self.log.error("Memory consistency check failed for read transaction")
            return basic_match and memory_match
        
        return basic_match

# Usage
memory_scoreboard = MemoryGAXIScoreboard("MemorySystem", gaxi_field_config, adapter, log=logger)

# Test write-then-read sequence
write_packet = create_gaxi_write(addr=0x1000, data=0xABCDEF00)
read_packet = create_gaxi_read(addr=0x1000, data=0xABCDEF00)

memory_scoreboard.add_expected(write_packet)  # Updates memory
memory_scoreboard.add_expected(read_packet)   # Verified against memory

# ... add actual transactions from DUT ...
```

### Advanced Multi-Channel Verification

Sixteen channels routed by a packet field—one scoreboard each, one router in front.

```python
# Multi-channel GAXI verification system
async def test_multi_channel_gaxi():
    # Define multi-channel field configuration
    field_config = FieldConfig.from_dict({
        'addr': 32,
        'data': 64,
        'cmd': 1,
        'strb': 8,
        'channel': 4,
        'id': 8
    })
    
    # Create channel-specific scoreboards
    scoreboards = {}
    for channel in range(16):
        scoreboards[channel] = GAXIScoreboard(
            f"Channel_{channel}",
            field_config,
            log=logger
        )
    
    # Transaction router
    class GAXIChannelRouter:
        def __init__(self, scoreboards):
            self.scoreboards = scoreboards
        
        def route_expected(self, packet):
            channel = packet.fields.get('channel', 0)
            if channel in self.scoreboards:
                self.scoreboards[channel].add_expected(packet)
            else:
                print(f"Unknown channel: {channel}")
        
        def route_actual(self, packet):
            channel = packet.fields.get('channel', 0)
            if channel in self.scoreboards:
                self.scoreboards[channel].add_actual(packet)
    
    router = GAXIChannelRouter(scoreboards)
    
    # Generate test traffic
    for channel in range(4):  # Test first 4 channels
        for addr in range(0x1000, 0x2000, 0x100):
            # Write transaction
            write_packet = GAXIPacket(field_config)
            write_packet.fields['addr'] = addr
            write_packet.fields['data'] = 0xDEADBEEF + addr
            write_packet.fields['cmd'] = 1
            write_packet.fields['strb'] = 0xFF
            write_packet.fields['channel'] = channel
            write_packet.fields['id'] = (channel << 4) | (addr & 0xF)
            
            router.route_expected(write_packet)
            
            # Corresponding read transaction
            read_packet = GAXIPacket(field_config)
            read_packet.fields['addr'] = addr
            read_packet.fields['data'] = 0xDEADBEEF + addr
            read_packet.fields['cmd'] = 0
            read_packet.fields['channel'] = channel
            read_packet.fields['id'] = (channel << 4) | (addr & 0xF)
            
            router.route_expected(read_packet)
    
    # ... simulate DUT and route actual transactions ...
    
    # Generate comprehensive report
    total_errors = 0
    for channel, scoreboard in scoreboards.items():
        if scoreboard.transaction_count > 0:
            errors = scoreboard.report()
            total_errors += errors
            pass_rate = scoreboard.result()
            print(f"Channel {channel}: {'PASS' if errors == 0 else 'FAIL'} ({pass_rate:.2%})")
    
    print(f"Overall Result: {'PASS' if total_errors == 0 else 'FAIL'}")
```

### Performance and Coverage Analysis

Subclass to collect field coverage and error patterns while the comparisons run.

```python
# Enhanced GAXI scoreboard with analytics
class AnalyticsGAXIScoreboard(GAXIScoreboard):
    def __init__(self, name, field_config, log=None):
        super().__init__(name, field_config, log)
        self.field_coverage = {}
        self.transaction_timing = []
        self.error_patterns = {}
    
    def _compare_transactions(self, expected, actual):
        # Record transaction timing
        if hasattr(actual, 'timestamp'):
            self.transaction_timing.append(actual.timestamp)
        
        # Track field coverage
        for field_name in self.field_config.field_names():
            if field_name not in self.field_coverage:
                self.field_coverage[field_name] = set()
            
            if field_name in actual.fields:
                self.field_coverage[field_name].add(actual.fields[field_name])
        
        # Perform comparison
        result = super()._compare_transactions(expected, actual)
        
        # Track error patterns
        if not result:
            error_key = self._classify_error(expected, actual)
            self.error_patterns[error_key] = self.error_patterns.get(error_key, 0) + 1
        
        return result
    
    def _classify_error(self, expected, actual):
        """Classify error type for pattern analysis"""
        mismatched_fields = []
        for field_name in self.field_config.field_names():
            if (field_name in expected.fields and field_name in actual.fields and
                expected.fields[field_name] != actual.fields[field_name]):
                mismatched_fields.append(field_name)
        
        return tuple(sorted(mismatched_fields))
    
    def get_analytics_report(self):
        # Field coverage analysis
        coverage_report = {}
        for field_name, values in self.field_coverage.items():
            field_width = self.field_config[field_name]
            max_values = 2 ** field_width
            coverage_pct = len(values) / max_values * 100
            coverage_report[field_name] = {
                'unique_values': len(values),
                'max_possible': max_values,
                'coverage_percent': coverage_pct
            }
        
        # Timing analysis
        timing_stats = {}
        if self.transaction_timing:
            timing_stats = {
                'count': len(self.transaction_timing),
                'avg_interval': (max(self.transaction_timing) - min(self.transaction_timing)) / len(self.transaction_timing),
                'throughput': len(self.transaction_timing) / (max(self.transaction_timing) - min(self.transaction_timing))
            }
        
        return {
            'field_coverage': coverage_report,
            'timing_statistics': timing_stats,
            'error_patterns': self.error_patterns,
            'transaction_count': self.transaction_count,
            'error_count': self.error_count
        }

# Usage
analytics_scoreboard = AnalyticsGAXIScoreboard("Analytics", gaxi_field_config, log=logger)

# ... run test ...

report = analytics_scoreboard.get_analytics_report()
print("Coverage Analysis:")
for field, stats in report['field_coverage'].items():
    print(f"  {field}: {stats['coverage_percent']:.1f}% ({stats['unique_values']}/{stats['max_possible']})")

print("Error Pattern Analysis:")
for pattern, count in report['error_patterns'].items():
    print(f"  Fields {pattern}: {count} occurrences")
```

## Best Practices

### Modern Architecture Usage
- Use `FieldConfig` objects everywhere; the dict form works, but the object keeps everyone honest
- Use the fields dictionary on packets rather than loose attributes
- Let the timing-field exclusion do its job—don't scrub timestamps by hand

### Protocol Transformation
- `TransformScoreboard` for cross-protocol checks
- Custom transformers for domain-specific conversions
- Sanity-check a new transformer on known patterns before trusting it in a regression

### Memory Integration
- Get the field mapping right first; everything downstream depends on it
- Memory adapters for data-consistency questions
- Clear memory between phases when stale contents would mislead the check

### Performance Optimization
- Efficient comparison paths matter at high throughput
- Watch memory usage in long, high-volume runs
- Batch operations for large test sets

## Integration Points

### Factory Integration
```python
from CocoTBFramework.components.gaxi.gaxi_factories import create_gaxi_scoreboard

# Simplified scoreboard creation
scoreboard = create_gaxi_scoreboard("TestScoreboard", field_config, log=logger)
```

### Monitor Integration
```python
# Connect GAXI monitor to scoreboard
def on_gaxi_packet(packet):
    scoreboard.add_actual(packet)

gaxi_monitor.add_callback(on_gaxi_packet)
```

### Test Environment Integration
```python
# Complete GAXI test environment
class GAXITestEnvironment:
    def __init__(self, dut, clock, field_config):
        self.scoreboard = GAXIScoreboard("TestEnv", field_config, log=logger)
        self.memory_adapter = GAXItoMemoryAdapter(MemoryModel(1024*1024))
        
        # Connect monitors
        self.master_monitor = GAXIMonitor(dut.master, clock, field_config, is_slave=False)
        self.slave_monitor = GAXIMonitor(dut.slave, clock, field_config, is_slave=True)
        
        self.master_monitor.add_callback(self.scoreboard.add_actual)
    
    def verify_transaction(self, expected_packet):
        self.scoreboard.add_expected(expected_packet)
    
    def get_results(self):
        return {
            'errors': self.scoreboard.report(),
            'pass_rate': self.scoreboard.result()
        }
```

Since everything AXI-family in the framework bottoms out in GAXI, this scoreboard is the one worth knowing well—the transform and memory pieces included, because bridges and memory-mapped DUTs are where the interesting bugs live.
