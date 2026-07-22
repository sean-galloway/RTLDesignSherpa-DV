# apb5_components.py

This module is where the APB5 protocol actually lives in the testbench: a monitor, a slave, and a master, all built on the APB4 components and extended with the AMBA5 extras — user-defined sideband signals, requester-driven wake-up, and parity signal monitoring.

## Overview

Three classes make up the component layer:

- **APB5Monitor**: watches the bus and records every completed transfer, user signals and PWAKEUP included, without driving a single pin
- **APB5Slave**: answers transfers out of a memory-backed register array, with configurable PREADY timing, error injection, and randomized PRUSER/PBUSER responses
- **APB5Master**: drives read and write transfers, carries the user signals end to end, and owns PWAKEUP

### PWAKEUP Direction

Worth stating up front, because earlier versions of this library modeled it the other way: per AMBA APB5 (IHI 0024E), **PWAKEUP is driven by the requester (master)**. It is asserted with (or before) PSEL and held until the transfer completes. That decision determines which component does what:

- **APB5Master** drives PWAKEUP — asserted with PSEL on every transfer when `wakeup_enable` is set, dropped when PSEL falls. The driven value is recorded in the transaction's `wakeup` field.
- **APB5Slave** and **APB5Monitor** only *observe* PWAKEUP. Whatever they sample lands in the captured packet's `wakeup` field; they never drive the pin.

### Key Features

- Full APB5 signal support, with every AMBA5 extension treated as optional
- Four user signal channels (PAUSER, PWUSER, PRUSER, PBUSER), each with its own width
- Requester-driven wake-up via PWAKEUP
- Optional parity signal monitoring (PWDATAPARITY, PADDRPARITY, PCTRLPARITY, and friends)
- Memory-backed slave model
- Timing randomization, plus randomized user-signal values on responses
- Transaction queues on master and slave for scoreboard hookup

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

The split between those two lists is what makes partial implementations painless: `apb5_signals` is bound as the `cocotb_bus` **required** signal list and `apb5_optional_signals` as the **optional** list, so a DUT that implements only some of the AMBA5 extensions still binds cleanly. The flip side is that you can't assume an extension signal exists — guard every access with `is_signal_present()`.

## Core Classes

### APB5Monitor

A pure observer. The monitor never drives the bus; it watches for completed transfers and captures everything that's there, including the AMBA5 user attributes and the wake-up state.

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

Returns True if the named signal is actually present on the bus. Call it before you touch any AMBA5 extension — that is the whole point of having optional signals.

```python
if monitor.is_signal_present('PWAKEUP'):
    # Handle wake-up signal monitoring
    pass

if monitor.is_signal_present('PAUSER'):
    # User signal is available
    pass
```

##### `print(transaction)`

Dumps a formatted transaction to the log at debug level.

**Parameters:**
- `transaction`: APB5Packet transaction to display

```python
monitor.print(packet)  # Logs: "APB5_Monitor - APB5 Transaction #1: APB5Packet(...)"
```

#### Transaction Detection

A transfer counts as complete when all of the following hold:

- `PSEL` is asserted
- `PENABLE` is asserted
- `PREADY` is asserted
- All signals have resolvable values

When that fires, the monitor captures whichever APB5 extension signals are present (PAUSER, PWUSER, PRUSER, PBUSER, PWAKEUP) and wraps the transfer in an APB5Packet. Sampling happens on the falling clock edge with a 200ps settling delay — far enough from the driving edge that you're never racing the DUT's own output logic.

### APB5Slave

The slave answers transfers out of a memory-backed register array. You control how long it takes to assert PREADY, how often it returns an error, and what it drives on PRUSER and PBUSER.

#### Constructor

```python
APB5Slave(entity, title, prefix, clock, registers, signals=None,
          bus_width=32, addr_width=12,
          auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
          randomizer=None, log=None, error_overflow=False, **kwargs)
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

> **Deprecated:** the old `wakeup_generator` parameter is still accepted for backward compatibility but **ignored** (with a `DeprecationWarning`). PWAKEUP belongs to the requester — control it via `APB5Master(wakeup_enable=...)` / `APB5Master.set_wakeup_enable()`.

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

If you don't pass a randomizer, the slave builds this one:

```python
FlexRandomizer({
    'ready': ([(0, 1), (2, 5), (6, 10)], [5, 2, 1]),      # Mostly short delays
    'error': ([(0, 0), (1, 1)], [10, 0]),                  # No errors by default
    'pruser': ([(0, (1 << ruser_width) - 1)], [1]),        # Random PRUSER values
    'pbuser': ([(0, (1 << buser_width) - 1)], [1]),        # Random PBUSER values
})
```

Short PREADY delays most of the time, no errors, and PRUSER/PBUSER spread across their full configured width — a reasonable stand-in for a well-behaved peripheral.

#### Methods

##### `is_signal_present(signal_name) -> bool`

Same presence check as the monitor — ask before you rely on an extension signal.

```python
if slave.is_signal_present('PRUSER'):
    # PRUSER signal is connected
    pass
```

##### `print(transaction)`

Logs a transaction at debug level.

> **Removed:** the old `set_wakeup(value)` method is gone. The slave never owned PWAKEUP in the first place — the requester drives it. See [PWAKEUP Direction](#pwakeup-direction) and `APB5Master.set_wakeup_enable()`.

#### Response Behavior

Everything about how the slave responds is tunable:

- **Ready Delay**: cycles to wait before asserting PREADY (via the `ready` randomizer field)
- **Error Injection**: random or deterministic PSLVERR generation (via the `error` randomizer field)
- **User Signal Response**: fresh randomized PRUSER and PBUSER values on every response
- **PWAKEUP**: observed, not driven — the sampled value is recorded in each captured packet's `wakeup` field
- **Address Overflow**: optional error when an address falls outside the register array

#### Transaction Queue

Every transaction the slave answers lands in its `sentQ` deque as an APB5Packet, so a scoreboard can walk the full history after the fact.

### APB5Master

The master drives transfers. It owns the request side of the bus — address, write data, strobes, the request-side user signals, and PWAKEUP — and captures the response back into the transaction record.

#### Constructor

```python
APB5Master(entity, title, prefix, clock, signals=None,
           bus_width=32, addr_width=12,
           auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
           randomizer=None, log=None, wakeup_enable=True, **kwargs)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | object | *required* | DUT entity to drive |
| `title` | str | *required* | Master identifier for logging |
| `prefix` | str | *required* | Signal prefix for bus connection (trailing `_` auto-stripped) |
| `clock` | signal | *required* | Clock signal for synchronization |
| `signals` | list | None | Custom signal list (default: all APB5 signals) |
| `bus_width` | int | 32 | Data bus width in bits |
| `addr_width` | int | 12 | Address bus width in bits |
| `auser_width` | int | 4 | PAUSER width in bits |
| `wuser_width` | int | 4 | PWUSER width in bits |
| `ruser_width` | int | 4 | PRUSER width in bits |
| `buser_width` | int | 4 | PBUSER width in bits |
| `randomizer` | FlexRandomizer | None | PSEL/PENABLE delay randomizer |
| `log` | Logger | None | Logger instance (default: entity logger) |
| `wakeup_enable` | bool | True | Drive requester-owned PWAKEUP (asserted with PSEL, held through the transfer) when present on the bus |

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

Same presence check as the other components.

##### `set_wakeup_enable(enable)`

Turns requester-driven PWAKEUP assertion on or off for the transfers that follow. It's enabled by default: the master asserts PWAKEUP together with PSEL on every transfer and deasserts it when PSEL falls, per AMBA APB5 (IHI 0024E). Since the toggle applies to subsequent transfers, you can flip it mid-test to walk your power controller through its sleep and wake paths.

**Parameters:**
- `enable`: Truthy to assert PWAKEUP on subsequent transfers, falsy to hold it low.

```python
master.set_wakeup_enable(False)  # stop asserting PWAKEUP
# ... transfers run with PWAKEUP held low ...
master.set_wakeup_enable(True)   # resume asserting PWAKEUP with PSEL
```

##### `send(transaction)`

Sends one transaction, driving every signal that's actually present on the bus, user attributes included.

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

One-shot write: builds the packet, runs the transfer, and hands back the completed transaction.

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

One-shot read. Same idea as `write()` — the returned packet has `prdata`, `pruser`, and `pbuser` filled in from the response.

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

The transfer itself is the textbook APB two-phase sequence, with the AMBA5 signals riding along:

1. **Setup Phase**: drive PSEL, PADDR, PWRITE, PWDATA, PSTRB, PPROT, PAUSER, and PWUSER — plus PWAKEUP, asserted with PSEL when `wakeup_enable` is set
2. **Access Phase**: assert PENABLE
3. **Wait for Ready**: poll PREADY on falling clock edges
4. **Response Capture**: sample PRDATA, PSLVERR, PRUSER, and PBUSER (with a 200ps settling delay). PWAKEUP isn't sampled here — the master drove it, so it already knows the value.
5. **Deassert**: clear PSEL and PENABLE; PWAKEUP falls with PSEL

#### Transaction Queue

Completed transactions accumulate in the master's `sentQ` deque, one APB5Packet per transfer.

## Usage Patterns

### Basic Monitor Setup

A monitor with a callback is usually all you need to start watching traffic:

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

Round-trip a write with user attributes, then read it back. The response sidebands come back randomized by the slave:

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

If the default response behavior doesn't match your DUT's timing, build a randomizer and hand it to the factory:

```python
from CocoTBFramework.components.apb5.apb5_factories import (
    create_apb5_slave, create_apb5_randomizer
)

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

The slave's register storage is the shared MemoryModel, so it behaves like every other memory-backed component in the framework:

```python
# Memory model provides:
# - Byte-level access control with strobe masks
# - Access tracking and coverage
# - Boundary checking with configurable overflow behavior
# - Preset register values
```

### Packet Integration

Everything on the bus speaks APB5Packet:

```python
# Automatic field extraction including user signals
# Protocol compliance checking
# Transaction correlation via sentQ
# APB4 backward compatibility via to_apb4_packet()
```

### Randomization Integration

Timing and user-signal randomization both run through FlexRandomizer:

```python
# Configurable delay distributions for PREADY
# Error injection patterns via error field
# Randomized PRUSER and PBUSER values per response
# Full range based on configured user signal widths
```

## Best Practices

### 1. **Match User Signal Widths**

The widths you pass in configure the randomizer ranges and the packet field layout, so they need to agree with each other — and with the DUT. Define them once and share them:

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

A DUT that implements only half the AMBA5 extensions is normal, not broken. Check before you touch:

```python
# Always check signal presence before accessing
if master.is_signal_present('PAUSER'):
    # PAUSER is connected
    pass

if master.is_signal_present('PWAKEUP'):
    master.set_wakeup_enable(True)  # requester drives PWAKEUP
```

### 3. **Verify User Signal Round-Trip**

The cheapest sideband check is comparing what the master sent against what the monitor saw:

```python
# Check that user signals are captured correctly
await master.send(packet)
sent = master.sentQ[-1]
observed = monitor._recvQ[-1]  # BusMonitor receive queue

assert sent.fields['pauser'] == observed.fields['pauser']
```

That's the component layer. It stays deliberately close to the APB4 implementation — if you've used the APB4 BFM, the only new habits you need are the user sidebands and remembering that PWAKEUP belongs to the master.

---
