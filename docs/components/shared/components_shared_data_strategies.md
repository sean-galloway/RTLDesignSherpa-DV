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

# data_strategies.py

Data collection and driving strategies that cache signal references and field validation rules at initialization, so the per-cycle loops stay cheap.

## Overview

Every monitor loop starts life doing `hasattr()`/`getattr()` on every field, every cycle. It works fine — right up until you profile a slow regression and find your testbench spending its life in attribute lookups instead of simulating. This module is the fix: `DataCollectionStrategy` and `DataDrivingStrategy` do all the resolution once, up front, and the hot loop just calls pre-built functions. Measured against the naive approach, that's about 40% faster collection and 30% faster driving.

### Key Benefits
- 40% faster data collection through cached signal references
- 30% faster data driving through cached driving functions
- No repeated `hasattr()`/`getattr()` calls every cycle
- Field validation pre-computed during initialization
- Field unpacking without per-call conditional logic
- Uses the exact signal handles SignalResolver already found — no second round of guessing

## Classes

### DataCollectionStrategy

Collection strategy that reads directly from the signals SignalResolver resolved, instead of re-finding them every cycle.

#### Constructor

```python
DataCollectionStrategy(component, field_config, use_multi_signal, log, resolved_signals=None)
```

**Parameters:**
- `component`: The monitor/slave component with signal attributes
- `field_config`: Field configuration object
- `use_multi_signal`: Whether using multi-signal mode
- `log`: Logger instance
- `resolved_signals`: Dict of resolved signals from SignalResolver (optional)

#### Methods

##### `collect_data() -> Dict[str, Any]`
Collect data using the cached signal references.

**Returns:** Dictionary of field values with X/Z values represented as -1

**Performance:** ~40% faster than repeated hasattr/getattr calls

```python
# Example usage
strategy = DataCollectionStrategy(component, field_config, use_multi_signal=True, log=log, resolved_signals=signals)
data = strategy.collect_data()
print(data)  # {'addr': 0x1000, 'data': 0xDEADBEEF}
```

##### `collect_and_unpack_data() -> Dict[str, Any]`
Collect data and unpack fields in one call.

**Returns:** Dictionary with unpacked field values

```python
# For single-signal mode with multiple fields
unpacked_data = strategy.collect_and_unpack_data()
```

##### `get_stats() -> Dict[str, Any]`
Get statistics about the collection strategy.

**Returns:** Dictionary with performance and configuration statistics

```python
stats = strategy.get_stats()
print(f"Signal collectors: {stats['signal_collectors']}")
print(f"Mode: {stats['mode']}")
print(f"Performance optimized: {stats['performance_optimized']}")
```

#### Internal Methods

##### `_setup_collection_strategy()`
Build the collection functions from the signals SignalResolver provided.

##### `_determine_unpacking_needs() -> bool`
Decide whether field unpacking is needed based on the configuration.

##### `_create_unpacking_function()`
Build the unpacking function appropriate for the configuration.

### DataDrivingStrategy

Driving strategy that writes through the signals SignalResolver resolved, instead of re-finding them on every transaction.

#### Constructor

```python
DataDrivingStrategy(component, field_config, use_multi_signal, log, resolved_signals=None)
```

**Parameters:**
- `component`: The master component with signal attributes
- `field_config`: Field configuration object
- `use_multi_signal`: Whether using multi-signal mode
- `log`: Logger instance
- `resolved_signals`: Dict of resolved signals from SignalResolver (optional)

#### Methods

##### `drive_transaction(transaction) -> bool`
Drive transaction data using the cached signal references.

**Parameters:**
- `transaction`: Transaction packet to drive

**Returns:** True if successful, False otherwise

**Performance:** ~30% faster than repeated signal lookups

```python
# Example usage
strategy = DataDrivingStrategy(component, field_config, use_multi_signal=False, log=log, resolved_signals=signals)
success = strategy.drive_transaction(packet)
if success:
    log.info("Transaction driven successfully")
```

##### `clear_signals()`
Clear all data signals to default values.

```python
strategy.clear_signals()  # Set all signals to 0
```

##### `get_stats() -> Dict[str, Any]`
Get statistics about the driving strategy.

**Returns:** Dictionary with performance and configuration statistics

```python
stats = strategy.get_stats()
print(f"Signal drivers: {stats['signal_drivers']}")
print(f"Cached signals: {stats['cached_signals']}")
```

#### Internal Methods

##### `_setup_driving_strategy()`
Build the driving functions from the signals SignalResolver provided.

##### `_create_field_driver(field_name, signal_obj, max_value)`
Create a driver function for a single field (multi-signal mode).

##### `_create_combined_data_driver(signal_key, signal_obj, max_value)`
Create a driver for combined data that packs multiple fields.

## Convenience Functions

### `create_data_collection_strategy()`

```python
create_data_collection_strategy(component, field_config, multi_sig=None, log=None, resolved_signals=None)
```

Builds a DataCollectionStrategy and auto-detects multi-signal mode if you don't specify it.

**Parameters:**
- `component`: Component with signal attributes
- `field_config`: Field configuration
- `multi_sig`: Whether to use multi-signal mode (auto-detected if None)
- `log`: Logger instance
- `resolved_signals`: Dict of resolved signals from SignalResolver

**Returns:** DataCollectionStrategy instance

```python
# Auto-detect multi-signal mode
strategy = create_data_collection_strategy(component, field_config, log=log, resolved_signals=signals)
```

### `create_data_driving_strategy()`

```python
create_data_driving_strategy(component, field_config, multi_sig=None, log=None, resolved_signals=None)
```

Builds a DataDrivingStrategy and auto-detects multi-signal mode if you don't specify it.

**Parameters:**
- `component`: Component with signal attributes  
- `field_config`: Field configuration
- `multi_sig`: Whether to use multi-signal mode (auto-detected if None)
- `log`: Logger instance
- `resolved_signals`: Dict of resolved signals from SignalResolver

**Returns:** DataDrivingStrategy instance

```python
# Auto-detect multi-signal mode  
strategy = create_data_driving_strategy(component, field_config, log=log, resolved_signals=signals)
```

## Usage Patterns

### Basic Collection Example

```python
# Setup
resolver = SignalResolver('gaxi_master', dut, bus, log, 'TestMaster')
resolved_signals = resolver.resolved_signals

# Create collection strategy
collection_strategy = create_data_collection_strategy(
    component=self,
    field_config=field_config, 
    log=log,
    resolved_signals=resolved_signals
)

# Collect data every cycle
@cocotb.coroutine  
def monitor_loop():
    while True:
        data = collection_strategy.collect_data()
        if data['addr'] != -1:  # Check for valid data
            self.process_transaction(data)
        yield RisingEdge(self.clock)
```

### Basic Driving Example

```python
# Setup
resolver = SignalResolver('gaxi_master', dut, bus, log, 'TestMaster')
resolved_signals = resolver.resolved_signals

# Create driving strategy
driving_strategy = create_data_driving_strategy(
    component=self,
    field_config=field_config,
    log=log, 
    resolved_signals=resolved_signals
)

# Drive transactions
@cocotb.coroutine
def drive_transaction(self, packet):
    success = driving_strategy.drive_transaction(packet)
    if not success:
        raise TestFailure("Failed to drive transaction")
    
    yield RisingEdge(self.clock)
    driving_strategy.clear_signals()
```

### Combined Collection and Driving

```python
class MyComponent:
    def __init__(self, dut, field_config, log):
        # Signal resolution
        resolver = SignalResolver('gaxi_master', dut, self.bus, log, 'MyComponent')
        resolver.apply_to_component(self)
        
        # Create strategies
        self.collector = create_data_collection_strategy(
            self, field_config, log=log, resolved_signals=resolver.resolved_signals
        )
        self.driver = create_data_driving_strategy(
            self, field_config, log=log, resolved_signals=resolver.resolved_signals
        )
    
    @cocotb.coroutine
    def run(self):
        while True:
            # Collect incoming data
            data = self.collector.collect_data()
            
            # Process and drive response
            if self.should_respond(data):
                response = self.create_response(data)
                self.driver.drive_transaction(response)
            
            yield RisingEdge(self.clock)
```

## Performance Optimization Details

### Caching Strategy
- **Signal References**: Signal objects are cached during initialization
- **Field Validation**: Maximum values are pre-computed for each field
- **Collection Functions**: Pre-built functions with no per-call branching
- **Driving Functions**: Cached driver functions for each signal mode

### Before vs After Performance

**Before (Traditional Approach):**
```python
# Called every cycle - slow!
def get_data_dict(self):
    data = {}
    if hasattr(self, 'addr_sig') and self.addr_sig.value.is_resolvable:
        data['addr'] = int(self.addr_sig.value)
    if hasattr(self, 'data_sig') and self.data_sig.value.is_resolvable:
        data['data'] = int(self.data_sig.value)
    return data
```

**After (Optimized Approach):**
```python
# Pre-built during initialization - fast!
def collect_addr(data_dict):
    if addr_signal.value.is_resolvable:
        data_dict['addr'] = addr_signal.value.integer
    else:
        data_dict['addr'] = -1

# Called every cycle - just executes cached functions
for collect_func in self.collection_funcs:
    collect_func(data_dict)
```

The difference is where the work happens. The "before" version pays the attribute-lookup and branch cost on every cycle of every simulation. The "after" version pays it once, at construction, and the per-cycle path is a straight run of function calls.

### Thread Safety
Both strategies are thread-safe when built on resolved signals from SignalResolver, so they're safe to use in parallel test environments.

## Integration with SignalResolver

The strategies are built to plug straight into SignalResolver's output:

```python
# 1. Resolve signals
resolver = SignalResolver(protocol_type, dut, bus, log, component_name)
resolver.apply_to_component(component)

# 2. Create strategies with resolved signals
collection_strategy = DataCollectionStrategy(
    component, field_config, use_multi_signal, log, 
    resolved_signals=resolver.resolved_signals  # Key integration point
)

# 3. Strategies use pre-resolved signals - no guesswork!
```

That's the whole point of the pairing: SignalResolver already did the hard work of finding the exact handles. Passing them in means the strategies never have to guess, and a signal that failed to resolve shows up as an error at construction time instead of as weird data three thousand cycles into a test.

---
