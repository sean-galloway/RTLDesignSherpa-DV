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

# fifo_master.py

The write side of a FIFO testbench. FIFOMaster takes the packets you hand it and pushes them into the DUT, backing off when `full` asserts so you never write into a FIFO that can't take it. It inherits the shared plumbing from FIFOComponentBase while keeping the original component's API and timing.

## Overview

Under the hood it's a cocotb BusDriver plus the FIFO base. You create packets, call `send()`, and the master handles queuing, `full`-signal flow control, and — if you want — randomized gaps between writes. Statistics accumulate the whole time, so when the test ends you already know your throughput, latency, and stall count.

### Key Features
- **Transaction queuing**: `send()` queues and pipelines writes; you don't touch the handshakes
- **Flow control built in**: `full` is watched every cycle — writes pause and resume automatically, and stalls are counted
- **Randomized timing**: attach a FlexRandomizer to vary write delays from back-to-back to long gaps
- **Memory integration**: writes can be mirrored into a MemoryModel for later checking
- **Real statistics**: transactions sent, success rate, average latency, throughput, timeouts, protocol violations
- **Both signal modes**: packed data bus or one signal per field

## Core Class

### FIFOMaster

FIFO Master component for driving write transactions.

#### Constructor

```python
FIFOMaster(dut, title, prefix, clock, field_config,
           timeout_cycles=1000, mode='fifo_mux',
           bus_name='',
           pkt_prefix='',
           multi_sig=False,
           randomizer=None, log=None, super_debug=False,
           signal_map=None, **kwargs)
```

**Parameters:**
- `dut`: Device under test
- `title`: Component title/name
- `prefix`: Bus prefix for signal naming
- `clock`: Clock signal
- `field_config`: Field configuration (FieldConfig object or dict)
- `timeout_cycles`: Cycles to wait for `full` to clear before giving up (default: 1000)
- `mode`: FIFO mode ('fifo_mux', 'fifo_flop')
- `bus_name`: Bus/channel name
- `pkt_prefix`: Packet field prefix
- `multi_sig`: Whether using multi-signal mode
- `randomizer`: Optional randomizer for write delays
- `log`: Logger instance
- `super_debug`: Enable detailed debugging
- `signal_map`: Optional manual signal mapping
- `**kwargs`: Additional arguments for BusDriver

The defaults are sane for a simple data-only FIFO. The knobs you'll actually reach for are `timeout_cycles`, `mode`, `multi_sig`, and `randomizer`.

**Example:**
```python
# Basic FIFO master
master = FIFOMaster(
    dut=dut,
    title="WriteMaster",
    prefix="",
    clock=clock,
    field_config=field_config
)

# Advanced configuration
master = FIFOMaster(
    dut=dut,
    title="AdvancedMaster",
    prefix="",
    clock=clock,
    field_config=field_config,
    timeout_cycles=2000,
    mode='fifo_flop',
    multi_sig=True,
    randomizer=custom_randomizer,
    signal_map={'write': 'wr_en', 'full': 'fifo_full'}
)
```

## Core Methods

### Transaction Management

#### `async send(packet)`

The interface you want. Queue one packet; returns when the transfer completes.

**Parameters:**
- `packet`: FIFOPacket to send

**Returns:** True when transaction completes

```python
# Create and send packet
packet = master.create_packet(data=0xDEADBEEF)
await master.send(packet)
```

#### `async busy_send(transaction)`

Send a transaction and wait for completion — the older entry point, kept alongside `send()`.

**Parameters:**
- `transaction`: Transaction packet to send

```python
# Send with completion waiting
packet = FIFOPacket(field_config, addr=0x1000, data=0x12345678)
await master.busy_send(packet)
```

#### `create_packet(**field_values)`

Build a FIFOPacket from keyword field values. Fields you don't set take their defaults.

**Parameters:**
- `**field_values`: Field values to set in packet

**Returns:** FIFOPacket instance with specified values

```python
# Create packet with multiple fields
packet = master.create_packet(
    addr=0x1000,
    data=0xDEADBEEF,
    cmd=0x2
)

# Create simple data packet
packet = master.create_packet(data=0x12345678)
```

### Bus Control

#### `async reset_bus()`

Drop queued transactions and return the interface to idle.

```python
# Reset master and clear queues
await master.reset_bus()
```

#### `async wait_cycles(cycles)`

Exactly what it says — an idle helper for pacing tests.

**Parameters:**
- `cycles`: Number of cycles to wait

```python
# Wait for 10 cycles
await master.wait_cycles(10)
```

### Memory Operations

#### `async write_to_memory(packet)`

Mirror a packet into the attached MemoryModel.

**Parameters:**
- `packet`: Packet to write to memory

**Returns:** True if successful, False otherwise — failures here are usually an address-range problem.

```python
# Write to memory
packet = master.create_packet(addr=0x1000, data=0xDEADBEEF)
success = await master.write_to_memory(packet)
if success:
    log.info("Memory write successful")
```

#### `async read_from_memory(packet)`

Read the MemoryModel at the packet's address.

**Parameters:**
- `packet`: Packet with address to read from

**Returns:** Tuple of (success, data)

```python
# Read from memory
packet = master.create_packet(addr=0x1000)
success, data = await master.read_from_memory(packet)
if success:
    log.info(f"Read data: 0x{data:X}")
```

### Statistics and Monitoring

#### `get_stats()`

The full picture. Master counters live under `'master_stats'`; the FIFO base's counters are merged in alongside.

**Returns:** Dictionary containing all statistics

```python
stats = master.get_stats()

# Master-specific statistics
master_stats = stats['master_stats']
print(f"Transactions sent: {master_stats['transactions_sent']}")
print(f"Success rate: {master_stats['success_rate_percent']:.1f}%")
print(f"Average latency: {master_stats['average_latency_ms']:.2f}ms")
print(f"Current throughput: {master_stats['current_throughput_tps']:.1f} TPS")

# Component statistics
print(f"Transfer busy: {stats['transfer_busy']}")
print(f"Queue depth: {stats['queue_depth']}")

# Base statistics from FIFOComponentBase
print(f"Component type: {stats['component_type']}")
print(f"Signal mapping: {stats['signal_mapping_source']}")
```

## Usage Patterns

### Basic Write Operations

The smallest useful master test:

```python
# Set up master
field_config = FieldConfig.create_data_only(32)
master = FIFOMaster(dut, "Master", "", clock, field_config)

# Send single transaction
packet = master.create_packet(data=0x12345678)
await master.send(packet)

# Send multiple transactions
for i in range(10):
    packet = master.create_packet(data=0x1000 + i)
    await master.send(packet)
```

### Multi-Field Transactions

With `multi_sig=True` each field gets its own DUT signal. The packet API doesn't change.

```python
# Configure multi-field packets
field_config = FieldConfig()
field_config.add_field(FieldDefinition("addr", 32, format="hex"))
field_config.add_field(FieldDefinition("data", 32, format="hex"))
field_config.add_field(FieldDefinition("cmd", 4, format="hex"))

# Create master with multi-signal mode
master = FIFOMaster(
    dut=dut,
    title="MultiFieldMaster",
    prefix="",
    clock=clock,
    field_config=field_config,
    multi_sig=True
)

# Send complex transactions
packet = master.create_packet(
    addr=0x1000,
    data=0xDEADBEEF,
    cmd=0x2  # WRITE command
)
await master.send(packet)
```

### Randomized Timing

The randomizer shapes the gaps between writes — mostly back-to-back for throughput, long tails for stress:

```python
# Create randomizer for write delays
write_randomizer = FlexRandomizer({
    'write_delay': ([(0, 0), (1, 5), (10, 20)], [0.6, 0.3, 0.1])
})

# Create master with randomized timing
master = FIFOMaster(
    dut=dut,
    title="RandomMaster",
    prefix="",
    clock=clock,
    field_config=field_config,
    randomizer=write_randomizer
)

# Sends will have randomized delays
for i in range(50):
    packet = master.create_packet(data=0x2000 + i)
    await master.send(packet)  # Each send has random delay
```

### Memory-Integrated Testing

Attach a MemoryModel and every write can be checked against it later. It's the poor man's scoreboard, and often it's all you need:

```python
# Set up memory model
memory = MemoryModel(num_lines=256, bytes_per_line=4)

# Create master with memory integration
master = FIFOMaster(
    dut=dut,
    title="MemoryMaster",
    prefix="",
    clock=clock,
    field_config=field_config,
    memory_model=memory
)

# Transactions automatically written to memory
for addr in range(0x1000, 0x1100, 4):
    packet = master.create_packet(addr=addr, data=addr + 0x5000)
    await master.send(packet)
    
    # Verify memory write
    success = await master.write_to_memory(packet)
    assert success, f"Failed to write to memory at {addr:X}"

# Read back and verify
for addr in range(0x1000, 0x1100, 4):
    packet = master.create_packet(addr=addr)
    success, data = await master.read_from_memory(packet)
    assert success and data == addr + 0x5000
```

### High-Performance Batch Operations

For long runs, keep an eye on the stall counter — it tells you whether the DUT or the testbench is the bottleneck:

```python
class BatchMaster:
    def __init__(self, dut, clock, field_config):
        self.master = FIFOMaster(dut, "BatchMaster", "", clock, field_config)
        
    async def send_batch(self, packets, batch_size=10):
        """Send packets in batches for optimal performance"""
        for i in range(0, len(packets), batch_size):
            batch = packets[i:i+batch_size]
            
            # Send batch
            for packet in batch:
                await self.master.send(packet)
            
            # Check for flow control issues
            stats = self.master.get_stats()
            if stats['master_stats']['flow_control_stalls'] > 100:
                log.warning("High flow control stalls detected")
                # Adjust timing or batch size
                
    async def stress_test(self, count=1000):
        """High-throughput stress test"""
        packets = []
        for i in range(count):
            packet = self.master.create_packet(data=0x8000 + i)
            packets.append(packet)
        
        start_time = time.time()
        await self.send_batch(packets)
        end_time = time.time()
        
        # Analyze performance
        stats = self.master.get_stats()
        duration = end_time - start_time
        throughput = count / duration
        
        log.info(f"Stress test: {throughput:.1f} transactions/sec")
        log.info(f"Success rate: {stats['master_stats']['success_rate_percent']:.1f}%")
        log.info(f"Flow control stalls: {stats['master_stats']['flow_control_stalls']}")
```

### Error Handling and Recovery

Timeouts and retries: this pattern resets the bus between attempts so a wedged interface doesn't poison the next try.

```python
class RobustMaster:
    def __init__(self, dut, clock, field_config):
        self.master = FIFOMaster(
            dut=dut,
            title="RobustMaster",
            prefix="",
            clock=clock,
            field_config=field_config,
            timeout_cycles=2000  # Longer timeout for problematic interfaces
        )
        self.error_count = 0
        
    async def robust_send(self, packet, max_retries=3):
        """Send with retry on failure"""
        for attempt in range(max_retries + 1):
            try:
                await self.master.send(packet)
                return True
                
            except Exception as e:
                self.error_count += 1
                log.warning(f"Send attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries:
                    # Reset bus and retry
                    await self.master.reset_bus()
                    await self.master.wait_cycles(10)
                else:
                    log.error(f"All {max_retries + 1} attempts failed")
                    return False
        
        return False
    
    async def monitored_send(self, packet):
        """Send with continuous monitoring"""
        stats_before = self.master.get_stats()
        
        success = await self.robust_send(packet)
        
        stats_after = self.master.get_stats()
        
        # Check for new issues
        master_stats = stats_after['master_stats']
        prev_stats = stats_before['master_stats']
        
        new_violations = (master_stats['protocol_violations'] - 
                         prev_stats['protocol_violations'])
        new_timeouts = (master_stats['timeout_events'] - 
                       prev_stats['timeout_events'])
        
        if new_violations > 0:
            log.error(f"Protocol violations detected: {new_violations}")
        if new_timeouts > 0:
            log.error(f"Timeouts detected: {new_timeouts}")
            
        return success and new_violations == 0 and new_timeouts == 0
```

### Custom Signal Mapping

If the DUT names its signals `wr_en` / `almost_full` / `din`, don't rename the RTL — map them:

```python
# For non-standard FIFO interfaces
def create_custom_master(dut, clock, custom_signals):
    """Create master with custom signal naming"""
    
    # Map custom signals to expected names
    signal_map = {
        'write': custom_signals.get('write_enable', 'write'),
        'full': custom_signals.get('full_flag', 'full'),
        'data': custom_signals.get('write_data', 'data')
    }
    
    # Create field configuration
    field_config = FieldConfig.create_data_only(32)
    
    # Create master with custom mapping
    master = FIFOMaster(
        dut=dut,
        title="CustomMaster",
        prefix="",
        clock=clock,
        field_config=field_config,
        signal_map=signal_map,
        super_debug=True  # Enable for signal mapping debugging
    )
    
    return master

# Usage with custom interface
custom_signals = {
    'write_enable': 'wr_en',
    'full_flag': 'almost_full',
    'write_data': 'din'
}
master = create_custom_master(dut, clock, custom_signals)
```

## Performance Analysis

### Monitoring Performance

The stats are cumulative, so rates come from differences. Take snapshots during the run and diff them:

```python
class PerformanceAnalyzer:
    def __init__(self, master):
        self.master = master
        self.snapshots = []
        
    def take_snapshot(self):
        """Take performance snapshot"""
        stats = self.master.get_stats()
        snapshot = {
            'timestamp': time.time(),
            'stats': stats['master_stats'].copy()
        }
        self.snapshots.append(snapshot)
    
    def analyze_performance(self):
        """Analyze performance over time"""
        if len(self.snapshots) < 2:
            return {}
            
        recent = self.snapshots[-1]['stats']
        baseline = self.snapshots[0]['stats']
        
        analysis = {
            'total_transactions': recent['transactions_sent'],
            'success_rate': recent['success_rate_percent'],
            'average_latency_ms': recent['average_latency_ms'],
            'current_throughput_tps': recent['current_throughput_tps'],
            'flow_control_stalls': recent['flow_control_stalls'],
            'protocol_violations': recent['protocol_violations']
        }
        
        # Calculate rates since baseline
        time_diff = self.snapshots[-1]['timestamp'] - self.snapshots[0]['timestamp']
        if time_diff > 0:
            tx_diff = recent['transactions_sent'] - baseline['transactions_sent']
            analysis['average_rate_tps'] = tx_diff / time_diff
        
        return analysis

# Usage in test
analyzer = PerformanceAnalyzer(master)

# Take baseline snapshot
analyzer.take_snapshot()

# Run test operations
for i in range(1000):
    packet = master.create_packet(data=0x3000 + i)
    await master.send(packet)
    
    # Take periodic snapshots
    if i % 100 == 0:
        analyzer.take_snapshot()

# Final analysis
performance = analyzer.analyze_performance()
print(f"Test performance: {performance}")
```

## Error Conditions

### Flow Control Handling

The master handles `full` itself: it drops `write`, waits for `full` to clear, and resumes where it left off. Every stall is counted, so a DUT that starves the master shows up in the numbers even when the test passes.

```python
# Master will:
# 1. Detect full signal assertion
# 2. Deassert write signal
# 3. Wait for full signal to deassert
# 4. Resume writing
# 5. Track flow control stalls in statistics

# Monitor flow control in your test
stats = master.get_stats()
if stats['master_stats']['flow_control_stalls'] > expected_threshold:
    log.warning("Excessive flow control stalls detected")
```

### Timeout Protection

If `full` never clears, the master gives up after `timeout_cycles` and records a timeout event:

```python
# Configure timeout for problematic interfaces
master = FIFOMaster(
    dut=dut,
    title="TimeoutProtectedMaster",
    prefix="",
    clock=clock,
    field_config=field_config,
    timeout_cycles=5000  # Wait up to 5000 cycles for not-full
)

# Timeouts are automatically tracked in statistics
stats = master.get_stats()
timeout_count = stats['master_stats']['timeout_events']
```

## Best Practices

### 1. **Use Factory Functions**
`create_fifo_master` wires up the boilerplate the same way every time:
```python
# Recommended - use factory for setup
master = create_fifo_master(dut, "Master", clock, field_config)

# Rather than direct instantiation
```

### 2. **Monitor Statistics Regularly**
Watch the success rate, not just pass/fail. A master limping along at 90% is telling you something:
```python
# Check performance periodically
if cycle % 1000 == 0:
    stats = master.get_stats()
    if stats['master_stats']['success_rate_percent'] < 95:
        log.warning("Low success rate detected")
```

### 3. **Use Appropriate Randomizers**
Match the randomizer to the purpose of the test. Throughput runs want mostly zero-delay writes; stress runs want ugly gaps:
```python
# For high-throughput testing
fast_randomizer = FlexRandomizer({
    'write_delay': ([(0, 0), (1, 1)], [9, 1])  # Mostly back-to-back
})

# For stress testing
stress_randomizer = FlexRandomizer({
    'write_delay': ([(0, 2), (5, 20), (50, 100)], [5, 3, 1])  # Variable delays
})
```

### 4. **Handle Memory Integration**
If you attached a model, check the results:
```python
# Always check memory operations
if master.memory_model:
    success = await master.write_to_memory(packet)
    if not success:
        log.error("Memory write failed")
```

### 5. **Reset Between Test Phases**
Stale queue state is a classic source of "passes alone, fails in the suite":
```python
# Reset master state between test phases
await master.reset_bus()
```

That's the master: hand it packets, let it deal with `full`, and read the stats when the dust settles.
