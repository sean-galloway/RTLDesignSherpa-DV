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

# fifo_component_base.py

Shared base class for FIFOMaster, FIFOMonitor, and FIFOSlave. Signal resolution, data handling, memory access, and statistics all live here so the three components only implement them once — and so a fix lands in all three at the same time.

> **Deprecation note:** `FIFOComponentBase` is now a thin compatibility shim over
> [`GAXIComponentBase`](../gaxi/components_gaxi_gaxi_component_base.md) (see issue #6).
> The GAXI base is the canonical ready/valid component chassis and accepts
> `protocol_type='fifo_master'` / `'fifo_slave'` directly. The only behavioral
> delta in the shim is the default `mode='fifo_mux'` (vs. `'skid'` for GAXI).
> New code should subclass `GAXIComponentBase` directly; this shim will be
> removed in a future release. The functionality documented below is provided
> by the inherited GAXI base.

## Overview

Everything a FIFO component needs that isn't specific to writing or reading lives in this class: finding the DUT's signals, packing and unpacking fields, moving data to and from a MemoryModel, and keeping statistics. It sits on the shared framework pieces rather than re-implementing them, which is exactly why the deprecation note above points you at GAXIComponentBase — that's where all of this actually lives now.

### Key Features
- **Unified signal resolution**: automatic discovery against the DUT, with a manual `signal_map` override for interfaces that don't follow the expected naming
- **Cached for speed**: signal handles are resolved once and reused, which is where the 40% faster data collection and 30% faster driving come from
- **Memory integration**: attach a MemoryModel and transactions can be checked against expected data as they move
- **Single- or multi-signal modes**: pack every field into one data bus, or give each field its own signal
- **Statistics included**: performance and error counters collected by the base, available to every subclass

## Core Class

### FIFOComponentBase

The base class all three FIFO components are built on.

#### Constructor

```python
FIFOComponentBase(dut, title, prefix, clock, field_config,
                  protocol_type,  # Must be specified by subclass
                  mode='fifo_mux',
                  bus_name='',
                  pkt_prefix='',
                  multi_sig=False,
                  randomizer=None,
                  memory_model=None,
                  log=None,
                  super_debug=False,
                  signal_map=None,  # NEW: Optional manual signal mapping
                  **kwargs)
```

**Parameters:**
- `dut`: Device under test
- `title`: Component title/name
- `prefix`: Bus prefix for signal naming
- `clock`: Clock signal
- `field_config`: Field configuration (FieldConfig object or dict)
- `protocol_type`: Protocol type ('fifo_master' or 'fifo_slave') — the subclass sets this, you don't
- `mode`: FIFO mode ('fifo_mux', 'fifo_flop')
- `bus_name`: Bus/channel name
- `pkt_prefix`: Packet field prefix
- `multi_sig`: Whether using multi-signal mode
- `randomizer`: Optional randomizer for timing control
- `memory_model`: Optional memory model for transactions
- `log`: Logger instance
- `super_debug`: Enable detailed debugging
- `signal_map`: Optional manual signal mapping override
- `**kwargs`: Additional arguments for specific component types

#### Signal Map Format

When the DUT's signal names don't match what discovery expects, pass a `signal_map` that translates logical names to real ones:

**FIFO Master:**
```python
signal_map = {
    'write': 'wr_en',      # Write enable signal
    'full': 'fifo_full',   # FIFO full signal  
    'data': 'wr_data'      # Write data signal (single-signal mode)
    # OR field names for multi-signal mode:
    # 'addr': 'wr_addr', 'data': 'wr_data', 'cmd': 'wr_cmd'
}
```

**FIFO Slave:**
```python
signal_map = {
    'read': 'rd_en',       # Read enable signal
    'empty': 'fifo_empty', # FIFO empty signal
    'data': 'rd_data'      # Read data signal (single-signal mode)
    # OR field names for multi-signal mode:
    # 'addr': 'rd_addr', 'data': 'rd_data', 'cmd': 'rd_cmd'
}
```

## Core Methods

### Initialization and Setup

#### `complete_base_initialization(bus=None)`

Call this from your subclass *after* the cocotb parent (BusDriver or BusMonitor) has been initialized. The order matters — the base needs the bus handle, and that only exists once the cocotb side is up.

```python
# Subclass usage pattern
def __init__(self, ...):
    # Initialize FIFOComponentBase
    FIFOComponentBase.__init__(self, ...)
    
    # Initialize cocotb parent (BusDriver/BusMonitor)  
    BusDriver.__init__(self, dut, prefix, clock, **kwargs)
    
    # Complete base initialization
    self.complete_base_initialization(self.bus)
```

### Data Handling (Unified Strategies)

#### `get_data_dict_unified()`

Read the current signal values and unpack them into fields. One call, no conditionals — the multi-signal vs. packed-data difference is handled inside the strategy.

**Returns:** Dictionary of field values, properly unpacked

```python
# Collect data from signals
data_dict = component.get_data_dict_unified()
print(data_dict)  # {'addr': 0x1000, 'data': 0xDEADBEEF, 'cmd': 0x2}
```

#### `drive_transaction_unified(transaction)`

Pack a transaction and drive it onto the signals.

**Parameters:**
- `transaction`: Transaction packet to drive

**Returns:** True if successful, False otherwise — check it. A drive that silently failed looks exactly like a DUT bug until you burn an afternoon figuring out it isn't.

```python
# Drive transaction to signals
packet = FIFOPacket(field_config, addr=0x1000, data=0xDEADBEEF)
success = component.drive_transaction_unified(packet)
if not success:
    log.error("Failed to drive transaction")
```

#### `clear_signals_unified()`

Drive every data signal back to a safe value.

```python
# Clear all signals
component.clear_signals_unified()
```

### Memory Operations (Unified Integration)

#### `write_to_memory_unified(transaction)`

Write a transaction into the attached MemoryModel.

**Parameters:**
- `transaction`: Transaction to write to memory

**Returns:** Tuple of (success, error_message) — the error message is worth logging, it tells you *why*.

```python
# Write transaction to memory
packet = FIFOPacket(field_config, addr=0x1000, data=0xDEADBEEF)
success, error = component.write_to_memory_unified(packet)
if success:
    log.info("Memory write successful")
else:
    log.error(f"Memory write failed: {error}")
```

#### `read_from_memory_unified(transaction, update_transaction=True)`

Read from the MemoryModel at the transaction's address.

**Parameters:**
- `transaction`: Transaction with address to read from
- `update_transaction`: Whether to update transaction with read data

**Returns:** Tuple of (success, data, error_message). With `update_transaction=True` the packet's data field gets filled in for you.

```python
# Read from memory  
packet = FIFOPacket(field_config, addr=0x1000)
success, data, error = component.read_from_memory_unified(packet, update_transaction=True)
if success:
    log.info(f"Read data: 0x{data:X}")
    # packet.data now contains the read value
else:
    log.error(f"Memory read failed: {error}")
```

### Statistics and Monitoring

#### `get_base_stats_unified()`

One dict with everything the base knows about itself: component config, signal resolution, data strategy performance, memory stats.

**Returns:** Dictionary containing base statistics

```python
base_stats = component.get_base_stats_unified()
print(f"Component type: {base_stats['component_type']}")
print(f"Signal mapping source: {base_stats['signal_mapping_source']}")
print(f"Field count: {base_stats['field_count']}")
print(f"Multi-signal mode: {base_stats['multi_signal']}")

# Includes nested statistics:
# - signal_resolver_stats: Signal resolution details
# - data_collector_stats: Collection performance
# - data_driver_stats: Driving performance  
# - memory_stats: Memory model statistics (if available)
```

#### `set_randomizer(randomizer)`

Swap in a new timing randomizer at runtime.

**Parameters:**
- `randomizer`: FlexRandomizer instance

```python
# Update randomizer
new_randomizer = FlexRandomizer({
    'write_delay': ([(0, 0), (1, 5)], [8, 2])
})
component.set_randomizer(new_randomizer)
```

## Usage Patterns

### Basic Component Setup

The initialization order is the thing people get wrong, so here it is in full:

```python
class CustomFIFOComponent(FIFOComponentBase, BusDriver):
    def __init__(self, dut, title, prefix, clock, field_config, **kwargs):
        # Initialize base class
        FIFOComponentBase.__init__(
            self,
            dut=dut,
            title=title,
            prefix=prefix,
            clock=clock,
            field_config=field_config,
            protocol_type='fifo_master',  # Specify protocol type
            **kwargs
        )
        
        # Initialize cocotb parent
        BusDriver.__init__(self, dut, prefix, clock, **kwargs)
        
        # Complete base initialization
        self.complete_base_initialization(self.bus)
        
        # Component-specific initialization
        self.custom_setup()
    
    def custom_setup(self):
        # Component-specific setup code
        pass
```

### Automatic Signal Discovery

Most of the time you don't map anything — the resolver finds the signals itself:

```python
# Let base class automatically discover signals
master = CustomFIFOComponent(
    dut=dut,
    title="AutoMaster",
    prefix="",  # SignalResolver handles discovery
    clock=clock,
    field_config=field_config,
    mode='fifo_mux',
    multi_sig=True
)

# Base class automatically finds and maps signals
# Access resolved signals: master.write_sig, master.data_sig, etc.
```

### Manual Signal Mapping

When it can't — custom names, `almost_full` instead of `full` — override:

```python
# Override signal discovery for non-standard naming
signal_map = {
    'write': 'wr_enable',
    'full': 'almost_full',
    'addr': 'write_address',
    'data': 'write_data'
}

master = CustomFIFOComponent(
    dut=dut,
    title="ManualMaster", 
    prefix="",
    clock=clock,
    field_config=field_config,
    signal_map=signal_map,
    multi_sig=True
)
```

### Memory-Integrated Component

Attach a MemoryModel and the unified memory helpers become available:

```python
# Component with built-in memory support
memory = MemoryModel(num_lines=256, bytes_per_line=4)

master = CustomFIFOComponent(
    dut=dut,
    title="MemoryMaster",
    prefix="",
    clock=clock,
    field_config=field_config,
    memory_model=memory
)

# Use unified memory operations
packet = FIFOPacket(field_config, addr=0x1000, data=0xDEADBEEF)
success, error = master.write_to_memory_unified(packet)
```

### Performance-Optimized Component

```python
class HighPerformanceFIFOComponent(FIFOComponentBase, BusDriver):
    def __init__(self, dut, title, prefix, clock, field_config, **kwargs):
        # Enable performance features
        FIFOComponentBase.__init__(
            self,
            dut=dut,
            title=title,
            prefix=prefix,
            clock=clock,
            field_config=field_config,
            protocol_type='fifo_master',
            super_debug=False,  # Disable for performance
            **kwargs
        )
        
        BusDriver.__init__(self, dut, prefix, clock, **kwargs)
        self.complete_base_initialization(self.bus)
    
    async def high_speed_transfer(self, packets):
        """Optimized batch transfer using unified strategies"""
        for packet in packets:
            # Use unified driving for maximum performance
            if not self.drive_transaction_unified(packet):
                log.error(f"Failed to drive packet: {packet}")
                continue
            
            # Wait for transfer
            await RisingEdge(self.clock)
            
            # Clear signals efficiently
            self.clear_signals_unified()
    
    def get_performance_metrics(self):
        """Get detailed performance analysis"""
        stats = self.get_base_stats_unified()
        
        # Analyze data strategy performance
        if 'data_driver_stats' in stats:
            driver_stats = stats['data_driver_stats']
            print(f"Cached signals: {driver_stats.get('cached_signals', 0)}")
            print(f"Performance optimized: {driver_stats.get('performance_optimized', False)}")
        
        return stats
```

### Multi-Signal vs Single-Signal Mode

Same fields, two ways to wire them:

```python
# Multi-signal mode: Each field has individual signal
multi_sig_config = FieldConfig()
multi_sig_config.add_field(FieldDefinition("addr", 32))
multi_sig_config.add_field(FieldDefinition("data", 32))
multi_sig_config.add_field(FieldDefinition("cmd", 4))

master_multi = CustomFIFOComponent(
    dut, "MultiSigMaster", "", clock, multi_sig_config, multi_sig=True
)
# Creates: addr_sig, data_sig, cmd_sig

# Single-signal mode: All fields packed into data signal  
master_single = CustomFIFOComponent(
    dut, "SingleSigMaster", "", clock, multi_sig_config, multi_sig=False
)
# Creates: data_sig (with fields packed)
```

### Advanced Randomization

The randomizer isn't just delays — you can shape bursts and idle time too:

```python
# Custom randomizer for specific timing patterns
custom_randomizer = FlexRandomizer({
    'write_delay': ([(0, 0), (1, 3), (10, 20)], [0.7, 0.2, 0.1]),
    'burst_size': [1, 2, 4, 8, 16],
    'idle_cycles': ([(0, 5), (10, 50)], [0.8, 0.2])
})

master = CustomFIFOComponent(
    dut=dut,
    title="RandomizedMaster",
    prefix="",
    clock=clock,
    field_config=field_config,
    randomizer=custom_randomizer
)

# Use randomizer in component
delay_values = master.randomizer.next()
write_delay = delay_values['write_delay']
burst_size = delay_values['burst_size']
```

## Internal Infrastructure

### Field Configuration Normalization

The base takes a FieldConfig, a plain dict, or nothing at all, and ends up with a FieldConfig either way:

```python
# Accepts dict and converts to FieldConfig
dict_config = {
    'addr': {'bits': 32, 'format': 'hex'},
    'data': {'bits': 32, 'format': 'hex'}
}
component = CustomFIFOComponent(..., field_config=dict_config)

# Accepts FieldConfig directly  
field_config = FieldConfig.create_standard(32, 32)
component = CustomFIFOComponent(..., field_config=field_config)

# Creates default if None
component = CustomFIFOComponent(..., field_config=None)  # Creates data-only config
```

### Randomizer Setup

Don't pass a randomizer and you get a sensible default based on protocol type:

```python
# FIFO Master gets write-focused randomizer
'write_delay': ([(0, 0), (1, 8), (9, 20)], [5, 2, 1])

# FIFO Slave gets read-focused randomizer  
'read_delay': ([(0, 1), (2, 8), (9, 30)], [5, 2, 1])
```

### Data Strategy Setup

Both strategies receive the pre-resolved signals, so they never pay the lookup cost twice:

```python
# Data collection for all components (monitoring)
self.data_collector = DataCollectionStrategy(
    component=self,
    field_config=self.field_config,
    use_multi_signal=self.use_multi_signal,
    log=self.log,
    resolved_signals=resolved_signals  # Pre-resolved signals
)

# Data driving for masters and slaves
self.data_driver = DataDrivingStrategy(
    component=self,
    field_config=self.field_config,
    use_multi_signal=self.use_multi_signal,
    log=self.log,
    resolved_signals=resolved_signals  # Pre-resolved signals
)
```

## Error Handling

### Signal Resolution Errors

If discovery fails you get a RuntimeError with the details. The usual recovery is a manual map:

```python
try:
    component = CustomFIFOComponent(dut, title, prefix, clock, field_config)
except RuntimeError as e:
    # Signal mapping failed - detailed error info provided
    log.error(f"Signal resolution failed: {e}")
    
    # Try manual signal mapping as fallback
    signal_map = create_manual_signal_map()
    component = CustomFIFOComponent(
        dut, title, prefix, clock, field_config, signal_map=signal_map
    )
```

### Memory Operation Errors

The memory helpers return success flags rather than raising. Check them:

```python
# Always check memory operation results
success, error = component.write_to_memory_unified(packet)
if not success:
    log.error(f"Memory write failed: {error}")
    # Handle error appropriately

success, data, error = component.read_from_memory_unified(packet)
if not success:
    log.error(f"Memory read failed: {error}")
    # Handle error appropriately
```

## Best Practices

### 1. **Use Unified Methods**
They exist so every component behaves identically. Hand-rolling your own collection or drive path reintroduces the duplication this class was built to kill:
```python
# Good - unified data collection
data = component.get_data_dict_unified()

# Good - unified transaction driving
success = component.drive_transaction_unified(packet)
```

### 2. **Check Operation Results**
The return values are there for a reason:
```python
# Check driving success
if not component.drive_transaction_unified(packet):
    log.error("Transaction driving failed")
    
# Check memory operations  
success, error = component.write_to_memory_unified(packet)
if not success:
    handle_memory_error(error)
```

### 3. **Use Signal Maps for Non-Standard Interfaces**
Don't fight the auto-discovery. If your RTL says `wr_en` and `almost_full`, say so:
```python
signal_map = {
    'write': 'wr_en',
    'full': 'almost_full',
    'data': 'write_data'
}
component = CustomFIFOComponent(..., signal_map=signal_map)
```

### 4. **Monitor Performance**
Glance at the stats occasionally. If `performance_optimized` is False, something kept the caching from kicking in and you'll want to know why:
```python
stats = component.get_base_stats_unified()
if 'data_collector_stats' in stats:
    collector_stats = stats['data_collector_stats']
    if not collector_stats.get('performance_optimized', False):
        log.warning("Data collection not optimized")
```

### 5. **Proper Initialization Order**
Base first, cocotb parent second, `complete_base_initialization()` third, then your own setup:
```python
# 1. Initialize FIFOComponentBase
# 2. Initialize cocotb parent class
# 3. Call complete_base_initialization()
# 4. Component-specific setup
```

One last time, because it matters: for new code, subclass `GAXIComponentBase` directly. Everything on this page comes from there anyway — this shim only exists so older tests keep working.
