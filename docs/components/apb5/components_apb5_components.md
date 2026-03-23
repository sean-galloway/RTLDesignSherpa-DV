# apb5_components.py

APB5 Protocol Components providing Monitor, Master, and Slave implementations with AMBA5 extension support. This module extends the APB4 protocol components with user-defined signals, wake-up support, and parity signal monitoring for comprehensive APB5 verification.

## Overview

The `apb5_components.py` module provides three main classes that implement the APB5 protocol:
- **APB5Monitor**: Observes and logs APB5 transactions including user signals and wake-up
- **APB5Slave**: Responds to APB5 transactions with memory backing and randomized user signal responses
- **APB5Master**: Drives APB5 transactions with user signal and wake-up capture support

### Key Features
- **Full APB5 signal support** with optional signal handling for all AMBA5 extensions
- **User signal channels** (PAUSER, PWUSER, PRUSER, PBUSER) with configurable widths
- **Wake-up signal support** via PWAKEUP
- **Optional parity signal monitoring** (PWDATAPARITY, PADDRPARITY, PCTRLPARITY, etc.)
- **Memory model integration** for realistic slave behavior
- **Configurable timing randomization** with user signal value randomization
- **Transaction queuing and pipelining** for performance testing

## Constants and Mappings

### Signal Definitions

```python
# APB PWRITE mapping
pwrite = ['READ', 'WRITE']

# Required APB5 signals (APB4 base)
apb5_signals = [
    "PSEL",      # Peripheral select
    "PWRITE",    # Write enable
    "PENABLE",   # Enable signal
    "PADDR",     # Address bus
    "PWDATA",    # Write data bus
    "PRDATA",    # Read data bus
    "PREADY"     # Ready signal
]

# Optional APB5 signals (APB4 + AMBA5 extensions)
apb5_optional_signals = [
    "PPROT",           # Protection control
    "PSLVERR",         # Slave error
    "PSTRB",           # Write strobes
    "PAUSER",          # Request user attributes
    "PWUSER",          # Write data user attributes
    "PRUSER",          # Read data user attributes
    "PBUSER",          # Response user attributes
    "PWAKEUP",         # Wake-up request
    "PWDATAPARITY",    # Write data parity
    "PADDRPARITY",     # Address parity
    "PCTRLPARITY",     # Control signal parity
    "PRDATAPARITY",    # Read data parity
    "PREADYPARITY",    # Ready parity
    "PSLVERRPARITY",   # Slave error parity
]
```

## Core Classes

### APB5Monitor

Bus monitor for observing and logging APB5 transactions without interfering with protocol operation. Captures all APB5 extension signals including user attributes and wake-up status.

#### Constructor

```python
APB5Monitor(entity, title, prefix, clock, signals=None,
            bus_width=32, addr_width=12,
            auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
            log=None, **kwargs)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | object | *required* | DUT entity to monitor |
| `title` | str | *required* | Monitor identifier for logging |
| `prefix` | str | *required* | Signal prefix for bus connection (trailing `_` auto-stripped) |
| `clock` | signal | *required* | Clock signal for synchronization |
| `signals` | list | None | Custom signal list (default: all APB5 signals) |
| `bus_width` | int | 32 | Data bus width in bits |
| `addr_width` | int | 12 | Address bus width in bits |
| `auser_width` | int | 4 | PAUSER width in bits |
| `wuser_width` | int | 4 | PWUSER width in bits |
| `ruser_width` | int | 4 | PRUSER width in bits |
| `buser_width` | int | 4 | PBUSER width in bits |
| `log` | Logger | None | Logger instance (default: entity logger) |

```python
# Create APB5 monitor
monitor = APB5Monitor(
    entity=dut,
    title="APB5_Monitor",
    prefix="apb_",
    clock=dut.clk,
    bus_width=32,
    addr_width=16,
    auser_width=8,
    ruser_width=8
)
```

#### Methods

##### `is_signal_present(signal_name) -> bool`
Check if an optional signal is present and connected on the bus.

```python
if monitor.is_signal_present('PWAKEUP'):
    # Handle wake-up signal monitoring
    pass

if monitor.is_signal_present('PAUSER'):
    # User signal is available
    pass
```

##### `print(transaction)`
Print formatted transaction information to log at debug level.

**Parameters:**
- `transaction`: APB5Packet transaction to display

```python
monitor.print(packet)  # Logs: "APB5_Monitor - APB5 Transaction #1: APB5Packet(...)"
```

#### Transaction Detection

The monitor automatically detects valid APB5 transactions when:
- `PSEL` is asserted
- `PENABLE` is asserted
- `PREADY` is asserted
- All signals have resolvable values

On detection, the monitor captures all present APB5 extension signals (PAUSER, PWUSER, PRUSER, PBUSER, PWAKEUP) and creates an APB5Packet record. Sampling occurs on the falling clock edge with a 200ps settling delay.

### APB5Slave

APB5 slave implementation with memory backing, configurable response behavior, and randomized user signal responses.

#### Constructor

```python
APB5Slave(entity, title, prefix, clock, registers, signals=None,
          bus_width=32, addr_width=12,
          auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
          randomizer=None, log=None, error_overflow=False,
          wakeup_generator=None, **kwargs)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | object | *required* | DUT entity to connect to |
| `title` | str | *required* | Slave identifier for logging |
| `prefix` | str | *required* | Signal prefix for bus connection (trailing `_` auto-stripped) |
| `clock` | signal | *required* | Clock signal for synchronization |
| `registers` | list[int] | *required* | Initial register values (byte array) |
| `signals` | list | None | Custom signal list (default: all APB5 signals) |
| `bus_width` | int | 32 | Data bus width in bits |
| `addr_width` | int | 12 | Address bus width in bits |
| `auser_width` | int | 4 | PAUSER width in bits |
| `wuser_width` | int | 4 | PWUSER width in bits |
| `ruser_width` | int | 4 | PRUSER width in bits |
| `buser_width` | int | 4 | PBUSER width in bits |
| `randomizer` | FlexRandomizer | None | Timing and user signal randomizer |
| `log` | Logger | None | Logger instance (default: entity logger) |
| `error_overflow` | bool | False | Generate errors on address overflow |
| `wakeup_generator` | callable | None | Callback to generate wake-up events |

```python
# Create APB5 slave with 256 registers and error overflow detection
registers = [0] * 1024  # 256 32-bit registers
slave = APB5Slave(
    entity=dut,
    title="APB5_Slave",
    prefix="apb_",
    clock=dut.clk,
    registers=registers,
    bus_width=32,
    addr_width=16,
    ruser_width=8,
    buser_width=8,
    error_overflow=True
)
```

#### Default Randomizer

When no randomizer is provided, the slave uses a default configuration:

```python
FlexRandomizer({
    'ready': ([(0, 1), (2, 5), (6, 10)], [5, 2, 1]),      # Mostly short delays
    'error': ([(0, 0), (1, 1)], [10, 0]),                  # No errors by default
    'pruser': ([(0, (1 << ruser_width) - 1)], [1]),        # Random PRUSER values
    'pbuser': ([(0, (1 << buser_width) - 1)], [1]),        # Random PBUSER values
})
```

#### Methods

##### `is_signal_present(signal_name) -> bool`
Check if an optional signal is present on the bus.

```python
if slave.is_signal_present('PRUSER'):
    # PRUSER signal is connected
    pass
```

##### `print(transaction)`
Print transaction for debug logging.

##### `set_wakeup(value)`
Set the PWAKEUP signal value. Only effective if PWAKEUP is present on the bus.

**Parameters:**
- `value`: Integer value to drive on PWAKEUP (0 or 1)

```python
await slave.set_wakeup(1)  # Assert wake-up
# ... perform operations ...
await slave.set_wakeup(0)  # Deassert wake-up
```

#### Response Behavior

The slave provides configurable response timing and user signal generation:
- **Ready Delay**: Configurable cycles before asserting PREADY (via `ready` randomizer field)
- **Error Injection**: Random or deterministic error generation (via `error` randomizer field)
- **User Signal Response**: Randomized PRUSER and PBUSER values on each response
- **Wake-up Generation**: Optional wake-up generator callback
- **Address Overflow**: Configurable error on out-of-range addresses

#### Transaction Queue

The slave maintains a `sentQ` deque containing APB5Packet records of all processed transactions, accessible for post-transaction verification.

### APB5Master

APB5 master implementation that drives transactions with user signal support and response capture.

#### Constructor

```python
APB5Master(entity, title, prefix, clock,
           bus_width=32, addr_width=12,
           auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
           log=None, **kwargs)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | object | *required* | DUT entity to drive |
| `title` | str | *required* | Master identifier for logging |
| `prefix` | str | *required* | Signal prefix for bus connection (trailing `_` auto-stripped) |
| `clock` | signal | *required* | Clock signal for synchronization |
| `bus_width` | int | 32 | Data bus width in bits |
| `addr_width` | int | 12 | Address bus width in bits |
| `auser_width` | int | 4 | PAUSER width in bits |
| `wuser_width` | int | 4 | PWUSER width in bits |
| `ruser_width` | int | 4 | PRUSER width in bits |
| `buser_width` | int | 4 | PBUSER width in bits |
| `log` | Logger | None | Logger instance (default: entity logger) |

```python
# Create APB5 master with 8-bit user signals
master = APB5Master(
    entity=dut,
    title="APB5_Master",
    prefix="apb_",
    clock=dut.clk,
    bus_width=32,
    addr_width=16,
    auser_width=8,
    wuser_width=8
)
```

#### Methods

##### `is_signal_present(signal_name) -> bool`
Check if a signal is present on the bus.

##### `send(transaction)`
Send an APB5 transaction. Drives all present APB5 signals including user attributes.

**Parameters:**
- `transaction`: APB5Packet to transmit

```python
packet = APB5Packet(
    pwrite=1, paddr=0x100,
    pwdata=0xDEADBEEF,
    pstrb=0xF,
    pauser=0x5,
    pwuser=0xA
)
await master.send(packet)
```

##### `write(address, data, strb=None, pprot=0, pauser=0, pwuser=0) -> APB5Packet`
Perform an APB5 write transaction with convenience parameters.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `address` | int | *required* | Target address |
| `data` | int | *required* | Write data value |
| `strb` | int | None | Write strobe mask (default: all bytes enabled) |
| `pprot` | int | 0 | Protection control value |
| `pauser` | int | 0 | Request user attribute value |
| `pwuser` | int | 0 | Write data user attribute value |

**Returns:** APB5Packet with completed transaction (including response fields)

```python
# Simple write
result = await master.write(address=0x200, data=0x12345678)

# Write with user signals and partial strobe
result = await master.write(
    address=0x300,
    data=0xAABBCCDD,
    strb=0x3,
    pauser=0xF,
    pwuser=0x5
)
```

##### `read(address, pprot=0, pauser=0) -> APB5Packet`
Perform an APB5 read transaction with convenience parameters.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `address` | int | *required* | Target address |
| `pprot` | int | 0 | Protection control value |
| `pauser` | int | 0 | Request user attribute value |

**Returns:** APB5Packet with completed transaction (prdata, pruser, pbuser populated)

```python
# Simple read
result = await master.read(address=0x200)
read_data = result.fields['prdata']
ruser_val = result.fields['pruser']

# Read with user attribute
result = await master.read(address=0x300, pauser=0xA)
```

#### Transaction Pipeline

The master implements the standard APB transaction pipeline with APB5 extensions:
1. **Setup Phase**: Drive PSEL, PADDR, PWRITE, PWDATA, PSTRB, PPROT, PAUSER, PWUSER
2. **Access Phase**: Assert PENABLE
3. **Wait for Ready**: Poll PREADY on rising clock edges
4. **Response Capture**: Sample PRDATA, PSLVERR, PRUSER, PBUSER, PWAKEUP (with 200ps settling delay)
5. **Deassert**: Clear PSEL and PENABLE

#### Transaction Queue

The master maintains a `sentQ` deque containing APB5Packet records of all completed transactions.

## Usage Patterns

### Basic Monitor Setup

```python
import cocotb
from cocotb.triggers import Timer
from CocoTBFramework.components.apb5 import APB5Monitor

@cocotb.test()
async def monitor_test(dut):
    monitor = APB5Monitor(
        entity=dut,
        title="Protocol_Monitor",
        prefix="apb_",
        clock=dut.clk,
        bus_width=32,
        auser_width=8
    )

    # Add callback for transaction observation
    def transaction_callback(packet):
        print(f"Observed: {packet.formatted(compact=True)}")
        print(f"  PAUSER: 0x{packet.fields['pauser']:02X}")
        print(f"  PRUSER: 0x{packet.fields['pruser']:02X}")

    monitor.add_callback(transaction_callback)

    # Monitor runs automatically
    await Timer(1000, units='ns')
```

### Master-Slave Communication with User Signals

```python
from cocotb.triggers import RisingEdge
from CocoTBFramework.components.apb5 import APB5Master, APB5Slave, APB5Packet

async def master_slave_test(dut):
    master = APB5Master(dut, "Master", "m_apb_", dut.clk, auser_width=8)
    slave = APB5Slave(
        dut, "Slave", "s_apb_", dut.clk,
        registers=[0] * 256,
        ruser_width=8, buser_width=8
    )

    # Write with user attributes
    write_pkt = APB5Packet(
        pwrite=1, paddr=0x100,
        pwdata=0x12345678,
        pstrb=0xF,
        pauser=0xAB,
        pwuser=0xCD
    )
    await master.send(write_pkt)

    # Read back - response will include randomized PRUSER and PBUSER
    result = await master.read(address=0x100, pauser=0xAB)
    print(f"Read data: 0x{result.fields['prdata']:08X}")
    print(f"PRUSER: 0x{result.fields['pruser']:02X}")
    print(f"PBUSER: 0x{result.fields['pbuser']:02X}")
```

### Custom Slave Randomizer with User Signals

```python
from CocoTBFramework.components.apb5 import create_apb5_slave, create_apb5_randomizer

async def custom_randomizer_test(dut):
    # Create randomizer with specific user signal patterns
    randomizer = create_apb5_randomizer(
        ready_delay_weights=([(0, 0), (1, 3)], [4, 1]),
        error_weights=([(0, 0), (1, 1)], [5, 1]),
        ruser_width=8,
        buser_width=8
    )

    slave = create_apb5_slave(
        dut, "Custom_Slave", "apb_", dut.clk,
        registers=[0] * 512,
        ruser_width=8, buser_width=8,
        randomizer=randomizer,
        error_overflow=True
    )
```

## Integration with Framework

### Memory Model Integration

The APB5Slave uses the shared MemoryModel for realistic memory behavior:

```python
# Memory model provides:
# - Byte-level access control with strobe masks
# - Access tracking and coverage
# - Boundary checking with configurable overflow behavior
# - Preset register values
```

### Packet Integration

Components work seamlessly with APB5Packet:

```python
# Automatic field extraction including user signals
# Protocol compliance checking
# Transaction correlation via sentQ
# APB4 backward compatibility via to_apb4_packet()
```

### Randomization Integration

Uses FlexRandomizer for comprehensive timing and user signal control:

```python
# Configurable delay distributions for PREADY
# Error injection patterns via error field
# Randomized PRUSER and PBUSER values per response
# Full range based on configured user signal widths
```

## Best Practices

### 1. **Match User Signal Widths**
```python
# Ensure widths match between master, slave, and monitor
AUSER_W = 8
RUSER_W = 8

master = APB5Master(dut, "M", "apb_", dut.clk, auser_width=AUSER_W)
slave = APB5Slave(dut, "S", "apb_", dut.clk, registers=[0]*256,
                  auser_width=AUSER_W, ruser_width=RUSER_W)
monitor = APB5Monitor(dut, "Mon", "apb_", dut.clk,
                      auser_width=AUSER_W, ruser_width=RUSER_W)
```

### 2. **Handle Optional Signals Gracefully**
```python
# Always check signal presence before accessing
if master.is_signal_present('PAUSER'):
    # PAUSER is connected
    pass

if slave.is_signal_present('PWAKEUP'):
    await slave.set_wakeup(1)
```

### 3. **Verify User Signal Round-Trip**
```python
# Check that user signals are captured correctly
await master.send(packet)
sent = master.sentQ[-1]
observed = monitor.recv_queue[-1]  # If using callbacks

assert sent.fields['pauser'] == observed.fields['pauser']
```

The APB5 components provide a comprehensive foundation for APB5 protocol verification, extending the proven APB4 infrastructure with full AMBA5 extension support for user signals, wake-up, and parity checking.
