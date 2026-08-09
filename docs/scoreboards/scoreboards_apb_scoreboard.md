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

# apb_scoreboard.py

Two scoreboards live here. `APBScoreboard` handles the single-slave case; `APBCrossbarScoreboard` handles systems where an address decoder steers each transaction to one of several slaves. There's also an APB→GAXI transformer kept here for backward compatibility.

## Overview

- **Single-Slave Verification**: straightforward expected-vs-actual checking for one APB slave
- **Multi-Slave Support**: address-based routing to a per-slave scoreboard
- **Direction-Aware Comparison**: reads and writes compared on the fields that matter to each
- **Enhanced Error Reporting**: mismatches logged field by field
- **Protocol Transformation**: APB → GAXI conversion support

## Classes

### APBScoreboard

The single-slave workhorse. Queueing and reporting come from `BaseScoreboard`; what this class adds is APB-aware comparison and mismatch logging that actually tells you which field broke.

```python
class APBScoreboard(BaseScoreboard):
    def __init__(self, name, addr_width=32, data_width=32, log=None)
```

**Parameters:**
- `name`: scoreboard name; shows up in reports
- `addr_width`: address bus width in bits (default: 32)
- `data_width`: data bus width in bits (default: 32)
- `log`: logger for mismatch detail

**Key Attributes:**
- `addr_width`: address bus width
- `data_width`: data bus width  
- `strb_width`: strobe width (data_width // 8)
- `master_transactions`: transactions tracked by master ID

## Core Methods

### Transaction Comparison

#### `_compare_transactions(expected, actual)`
Comparison the simple way: type-check both packets, then lean on `APBPacket.__eq__`, which already knows which fields matter.

**Parameters:**
- `expected`: expected APB transaction (APBPacket)
- `actual`: actual APB transaction (APBPacket)

**Returns:**
- `bool`: True on match, False otherwise

**Comparison Logic:**
- Both transactions must be APBPacket instances
- Uses APBPacket's built-in `__eq__` method
- Direction, address, data, and control fields are all covered by that equality

```python
# Automatic comparison when both transactions available
scoreboard.add_expected(expected_apb_packet)
scoreboard.add_actual(actual_apb_packet)  # Triggers comparison
```

#### `_log_mismatch(expected, actual)`
When a comparison fails, this walks the packet field by field so the log names the difference—direction, address, data, strobe—instead of just announcing that one exists.

**Parameters:**
- `expected`: expected APB transaction
- `actual`: actual APB transaction

**Detailed Logging:**
- Direction mismatch detection
- Address field comparison
- Data field analysis for both read and write
- Strobe field validation
- Enable signal checking

```python
# Example mismatch log output:
# APB Cycle mismatch:
#   Expected: WRITE addr=0x1000 data=0xDEADBEEF strb=0xF
#   Actual:   WRITE addr=0x1000 data=0xBEEFDEAD strb=0xF
#   Data mismatch: expected=0xDEADBEEF, actual=0xBEEFDEAD
```

## Multi-Slave Support

### APBCrossbarScoreboard

One `APBScoreboard` per slave under the hood, with an address map in front that routes each transaction where it belongs.

```python
class APBCrossbarScoreboard:
    def __init__(self, name, num_slaves, addr_width=32, data_width=32, log=None)
```

**Parameters:**
- `name`: scoreboard name
- `num_slaves`: how many slaves sit behind the crossbar
- `addr_width`: address bus width (default: 32)
- `data_width`: data bus width (default: 32)  
- `log`: logger instance

**Architecture:**
- An individual `APBScoreboard` for each slave
- Address-based routing, automatic once configured
- Address ranges you can redefine per slave
- One combined report across all of them

### Address Mapping

#### `set_address_map(addr_map)`
Give each slave its address range.

**Parameters:**
- `addr_map`: list of `(base_addr, end_addr)` tuples, one per slave

**Default Mapping:**
- Slave 0: 0x0000 - 0x0FFC
- Slave 1: 0x1000 - 0x1FFC
- Slave N: N*0x1000 - (N*0x1000 + 0xFFC)

```python
# Custom address mapping
scoreboard = APBCrossbarScoreboard("MultiSlave", num_slaves=3)
addr_map = [
    (0x0000, 0x7FFF),  # Slave 0: 32KB
    (0x8000, 0xBFFF),  # Slave 1: 16KB  
    (0xC000, 0xFFFF),  # Slave 2: 16KB
]
scoreboard.set_address_map(addr_map)
```

#### `get_slave_idx(addr)`
Which slave owns this address?

**Parameters:**
- `addr`: the address to route

**Returns:**
- `int`: slave index

**Routing Logic:**
1. Check the configured map for a range that contains the address
2. If nothing claims it, fall back to modulo routing: `addr // 0x1000 % num_slaves`—a misconfigured map degrades to something predictable instead of dropping the transaction

### Transaction Management

#### `add_master_transaction(transaction, master_id)`
Add a master-side transaction; the scoreboard routes it.

**Parameters:**
- `transaction`: the APB transaction to route
- `master_id`: master identifier for tracking

**Behavior:**
- Resolves the target slave with `get_slave_idx()`
- Forwards the transaction to that slave's scoreboard
- Keeps per-master tracking up to date

```python
# Automatic routing based on address
scoreboard.add_master_transaction(transaction, master_id=0)
# Transaction routed to correct slave based on address
```

#### `add_slave_transaction(transaction, slave_idx)`
Add a transaction that came from a specific slave.

**Parameters:**
- `transaction`: APB transaction from the slave
- `slave_idx`: slave index (0 to num_slaves-1)

**Error Handling:**
- Out-of-range slave indices are logged, not silently accepted

### Reporting

#### `report()`
One line per slave, plus the overall verdict.

**Returns:**
- `str`: combined report from all slave scoreboards

**Report Format:**
```
APB Multi-Slave Scoreboard Report (MultiSlave):
Slave 0: PASS
Slave 1: FAIL (0.95)
Slave 2: PASS
Overall: FAIL
```

## Protocol Transformation

### APBtoGAXITransformer

APB-to-GAXI conversion.

> **Compatibility subclass.** This class now derives from the canonical
> `scoreboards.apb_gaxi_transformer.APBtoGAXITransformer`, keeping the
> constructor and list-returning `transform()` documented below while
> inheriting `apb_to_gaxi()` / `gaxi_to_apb()`. Both import paths work; reach for
> `apb_gaxi_transformer` in new code. See
> [APB-GAXI Transformer](scoreboards_apb_gaxi_transformer.md).

```python
class APBtoGAXITransformer(ProtocolTransformer):
    def __init__(self, gaxi_field_config, packet_class, log=None)
```

**Parameters:**
- `gaxi_field_config`: GAXI field configuration
- `packet_class`: GAXI packet class to instantiate
- `log`: logger instance

### Transformation Logic

#### `transform(apb_cycle)`
Convert one APB transaction into GAXI packet(s).

**Parameters:**
- `apb_cycle`: the APB packet to transform

**Returns:**
- `List[GAXIPacket]`: the transformed packets

**Field Mapping:**
- `apb.paddr` → `gaxi.addr`
- `apb.pwdata/prdata` → `gaxi.data` (direction-dependent)
- `apb.pstrb` → `gaxi.strb` (writes only)

```python
# Create transformer
transformer = APBtoGAXITransformer(gaxi_field_config, GAXIPacket, log=logger)

# Use with scoreboard
gaxi_scoreboard = GAXIScoreboard("Bridge", gaxi_field_config, log=logger)
gaxi_scoreboard.set_transformer(transformer)

# APB transactions automatically converted for GAXI comparison
gaxi_scoreboard.add_expected(apb_transaction)  # Transformed to GAXI
gaxi_scoreboard.add_actual(gaxi_packet)        # Direct comparison
```

## Usage Examples

### Basic Single-Slave Verification

The minimal loop: build expected and actual packets, hand them over, read the verdict.

```python
from CocoTBFramework.scoreboards.apb_scoreboard import APBScoreboard
from CocoTBFramework.components.apb.apb_packet import APBPacket

# Create scoreboard
scoreboard = APBScoreboard("APB_Slave", addr_width=32, data_width=32, log=logger)

# Create test transactions
expected = APBPacket()
expected.direction = 'WRITE'
expected.paddr = 0x1000
expected.pwdata = 0xDEADBEEF
expected.pstrb = 0xF

actual = APBPacket()
actual.direction = 'WRITE'  
actual.paddr = 0x1000
actual.pwdata = 0xDEADBEEF
actual.pstrb = 0xF

# Verify transactions
scoreboard.add_expected(expected)
scoreboard.add_actual(actual)

# Check results
error_count = scoreboard.report()
pass_rate = scoreboard.result()
print(f"Verification: {'PASS' if error_count == 0 else 'FAIL'} ({pass_rate:.2%})")
```

### Multi-Slave System Verification

Four peripherals, four address ranges, and routing you don't have to think about after setup.

```python
from CocoTBFramework.scoreboards.apb_scoreboard import APBCrossbarScoreboard

# Create multi-slave scoreboard
scoreboard = APBCrossbarScoreboard("APB_System", num_slaves=4, log=logger)

# Configure custom address mapping
addr_map = [
    (0x0000, 0x0FFF),  # Peripheral 0: GPIO
    (0x1000, 0x1FFF),  # Peripheral 1: UART
    (0x2000, 0x2FFF),  # Peripheral 2: SPI
    (0x3000, 0x3FFF),  # Peripheral 3: I2C
]
scoreboard.set_address_map(addr_map)

# Add transactions - automatically routed
gpio_transaction = create_apb4_transaction(addr=0x0100, data=0xFF)  # → Slave 0
uart_transaction = create_apb4_transaction(addr=0x1004, data=0x55)  # → Slave 1

scoreboard.add_master_transaction(gpio_transaction, master_id=0)
scoreboard.add_master_transaction(uart_transaction, master_id=0)

# Add expected slave responses
scoreboard.add_slave_transaction(gpio_response, slave_idx=0)
scoreboard.add_slave_transaction(uart_response, slave_idx=1)

# Generate comprehensive report
print(scoreboard.report())
```

### Cross-Protocol Bridge Verification

When the DUT converts APB to GAXI, install the transformer and compare in the GAXI domain.

```python
from CocoTBFramework.scoreboards.apb_scoreboard import APBtoGAXITransformer
from CocoTBFramework.scoreboards.gaxi_scoreboard import GAXIScoreboard

# Create transformer and target scoreboard
transformer = APBtoGAXITransformer(gaxi_field_config, GAXIPacket, log=logger)
bridge_scoreboard = GAXIScoreboard("APB_GAXI_Bridge", gaxi_field_config, log=logger)
bridge_scoreboard.set_transformer(transformer)

# Verify APB input produces correct GAXI output
apb_input = create_apb4_write(addr=0x2000, data=0x12345678)
gaxi_output = monitor_gaxi_transaction()

bridge_scoreboard.add_expected(apb_input)    # Automatically transformed
bridge_scoreboard.add_actual(gaxi_output)   # Direct GAXI comparison

# Analysis
errors = bridge_scoreboard.report()
if errors == 0:
    print("Bridge verification passed")
else:
    print(f"Bridge verification failed: {errors} errors")
```

### Enhanced Error Analysis

Subclass and override `_log_mismatch` when you want arithmetic on the mismatch—address offsets and XOR masks beat eyeballing hex dumps.

```python
# Custom scoreboard with detailed error reporting
class DetailedAPBScoreboard(APBScoreboard):
    def _log_mismatch(self, expected, actual):
        super()._log_mismatch(expected, actual)
        
        # Additional analysis
        if self.log:
            if expected.paddr != actual.paddr:
                addr_diff = actual.paddr - expected.paddr
                self.log.error(f"  Address offset: 0x{addr_diff:X}")
            
            if hasattr(expected, 'pwdata') and hasattr(actual, 'pwdata'):
                if expected.pwdata != actual.pwdata:
                    xor_result = expected.pwdata ^ actual.pwdata
                    self.log.error(f"  Data XOR: 0x{xor_result:08X}")

# Usage with enhanced reporting
detailed_scoreboard = DetailedAPBScoreboard("Detailed", log=logger)
```

## Best Practices

### Address Mapping Configuration
- Keep slave ranges clear and non-overlapping
- Power-of-2 boundaries make the decode logic—and your debugging—easier
- Write the map down in the test configuration so the bench and the DUT can't drift apart

### Transaction Tracking
- Meaningful master IDs pay off when you're correlating transactions later
- `clear()` between test phases
- Watch queue sizes in long runs

### Error Analysis
- Leave detailed logging on while debugging mismatches
- The field-by-field output is your first stop, not the waveform
- Keep mismatch pairs around for post-test analysis

### Performance Optimization
- Size queues for the traffic you actually expect
- Use batch operations when pushing large transaction sets
- Retire completed transactions periodically

## Integration Points

### Monitor Integration

```python
# Connect APB monitor to scoreboard
def on_apb_transaction(packet):
    scoreboard.add_actual(packet)

apb_monitor.add_callback(on_apb_transaction)
```

### Test Sequence Integration

```python
# Generate expected transactions from test sequence
sequence = APBSequence("test_pattern")
for packet in sequence.generate():
    scoreboard.add_expected(packet)
```

Single slave or a whole crossbar, it's the same comparison machinery underneath—with the transformer hook for when the DUT turns out to be a bridge.
