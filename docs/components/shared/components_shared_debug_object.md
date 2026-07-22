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

# debug_object.py

Object inspection helpers for debugging — the functions you reach for when a packet or signal container isn't holding what you think it's holding.

## Overview

Every verification engineer eventually writes this file. You're staring at a component mid-test, something's off, and you need to know what attributes it actually has and what values they're carrying. `debug_object.py` is that file, already written: dump an object's attributes with types and values, print them to a logger, or print a dict without writing the same three-line loop for the hundredth time. It's most useful on signal containers, packet contents, and component state.

## Functions

### `get_object_details(obj) -> Dict[str, Dict[str, Any]]`

Returns a dictionary with all attributes of the given object, including their types and values.

**Parameters:**
- `obj`: The object to inspect

**Returns:** Dictionary with attribute names as keys, and dictionaries containing 'type' and 'value' as values

**Features:**
- Skips private attributes (those starting with `_`)
- Skips methods and callable objects
- Survives attributes that raise exceptions when accessed
- Reports the type of each attribute alongside the value

```python
# Example usage
class MyComponent:
    def __init__(self):
        self.address = 0x1000
        self.data = 0xDEADBEEF
        self.enabled = True
        self.name = "TestComponent"

component = MyComponent()
details = get_object_details(component)

# Returns:
# {
#     'address': {'type': 'int', 'value': 4096},
#     'data': {'type': 'int', 'value': 3735928559}, 
#     'enabled': {'type': 'bool', 'value': True},
#     'name': {'type': 'str', 'value': 'TestComponent'}
# }
```

### `print_object_details(obj, log, name="Object", max_value_length=5000)`

Prints formatted details of all attributes of the given object to a logger.

**Parameters:**
- `obj`: The object to inspect
- `log`: Logger instance to write output to
- `name`: A name to identify the object in the output (default: "Object")
- `max_value_length`: Maximum length for printing attribute values (default: 5000)

**Output Format:**
```
=== {name} Details ===
Class: {ClassName}
Total attributes: {count}
--------------------------------------------------------------------------------
attribute_name: type_name = value
...
--------------------------------------------------------------------------------
```

```python
# Example usage
import logging
log = logging.getLogger(__name__)

class SignalContainer:
    def __init__(self):
        self.clock = None
        self.reset = None
        self.valid = True
        self.data = bytearray([0xDE, 0xAD, 0xBE, 0xEF])

signals = SignalContainer()
print_object_details(signals, log, "Signal Container")

# Output:
# === Signal Container Details ===
# Class: SignalContainer
# Total attributes: 4
# --------------------------------------------------------------------------------
# clock: NoneType = None
# data: bytearray = bytearray(b'\xde\xad\xbe\xef')
# reset: NoneType = None
# valid: bool = True
# --------------------------------------------------------------------------------
```

### `print_dict_to_log(name, d, log, prefix="")`

Print dictionary to logger with each key-value pair on its own line.

**Parameters:**
- `name`: Name/title for the dictionary output
- `d`: Dictionary to print
- `log`: Logger instance to write output to
- `prefix`: Optional prefix for each line (default: "")

**Output Format:**
```
=== {name} Details ===
{prefix}::{key}: {value}
...
```

```python
# Example usage
config_dict = {
    'addr_width': 32,
    'data_width': 64, 
    'protocol': 'AXI4',
    'endianness': 'little'
}

print_dict_to_log("Configuration", config_dict, log, prefix="CONFIG")

# Output (insertion order):
# === Configuration Details ===
# CONFIG::addr_width: 32
# CONFIG::data_width: 64
# CONFIG::protocol: AXI4
# CONFIG::endianness: little
```

## Usage Patterns

### Basic Object Inspection

```python
def debug_component_state(component, log):
    """Debug helper to inspect component state"""
    log.info("=== Component State Debug ===")
    
    # Get detailed attribute information
    details = get_object_details(component)
    
    # Print formatted details
    print_object_details(component, log, "Component State")
    
    # Print specific attribute if needed
    if 'status' in details:
        log.info(f"Component status: {details['status']['value']} ({details['status']['type']})")
```

### Signal Debugging

```python
def debug_bus_signals(bus, log):
    """Debug all signals on a bus object"""
    print_object_details(bus, log, "Bus Signals")
    
    # Get raw details for programmatic inspection
    details = get_object_details(bus)
    
    # Check for specific signal types
    signal_attrs = []
    for attr_name, info in details.items():
        if 'signal' in info['type'].lower():
            signal_attrs.append(attr_name)
    
    if signal_attrs:
        log.info(f"Found {len(signal_attrs)} signals: {signal_attrs}")
    else:
        log.warning("No signal attributes found on bus")
```

### Configuration Debugging

```python
def debug_field_config(field_config, log):
    """Debug field configuration contents"""
    config_dict = {}
    
    # Extract field information
    for field_name in field_config.field_names():
        field_def = field_config.get_field(field_name)
        config_dict[field_name] = {
            'bits': field_def.bits,
            'format': field_def.format,
            'default': field_def.default
        }
    
    print_dict_to_log("Field Configuration", config_dict, log, "FIELD")
```

### Transaction Debugging

```python
def debug_transaction(packet, log):
    """Debug transaction packet contents"""
    log.info("=== Transaction Debug ===")
    
    # Print full packet details
    print_object_details(packet, log, "Transaction Packet")
    
    # Print FIFO representation
    if hasattr(packet, 'pack_for_fifo'):
        fifo_data = packet.pack_for_fifo()
        print_dict_to_log("FIFO Data", fifo_data, log, "FIFO")
    
    # Check for timing information
    details = get_object_details(packet)
    timing_attrs = ['start_time', 'end_time', 'duration']
    
    for attr in timing_attrs:
        if attr in details and details[attr]['value'] != 0:
            log.info(f"Timing - {attr}: {details[attr]['value']}")
```

### Error Handling in Object Inspection

```python
def safe_object_debug(obj, log, obj_name="Unknown"):
    """Safely debug an object with error handling"""
    try:
        print_object_details(obj, log, obj_name)
    except Exception as e:
        log.error(f"Failed to debug {obj_name}: {e}")
        
        # Fallback - basic information
        log.info(f"{obj_name} type: {type(obj)}")
        log.info(f"{obj_name} dir: {[attr for attr in dir(obj) if not attr.startswith('_')]}")
```

### Comparative Debugging

```python
def compare_objects(obj1, obj2, log, name1="Object1", name2="Object2"):
    """Compare two objects and highlight differences"""
    details1 = get_object_details(obj1)
    details2 = get_object_details(obj2)
    
    # Find common attributes
    common_attrs = set(details1.keys()) & set(details2.keys())
    only_in_1 = set(details1.keys()) - set(details2.keys())
    only_in_2 = set(details2.keys()) - set(details1.keys())
    
    log.info(f"=== Comparing {name1} vs {name2} ===")
    
    # Report differences
    differences = []
    for attr in common_attrs:
        if details1[attr]['value'] != details2[attr]['value']:
            differences.append(attr)
            log.info(f"DIFF {attr}: {name1}={details1[attr]['value']} vs {name2}={details2[attr]['value']}")
    
    if only_in_1:
        log.info(f"Only in {name1}: {list(only_in_1)}")
    
    if only_in_2:
        log.info(f"Only in {name2}: {list(only_in_2)}")
        
    if not differences and not only_in_1 and not only_in_2:
        log.info("Objects are identical")
    
    return {
        'differences': differences,
        'only_in_1': list(only_in_1),
        'only_in_2': list(only_in_2)
    }
```

The comparative pattern earns its keep when a packet mutates somewhere between the driver and the scoreboard and you can't tell where. Snapshot both ends, diff them, and the field that changed names itself.

## Integration with CocoTB

### Signal State Debugging

```python
@cocotb.coroutine
def debug_signal_states(dut, log):
    """Debug all DUT signal states"""
    log.info("=== DUT Signal States ===")
    
    # Get all top-level signals
    signals = {}
    for attr_name in dir(dut):
        if not attr_name.startswith('_'):
            try:
                attr = getattr(dut, attr_name)
                if hasattr(attr, 'value'):
                    signals[attr_name] = {
                        'value': str(attr.value),
                        'type': type(attr).__name__
                    }
            except:
                pass
    
    print_dict_to_log("DUT Signals", signals, log, "SIG")
```

### Component State Snapshots

```python
def create_debug_snapshot(component, log, snapshot_name=""):
    """Create a debug snapshot of component state"""
    timestamp = cocotb.utils.get_sim_time()
    log.info(f"=== Debug Snapshot: {snapshot_name} at {timestamp} ===")
    
    print_object_details(component, log, f"Component Snapshot ({snapshot_name})")
    
    # Include statistics if available
    if hasattr(component, 'stats') and hasattr(component.stats, 'get_stats'):
        stats = component.stats.get_stats()
        print_dict_to_log("Component Statistics", stats, log, "STAT")
```

## Error Handling

The debug functions are built to survive the objects you're most likely to throw at them:

- **Attribute Access Errors**: Attributes that raise on access are handled safely
- **Type Conversion Errors**: Objects that can't be stringified don't kill the dump
- **Missing Logger**: Functions fall back to print if the logger is None
- **Large Objects**: Long string representations are truncated automatically

## Best Practices

1. **Use During Development**: Crank up the detail while you're bringing a test up, then dial it back for regression runs — full object dumps are not cheap.

2. **Snapshot Key States**: Take snapshots at test milestones so you can compare "known good" against "whatever this is."

3. **Compare Before/After**: Object comparison is the fastest way to find the field that moved.

4. **Filter Output**: Use `max_value_length` to keep large objects from flooding the log.

5. **Conditional Debugging**: Gate the dumps behind a log level so they vanish when you don't need them:

```python
if log.isEnabledFor(logging.DEBUG):
    print_object_details(complex_object, log, "Debug State")
```

---
