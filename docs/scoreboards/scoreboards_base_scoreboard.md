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

# base_scoreboard.py

Every protocol scoreboard in the framework descends from `BaseScoreboard`. It owns the two queues—expected and actual—the compare-on-arrival machinery, error counting, and reporting. Subclasses only have to answer one question: do these two transactions match? The other half of this file, `ProtocolTransformer`, covers the case where expected and actual don't even speak the same protocol.

## Overview

- **Transaction Queue Management**: expected vs. actual, matched automatically
- **Comparison Framework**: the matching machinery; you supply the comparison
- **Error Tracking**: counts, mismatch pairs, logging
- **Protocol Transformation**: the hook for cross-protocol checking
- **Statistics Generation**: pass/fail rates and reporting

## Classes

### BaseScoreboard

The base class for every protocol scoreboard in the framework.

```python
class BaseScoreboard:
    def __init__(self, name, log=None)
```

**Parameters:**
- `name`: shows up in logs and report headers
- `log`: where the detail goes

**Core Attributes:**
- `expected_queue`: deque of transactions you're waiting for
- `actual_queue`: deque of transactions the DUT produced  
- `error_count`: mismatches so far
- `transaction_count`: everything processed
- `mismatched`: the (expected, actual) pairs that failed, kept for inspection
- `transformer`: optional protocol converter

## Core Methods

### Transaction Management

#### `add_expected(transaction)`
Queue a transaction you expect the DUT to produce. If a transformer is installed, the conversion happens here—that's the whole cross-protocol trick.

**Parameters:**
- `transaction`: the expected transaction

**Behavior:**
- With a transformer set, the transaction is converted before queueing
- Transformed results land in the expected queue
- One source transaction can produce several queued expectations

```python
# Basic usage
scoreboard.add_expected(expected_packet)

# With transformer
scoreboard.set_transformer(apb_to_gaxi_transformer)
scoreboard.add_expected(apb_transaction)  # Automatically transformed to GAXI
```

#### `add_actual(transaction)`
Queue something the DUT actually did. If an expected transaction is waiting, the comparison runs immediately—failures surface at the moment of mismatch, not at end of test.

**Parameters:**
- `transaction`: the transaction that arrived

**Behavior:**
- Added to the actual queue
- Transaction counter bumped
- `_compare_next()` fires as soon as both queues have something to compare

```python
# Automatic comparison triggered
scoreboard.add_actual(actual_packet)
```

### Comparison Framework

#### `_compare_next()`
The engine room. Pops one transaction from each queue, calls your `_compare_transactions()`, and on failure bumps the error count, saves the pair in `mismatched`, and calls `_log_mismatch()`.

#### `_compare_transactions(expected, actual)` *(Abstract)*
The one method you must write. Return True if the two transactions agree.

**Parameters:**
- `expected`: expected transaction
- `actual`: actual transaction

**Returns:**
- `bool`: True on match, False otherwise

**Implementation Example:**
```python
def _compare_transactions(self, expected, actual):
    """Compare APB transactions based on direction, address, and data"""
    if not isinstance(expected, APBPacket) or not isinstance(actual, APBPacket):
        return False
    
    return expected == actual  # Use packet's __eq__ method
```

#### `_log_mismatch(expected, actual)`
Override this. The default logs the two transactions; a good override tells you which field broke.

**Parameters:**
- `expected`: expected transaction
- `actual`: actual transaction

**Default Behavior:**
- Logs a basic mismatch with the transaction strings
- Protocol-specific subclasses usually do field-by-field comparison

### Reporting and Statistics

#### `report()`
End-of-test accounting. Leftover expecteds are failures (something you predicted never happened); leftover actuals are failures too (the DUT did something you didn't predict). Both land in the count.

**Returns:**
- `int`: total errors—mismatches plus leftovers

**Report Contents:**
- Leftover expected transactions (never received)
- Leftover actual transactions (nothing expected them)
- Total transaction count and error summary

```python
error_count = scoreboard.report()
if error_count == 0:
    print("All transactions matched successfully")
```

#### `result()`
Pass rate as a ratio.

**Returns:**
- `float`: pass rate from 0.0 to 1.0

**Calculation:**
- Total = transaction_count + len(expected_queue)
- Failures = error_count + len(expected_queue) + len(actual_queue)
- Result = (total - failures) / total

```python
pass_rate = scoreboard.result()
print(f"Verification pass rate: {pass_rate:.2%}")
```

### Utility Methods

#### `set_transformer(transformer)`
Install the converter. From here on, expected transactions are transformed before queueing.

**Parameters:**
- `transformer`: ProtocolTransformer instance

```python
transformer = APBtoGAXITransformer(gaxi_field_config, GAXIPacket)
scoreboard.set_transformer(transformer)
```

#### `clear()`
Queues emptied, counters zeroed, transformer kept. Use between test phases.

```python
# Reset between test phases
scoreboard.clear()
```

## Protocol Transformer Framework

### ProtocolTransformer

The base class for protocol converters. Note that `transform()` returns a *list*: one source transaction can legitimately become zero target transactions (the conversion failed) or several.

```python
class ProtocolTransformer:
    def __init__(self, source_type, target_type, log=None)
```

**Parameters:**
- `source_type`: source protocol name (e.g., "APB")
- `target_type`: target protocol name (e.g., "GAXI")
- `log`: logger instance

**Statistics:**
- `num_transformations`: conversions that worked
- `num_failures`: conversions that didn't

### Core Methods

#### `transform(transaction)` *(Abstract)*
Do the conversion. Return a list of target transactions—empty if it can't be done.

**Parameters:**
- `transaction`: source transaction to transform

**Returns:**
- `List`: target transactions (empty if the conversion failed)

**Implementation Example:**
```python
def transform(self, apb_transaction):
    """Transform APB to GAXI transaction"""
    gaxi_packet = GAXIPacket(self.field_config)
    
    # Map fields
    gaxi_packet.addr = apb_transaction.paddr
    gaxi_packet.data = apb_transaction.pwdata if apb_transaction.direction == 'WRITE' else apb_transaction.prdata
    gaxi_packet.cmd = 1 if apb_transaction.direction == 'WRITE' else 0
    
    return [gaxi_packet]
```

#### `try_transform(transaction)`
`transform()` wrapped in exception handling, so one malformed packet doesn't take the whole test down. Failures get counted and logged; you get an empty list back.

**Parameters:**
- `transaction`: source transaction to transform

**Returns:**
- `List`: target transactions (empty on failure)

**Behavior:**
- Wraps `transform()` with exception handling
- Updates success/failure statistics
- Logs transformation errors

```python
# Safe transformation
results = transformer.try_transform(source_transaction)
if results:
    print(f"Transformation successful: {len(results)} target transactions")
```

#### `report()`
Conversion statistics as a string.

**Returns:**
- `str`: report with transformation statistics

```python
print(transformer.report())
# Output:
# APB to GAXI Transformer Report
#   Successful transformations: 150
#   Failed transformations: 3
```

## Usage Patterns

### Basic Scoreboard Usage

The minimal custom scoreboard: inherit, implement two methods, done.

```python
from CocoTBFramework.scoreboards.base_scoreboard import BaseScoreboard

class CustomScoreboard(BaseScoreboard):
    def _compare_transactions(self, expected, actual):
        # Implement protocol-specific comparison
        return expected.key_field == actual.key_field
    
    def _log_mismatch(self, expected, actual):
        # Enhanced mismatch logging
        if self.log:
            self.log.error(f"Mismatch in {self.name}:")
            self.log.error(f"  Expected: {expected}")
            self.log.error(f"  Actual: {actual}")

# Usage
scoreboard = CustomScoreboard("TestScoreboard", log=logger)
scoreboard.add_expected(expected_transaction)
scoreboard.add_actual(actual_transaction)
error_count = scoreboard.report()
```

### Protocol Transformation

A transformer in the wild: APB in, GAXI out.

```python
from CocoTBFramework.scoreboards.base_scoreboard import ProtocolTransformer

class APBtoGAXITransformer(ProtocolTransformer):
    def __init__(self, gaxi_field_config, log=None):
        super().__init__("APB", "GAXI", log)
        self.field_config = gaxi_field_config
    
    def transform(self, apb_transaction):
        # Create GAXI packet
        gaxi_packet = GAXIPacket(self.field_config)
        
        # Map protocol fields
        gaxi_packet.addr = apb_transaction.paddr
        gaxi_packet.cmd = 1 if apb_transaction.direction == 'WRITE' else 0
        
        if apb_transaction.direction == 'WRITE':
            gaxi_packet.data = apb_transaction.pwdata
        else:
            gaxi_packet.data = apb_transaction.prdata
            
        return [gaxi_packet]

# Usage with scoreboard
transformer = APBtoGAXITransformer(gaxi_field_config, log=logger)
scoreboard.set_transformer(transformer)

# APB transactions automatically converted to GAXI for comparison
scoreboard.add_expected(apb_transaction)  # Transformed to GAXI
scoreboard.add_actual(gaxi_packet)        # Direct GAXI comparison
```

### Multi-Protocol Verification

Wire the transformer into the scoreboard and the cross-protocol comparison writes itself.

```python
# Create cross-protocol verification system
apb_to_gaxi = APBtoGAXITransformer(gaxi_config, log=logger)
gaxi_scoreboard = GAXIScoreboard("Bridge", gaxi_config, log=logger)
gaxi_scoreboard.set_transformer(apb_to_gaxi)

# Verify APB input produces correct GAXI output
gaxi_scoreboard.add_expected(apb_input)    # Transformed to GAXI
gaxi_scoreboard.add_actual(gaxi_output)    # Direct comparison

# Generate verification results
errors = gaxi_scoreboard.report()
pass_rate = gaxi_scoreboard.result()
```

## Best Practices

### Error Handling
- Always pass a logger—you'll want the detail eventually, usually at the worst time
- Override `_log_mismatch()` for protocol-specific error analysis
- Use `try_transform()` unless you enjoy exceptions mid-test

### Performance Optimization
- `clear()` between test phases to keep memory in check
- The queues are deques for a reason; don't rebuild them as lists
- Watch transaction counts in long-running tests

### Extensibility
- Inherit from `BaseScoreboard` for protocol-specific scoreboards
- Write custom transformers for exotic conversions
- Compose transformers when one hop isn't enough

## Integration Points

### Monitor Integration
```python
# Connect monitor callbacks to scoreboard
def on_transaction_received(packet):
    scoreboard.add_actual(packet)

monitor.add_callback(on_transaction_received)
```

### Memory Model Integration

Scoreboards can also check against a memory model instead of queued expectations:

```python
# Memory-backed verification
class MemoryScoreboard(BaseScoreboard):
    def __init__(self, name, memory_model, log=None):
        super().__init__(name, log)
        self.memory = memory_model
    
    def _compare_transactions(self, expected, actual):
        # Compare against memory contents
        stored_data = self.memory.read(actual.addr)
        return stored_data == actual.data
```

Two classes, and everything else in this directory is a specialization of them.
