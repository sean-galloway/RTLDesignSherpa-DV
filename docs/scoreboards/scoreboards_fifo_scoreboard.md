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

# fifo_scoreboard.py

FIFO traffic looks simple—data in, data out, order preserved—right up until a strobe or a channel field goes sideways. `FIFOScoreboard` compares packets field by field against your `FieldConfig`, and the companion `MemoryAdapter` ties packets to a memory model for FIFOs that are really buffering memory traffic.

## Overview

- **Field-based Comparison**: the `FieldConfig` defines the packet; comparison follows it
- **Memory Model Integration**: built-in adapter for data-consistency checking
- **FIFO Packet Support**: native `FIFOPacket` handling with readable mismatch logs
- **Configurable Verification**: field mapping and comparison logic you can bend to your packet shape

## Classes

### FIFOScoreboard

Field-configurable FIFO verification.

```python
class FIFOScoreboard(BaseScoreboard):
    def __init__(self, name, field_config, log=None)
```

**Parameters:**
- `name`: scoreboard name; shows up in reports
- `field_config`: field configuration defining the packet structure
- `log`: logger for mismatch detail

**Key Features:**
- FieldConfig drives the packet structure
- Mismatch logging with field-by-field analysis
- Works with the FIFOPacket class
- Comparison logic you can override

## Core Methods

### Transaction Comparison

#### `_compare_transactions(expected, actual)`
Type-check, then `FIFOPacket.__eq__`—which already compares every field the config defines.

**Parameters:**
- `expected`: expected FIFO transaction (FIFOPacket)
- `actual`: actual FIFO transaction (FIFOPacket)

**Returns:**
- `bool`: True on match, False otherwise

**Comparison Logic:**
- Both transactions must be FIFOPacket instances
- Uses FIFOPacket's built-in `__eq__` method
- Every field in field_config is covered by that equality

```python
# Automatic comparison when both transactions available
scoreboard.add_expected(expected_fifo_packet)
scoreboard.add_actual(actual_fifo_packet)  # Triggers comparison
```

#### `_log_mismatch(expected, actual)`
Prints both packets compactly, then walks the fields and names the ones that differ, values in hex. No guessing which field to look at.

**Parameters:**
- `expected`: expected FIFO packet
- `actual`: actual FIFO packet

**Detailed Logging:**
- Uses the packet's `formatted(compact=True)` method for readable output
- Field-by-field comparison using field_config
- Hex display for mismatched values
- The guilty fields identified by name

```python
# Example mismatch log output:
# FIFO Packet mismatch:
#   Expected: data=0xDEADBEEF, ctrl=0x1, valid=1
#   Actual:   data=0xBEEFDEAD, ctrl=0x1, valid=1
#   Field 'data' mismatch: expected=0xDEADBEEF, actual=0xBEEFDEAD
```

## Memory Model Integration

### MemoryAdapter

Some FIFOs carry memory traffic. The adapter pulls address/data/control out of a packet—using your field names via `field_map`—and applies them to a memory model, so "did the data survive the FIFO" becomes a checkable question.

```python
class MemoryAdapter:
    def __init__(self, memory_model, field_map=None, log=None)
```

**Parameters:**
- `memory_model`: memory model instance for storage and retrieval
- `field_map`: dictionary mapping memory operations to packet fields
- `log`: logger for operation tracking

**Default Field Mapping:**
- `'addr'`: address field for memory operations
- `'data'`: data field for read/write operations
- `'ctrl'`: control field for operation type

### Memory Operations

#### `write_to_memory(packet)`
Extract the address, write the data, log the operation.

**Parameters:**
- `packet`: FIFO packet carrying the write data

**Behavior:**
- Pulls the address out using the field mapping
- Writes the data to memory at that address
- Logs the write for debugging
- Field-mapping errors handled gracefully, not raised

```python
# Write packet to memory
adapter = MemoryAdapter(memory_model, field_map={'addr': 'address', 'data': 'payload'})
adapter.write_to_memory(fifo_packet)
```

#### `read_from_memory(packet)`
Read back and compare.

**Parameters:**
- `packet`: FIFO packet carrying the expected read data

**Returns:**
- `bool`: True when memory agrees with the packet

**Behavior:**
- Pulls the address out of the packet
- Reads memory at that address
- Compares memory contents against the packet's data field
- Returns the verdict

```python
# Verify read data matches memory
match = adapter.read_from_memory(read_packet)
if not match:
    print("Memory data mismatch detected")
```

#### `verify_packet_consistency(packet)`
The full check, returned as a results dictionary.

**Parameters:**
- `packet`: FIFO packet to verify

**Returns:**
- `dict`: verification results with detailed status

**Verification Checks:**
- Address field validity
- Data consistency with memory contents
- Control field interpretation
- Field mapping completeness

```python
# Comprehensive verification
results = adapter.verify_packet_consistency(packet)
print(f"Verification status: {results['status']}")
print(f"Details: {results['details']}")
```

## Usage Examples

### Basic FIFO Verification

Define the fields, build packets, compare. The FieldConfig is doing the structural work here.

```python
from CocoTBFramework.scoreboards.fifo_scoreboard import FIFOScoreboard
from CocoTBFramework.components.fifo.fifo_packet import FIFOPacket
from CocoTBFramework.components.shared.field_config import FieldConfig

# Define field configuration
field_config = FieldConfig.from_dict({
    'data': 32,
    'valid': 1,
    'ready': 1,
    'ctrl': 4
})

# Create scoreboard
scoreboard = FIFOScoreboard("FIFO_Test", field_config, log=logger)

# Create test packets
expected = FIFOPacket(field_config)
expected.fields['data'] = 0xDEADBEEF
expected.fields['valid'] = 1
expected.fields['ready'] = 1
expected.fields['ctrl'] = 0x5

actual = FIFOPacket(field_config)
actual.fields['data'] = 0xDEADBEEF
actual.fields['valid'] = 1
actual.fields['ready'] = 1
actual.fields['ctrl'] = 0x5

# Verify transactions
scoreboard.add_expected(expected)
scoreboard.add_actual(actual)

# Check results
error_count = scoreboard.report()
pass_rate = scoreboard.result()
print(f"FIFO Verification: {'PASS' if error_count == 0 else 'FAIL'} ({pass_rate:.2%})")
```

### Memory-Backed FIFO Verification

Write through the adapter, then check that a read packet matches what the memory model holds.

```python
from CocoTBFramework.scoreboards.fifo_scoreboard import MemoryAdapter
from CocoTBFramework.components.shared.memory_model import MemoryModel

# Create memory model and adapter
memory = MemoryModel(size=1024*1024, log=logger)
field_map = {
    'addr': 'address',
    'data': 'payload',
    'ctrl': 'command'
}
adapter = MemoryAdapter(memory, field_map, log=logger)

# Create memory-integrated scoreboard
scoreboard = FIFOScoreboard("MemoryFIFO", field_config, log=logger)

# Test memory consistency
write_packet = FIFOPacket(field_config)
write_packet.fields['address'] = 0x1000
write_packet.fields['payload'] = 0x12345678
write_packet.fields['command'] = 0x1  # Write command

# Write to memory
adapter.write_to_memory(write_packet)

# Create expected read packet
read_packet = FIFOPacket(field_config)
read_packet.fields['address'] = 0x1000
read_packet.fields['payload'] = 0x12345678
read_packet.fields['command'] = 0x0  # Read command

# Verify read consistency
match = adapter.read_from_memory(read_packet)
print(f"Memory consistency: {'PASS' if match else 'FAIL'}")

# Use with scoreboard for automated verification
scoreboard.add_expected(read_packet)
# ... actual packet from DUT ...
scoreboard.add_actual(actual_read_packet)
```

### Advanced FIFO System Verification

Sixteen channels, one scoreboard each, and a burst generator so the expected traffic doesn't get written by hand.

```python
# Multi-channel FIFO verification
async def test_multi_channel_fifo():
    # Define complex field configuration
    field_config = FieldConfig.from_dict({
        'data': 64,
        'channel': 4,
        'valid': 1,
        'ready': 1,
        'last': 1,
        'user': 8
    })
    
    # Create channel-specific scoreboards
    scoreboards = {}
    for channel in range(16):
        scoreboards[channel] = FIFOScoreboard(
            f"Channel_{channel}", 
            field_config, 
            log=logger
        )
    
    # Create test traffic generator
    class ChannelTrafficGenerator:
        def __init__(self, field_config):
            self.field_config = field_config
            self.packet_id = 0
        
        def generate_packet(self, channel, data_pattern):
            packet = FIFOPacket(self.field_config)
            packet.fields['data'] = data_pattern
            packet.fields['channel'] = channel
            packet.fields['valid'] = 1
            packet.fields['ready'] = 1
            packet.fields['last'] = 0
            packet.fields['user'] = self.packet_id & 0xFF
            self.packet_id += 1
            return packet
        
        def generate_burst(self, channel, length, base_data):
            packets = []
            for i in range(length):
                data = base_data + i
                packet = self.generate_packet(channel, data)
                if i == length - 1:
                    packet.fields['last'] = 1
                packets.append(packet)
            return packets
    
    generator = ChannelTrafficGenerator(field_config)
    
    # Generate test patterns for each channel
    for channel in range(4):  # Test first 4 channels
        burst = generator.generate_burst(channel, 16, 0x1000 + channel * 0x100)
        for packet in burst:
            scoreboards[channel].add_expected(packet)
    
    # Simulate DUT operation and verify
    # ... DUT simulation code ...
    
    # Generate verification report
    total_errors = 0
    for channel, scoreboard in scoreboards.items():
        errors = scoreboard.report()
        total_errors += errors
        if errors > 0:
            print(f"Channel {channel}: {errors} errors")
        else:
            print(f"Channel {channel}: PASS")
    
    print(f"Overall: {'PASS' if total_errors == 0 else 'FAIL'} ({total_errors} total errors)")
```

### Performance Analysis Integration

Subclass to collect throughput and latency alongside the pass/fail data.

```python
# FIFO performance verification
class PerformanceFIFOScoreboard(FIFOScoreboard):
    def __init__(self, name, field_config, log=None):
        super().__init__(name, field_config, log)
        self.throughput_data = []
        self.latency_data = []
        self.start_time = None
    
    def add_actual(self, transaction):
        # Record timing data
        if hasattr(transaction, 'timestamp'):
            if self.start_time is None:
                self.start_time = transaction.timestamp
            
            # Calculate throughput
            elapsed = transaction.timestamp - self.start_time
            if elapsed > 0:
                throughput = self.transaction_count / elapsed
                self.throughput_data.append(throughput)
        
        # Call parent method
        super().add_actual(transaction)
    
    def _compare_transactions(self, expected, actual):
        # Calculate latency if both have timestamps
        if hasattr(expected, 'timestamp') and hasattr(actual, 'timestamp'):
            latency = actual.timestamp - expected.timestamp
            self.latency_data.append(latency)
        
        return super()._compare_transactions(expected, actual)
    
    def get_performance_stats(self):
        stats = {
            'avg_throughput': sum(self.throughput_data) / len(self.throughput_data) if self.throughput_data else 0,
            'max_throughput': max(self.throughput_data) if self.throughput_data else 0,
            'avg_latency': sum(self.latency_data) / len(self.latency_data) if self.latency_data else 0,
            'max_latency': max(self.latency_data) if self.latency_data else 0,
            'total_transactions': self.transaction_count
        }
        return stats

# Usage
perf_scoreboard = PerformanceFIFOScoreboard("PerfTest", field_config, log=logger)

# ... run test ...

stats = perf_scoreboard.get_performance_stats()
print(f"Average Throughput: {stats['avg_throughput']:.2f} transactions/ns")
print(f"Average Latency: {stats['avg_latency']:.2f} ns")
```

### Custom Field Verification

When strict equality is the wrong check—a tolerance band on data, a checksum that has to hold—attach validators per field.

```python
# Custom field validation scoreboard
class CustomFIFOScoreboard(FIFOScoreboard):
    def __init__(self, name, field_config, custom_validators=None, log=None):
        super().__init__(name, field_config, log)
        self.custom_validators = custom_validators or {}
        self.validation_errors = {}
    
    def _compare_transactions(self, expected, actual):
        # Standard comparison
        basic_match = super()._compare_transactions(expected, actual)
        
        # Custom field validation
        validation_passed = True
        for field_name, validator in self.custom_validators.items():
            if field_name in expected.fields and field_name in actual.fields:
                try:
                    if not validator(expected.fields[field_name], actual.fields[field_name]):
                        validation_passed = False
                        self.validation_errors[field_name] = self.validation_errors.get(field_name, 0) + 1
                        if self.log:
                            self.log.error(f"Custom validation failed for field '{field_name}'")
                except Exception as e:
                    validation_passed = False
                    if self.log:
                        self.log.error(f"Validation error for field '{field_name}': {e}")
        
        return basic_match and validation_passed

# Custom validators
def validate_data_range(expected, actual):
    """Validate data is within acceptable range of expected value"""
    tolerance = 0x10  # Allow small variation
    return abs(expected - actual) <= tolerance

def validate_checksum(expected, actual):
    """Validate data checksum"""
    def calc_checksum(data):
        return (data ^ (data >> 16)) & 0xFFFF
    
    return calc_checksum(expected) == calc_checksum(actual)

# Usage
validators = {
    'data': validate_data_range,
    'checksum': validate_checksum
}

custom_scoreboard = CustomFIFOScoreboard(
    "CustomValidation", 
    field_config, 
    custom_validators=validators,
    log=logger
)
```

## Best Practices

### Field Configuration
- Field names should match the DUT interface; debugging across a rename is misery
- Keep naming consistent across components
- Write down what each field means and which values are legal

### Memory Model Integration
- Size the memory model for the test you're actually running
- Use realistic address patterns
- Clear memory between phases when stale contents would mislead the check

### Performance Optimization
- Efficient field comparison matters at high throughput
- Watch memory usage with large packet volumes
- Batch verification if per-packet overhead starts showing up

### Error Analysis
- Field-level logging first, waveform second
- Custom validators for domain rules equality can't express
- Keep packet history for temporal questions

## Integration Points

### Monitor Integration
```python
# Connect FIFO monitor to scoreboard
def on_fifo_packet(packet):
    scoreboard.add_actual(packet)

fifo_monitor.add_callback(on_fifo_packet)
```

### Test Sequence Integration
```python
# Generate expected packets from sequence
sequence = FIFOSequence("test_pattern", field_config)
for packet in sequence.generate():
    scoreboard.add_expected(packet)
```

### Coverage Integration

Field coverage falls out of the packets you've already seen:

```python
# Field coverage analysis
def analyze_field_coverage(scoreboard):
    field_values = {}
    for packet in scoreboard.get_all_packets():
        for field, value in packet.fields.items():
            if field not in field_values:
                field_values[field] = set()
            field_values[field].add(value)
    
    for field, values in field_values.items():
        coverage = len(values) / (2 ** field_config[field]) * 100
        print(f"Field '{field}' coverage: {coverage:.1f}%")
```

Field-configurable comparison for the packets themselves, a memory adapter for the data behind them—between the two, most FIFO verification questions have an answer here.
