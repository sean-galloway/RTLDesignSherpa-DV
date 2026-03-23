# smbus_components.py

SMBus/I2C Bus Functional Model components providing Monitor, Master, Slave, and CRC implementations for comprehensive SMBus protocol verification. This module handles bit-level bus communication using tristate (open-drain) signal interfaces and supports all SMBus 2.0 transaction types.

## Overview

The `smbus_components.py` module provides four main classes:
- **SMBusCRC**: CRC-8 calculator for Packet Error Checking (PEC)
- **SMBusMonitor**: Passive bus monitor for transaction capture
- **SMBusSlave**: Active slave device emulation with memory-mapped registers
- **SMBusMaster**: Active master device emulation for initiating transactions

### Key Features
- **Tristate signal interface** modeling open-drain bus behavior
- **Bit-level protocol implementation** for accurate bus timing
- **All SMBus 2.0 transaction types** (Quick, Byte, Word, Block)
- **START/STOP/Repeated START** condition generation and detection
- **ACK/NAK handling** with proper bus release semantics
- **Memory-mapped register model** for slave responses
- **CRC-8 PEC support** for data integrity checking
- **Clock stretching** capability for slave-paced transactions

## Core Classes

### SMBusCRC

CRC-8 calculator implementing the SMBus PEC (Packet Error Checking) polynomial.

#### Class Attributes

- `POLY`: CRC-8 polynomial constant (`0x07`), representing x^8 + x^2 + x + 1

#### Methods

##### `calculate(data) -> int` [Static]

Calculate CRC-8 for SMBus PEC over a list of bytes.

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

Passive bus monitor that captures SMBus transactions by observing the SCL and SDA input signals without driving any bus signals.

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
Queue of received SMBusPacket objects. New packets are appended as they are captured.

```python
# Check captured transactions
while monitor.recv_queue:
    packet = monitor.recv_queue.popleft()
    print(packet.formatted(compact=False))
```

##### `transaction_count -> int`
Total number of transactions captured since the monitor started.

```python
print(f"Captured {monitor.transaction_count} transactions")
```

#### Methods

##### `start()`
Start the monitor. Launches the internal monitoring coroutine that watches for START conditions and captures transactions.

```python
monitor.start()  # Begin monitoring
```

##### `stop()`
Stop the monitor. Kills the monitoring coroutine and releases resources.

```python
monitor.stop()  # Stop monitoring
```

#### Transaction Detection

The monitor detects transactions through the following process:
1. **Wait for START**: SDA falling edge while SCL is high
2. **Receive address byte**: 7-bit address + R/W bit with ACK
3. **Receive data bytes**: Continue receiving until STOP or repeated START
4. **Parse transaction**: Determine transaction type from byte count and direction
5. **Finalize**: Timestamp, queue, log, and invoke callback

Transaction type is automatically determined from the number of data bytes and the R/W direction:

| Data Bytes After Address | Write Type | Read Type |
|--------------------------|------------|-----------|
| 0 | QUICK_CMD | QUICK_CMD |
| 1 | SEND_BYTE | RECV_BYTE |
| 2 | WRITE_BYTE | READ_BYTE |
| 3 | WRITE_WORD | READ_WORD |
| 4+ | BLOCK_WRITE | BLOCK_READ |

### SMBusSlave

Active slave device emulation that responds to master transactions with a memory-mapped register model and configurable clock stretching.

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
Start the slave. Releases the bus and launches the main processing loop.

```python
slave.start()
```

##### `stop()`
Stop the slave. Kills the processing coroutine and releases the bus.

```python
slave.stop()
```

##### `write_memory(addr, data)`
Pre-load data into slave memory. Addresses wrap around at `memory_size`.

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
Read data from slave memory. Returns `0xFF` for uninitialized addresses.

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
Clear all memory contents.

```python
slave.clear_memory()
```

#### Slave Behavior

The slave processes transactions through the following flow:
1. **Wait for START**: Detect SDA falling while SCL high
2. **Address Match**: Receive address byte, compare with `slave_addr`, send ACK if match
3. **Write Handling**: First data byte becomes command/register address; subsequent bytes written to memory with auto-increment
4. **Read Handling**: Send bytes from memory starting at current address; continue until master sends NAK
5. **Bus Release**: Release SDA/SCL after each operation

### SMBusMaster

Active master device emulation that generates SMBus transactions with configurable clock timing.

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

Execute a Quick Command transaction (address-only, no data).

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

Execute a Write Byte Data transaction (command + 1 data byte).

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

Execute a Read Byte Data transaction (command phase + read phase with repeated START).

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

Execute a Block Write transaction (command + byte count + data bytes).

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

Execute a Block Read transaction (command phase + read phase with byte count).

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

All master transactions follow this general flow:
1. **Generate START**: SDA falls while SCL high
2. **Send Address Byte**: 7-bit address + R/W bit, check for ACK
3. **Send/Receive Data**: Command byte, data bytes with ACK handling
4. **Repeated START** (for reads): Re-address with read bit
5. **Generate STOP**: SDA rises while SCL high

For read transactions (read_byte_data, block_read), the master uses a repeated START to switch from write mode (for the command phase) to read mode (for the data phase).

## Usage Patterns

### Complete Testbench with Monitor Verification

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

### 1. **Start Slaves Before Masters**
```python
# Always start responders first
slave.start()
monitor.start()

# Then initiate transactions
result = await master.write_byte_data(0x50, 0x10, 0xAB)
```

### 2. **Use Consistent Signal Names**
```python
# Define signal names once
SCL_SIGNALS = dict(scl_i='smb_scl_i', scl_o='smb_scl_o', scl_t='smb_scl_t')
SDA_SIGNALS = dict(sda_i='smb_sda_i', sda_o='smb_sda_o', sda_t='smb_sda_t')

master = SMBusMaster(dut, "Master", **SCL_SIGNALS, **SDA_SIGNALS)
slave = SMBusSlave(dut, "Slave", **SCL_SIGNALS, **SDA_SIGNALS, slave_addr=0x50)
```

### 3. **Clean Up After Tests**
```python
# Stop components to release bus
try:
    # ... test code ...
finally:
    monitor.stop()
    slave.stop()
```

### 4. **Check Transaction Status**
```python
result = await master.write_byte_data(0x50, 0x10, 0xAB)

# Always check status
assert result.completed, "Transaction did not complete"
assert result.ack_received, "No ACK from slave"
assert not result.timeout, "Transaction timed out"
assert not result.arbitration_lost, "Lost arbitration"
```

### 5. **Use Monitor for Protocol Debug**
```python
monitor = SMBusMonitor(dut, "Debug_Monitor",
    callback=lambda pkt: print(pkt.formatted(compact=False)))
monitor.start()
# Multi-line output shows full transaction details
```

The SMBus components provide a comprehensive foundation for SMBus/I2C protocol verification, from basic byte-level transactions to complex block transfers with PEC integrity checking, supporting both directed and monitor-based testing methodologies.
