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

# gaxi_component_base.py

The class every GAXI component stands on. GAXIMaster, GAXISlave and GAXIMonitor all inherit from it, and because the AXI4/AXI5/AXI-Stream/FIFO BFMs delegate to the GAXI pipelines, most of the traffic anywhere in this framework ends up flowing through code defined here. It exists so that signal resolution, field handling, memory access and statistics live in exactly one place instead of three.

## Overview

The `GAXIComponentBase` class provides:
- **Signal resolution and data-strategy setup**, once for the whole family
- **Field configuration and packet management** in a common shape
- **Memory model access** using the base MemoryModel directly
- **Statistics and logging** that look the same on every component
- **Resolved signals handed to the DataStrategies**, so nothing downstream has to re-derive them

Every parameter the old components took still means what it meant; the only addition is the optional `signal_map` for manual signal naming.

## Class

### GAXIComponentBase

```python
class GAXIComponentBase:
    def __init__(self, dut, title, prefix, clock, field_config,
                 protocol_type,  # Must be specified by subclass
                 mode='skid', bus_name='', pkt_prefix='', multi_sig=False,
                 randomizer=None, memory_model=None, log=None,
                 super_debug=False, signal_map=None, packet_class=None, **kwargs)
```

**Parameters:**
- `dut`: Device under test
- `title`: Component title/name
- `prefix`: Bus prefix
- `clock`: Clock signal
- `field_config`: Field configuration (FieldConfig or dict)
- `protocol_type`: Protocol type ('gaxi_master', 'gaxi_slave', 'axis_master', 'axis_slave', 'fifo_master', or 'fifo_slave')
- `mode`: GAXI mode ('skid', 'fifo_mux', 'fifo_flop')
- `bus_name`: Bus/channel name
- `pkt_prefix`: Packet field prefix
- `multi_sig`: Whether using multi-signal mode
- `randomizer`: Optional randomizer for timing
- `memory_model`: Optional memory model for transactions
- `log`: Logger instance
- `super_debug`: Enable detailed debugging
- `signal_map`: Optional dict mapping signal names to DUT signal names
- `packet_class`: Optional `Packet` subclass produced by the component's
  pipeline. `None` (default) keeps the class-level default (`GAXIPacket` for
  GAXI, `FIFOPacket` for FIFO). Must be a `Packet` subclass — validated at
  construction. See [`_build_packet()`](#_build_packetfield_values).
- `**kwargs`: Additional arguments for specific component types

**Signal Map Format:**
```python
# Manual signal mapping (bypasses automatic discovery)
signal_map = {
    'valid': 'dut_valid_signal_name',
    'ready': 'dut_ready_signal_name', 
    'data': 'dut_data_signal_name'     # For single-signal mode
    # Or individual field names for multi-signal mode
}
```

## Key Methods

### Core Initialization

#### `complete_base_initialization(bus=None)`
Finish initialization after the cocotb parent class is set up.

**You must call this from the subclass** after its BusDriver/BusMonitor `__init__` completes — skip it and the data strategies never get built, and nothing downstream works.

```python
# In subclass __init__ after BusDriver.__init__:
self.complete_base_initialization(self.bus)
```

### Unified Data Operations

#### `get_data_dict_unified()`
Read the current signal values, unpacked into fields.

**Returns:** Dictionary of field values, properly unpacked

```python
# Clean data collection with automatic field unpacking
data = component.get_data_dict_unified()
print(data)  # {'addr': 0x1000, 'data': 0xDEADBEEF, 'cmd': 0x2}
```

#### `drive_transaction_unified(transaction)`
Drive a transaction's fields through the unified DataDrivingStrategy.

**Parameters:**
- `transaction`: Transaction to drive

**Returns:** True if successful, False otherwise

```python
packet = component.create_packet(addr=0x1000, data=0xDEADBEEF)
success = component.drive_transaction_unified(packet)
```

#### `clear_signals_unified()`
Clear all data signals using unified strategy.

```python
component.clear_signals_unified()  # Set all signals to 0
```

### Memory Operations

#### `write_to_memory_unified(transaction)`
Write transaction to memory using base MemoryModel.

**Parameters:**
- `transaction`: Transaction to write

**Returns:** Tuple of (success, error_message)

```python
success, error = component.write_to_memory_unified(packet)
if not success:
    log.error(f"Memory write failed: {error}")
```

#### `read_from_memory_unified(transaction, update_transaction=True)`
Read data from memory using base MemoryModel.

**Parameters:**
- `transaction`: Transaction with address to read
- `update_transaction`: Whether to update transaction with read data

**Returns:** Tuple of (success, data, error_message)

```python
success, data, error = component.read_from_memory_unified(packet)
if success:
    log.info(f"Read data: 0x{data:X}")
```

### Packet Construction

#### `_build_packet(**field_values)`

One hook controls every packet this family builds. The receive pipeline,
`create_packet()`, and the master's transmit path all construct their packets
here — so if you need a different packet class, this is the only place you
have to touch.

**Parameters:**
- `**field_values`: Optional initial field values. Names matching a field the
  packet exposes are assigned after construction; unknown names are ignored
  (preserving the historical `create_packet()` contract).

**Returns:** A newly constructed packet instance.

The class constructed is resolved in this order:

1. `self.packet_class`, if a `packet_class=` argument was passed to the
   component or its factory.
2. `self._default_packet_class` — `GAXIPacket` for GAXI components,
   `FIFOPacket` for the FIFO chassis.

With neither supplied, behavior is identical to before the hook existed: a
plain `GAXIPacket(self.field_config)`.

```python
# Default: plain GAXIPacket
packet = component._build_packet()

# Via the packet_class argument (also accepted by every factory)
slave = create_gaxi_slave(dut, "Slave", "", clock, packet_class=MyPacket)
# slave's receive pipeline now produces MyPacket instances
```

##### Overriding the hook

`packet_class=` covers packet classes constructible as
`PacketClass(field_config)`. When a protocol packet needs **extra constructor
arguments**, override `_build_packet()` instead — this is the supported
extension point for protocol BFMs that delegate to the GAXI pipelines
(AXI4/AXI5/AXIS/FIFO):

```python
class AXIS5Slave(GAXISlave):
    def __init__(self, *args, parity_enabled=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.parity_enabled = parity_enabled

    def _build_packet(self, **field_values):
        return AXIS5Packet(
            self.field_config,
            parity_enabled=self.parity_enabled,
            **field_values,
        )
```

This matters because the whole pipeline routes through the hook: downstream
`isinstance(packet, AXIS5Packet)` checks keep working. Before the hook
existed, the receive path hard-coded `GAXIPacket(self.field_config)`, so a
delegating slave or monitor silently lost its protocol packet subclass.

An override takes precedence over `packet_class`. Subclasses that only need
a different default (no extra constructor arguments) can instead set the
class attribute:

```python
class FIFOComponentBase(GAXIComponentBase):
    _default_packet_class = FIFOPacket
```

### Statistics and Configuration

#### `get_base_stats_unified()`
The statistics every component reports, whatever its role.

**Returns:** Dictionary containing base statistics

```python
stats = component.get_base_stats_unified()
print(f"Component type: {stats['component_type']}")
print(f"Signal mapping source: {stats['signal_mapping_source']}")
print(f"Field count: {stats['field_count']}")
```

#### `set_randomizer(randomizer)`
Swap in a new randomizer for timing control.

**Parameters:**
- `randomizer`: FlexRandomizer instance

```python
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer

new_randomizer = FlexRandomizer({
    'valid_delay': ([(0, 0), (1, 5)], [0.8, 0.2])
})
component.set_randomizer(new_randomizer)
```

## Usage Patterns

### Basic Component Creation

```python
from CocoTBFramework.components.gaxi.gaxi_master import GAXIMaster
from CocoTBFramework.components.shared.field_config import FieldConfig

# Create field configuration
field_config = FieldConfig()
field_config.add_field(FieldDefinition("addr", 32, format="hex"))
field_config.add_field(FieldDefinition("data", 32, format="hex"))

# Create master (inherits from GAXIComponentBase)
master = GAXIMaster(
    dut=dut,
    title="TestMaster", 
    prefix="",
    clock=clock,
    field_config=field_config,
    mode='skid',
    multi_sig=True,  # Individual signals for each field
    log=log          # Required by GAXIMaster
)
```

### Manual Signal Mapping

Automatic discovery handles conventional naming. When the DUT names its pins something creative, hand in a map and skip the guessing.

```python
# For non-standard signal names
signal_map = {
    'valid': 'master_valid_custom',
    'ready': 'slave_ready_custom',
    'addr': 'address_signal',      # Multi-signal mode
    'data': 'data_signal'
}

master = GAXIMaster(
    dut=dut,
    title="CustomMaster",
    prefix="",
    clock=clock, 
    field_config=field_config,
    signal_map=signal_map  # Override automatic discovery
)
```

### Memory Integration

```python
from CocoTBFramework.components.shared.memory_model import MemoryModel

# Create memory model
memory = MemoryModel(num_lines=1024, bytes_per_line=4, log=log)

# Create component with memory
master = GAXIMaster(
    dut=dut,
    title="MemoryMaster",
    prefix="",
    clock=clock,
    field_config=field_config,
    memory_model=memory
)

# Write to memory through component
packet = master.create_packet(addr=0x1000, data=0xDEADBEEF)
success, error = master.write_to_memory_unified(packet)
```

### Unified Data Collection

A minimal custom monitor, showing the two calls that matter — the cocotb parent first, then `complete_base_initialization()`, then the unified methods inside the loop.

```python
class CustomMonitor(GAXIComponentBase, BusMonitor):
    def __init__(self, dut, title, prefix, clock, field_config):
        GAXIComponentBase.__init__(
            self, dut, title, prefix, clock, field_config,
            protocol_type='gaxi_master'  # Monitor master side
        )
        BusMonitor.__init__(self, dut, prefix, clock)
        self.complete_base_initialization(self.bus)
    
    @cocotb.coroutine
    def _monitor_recv(self):
        while True:
            yield RisingEdge(self.clock)
            
            # Use unified data collection
            data = self.get_data_dict_unified()
            
            if data.get('valid', 0) == 1:
                # Process transaction
                packet = self.create_packet(**data)
                self._recv(packet)  # Add to cocotb queue
```

### Advanced Statistics

```python
def analyze_component_performance(component):
    """Analyze component performance using base stats"""
    stats = component.get_base_stats_unified()
    
    print(f"=== Component Analysis: {stats['title']} ===")
    print(f"Type: {stats['component_type']}")
    print(f"Mode: {stats['mode']}")
    print(f"Multi-signal: {stats['multi_signal']}")
    print(f"Fields: {stats['field_count']}")
    
    # Signal resolver statistics
    if 'signal_resolver_stats' in stats:
        resolver_stats = stats['signal_resolver_stats']
        print(f"Signal resolution rate: {resolver_stats['resolution_rate']:.1f}%")
        print(f"Signal conflicts: {resolver_stats['conflicts']}")
    
    # Data strategy statistics  
    if 'data_collector_stats' in stats:
        collector_stats = stats['data_collector_stats']
        print(f"Data collection mode: {collector_stats['mode']}")
        print(f"Performance optimized: {collector_stats['performance_optimized']}")
    
    # Memory statistics
    if 'memory_stats' in stats:
        memory_stats = stats['memory_stats']
        print(f"Memory operations: {memory_stats['reads'] + memory_stats['writes']}")
        print(f"Memory coverage: {memory_stats['read_coverage']:.1%}")
```

## Error Handling

### Signal Resolution Errors
```python
try:
    master = GAXIMaster(dut, "Master", "", clock, field_config)
except RuntimeError as e:
    # Detailed error with signal mapping diagnostics
    log.error(f"Signal mapping failed: {e}")
    
    # Try manual mapping as fallback
    signal_map = create_fallback_signal_map(dut)
    master = GAXIMaster(dut, "Master", "", clock, field_config, 
                       signal_map=signal_map)
```

### Memory Operation Errors

Memory helpers return `(success, error)` tuples rather than raising, so check the first element before trusting the rest.

```python
# Memory operations return success/error tuples
success, error = component.write_to_memory_unified(packet)
if not success:
    if "boundary" in error.lower():
        log.error(f"Address out of bounds: {error}")
    elif "type" in error.lower():
        log.error(f"Data type error: {error}")
    else:
        log.error(f"Memory error: {error}")
```

## Internal Architecture

### Signal Resolution Flow
1. **SignalResolver creation** with protocol type and parameters
2. **Pattern matching** against DUT ports (or manual mapping)
3. **Signal validation** and conflict detection
4. **DataStrategy creation** with resolved signals
5. **Component signal application** via `apply_to_component()`

### Data Strategy Integration

The resolver runs once, and the resolved signals are passed straight into the strategies. Nothing downstream goes back to the DUT to guess again.

```python
# Internal flow (handled automatically)
resolver = SignalResolver(protocol_type, dut, bus, log, title, ...)
resolved_signals = resolver.resolved_signals

# Pass resolved signals to strategies (eliminates guesswork)
data_collector = DataCollectionStrategy(..., resolved_signals=resolved_signals)
data_driver = DataDrivingStrategy(..., resolved_signals=resolved_signals)
```

### Memory Model Integration
- Uses base MemoryModel methods directly
- Transaction-based read/write operations
- Automatic field extraction and validation
- Error handling with detailed messages

## Best Practices

### 1. **Let Automatic Discovery Try First**
```python
# Try automatic discovery
component = GAXIMaster(dut, title, prefix, clock, field_config)

# Fall back to manual mapping if needed
if not all_signals_found:
    signal_map = {...}
    component = GAXIMaster(..., signal_map=signal_map)
```

### 2. **Always Complete Base Initialization**
```python
# In subclass after cocotb parent initialization
class MyComponent(GAXIComponentBase, BusDriver):
    def __init__(self, ...):
        GAXIComponentBase.__init__(self, ...)
        BusDriver.__init__(self, ...)
        self.complete_base_initialization(self.bus)  # Essential!
```

### 3. **Use the Unified Methods**

They're the ones the rest of the family uses, which means they're the ones that get fixed when something's wrong.

```python
# Prefer unified methods over custom implementations
data = component.get_data_dict_unified()  # Not custom _get_data_dict()
success = component.drive_transaction_unified(packet)  # Not custom driving
```

### 4. **Monitor Statistics for Performance**
```python
# Regular performance monitoring
stats = component.get_base_stats_unified()
if 'data_collector_stats' in stats:
    collector_stats = stats['data_collector_stats']
    if not collector_stats['performance_optimized']:
        log.warning("Data collection not optimized")
```

### 5. **Handle Memory Operations Gracefully**
```python
# Always check memory operation results
success, error = component.write_to_memory_unified(packet)
if not success:
    # Handle error appropriately for test context
    handle_memory_error(error, packet)
```

If you're building a new component on this layer: inherit here, call `complete_base_initialization()` after the cocotb parent is up, and use the unified methods rather than rolling your own. That's all the existing components do — it's why the AXI and FIFO BFMs on top can stay thin.
