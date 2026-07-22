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

# fifo_sequence.py

A sequence is just a list of transactions waiting to be turned into packets. FIFOSequence builds those lists — bursts, walking patterns, corner cases — so you don't hand-write every field value.

## Overview

The design here is deliberately simple. An earlier incarnation of this module tracked dependencies between transactions and tried to model FIFO state internally. Both are gone, on purpose: sequences generate traffic patterns. Whether that traffic was *correct* is the scoreboard's job, and the scoreboard already does it. What's left is the part that was actually useful:

- A plain list of transactions instead of a dependency graph
- Built-in pattern generation (incremental, walking bits, random, corner cases)
- PacketFactory and FieldConfig doing the packet work, as they do everywhere else
- Factory methods for the test batteries everyone ends up writing
- FIFO-flavored knobs (capacity, back-pressure) to shape realistic traffic

### Key Features
- **Simple transaction management**: a list, not a graph
- **Pattern generation**: the classic FIFO patterns are one method call each
- **Factory methods**: prebuilt sequences for burst, stress, capacity, and corner-case testing
- **Randomization support**: master/slave FlexRandomizers applied to every generated packet
- **Multi-field aware**: the sequence carries the FieldConfig, so packets come out fully structured
- **FIFO parameters**: capacity and back-pressure shape the traffic

## Core Class

### FIFOSequence

Simplified FIFO sequence generator focused on core functionality.

#### Constructor

```python
FIFOSequence(name="basic", field_config=None, packet_class=FIFOPacket, log=None)
```

**Parameters:**
- `name`: Sequence name for identification and logging
- `field_config`: Field configuration (FieldConfig object, dict, or None for data-only)
- `packet_class`: Packet class to use (default: FIFOPacket)
- `log`: Logger instance

**Properties:**
- `name`: Sequence identifier
- `field_config`: Normalized FieldConfig object
- `packet_factory`: PacketFactory instance for creating packets
- `transactions`: List of (field_values, delay) tuples
- `use_random_selection`: Whether to use random selection from sequences
- `master_randomizer`: Optional randomizer for master interface timing
- `slave_randomizer`: Optional randomizer for slave interface timing

A sequence with no `field_config` generates data-only packets. Give it a FieldConfig and every generated packet carries the full field structure.

```python
from .fifo_sequence import FIFOSequence
from ..shared.field_config import FieldConfig

# Create basic sequence
sequence = FIFOSequence("test_sequence", log=log)

# Create sequence with field configuration
field_config = FieldConfig.create_standard(addr_width=32, data_width=32)
sequence = FIFOSequence("multi_field", field_config=field_config, log=log)
```

## Transaction Management

### `add_transaction(field_values=None, delay=0)`

Append one transaction. `delay` is in cycles, applied before the transaction goes out.

**Parameters:**
- `field_values`: Dictionary of field values (default: empty dict)
- `delay`: Delay in cycles before this transaction

**Returns:** Transaction index in sequence

```python
# Add single data transaction
sequence.add_transaction({'data': 0x12345678}, delay=0)

# Add multi-field transaction
sequence.add_transaction({
    'addr': 0x1000,
    'data': 0xDEADBEEF,
    'cmd': 0x2
}, delay=2)
```

### `add_data_value(data, delay=0)`

Shortcut for the common case — a data-only packet.

**Parameters:**
- `data`: Data value
- `delay`: Delay in cycles

**Returns:** Transaction index

```python
# Add simple data values
sequence.add_data_value(0xDEADBEEF)
sequence.add_data_value(0xCAFEBABE, delay=3)
```

## Randomization Control

### `set_randomizers(master_randomizer=None, slave_randomizer=None)`

Randomizers set here get attached to every packet the sequence generates.

**Parameters:**
- `master_randomizer`: FlexRandomizer for master interface
- `slave_randomizer`: FlexRandomizer for slave interface

**Returns:** Self for method chaining

```python
from ..shared.flex_randomizer import FlexRandomizer

# Create randomizers
master_rand = FlexRandomizer({'write_delay': ([(0, 5)], [1.0])})
slave_rand = FlexRandomizer({'read_delay': ([(0, 3)], [1.0])})

# Apply to sequence
sequence.set_randomizers(master_randomizer=master_rand, slave_randomizer=slave_rand)
```

### `set_random_selection(enable=True)`

Pick transactions at random instead of in order.

```python
sequence.set_random_selection(True)  # Enable random selection
```

### `set_fifo_parameters(capacity=8, back_pressure=0.0)`

Tell the sequence about the FIFO it's targeting so the traffic looks like something a real FIFO would see.

**Parameters:**
- `capacity`: FIFO capacity in entries
- `back_pressure`: Probability of back-pressure (0.0 to 1.0)

**Returns:** Self for method chaining

```python
sequence.set_fifo_parameters(capacity=16, back_pressure=0.1)
```

## Pattern Generation Methods

### `add_data_incrementing(count, start=0, step=1, delay=0)`

The bread-and-butter pattern: `count` values starting at `start`, stepping by `step`.

```python
# Add 10 incrementing values starting from 0x1000
sequence.add_data_incrementing(count=10, start=0x1000, step=1)
```

### `add_walking_ones(data_width=32, delay=0)`

A single 1 walks across the bus. The classic stuck-bit check.

```python
# Add walking ones for 16-bit data
sequence.add_walking_ones(data_width=16)
```

### `add_walking_zeros(data_width=32, delay=0)`

Same idea inverted: a single 0 in a sea of 1s.

```python
# Add walking zeros for 32-bit data
sequence.add_walking_zeros(data_width=32)
```

### `add_random_data(count, delay=0)`

What it says.

```python
# Add 20 random data values
sequence.add_random_data(count=20)
```

### `add_corner_cases(delay=0)`

The usual suspects: all-zeros, all-ones, alternating 5s, alternating As.

```python
# Add standard corner cases: 0x00000000, 0xFFFFFFFF, 0x55555555, 0xAAAAAAAA
sequence.add_corner_cases()
```

## Packet Generation

### `generate_packets(count=None, apply_fifo_metadata=True)`

Turn the transaction list into FIFOPackets. Randomizers and FIFO metadata get applied here.

**Parameters:**
- `count`: Number of packets to generate (None = all transactions)
- `apply_fifo_metadata`: Whether to apply FIFO metadata (compatibility flag)

**Returns:** List of generated FIFOPacket instances

```python
# Generate all packets
packets = sequence.generate_packets()

# Generate first 5 packets
packets = sequence.generate_packets(count=5)

# Use packets with master
for packet in packets:
    await master.send(packet)
```

## Factory Methods

### `create_burst(name="burst", count=10, start=0x1000, log=None)`

A run of incrementing data, back to back.

```python
burst_seq = FIFOSequence.create_burst(
    name="data_burst",
    count=16,
    start=0x2000,
    log=log
)
```

### `create_pattern_test(name="patterns", data_width=32, log=None)`

A prebuilt mix of the common patterns.

```python
pattern_seq = FIFOSequence.create_pattern_test(
    name="comprehensive_patterns",
    data_width=32,
    log=log
)
```

### `create_stress_test(name="stress", count=50, burst_size=10, log=None)`

Bursts with gaps between them — exercises fill/drain behavior instead of steady-state flow.

```python
stress_seq = FIFOSequence.create_stress_test(
    name="stress_test",
    count=100,
    burst_size=20,
    log=log
)
```

### `create_data_stress_test(name="data_stress", data_width=32, delay=1, log=None)`

Every data pattern the module knows, in one sequence.

```python
data_stress = FIFOSequence.create_data_stress_test(
    name="data_patterns",
    data_width=32,
    delay=2,
    log=log
)
```

### `create_comprehensive_test(name="comprehensive", field_config=None, packets_per_pattern=10, data_width=32, capacity=None, include_dependencies=True, log=None)`

The everything-bagel: multiple pattern families with knobs for pattern count, data width, and capacity.

```python
comprehensive_seq = FIFOSequence.create_comprehensive_test(
    name="full_test",
    field_config=field_config,
    packets_per_pattern=15,
    data_width=32,
    capacity=16,
    include_dependencies=True,
    log=log
)
```

### `create_capacity_test(name="capacity_test", capacity=8, log=None)`

Sized to push the FIFO right up against its capacity limits — watermark and full-boundary bugs live here.

```python
capacity_seq = FIFOSequence.create_capacity_test(
    name="capacity_boundary",
    capacity=32,
    log=log
)
```

### `create_corner_case_test(name="corner_cases", field_config=None, log=None)`

Just the ugly values.

```python
corner_seq = FIFOSequence.create_corner_case_test(
    name="edge_cases",
    field_config=field_config,
    log=log
)
```

### `create_dependency_chain(name="dependency_chain", count=5, data_start=0, data_step=1, delay=0, log=None)`

A simplified dependency chain — kept for tests written against the old API.

```python
dep_seq = FIFOSequence.create_dependency_chain(
    name="dependent_ops",
    count=8,
    data_start=0x5000,
    data_step=4,
    delay=1,
    log=log
)
```

## Utility Methods

### `clear()`

Drop all transactions so the sequence can be rebuilt.

```python
sequence.clear()  # Remove all transactions
```

### `get_stats()`

Name and transaction count — sequences deliberately don't know more than that.

**Returns:** Dictionary with sequence statistics

```python
stats = sequence.get_stats()
print(f"Sequence '{stats['sequence_name']}' has {stats['transaction_count']} transactions")
```

### `get_dependency_graph()`

A stub kept for backward compatibility with code that asks for one. There is no graph anymore.

**Returns:** Minimal dependency graph structure

```python
dep_graph = sequence.get_dependency_graph()
print(f"Transaction count: {dep_graph['transaction_count']}")
```

## Usage Patterns

### Basic Sequence Creation and Usage

Build a pattern mix, generate, send:

```python
# Create sequence with basic patterns
sequence = FIFOSequence("basic_test", log=log)

# Add various patterns
sequence.add_data_incrementing(10, start=0x1000)
sequence.add_walking_ones(16)
sequence.add_random_data(5)
sequence.add_corner_cases()

# Generate packets and run
packets = sequence.generate_packets()
for packet in packets:
    await master.send(packet)
```

### Multi-Field Sequence Testing

With a FieldConfig, `add_transaction` takes full field dictionaries:

```python
# Create field configuration
field_config = FieldConfig()
field_config.add_field(FieldDefinition("addr", 32, format="hex"))
field_config.add_field(FieldDefinition("data", 32, format="hex"))
field_config.add_field(FieldDefinition("cmd", 4, format="hex"))

# Create sequence with multi-field support
sequence = FIFOSequence("multi_field_test", field_config=field_config, log=log)

# Add multi-field transactions
sequence.add_transaction({
    'addr': 0x1000,
    'data': 0xDEADBEEF,
    'cmd': 0x2  # WRITE
})

sequence.add_transaction({
    'addr': 0x2000,
    'data': 0x0,
    'cmd': 0x1  # READ
}, delay=3)

# Generate and use packets
packets = sequence.generate_packets()
```

### Factory-Based Test Generation

A test suite is mostly a loop over factory-built sequences:

```python
class FIFOTestSuite:
    def __init__(self, master, slave, log):
        self.master = master
        self.slave = slave
        self.log = log
        
    async def run_pattern_tests(self):
        """Run comprehensive pattern tests"""
        # Create different test sequences
        sequences = [
            FIFOSequence.create_burst("burst", count=20, log=self.log),
            FIFOSequence.create_pattern_test("patterns", data_width=32, log=self.log),
            FIFOSequence.create_stress_test("stress", count=50, burst_size=10, log=self.log),
            FIFOSequence.create_corner_case_test("corners", log=self.log)
        ]
        
        for sequence in sequences:
            self.log.info(f"Running sequence: {sequence.name}")
            packets = sequence.generate_packets()
            
            for packet in packets:
                await self.master.send(packet)
                
            self.log.info(f"Completed sequence: {sequence.name} ({len(packets)} packets)")
    
    async def run_capacity_tests(self, fifo_capacity=16):
        """Run FIFO capacity boundary tests"""
        capacity_seq = FIFOSequence.create_capacity_test("capacity", capacity=fifo_capacity, log=self.log)
        packets = capacity_seq.generate_packets()
        
        for packet in packets:
            await self.master.send(packet)
```

### Randomized Sequence Testing

Randomizers plus FIFO parameters make the same patterns hit differently every run:

```python
# Create randomizers
master_randomizer = FlexRandomizer({
    'write_delay': ([(0, 0), (1, 5), (10, 20)], [0.6, 0.3, 0.1])
})

slave_randomizer = FlexRandomizer({
    'read_delay': ([(0, 1), (2, 8)], [0.8, 0.2])
})

# Create sequence with randomization
sequence = FIFOSequence("randomized_test", log=log)
sequence.set_randomizers(master_randomizer=master_randomizer, slave_randomizer=slave_randomizer)
sequence.set_fifo_parameters(capacity=32, back_pressure=0.05)

# Add patterns with varying delays
sequence.add_data_incrementing(20, start=0x8000, step=4, delay=0)
sequence.add_random_data(15, delay=1)

# Generate packets with randomization applied
packets = sequence.generate_packets()
```

### Custom Pattern Creation

When the factories don't fit, compose your own phases. This one alternates bursts with idle gaps — the shape that finds watermark bugs:

```python
def create_custom_test_sequence(name, field_config, log):
    """Create a custom test sequence for specific testing needs"""
    sequence = FIFOSequence(name, field_config=field_config, log=log)
    
    # Phase 1: Basic connectivity
    sequence.add_data_incrementing(5, start=0x100, step=1)
    
    # Phase 2: Walking patterns
    sequence.add_walking_ones(16, delay=1)
    sequence.add_walking_zeros(16, delay=1)
    
    # Phase 3: Random stress
    sequence.add_random_data(20, delay=0)
    
    # Phase 4: Corner cases
    sequence.add_corner_cases(delay=2)
    
    # Phase 5: Burst patterns
    for i in range(3):
        sequence.add_data_incrementing(8, start=0x2000 + i*0x100, step=1, delay=0)
        if i < 2:  # Gap between bursts
            sequence.add_data_value(0x0, delay=5)
    
    return sequence

# Usage
custom_seq = create_custom_test_sequence("custom_test", field_config, log)
packets = custom_seq.generate_packets()
```

## Integration with Command Handler

Sequences don't drive anything themselves — the command handler runs them:

```python
# Create sequence
sequence = FIFOSequence.create_comprehensive_test("full_test", log=log)

# Process through command handler
await command_handler.process_sequence(sequence)

# Or process individual packets
packets = sequence.generate_packets()
for packet in packets:
    await command_handler.send_packet_with_delay(packet, delay_cycles=packet.sequence_delay)
```

## Best Practices

### 1. **Use Factory Methods for Common Patterns**
They're the patterns everyone ends up writing anyway. Hand-build only when they don't fit:
```python
# Prefer factory methods over manual construction
burst_seq = FIFOSequence.create_burst("burst", count=20)  # Good
```

### 2. **Set Meaningful Sequence Names**
The name shows up in logs and stats. "seq2" helps nobody at 2 AM:
```python
# Use descriptive names for debugging
sequence = FIFOSequence("write_burst_test_phase1", log=log)
```

### 3. **Configure FIFO Parameters for Realistic Testing**
A capacity-16 sequence running against a capacity-256 FIFO won't stress what you think it stresses:
```python
sequence.set_fifo_parameters(capacity=actual_fifo_capacity, back_pressure=0.1)
```

### 4. **Use Appropriate Delays**
Bursts, then gaps, then bursts. Steady-state traffic finds steady-state bugs; the gaps find the rest:
```python
# Add delays between transaction groups
sequence.add_data_incrementing(10, start=0x1000, delay=0)  # Burst
sequence.add_data_value(0x0, delay=5)  # Gap
sequence.add_data_incrementing(10, start=0x2000, delay=0)  # Next burst
```

### 5. **Leverage Randomization for Comprehensive Testing**
Directed patterns find the bugs you suspected. Randomized timing finds the ones you didn't:
```python
sequence.set_randomizers(master_randomizer=master_rand, slave_randomizer=slave_rand)
```

### 6. **Clear Sequences When Reusing**
```python
sequence.clear()  # Clear before adding new patterns
```

Keep sequences dumb: they generate traffic, not verdicts. That split is what makes them easy to write, easy to read, and easy to throw away.
