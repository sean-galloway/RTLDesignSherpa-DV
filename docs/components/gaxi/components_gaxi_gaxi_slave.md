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

# gaxi_slave.py

The receiving half of a GAXI interface — but not a passive one. The slave drives ready, so it owns backpressure, and it captures data with timing that depends on how the DUT implements its side of the interface. Pick the wrong capture mode and every packet looks shifted by a cycle; the modes exist because real FIFO interfaces genuinely differ.

## Overview

The `GAXISlave` class provides:
- **Three-phase receive pipeline** with per-phase debugging and error recovery
- **Active ready driving** with randomized delay — this is your backpressure knob
- **Three capture modes** matching the common DUT implementations (skid, fifo_mux, fifo_flop)
- **Memory model integration** using the base MemoryModel directly
- **Statistics** covering both the receive side and the pipeline internals
- **Pipeline debugging** you can toggle at runtime

Inherits from GAXIMonitorBase which provides common monitoring functionality and signal resolution.

## Class

### GAXISlave

```python
class GAXISlave(GAXIMonitorBase):
    def __init__(self, dut, title, prefix, clock, field_config,
                 timeout_cycles=1000, mode='skid', bus_name='', pkt_prefix='',
                 multi_sig=False, randomizer=None, memory_model=None,
                 log=None, super_debug=False, pipeline_debug=False,
                 signal_map=None, protocol_type='gaxi_slave', **kwargs)
```

**Parameters:**
- `dut`: Device under test
- `title`: Component title/name
- `prefix`: Bus prefix
- `clock`: Clock signal
- `field_config`: Field configuration
- `timeout_cycles`: Timeout for operations (default: 1000)
- `mode`: GAXI mode ('skid', 'fifo_mux', 'fifo_flop')
- `bus_name`: Bus/channel name
- `pkt_prefix`: Packet field prefix
- `multi_sig`: Whether using multi-signal mode
- `randomizer`: Optional randomizer for ready delays
- `memory_model`: Optional memory model for transactions
- `log`: Logger instance (required — raises ValueError if None; pass your TBBase logger)
- `super_debug`: Enable detailed debugging
- `pipeline_debug`: Enable pipeline phase debugging
- `signal_map`: Optional manual signal mapping override
- `**kwargs`: Additional arguments

## Data Capture Modes

The mode tells the slave when the DUT's data is actually valid relative to the handshake:

### Skid Mode (`mode='skid'`)
- **Data capture**: same cycle as the handshake
- The common case — an elastic or skid-buffered interface has stable data at the handshake
- Fastest response time

### FIFO MUX Mode (`mode='fifo_mux'`)
- **Data capture**: same cycle as the handshake
- For a multiplexed FIFO interface where data is combinatorially selected

### FIFO FLOP Mode (`mode='fifo_flop'`)
- **Data capture**: one cycle after the handshake
- For a registered FIFO interface — the output flop means new data shows up the cycle after the handshake, so capturing early records whatever was on the bus before

## Core Methods

### Bus Management

#### `async reset_bus()`
Reset bus with enhanced pipeline state management.

```python
await slave.reset_bus()
```

### Callback Management

#### `add_callback(callback)`
Register a function to run on every received transaction. This is where your checking lives.

**Parameters:**
- `callback`: Function to call when transaction is received

```python
def transaction_handler(packet):
    print(f"Received: {packet.formatted()}")

slave.add_callback(transaction_handler)
```

#### `remove_callback(callback)`
Remove callback.

```python
slave.remove_callback(transaction_handler)
```

### Data Access

#### `get_observed_packets(count=None)`
Read packets out of the receive queue.

**Parameters:**
- `count`: Number of packets to return (None = all)

**Returns:** List of observed packets

```python
# Get all observed packets
all_packets = slave.get_observed_packets()

# Get last 5 packets
recent_packets = slave.get_observed_packets(5)
```

#### `clear_observed_packets()`
Clear the observed packets queue.

```python
slave.clear_observed_packets()
```

### Pipeline Control and Debugging

#### `enable_pipeline_debug(enable=True)`
Turn pipeline debugging on or off at runtime.

```python
# Enable detailed pipeline logging
slave.enable_pipeline_debug(True)

# Disable for performance
slave.enable_pipeline_debug(False)
```

#### `get_pipeline_stats()`
Per-phase counters, including how many captures happened immediately versus deferred — a quick sanity check that your mode matches the DUT.

**Returns:** Dictionary with pipeline statistics

```python
pipeline_stats = slave.get_pipeline_stats()
print(f"Current state: {pipeline_stats['current_state']}")
print(f"Handshakes: {pipeline_stats['handshake_count']}")
print(f"Immediate captures: {pipeline_stats['immediate_captures']}")
print(f"Deferred captures: {pipeline_stats['deferred_captures']}")
```

#### `get_pipeline_debug_info()`
The detailed view: current state, phase timings, mode.

```python
debug_info = slave.get_pipeline_debug_info()
print(f"Phase timings: {debug_info['phase_timings']}")
print(f"Mode: {debug_info['mode']}")
```

### Statistics

#### `get_stats()`
Everything: slave-side counters, pipeline stats, and the base monitor stats in one dictionary.

**Returns:** Dictionary containing all statistics

```python
stats = slave.get_stats()
print(f"Monitor stats: {stats['slave_stats']}")
print(f"Pipeline stats: {stats['pipeline_stats']}")
print(f"Base stats: {stats}")
```

## Pipeline Architecture

The GAXISlave uses a structured 3-phase receive pipeline:

### Phase 1: Handle Pending Transactions
- Retire deferred captures from fifo_flop mode — the data from last cycle's handshake is valid now
- Runs first so deferred work never stacks up

### Phase 2: Ready Timing Control
- Pulls `ready_delay` from the randomizer and holds ready low for that many cycles
- Raises ready when the delay expires
- This phase is your backpressure generator

### Phase 3: Transaction Processing
- Watches for the valid/ready handshake
- Builds the packet and stamps the time
- Captures data immediately or defers it, per the mode
- Runs memory operations and fires callbacks

### Pipeline State Tracking
```python
# Pipeline states
"idle" → "monitor_start" → "cycle_start" → "phase1" → 
"phase2" → "phase3" → "cycle_end" → "cycle_start" ...

# Error states  
"error_recovery", "reset"
```

## Usage Patterns

### Basic Usage

```python
import cocotb
from cocotb.triggers import RisingEdge
from CocoTBFramework.components.gaxi import GAXISlave
from CocoTBFramework.components.shared.field_config import FieldConfig

@cocotb.test()
async def test_gaxi_slave(dut):
    clock = dut.clk
    
    # Create field configuration
    field_config = FieldConfig()
    field_config.add_field(FieldDefinition("addr", 32, format="hex"))
    field_config.add_field(FieldDefinition("data", 32, format="hex"))
    
    # Create slave
    slave = GAXISlave(
        dut=dut,
        title="TestSlave",
        prefix="",
        clock=clock,
        field_config=field_config,
        mode='skid',
        log=log,             # Required
        pipeline_debug=True  # Enable pipeline debugging
    )
    
    # Add callback to process transactions
    def process_transaction(packet):
        print(f"Slave received: addr=0x{packet.addr:X}, data=0x{packet.data:X}")
    
    slave.add_callback(process_transaction)
    
    # Reset bus
    await slave.reset_bus()
    
    # Start monitoring (automatically started)
    # Transactions will be captured and processed via callbacks
    
    # Wait for some transactions
    await Timer(1000, units='ns')
    
    # Check received transactions
    packets = slave.get_observed_packets()
    print(f"Received {len(packets)} transactions")
```

### Mode-Specific Configuration

Match the mode to the DUT's implementation, not to your preference:

```python
# Skid mode - immediate capture
skid_slave = GAXISlave(
    dut=dut,
    title="SkidSlave",
    prefix="s_",
    clock=clock,
    field_config=field_config,
    mode='skid'  # Immediate data capture
)

# FIFO FLOP mode - delayed capture  
flop_slave = GAXISlave(
    dut=dut,
    title="FlopSlave", 
    prefix="f_",
    clock=clock,
    field_config=field_config,
    mode='fifo_flop'  # Delayed data capture
)
```

### Advanced Configuration with Memory

```python
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer
from CocoTBFramework.components.shared.memory_model import MemoryModel

# Create randomizer for ready delays
randomizer = FlexRandomizer({
    'ready_delay': ([(0, 1), (2, 8), (9, 30)], [0.6, 0.3, 0.1])
})

# Create memory model for transaction storage
memory = MemoryModel(num_lines=1024, bytes_per_line=4, log=log)

# Create slave with advanced configuration
slave = GAXISlave(
    dut=dut,
    title="AdvancedSlave",
    prefix="adv_",
    clock=clock,
    field_config=field_config,
    randomizer=randomizer,
    memory_model=memory,
    mode='fifo_mux',
    pipeline_debug=True,
    multi_sig=True
)
```

### Memory-Integrated Processing

With a memory model attached, writes that arrive at the slave get stored as part of the pipeline — no callback code needed for basic storage.

```python
@cocotb.test()
async def test_memory_slave(dut):
    # Create memory model
    memory = MemoryModel(num_lines=256, bytes_per_line=4, log=log)
    
    # Create slave with memory
    slave = GAXISlave(
        dut=dut,
        title="MemorySlave",
        prefix="",
        clock=clock,
        field_config=field_config,
        memory_model=memory
    )
    
    # Memory operations happen automatically in the pipeline
    # Check memory contents after transactions
    await Timer(1000, units='ns')
    
    # Get memory statistics
    stats = slave.get_stats()
    if 'memory_stats' in stats:
        memory_stats = stats['memory_stats']
        print(f"Memory writes: {memory_stats['writes']}")
        print(f"Memory coverage: {memory_stats['write_coverage']:.1%}")
```

### Pipeline Performance Analysis

```python
@cocotb.test()
async def test_pipeline_performance(dut):
    slave = GAXISlave(dut, "PerfSlave", "", clock, field_config,
                     pipeline_debug=True)
    
    # Run for a period
    await Timer(10000, units='ns')
    
    # Analyze pipeline performance
    pipeline_stats = slave.get_pipeline_stats()
    
    print(f"Pipeline Performance Analysis:")
    print(f"  Total handshakes: {pipeline_stats['handshake_count']}")
    print(f"  Immediate captures: {pipeline_stats['immediate_captures']}")
    print(f"  Deferred captures: {pipeline_stats['deferred_captures']}")
    print(f"  Memory operations: {pipeline_stats['memory_operations']}")
    print(f"  Errors: {pipeline_stats['error_count']}")
    
    # Calculate efficiency metrics
    total_captures = (pipeline_stats['immediate_captures'] + 
                     pipeline_stats['deferred_captures'])
    if total_captures > 0:
        immediate_rate = pipeline_stats['immediate_captures'] / total_captures
        print(f"  Immediate capture rate: {immediate_rate:.1%}")
    
    # Get timing information
    debug_info = slave.get_pipeline_debug_info()
    for phase, timing in debug_info['phase_timings'].items():
        print(f"  {phase}: {timing}ns")
```

### Ready Delay Testing

```python
@cocotb.test()
async def test_ready_delays(dut):
    # Create randomizer with specific delay patterns
    randomizer = FlexRandomizer({
        'ready_delay': ([(0, 0), (1, 1), (5, 10)], [0.5, 0.3, 0.2])
    })
    
    slave = GAXISlave(
        dut=dut,
        title="DelayedSlave",
        prefix="",
        clock=clock,
        field_config=field_config,
        randomizer=randomizer,
        pipeline_debug=True
    )
    
    # Track ready signal behavior
    ready_assert_times = []
    ready_delays = []
    
    def track_ready_timing(packet):
        # This callback is called when transaction completes
        # Can analyze timing here
        pass
    
    slave.add_callback(track_ready_timing)
    
    # Monitor for a period
    await Timer(5000, units='ns')
    
    # Analyze ready delay effectiveness
    pipeline_stats = slave.get_pipeline_stats()
    print(f"Ready delay testing: {pipeline_stats['handshake_count']} handshakes")
```

### Callback-Based Processing

```python
class TransactionProcessor:
    def __init__(self):
        self.received_count = 0
        self.data_sum = 0
        
    def process_transaction(self, packet):
        """Callback for processing received transactions"""
        self.received_count += 1
        self.data_sum += packet.data
        
        print(f"Transaction {self.received_count}: "
              f"addr=0x{packet.addr:X}, data=0x{packet.data:X}")
        
        # Perform application-specific processing
        if packet.addr >= 0x8000:
            print("  → High address region access")
        
        if packet.data == 0xDEADBEEF:
            print("  → Test pattern detected")
    
    def get_summary(self):
        avg_data = self.data_sum / self.received_count if self.received_count > 0 else 0
        return {
            'received_count': self.received_count,
            'average_data': avg_data
        }

@cocotb.test()
async def test_callback_processing(dut):
    # Create processor
    processor = TransactionProcessor()
    
    # Create slave with callback
    slave = GAXISlave(dut, "CallbackSlave", "", clock, field_config)
    slave.add_callback(processor.process_transaction)
    
    # Run test
    await Timer(2000, units='ns')
    
    # Get processing summary
    summary = processor.get_summary()
    print(f"Processing summary: {summary}")
```

### Error Handling and Recovery

```python
@cocotb.test()
async def test_error_recovery(dut):
    slave = GAXISlave(dut, "ErrorSlave", "", clock, field_config,
                     pipeline_debug=True)
    
    # Callback that might cause errors
    def error_prone_callback(packet):
        if packet.data == 0xBADDATA:
            raise ValueError("Bad data detected")
        print(f"Processed: {packet.formatted()}")
    
    slave.add_callback(error_prone_callback)
    
    try:
        # Run test
        await Timer(1000, units='ns')
        
    except Exception as e:
        log.error(f"Test error: {e}")
        
        # Check pipeline state
        debug_info = slave.get_pipeline_debug_info()
        print(f"Pipeline state: {debug_info['current_state']}")
        
        # Pipeline should continue operating despite callback errors
        pipeline_stats = slave.get_pipeline_stats()
        print(f"Error count: {pipeline_stats['error_count']}")
        
        # Reset if needed
        await slave.reset_bus()
```

## Error Handling

### Signal Mapping Errors
```python
try:
    slave = GAXISlave(dut, "Slave", "", clock, field_config)
except RuntimeError as e:
    # Try manual signal mapping
    signal_map = {'valid': 'custom_valid', 'ready': 'custom_ready'}
    slave = GAXISlave(dut, "Slave", "", clock, field_config,
                     signal_map=signal_map)
```

### Memory Operation Errors

Memory failures are logged and counted, not raised — the receive pipeline keeps running. Check the memory stats if contents look wrong.

```python
# Memory operations handled automatically with error logging
# Check memory statistics for error information
stats = slave.get_stats()
if 'memory_stats' in stats:
    memory_stats = stats['memory_stats']
    if memory_stats['boundary_violations'] > 0:
        log.warning(f"Memory boundary violations: {memory_stats['boundary_violations']}")
```

### Pipeline Errors
```python
# Pipeline errors are tracked in statistics
pipeline_stats = slave.get_pipeline_stats()
if pipeline_stats['error_count'] > 0:
    log.warning(f"Pipeline errors detected: {pipeline_stats['error_count']}")
    
    # Get detailed error information
    debug_info = slave.get_pipeline_debug_info()
    print(f"Current state: {debug_info['current_state']}")
```

## Best Practices

### 1. **Match the Mode to the DUT**

The one configuration choice that actually matters. Get it wrong and your data is off by a cycle everywhere.

```python
# Match slave mode to DUT implementation
if dut_uses_registered_interface:
    mode = 'fifo_flop'  # Delayed capture
else:
    mode = 'skid'       # Immediate capture
```

### 2. **Use Callbacks, Not Polling**
```python
# Prefer callbacks over polling
slave.add_callback(process_transaction)

# Avoid polling _recvQ directly
# packets = slave._recvQ  # Don't do this
packets = slave.get_observed_packets()  # Do this instead
```

### 3. **Enable Pipeline Debugging During Development**
```python
slave = GAXISlave(..., pipeline_debug=True)   # Development
slave = GAXISlave(..., pipeline_debug=False)  # Production
```

### 4. **Tune Ready Delays to the Test's Intent**

Zero delay measures throughput; nonzero delay measures the master's manners. You need both.

```python
# For throughput testing
randomizer = FlexRandomizer({'ready_delay': ([(0, 0)], [1.0])})

# For realistic backpressure
randomizer = FlexRandomizer({
    'ready_delay': ([(0, 1), (2, 8)], [0.7, 0.3])
})
```

### 5. **Monitor Pipeline Statistics**
```python
# Regular statistics monitoring
if transaction_count % 100 == 0:
    pipeline_stats = slave.get_pipeline_stats()
    if pipeline_stats['error_count'] > expected_threshold:
        handle_error_condition()
```

Set the mode to match the DUT, hang your checking off `add_callback()`, and keep `pipeline_debug` off in regressions. And do use the ready delays at least some of the time — a master that only ever runs unthrottled is a master whose backpressure handling nobody has tested.
