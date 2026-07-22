# smbus_components.py

SMBus/I2C bus functional models: a passive monitor, an active master, an active slave, and the CRC-8 used for Packet Error Checking. Everything in this module works at the bit level over tristate (open-drain) signal interfaces, so the DUT sees a bus that behaves like the real thing — pull-ups, wired-AND, mid-byte repeated STARTs and all. Every SMBus 2.0 transaction type is covered.

## Overview

Four classes live in `smbus_components.py`:
- **SMBusCRC**: the CRC-8 calculator behind Packet Error Checking (PEC)
- **SMBusMonitor**: passive bus monitor — it listens and captures, and never drives a pin
- **SMBusSlave**: slave device model backed by a memory-mapped register file
- **SMBusMaster**: master device model that initiates transactions

### Key Features
- **Tristate signal interface** modeling open-drain behavior (you pull low or you let go — nobody drives high)
- **Bit-level protocol implementation**, so bus timing is real bus timing
- **All SMBus 2.0 transaction types** (Quick, Byte, Word, Block)
- **START/STOP/Repeated START** generation and detection, including conditions that land mid-byte
- **ACK/NAK handling** with proper bus release semantics
- **Memory-mapped register model** behind the slave
- **CRC-8 PEC support** for data integrity checking
- **Clock stretching** for slave-paced transactions

## Core Classes

### SMBusCRC

The CRC-8 behind SMBus Packet Error Checking. One polynomial, one static method — nothing to configure.

#### Class Attributes

- `POLY`: CRC-8 polynomial constant (`0x07`), representing x^8 + x^2 + x + 1

#### Methods

##### `calculate(data) -> int` [Static]

Run the CRC-8 over a list of bytes. The result is the value you append as the PEC byte; running the calculation again over data-plus-PEC yields zero, which is how you check a received PEC.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data` | list[int] | *required* | List of bytes to calculate CRC over |

**Returns:** 8-bit CRC value (0x00-0xFF)

```python
from CocoTBFramework.components.smbus import SMBusCRC

# Calculate PEC for an address + command + data sequence
pec = SMBusCRC.calculate([0xA0, 0x10, 0xAB])
print(f"PEC: 0x{pec:02X}")

# Verify PEC by including it in the calculation (result should be 0)
data_with_pec = [0xA0, 0x10, 0xAB, pec]
assert SMBusCRC.calculate(data_with_pec) == 0
```

### SMBusMonitor

A passive listener. It watches the SCL and SDA inputs, reconstructs transactions bit by bit, and never drives the bus — there are no `_o`/`_t` connections on this class at all.

#### Constructor

```python
SMBusMonitor(entity, title,
             scl_signal='smb_scl_i',
             sda_signal='smb_sda_i',
             clock=None,
             log=None,
             callback=None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | object | *required* | DUT handle |
| `title` | str | *required* | Monitor title for logging |
| `scl_signal` | str | `'smb_scl_i'` | Name of SCL input signal on the DUT |
| `sda_signal` | str | `'smb_sda_i'` | Name of SDA input signal on the DUT |
| `clock` | signal | None | Optional reference clock for timing |
| `log` | Logger | None | Logger instance (default: auto-created) |
| `callback` | callable | None | Callback function invoked on each captured packet |

A monitor with a callback, printing each transaction as it lands:

```python
from CocoTBFramework.components.smbus import SMBusMonitor

# Create monitor with callback
def on_transaction(packet):
    print(f"Captured: {packet.formatted()}")

monitor = SMBusMonitor(
    entity=dut,
    title="Bus_Monitor",
    scl_signal='smb_scl_i',
    sda_signal='smb_sda_i',
    callback=on_transaction
)
monitor.start()
```

#### Properties

##### `recv_queue -> deque`
Captured packets land here as they complete. It's a plain deque — pop them out and do what you like with them.

```python
# Check captured transactions
while monitor.recv_queue:
    packet = monitor.recv_queue.popleft()
    print(packet.formatted(compact=False))
```

##### `transaction_count -> int`
Running count of transactions captured since the monitor started.

```python
print(f"Captured {monitor.transaction_count} transactions")
```

#### Methods

##### `start()`
Launch the monitoring coroutine. From this point it watches for START conditions and captures whatever crosses the bus.

```python
monitor.start()  # Begin monitoring
```

##### `stop()`
Kill the monitoring coroutine and release its resources.

```python
monitor.stop()  # Stop monitoring
```

#### Transaction Detection

A capture runs like this:
1. **Wait for START**: SDA falling while SCL is high — the only time an SDA edge means "start of something"
2. **Receive the address byte**: 7-bit address plus R/W bit, then the ACK
3. **Receive data bytes**: keep going until a STOP or repeated START shows up
4. **Classify**: determine the transaction type from byte count and direction
5. **Finalize**: timestamp, queue, log, fire the callback

The part worth understanding is how bus conditions get attributed. Every clock phase of a byte — including the SCL-high phase after a bit or ACK has been sampled — races the expected SCL edge against any SDA edge. That's how the monitor catches a STOP or repeated START the moment it happens, even mid-byte, instead of discovering it a byte later. A condition that interrupts a byte kills that byte (the partial bits are discarded) and finalizes the packet; a repeated START rolls straight into capturing the next transaction without waiting for a fresh START edge.

Transaction type is inferred from the number of data bytes and the R/W direction:

| Data Bytes After Address | Write Type | Read Type |
|--------------------------|------------|-----------|
| 0 | QUICK_CMD | QUICK_CMD |
| 1 | SEND_BYTE | RECV_BYTE |
| 2 | WRITE_BYTE | READ_BYTE |
| 3 | WRITE_WORD | READ_WORD |
| 4+ | BLOCK_WRITE | BLOCK_READ |

One consequence of shape-based inference: a block write carrying a single data byte is wire-identical to a word write, so that's how it gets classified. If a captured packet's type surprises you, check it against this table before you blame the DUT.

### SMBusSlave

An active slave: it ACKs its own address, serves reads and writes out of a memory-mapped register model, and will stretch the clock if you ask it to.

#### Constructor

```python
SMBusSlave(entity, title,
           scl_i='smb_scl_i', scl_o='smb_scl_o', scl_t='smb_scl_t',
           sda_i='smb_sda_i', sda_o='smb_sda_o', sda_t='smb_sda_t',
           slave_addr=0x50,
           memory_size=256,
           clock_stretch_cycles=0,
           support_pec=False,
           log=None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | object | *required* | DUT handle |
| `title` | str | *required* | Slave title for logging |
| `scl_i` | str | `'smb_scl_i'` | SCL input signal name |
| `scl_o` | str | `'smb_scl_o'` | SCL output signal name |
| `scl_t` | str | `'smb_scl_t'` | SCL tristate control signal name |
| `sda_i` | str | `'smb_sda_i'` | SDA input signal name |
| `sda_o` | str | `'smb_sda_o'` | SDA output signal name |
| `sda_t` | str | `'smb_sda_t'` | SDA tristate control signal name |
| `slave_addr` | int | `0x50` | 7-bit slave address (0x00-0x7F) |
| `memory_size` | int | `256` | Size of internal memory in bytes |
| `clock_stretch_cycles` | int | `0` | Cycles to stretch clock (0=disabled) |
| `support_pec` | bool | `False` | Enable PEC support |
| `log` | Logger | None | Logger instance (default: auto-created) |

A 256-byte slave at 0x50, pre-loaded and started:

```python
from CocoTBFramework.components.smbus import SMBusSlave

# Create slave at address 0x50 with 256 bytes of memory
slave = SMBusSlave(
    entity=dut,
    title="EEPROM",
    slave_addr=0x50,
    memory_size=256
)

# Pre-load some data
slave.write_memory(0x00, [0x01, 0x02, 0x03, 0x04])

# Start responding to bus transactions
slave.start()
```

#### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `memory` | dict[int, int] | Internal memory storage (address -> byte value) |
| `transaction_count` | int | Number of transactions processed |
| `ack_count` | int | Number of ACKs sent |
| `nak_count` | int | Number of NAKs sent |

#### Methods

##### `start()`
Release the bus and launch the main loop — from here the slave watches for START and answers when its address comes up.

```python
slave.start()
```

##### `stop()`
Kill the processing coroutine and release the bus.

```python
slave.stop()
```

##### `write_memory(addr, data)`
Pre-load bytes into the register model. Addresses wrap around at `memory_size`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `addr` | int | *required* | Starting address |
| `data` | list[int] | *required* | List of bytes to write |

```python
# Pre-load register block
slave.write_memory(0x00, [0xAA, 0xBB, 0xCC, 0xDD])

# Pre-load configuration register
slave.write_memory(0x10, [0x01])
```

##### `read_memory(addr, length=1) -> list[int]`
Read back what the slave would return. Addresses that were never written come back as `0xFF`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `addr` | int | *required* | Starting address |
| `length` | int | 1 | Number of bytes to read |

**Returns:** List of byte values

```python
data = slave.read_memory(0x00, length=4)
print(f"Memory: {[f'0x{b:02X}' for b in data]}")
```

##### `clear_memory()`
Wipe the register model.

```python
slave.clear_memory()
```

#### Slave Behavior

The transaction flow, from the slave's side of the wire:
1. **Wait for START**: SDA falling while SCL is high
2. **Address match**: receive the address byte, compare against `slave_addr`, ACK on a match
3. **Writes**: the first data byte becomes the command/register address; later bytes go into memory with auto-increment. Byte reception races SDA edges, so a STOP or repeated START that lands between bytes — or inside one — terminates the write cleanly instead of swallowing the next transaction's address byte as data
4. **Reads**: send memory contents starting at the current address and keep going until the master NAKs
5. **Repeated START**: a repeated START that closes a write phase flows straight into re-addressing — the read phase of Read Byte Data or Block Read, say — with no fresh START edge required
6. **Bus release**: SDA and SCL are released after each operation

### SMBusMaster

The initiator. It generates SMBus transactions with a configurable SCL period — 10000 ns is the classic 100 kHz, or run faster if your DUT is up to it.

#### Constructor

```python
SMBusMaster(entity, title,
            scl_i='smb_scl_i', scl_o='smb_scl_o', scl_t='smb_scl_t',
            sda_i='smb_sda_i', sda_o='smb_sda_o', sda_t='smb_sda_t',
            clock_period_ns=10000,
            support_pec=False,
            log=None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity` | object | *required* | DUT handle |
| `title` | str | *required* | Master title for logging |
| `scl_i` | str | `'smb_scl_i'` | SCL input signal name |
| `scl_o` | str | `'smb_scl_o'` | SCL output signal name |
| `scl_t` | str | `'smb_scl_t'` | SCL tristate control signal name |
| `sda_i` | str | `'smb_sda_i'` | SDA input signal name |
| `sda_o` | str | `'smb_sda_o'` | SDA output signal name |
| `sda_t` | str | `'smb_sda_t'` | SDA tristate control signal name |
| `clock_period_ns` | int | `10000` | SCL clock period in nanoseconds (10000 = 100kHz) |
| `support_pec` | bool | `False` | Enable PEC support |
| `log` | Logger | None | Logger instance (default: auto-created) |

The default 100 kHz master, and a quicker 400 kHz one:

```python
from CocoTBFramework.components.smbus import SMBusMaster

# Create master at 100kHz (default)
master = SMBusMaster(
    entity=dut,
    title="Test_Master",
    clock_period_ns=10000
)

# Create master at 400kHz
fast_master = SMBusMaster(
    entity=dut,
    title="Fast_Master",
    clock_period_ns=2500
)
```

#### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `clock_period_ns` | int | Full SCL clock period in nanoseconds |
| `half_period_ns` | int | Half SCL clock period (derived) |
| `transaction_count` | int | Number of transactions completed |

#### Methods

##### `quick_command(slave_addr, read=False) -> SMBusPacket`

Address-only transaction — no data at all. The R/W bit is the entire payload.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `slave_addr` | int | *required* | 7-bit slave address |
| `read` | bool | False | True for read, False for write |

**Returns:** SMBusPacket with transaction result

```python
# Quick command (write)
result = await master.quick_command(slave_addr=0x50, read=False)
print(f"ACK received: {result.ack_received}")

# Quick command (read)
result = await master.quick_command(slave_addr=0x50, read=True)
```

##### `write_byte_data(slave_addr, command, data) -> SMBusPacket`

Command byte plus one data byte — the everyday register write.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `slave_addr` | int | *required* | 7-bit slave address |
| `command` | int | *required* | Command byte (register address) |
| `data` | int | *required* | Data byte to write |

**Returns:** SMBusPacket with transaction result

```python
# Write 0xAB to register 0x10 on slave 0x50
result = await master.write_byte_data(
    slave_addr=0x50, command=0x10, data=0xAB
)
print(f"Write completed: {result.completed}, ACK: {result.ack_received}")
```

##### `read_byte_data(slave_addr, command) -> SMBusPacket`

Command phase, repeated START, read phase. The byte you asked for lands in `packet.data[0]`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `slave_addr` | int | *required* | 7-bit slave address |
| `command` | int | *required* | Command byte (register address) |

**Returns:** SMBusPacket with transaction result (data in `packet.data[0]`)

```python
# Read from register 0x10 on slave 0x50
result = await master.read_byte_data(
    slave_addr=0x50, command=0x10
)
if result.ack_received:
    print(f"Read data: 0x{result.data[0]:02X}")
```

##### `block_write(slave_addr, command, data) -> SMBusPacket`

Command byte, byte count, then the data.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `slave_addr` | int | *required* | 7-bit slave address |
| `command` | int | *required* | Command byte |
| `data` | list[int] | *required* | List of data bytes to write |

**Returns:** SMBusPacket with transaction result

```python
# Block write 5 bytes starting at command 0x00
data = [0x11, 0x22, 0x33, 0x44, 0x55]
result = await master.block_write(
    slave_addr=0x50, command=0x00, data=data
)
print(f"Wrote {len(data)} bytes, ACK: {result.ack_received}")
```

##### `block_read(slave_addr, command, max_bytes=32) -> SMBusPacket`

Command phase, repeated START, then the slave's count byte and data. The data ends up in `packet.data`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `slave_addr` | int | *required* | 7-bit slave address |
| `command` | int | *required* | Command byte |
| `max_bytes` | int | 32 | Maximum bytes to read |

**Returns:** SMBusPacket with transaction result (data in `packet.data`)

```python
# Block read up to 32 bytes from command 0x00
result = await master.block_read(
    slave_addr=0x50, command=0x00, max_bytes=32
)
print(f"Read {len(result.data)} bytes: "
      f"{[f'0x{b:02X}' for b in result.data]}")
```

#### Transaction Protocol

Every master transaction runs the same general sequence:
1. **START**: SDA falls while SCL is high
2. **Address byte**: 7-bit address plus R/W, then check for ACK
3. **Data**: command byte, then data bytes, with ACK handling throughout
4. **Repeated START** (for reads): re-address with the read bit set
5. **STOP**: SDA rises while SCL is high

For the read transactions (`read_byte_data`, `block_read`) the master inserts the repeated START itself, switching from the write-mode command phase to the read-mode data phase. You just ask for the register.

## Usage Patterns

### Complete Testbench with Monitor Verification

Master drives, slave answers, monitor records — the shape most of your tests will have:

```python
import cocotb
from CocoTBFramework.components.smbus import (
    SMBusMaster, SMBusSlave, SMBusMonitor, SMBusCRC
)

@cocotb.test()
async def full_smbus_test(dut):
    # Create all components
    captured_packets = []

    monitor = SMBusMonitor(
        dut, "Monitor",
        callback=lambda pkt: captured_packets.append(pkt)
    )

    slave = SMBusSlave(
        dut, "Slave",
        slave_addr=0x50,
        memory_size=256
    )

    master = SMBusMaster(
        dut, "Master",
        clock_period_ns=10000
    )

    # Start passive components
    monitor.start()
    slave.start()

    # Write then read
    await master.write_byte_data(0x50, 0x10, 0xAB)
    result = await master.read_byte_data(0x50, 0x10)

    # Verify
    assert result.data[0] == 0xAB
    assert len(captured_packets) >= 2

    # Cleanup
    monitor.stop()
    slave.stop()
```

### Multi-Slave Environment

Slaves share a bus happily as long as the addresses differ. Here an EEPROM at 0x50 and a sensor at 0x48 coexist while the master talks to each in turn:

```python
@cocotb.test()
async def multi_slave_test(dut):
    # Create multiple slaves at different addresses
    eeprom = SMBusSlave(dut, "EEPROM", slave_addr=0x50, memory_size=256)
    sensor = SMBusSlave(dut, "Sensor", slave_addr=0x48, memory_size=16)

    # Pre-load sensor data
    sensor.write_memory(0x00, [0x1A, 0x2B])  # Temperature register

    eeprom.start()
    sensor.start()

    master = SMBusMaster(dut, "Master")

    # Read from sensor
    temp = await master.read_byte_data(slave_addr=0x48, command=0x00)
    print(f"Temperature MSB: 0x{temp.data[0]:02X}")

    # Write to EEPROM
    await master.write_byte_data(slave_addr=0x50, command=0x00, data=0xFF)
```

### PEC Verification

With `support_pec=True` on both ends, the expected PEC for a write is just the CRC over the address byte, command, and data:

```python
@cocotb.test()
async def pec_test(dut):
    master = SMBusMaster(dut, "Master", support_pec=True)
    slave = SMBusSlave(dut, "Slave", slave_addr=0x50, support_pec=True)

    slave.start()

    # Calculate expected PEC for a write transaction
    # Address byte (write) + command + data
    addr_byte = (0x50 << 1) | 0  # Write
    expected_pec = SMBusCRC.calculate([addr_byte, 0x10, 0xAB])
    print(f"Expected PEC: 0x{expected_pec:02X}")
```

## Best Practices

### 1. Start slaves before masters
If the master talks before anything is listening, the transaction NAKs into the void. Start the responders first:

```python
# Always start responders first
slave.start()
monitor.start()

# Then initiate transactions
result = await master.write_byte_data(0x50, 0x10, 0xAB)
```

### 2. Define the signal names once
Six signal names per component is twelve chances to typo something — I've burned an afternoon on exactly that. Put them in dicts and splat them in:

```python
# Define signal names once
SCL_SIGNALS = dict(scl_i='smb_scl_i', scl_o='smb_scl_o', scl_t='smb_scl_t')
SDA_SIGNALS = dict(sda_i='smb_sda_i', sda_o='smb_sda_o', sda_t='smb_sda_t')

master = SMBusMaster(dut, "Master", **SCL_SIGNALS, **SDA_SIGNALS)
slave = SMBusSlave(dut, "Slave", **SCL_SIGNALS, **SDA_SIGNALS, slave_addr=0x50)
```

### 3. Clean up after the test
Stopped components release the bus; ones left running can hold lines into whatever runs next. `finally` is your friend:

```python
# Stop components to release bus
try:
    # ... test code ...
finally:
    monitor.stop()
    slave.stop()
```

### 4. Check the status packet
The returned packet tells you how the transfer actually went — look at it. A NAK is a lot easier to diagnose when you assert on it immediately:

```python
result = await master.write_byte_data(0x50, 0x10, 0xAB)

# Always check status
assert result.completed, "Transaction did not complete"
assert result.ack_received, "No ACK from slave"
assert not result.timeout, "Transaction timed out"
assert not result.arbitration_lost, "Lost arbitration"
```

### 5. Debug with the monitor
When a transaction goes sideways, the monitor's detailed format shows you every byte and condition that hit the wire:

```python
monitor = SMBusMonitor(dut, "Debug_Monitor",
    callback=lambda pkt: print(pkt.formatted(compact=False)))
monitor.start()
# Multi-line output shows full transaction details
```

That's the whole toolkit: CRC for integrity, the monitor for the record, master and slave for the two ends of the wire. Start with one of each and add pieces as the testbench grows.
