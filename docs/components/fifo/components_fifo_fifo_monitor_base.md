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

# fifo_monitor_base.py

The shared plumbing behind FIFOMonitor and FIFOSlave. Both need to collect data, finish packets, update statistics, and talk to memory — this base does all of it once, so the two components can't drift apart.

## Overview

FIFOMonitorBase combines FIFOComponentBase with cocotb's BusMonitor. A pure monitor and an active slave turn out to need almost exactly the same machinery — the only real difference is that the slave also drives `read`. So the machinery lives here, and the subclasses keep only what makes them different.

### Key Features
- **One data collection path**: field unpacking happens in the strategy, not in per-component conditionals
- **One way to finish a packet**: timestamps, queue, stats, callbacks — no per-component variations
- **Memory hooks**: read/write through the MemoryModel with no extra wiring
- **Standard cocotb behavior**: packets land in `_recvQ`, callbacks fire as usual

## Core Class

### FIFOMonitorBase

Base class providing common FIFO monitoring functionality.

#### Constructor

```python
FIFOMonitorBase(dut, title, prefix, clock, field_config,
                mode='fifo_mux',
                bus_name='',
                pkt_prefix='',
                multi_sig=False,
                protocol_type=None,  # 'fifo_master' or 'fifo_slave' - set by subclass
                log=None, super_debug=False,
                signal_map=None, **kwargs)
```

**Parameters:**
- `dut`: Device under test
- `title`: Component title/name
- `prefix`: Bus prefix for signal naming
- `clock`: Clock signal
- `field_config`: Field configuration (FieldConfig object or dict)
- `mode`: FIFO mode ('fifo_mux', 'fifo_flop')
- `bus_name`: Bus/channel name
- `pkt_prefix`: Packet field prefix
- `multi_sig`: Whether using multi-signal mode
- `protocol_type`: Must be set by subclass ('fifo_master' or 'fifo_slave')
- `log`: Logger instance
- `super_debug`: Enable detailed debugging
- `signal_map`: Optional manual signal mapping
- `**kwargs`: Additional arguments for BusMonitor

**Note:** You won't instantiate this directly — use FIFOMonitor or FIFOSlave. This page exists so you know where their shared behavior comes from.

## Core Methods

### Data Collection (Unified)

#### `_get_data_dict()`

One call that returns the current signal values unpacked into fields. The multi-signal/packed distinction lives inside the strategy, not here.

**Returns:** Dictionary of field values, properly unpacked

```python
# Used internally by subclasses
data_dict = self._get_data_dict()
# Returns: {'addr': 0x1000, 'data': 0xDEADBEEF, 'cmd': 0x2}
```

Subclasses call this; your testbench probably never will. It replaced a pile of conditional unpacking logic that used to be duplicated, slightly differently, in every component.

### Packet Processing (Unified)

#### `_finish_packet(current_time, packet, data_dict=None)`

Everything that happens when a transaction completes, in one place: fields populated, end time stamped, packet pushed to `_recvQ`, stats updated, callbacks fired.

**Parameters:**
- `current_time`: Current simulation time
- `packet`: Packet to finish
- `data_dict`: Optional field data (if None, will collect fresh data)

```python
# Used internally by subclasses
packet = FIFOPacket(self.field_config)
packet.start_time = start_time

# Later, when transaction completes
current_time = cocotb.utils.get_sim_time('ns')
self._finish_packet(current_time, packet)

# Packet is automatically:
# 1. Populated with current field data
# 2. Given end_time timestamp
# 3. Added to cocotb _recvQ
# 4. Statistics updated
# 5. Callbacks triggered
```

Every monitoring component used to implement its own version of this, each with slightly different quirks. That went about as well as you'd expect.

### Packet Management

#### `create_packet(**field_values)`

Create a packet with specified field values.

**Parameters:**
- `**field_values`: Initial field values

**Returns:** FIFOPacket instance with specified field values

```python
# Create packet for testing or comparison
test_packet = monitor_base.create_packet(
    addr=0x1000,
    data=0xDEADBEEF,
    cmd=0x2
)
```

#### `get_observed_packets(count=None)`

Pull observed packets from the standard cocotb `_recvQ`.

**Parameters:**
- `count`: Number of packets to return (None = all)

**Returns:** List of observed packets

```python
# Get all observed packets
all_packets = monitor_base.get_observed_packets()

# Get last 5 packets
recent_packets = monitor_base.get_observed_packets(count=5)
```

#### `clear_queue()`

Empty the observation queue, using the standard cocotb pattern. Do it between test phases.

```python
# Clear accumulated observations
monitor_base.clear_queue()
```

### Memory Operations (Unified)

#### `handle_memory_write(packet)`

Push a packet's data into the attached MemoryModel.

**Parameters:**
- `packet`: Packet to write to memory

**Returns:** True if successful, False otherwise

```python
# Used by slave components for automatic memory storage
success = self.handle_memory_write(packet)
if success:
    log.debug("Memory write successful")
```

#### `handle_memory_read(packet)`

Fetch expected data for a packet's address. The slave uses this for memory-backed responses and checking.

**Parameters:**
- `packet`: Packet with address to read from

**Returns:** Tuple of (success, data)

```python
# Used by slave components for memory-based responses
success, data = self.handle_memory_read(packet)
if success:
    log.debug(f"Memory read successful, data=0x{data:X}")
```

### Statistics

#### `get_base_stats()`

One dict: component config, signal resolution, data strategy performance, memory stats, monitor counters, observed packet count.

**Returns:** Dictionary containing base statistics

```python
base_stats = monitor_base.get_base_stats()

# Includes:
# - Component configuration (component_type, mode, multi_signal, etc.)
# - Signal resolver statistics
# - Data strategy performance metrics
# - Memory model statistics (if available)
# - Monitor statistics (transactions_observed, protocol_violations, etc.)
# - Observed packet count
```

## Internal Implementation

### Unified Data Collection

Here's the before-and-after. The old version of this logic existed, near-identical, in two components:

```python
# OLD WAY (duplicated across components):
def get_data_dict_messy(self):
    data = {}
    if self.use_multi_signal:
        for field_name in self.field_config.field_names():
            signal = getattr(self, f"field_{field_name}_sig", None)
            if signal and signal.value.is_resolvable:
                data[field_name] = int(signal.value)
            else:
                data[field_name] = -1
    else:
        signal = getattr(self, "data_sig", None)
        if signal and signal.value.is_resolvable:
            combined_value = int(signal.value)
            # Complex unpacking logic...
        else:
            # Default values...
    return data

# NEW WAY (unified):
def _get_data_dict(self):
    return self.get_data_dict_unified()  # Single call, no conditionals!
```

One call. Which fields exist, whether they're resolvable, how to unpack them — all of that lives in the strategy, where it's tested once.

### Unified Packet Finishing

Same story for finishing packets. Two copies of the same logic, each with its own quirks, replaced by one implementation:

```python
# OLD WAY (duplicated with slight variations):
def finish_packet_messy(self, packet, data_dict):
    if data_dict:
        if hasattr(packet, 'unpack_from_fifo'):
            packet.unpack_from_fifo(data_dict)
        else:
            for field_name, value in data_dict.items():
                if value != -1:
                    if hasattr(packet, field_name):
                        setattr(packet, field_name, value)
    packet.end_time = current_time
    # Update statistics...
    # Add to queue...
    # Trigger callbacks...

# NEW WAY (unified):
def _finish_packet(self, current_time, packet, data_dict=None):
    # All logic centralized, consistent behavior guaranteed
```

## Usage Patterns

### Subclass Implementation

Writing a new monitoring component looks like this — the base does the heavy lifting, you decide what counts as a transaction:

```python
class MyFIFOComponent(FIFOMonitorBase):
    def __init__(self, dut, title, prefix, clock, field_config, **kwargs):
        # Initialize base with appropriate protocol_type
        super().__init__(
            dut=dut,
            title=title,
            prefix=prefix,
            clock=clock,
            field_config=field_config,
            protocol_type='fifo_master',  # or 'fifo_slave'
            **kwargs
        )
        
        # Component-specific initialization
        self.component_specific_setup()
    
    async def _monitor_recv(self):
        """Component-specific monitoring logic"""
        while True:
            await FallingEdge(self.clock)
            
            # Check for transaction
            if self.should_capture_transaction():
                # Create packet
                packet = FIFOPacket(self.field_config)
                packet.start_time = cocotb.utils.get_sim_time('ns')
                
                # Use unified data collection - no conditional mess!
                data_dict = self._get_data_dict()
                
                # Use unified packet finishing - consistent behavior!
                current_time = cocotb.utils.get_sim_time('ns')
                self._finish_packet(current_time, packet, data_dict)
    
    def should_capture_transaction(self):
        # Component-specific logic
        return True
```

### Clean Monitoring Loop

This is the point of the base class: the monitoring loop reads like what it does.

```python
# Example of clean monitoring implementation using base class
async def clean_monitor_recv(self):
    """Clean monitoring without conditional complexity"""
    try:
        while True:
            await FallingEdge(self.clock)
            current_time = cocotb.utils.get_sim_time('ns')
            
            # Check for valid transaction (component-specific)
            if self.detect_valid_transaction():
                # Create packet
                packet = FIFOPacket(self.field_config)
                packet.start_time = current_time
                
                # CLEAN: Single unified call for data collection
                data_dict = self._get_data_dict()
                
                # CLEAN: Single unified call for packet finishing
                self._finish_packet(current_time, packet, data_dict)
                
                # Handle memory operations if needed
                if self.memory_model:
                    self.handle_memory_write(packet)
    
    except Exception as e:
        self.log.error(f"Monitor error: {e}")
        raise
```

### Memory-Integrated Component

Add a MemoryModel and the unified handlers slot straight in:

```python
class MemoryIntegratedMonitor(FIFOMonitorBase):
    def __init__(self, dut, title, prefix, clock, field_config, memory_model, **kwargs):
        super().__init__(
            dut, title, prefix, clock, field_config,
            protocol_type='fifo_slave',  # Read side with memory
            memory_model=memory_model,
            **kwargs
        )
    
    async def _monitor_recv(self):
        """Monitor with automatic memory integration"""
        while True:
            await FallingEdge(self.clock)
            
            if self.detect_read_transaction():
                packet = FIFOPacket(self.field_config)
                packet.start_time = cocotb.utils.get_sim_time('ns')
                
                # Unified data collection
                data_dict = self._get_data_dict()
                
                # Unified packet finishing
                current_time = cocotb.utils.get_sim_time('ns')
                self._finish_packet(current_time, packet, data_dict)
                
                # Automatic memory handling - unified integration!
                if packet.cmd == 2:  # WRITE command
                    success = self.handle_memory_write(packet)
                    if not success:
                        self.log.warning("Memory write failed")
                elif packet.cmd == 1:  # READ command
                    success, data = self.handle_memory_read(packet)
                    if success:
                        # Verify read data matches memory
                        if hasattr(packet, 'data') and packet.data != data:
                            self.log.error(f"Data mismatch: packet=0x{packet.data:X}, memory=0x{data:X}")
```

### Statistics Collection

`get_base_stats()` gives you the standard counters; add your own on top:

```python
class StatisticsCollectingMonitor(FIFOMonitorBase):
    def __init__(self, dut, title, prefix, clock, field_config, **kwargs):
        super().__init__(dut, title, prefix, clock, field_config, **kwargs)
        self.custom_stats = {}
    
    async def _monitor_recv(self):
        """Monitor with enhanced statistics collection"""
        while True:
            await FallingEdge(self.clock)
            
            if self.detect_transaction():
                packet = FIFOPacket(self.field_config)
                packet.start_time = cocotb.utils.get_sim_time('ns')
                
                # Unified data collection
                data_dict = self._get_data_dict()
                
                # Custom statistics before packet finishing
                self.update_custom_stats(data_dict)
                
                # Unified packet finishing (includes standard statistics)
                current_time = cocotb.utils.get_sim_time('ns')
                self._finish_packet(current_time, packet, data_dict)
    
    def update_custom_stats(self, data_dict):
        """Update custom statistics"""
        if 'data' in data_dict and data_dict['data'] != -1:
            data_value = data_dict['data']
            
            # Track data patterns
            if data_value == 0:
                self.custom_stats['zero_data_count'] = self.custom_stats.get('zero_data_count', 0) + 1
            elif data_value == 0xFFFFFFFF:
                self.custom_stats['all_ones_count'] = self.custom_stats.get('all_ones_count', 0) + 1
    
    def get_stats(self):
        """Get enhanced statistics"""
        base_stats = self.get_base_stats()
        base_stats['custom_stats'] = self.custom_stats
        return base_stats
```

## Integration Benefits

### For FIFOMonitor

The monitor is this base plus a transaction detector. Nothing more:

```python
# FIFOMonitor inherits clean monitoring without any data handling complexity:
class FIFOMonitor(FIFOMonitorBase):
    async def _monitor_recv(self):
        # Focus only on monitoring logic
        # All data collection and packet processing handled by base class
        while True:
            await FallingEdge(self.clock)
            
            if self.is_valid_transaction():
                packet = FIFOPacket(self.field_config)
                packet.start_time = cocotb.utils.get_sim_time('ns')
                
                # Clean unified calls
                data_dict = self._get_data_dict()
                self._finish_packet(current_time, packet, data_dict)
```

### For FIFOSlave

The slave is this base plus read-signal driving. Same capture path as the monitor, which is exactly what you want — the two can't disagree about what a transaction looked like:

```python
# FIFOSlave inherits monitoring capabilities plus adds read signal control:
class FIFOSlave(FIFOMonitorBase):
    async def _monitor_recv(self):
        # Combines monitoring with active signal control
        while True:
            # Active read signal control
            await self.apply_read_delays()
            self.set_read_signal(1)
            
            await FallingEdge(self.clock)
            
            if self.is_valid_read():
                packet = FIFOPacket(self.field_config)
                packet.start_time = cocotb.utils.get_sim_time('ns')
                
                # Same clean unified calls as monitor
                data_dict = self._get_data_dict()
                self._finish_packet(current_time, packet, data_dict)
                
                # Additional slave-specific processing
                if self.memory_model:
                    self.handle_memory_write(packet)
```

## Performance Benefits

### Elimination of Code Duplication

Before this class existed, FIFOMonitor and FIFOSlave each carried about 150 lines of the same collection and packet-finishing code — call it 300 lines maintained in two places, free to drift apart. Now the base owns roughly 100 lines of shared logic, the monitor adds about 50 of its own, and the slave about 75. Fewer lines total, and none of them duplicated.

### Consistency Guarantee

Every monitoring component now collects data, finishes packets, updates stats, integrates memory, and handles errors the same way. When a monitor and a slave disagree about a transaction, it's a real difference — not an implementation artifact.

### Maintainability

One place to fix field unpacking, statistics, memory integration, and queue handling. A bug fixed here is fixed for everything that monitors.

## Best Practices

### 1. **Always Set protocol_type in Subclasses**
The base needs to know which side it's on:
```python
# Required in subclass __init__
super().__init__(
    ...,
    protocol_type='fifo_master',  # or 'fifo_slave'
    ...
)
```

### 2. **Use Unified Methods in Monitoring Loops**
That's what they're for. Bypassing them re-creates the mess this class cleaned up:
```python
# In _monitor_recv implementation:
data_dict = self._get_data_dict()  # Unified data collection
self._finish_packet(current_time, packet, data_dict)  # Unified finishing
```

### 3. **Leverage Memory Integration**
If a model is attached, use the handlers rather than poking the model directly:
```python
# If memory_model is available, use unified handlers
if self.memory_model:
    success = self.handle_memory_write(packet)
    success, data = self.handle_memory_read(packet)
```

### 4. **Use get_base_stats() in Subclasses**
Build your `get_stats()` on top of it so the standard counters never go missing:
```python
def get_stats(self):
    base_stats = self.get_base_stats()  # Gets all base statistics
    # Add component-specific statistics
    base_stats.update(my_custom_stats)
    return base_stats
```

### 5. **Call clear_queue() Between Test Phases**
```python
# Reset state between test phases
self.clear_queue()
```

If you're subclassing this, the contract is simple: implement `_monitor_recv`, call `_get_data_dict()` and `_finish_packet()`, and the rest is handled.
