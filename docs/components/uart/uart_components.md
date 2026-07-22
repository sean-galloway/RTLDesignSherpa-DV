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

**[← Back to Components Index](../components_index.md)** | **[Main Index](../components_index.md)**

# UART BFM Components

**Package:** `src/CocoTBFramework/components/uart/`
**Last Updated:** 2025-11-09

---

## Overview

The UART BFM (Bus Functional Model) package provides CocoTB-based verification components for UART protocol testing. These components implement the standard 8N1 UART protocol (8 data bits, no parity, 1 stop bit) with configurable baud rates.

### Package Contents

| Component | Purpose | Direction |
|-----------|---------|-----------|
| **UARTMaster** | UART transmitter | TX (sends data) |
| **UARTMonitor** | UART receiver monitor | RX (captures data) |
| **UARTSlave** | UART responder | RX/TX (echo, respond) |

---

## UARTMaster

### Purpose

Transmits UART data for stimulating DUT UART receivers. Used to drive commands and test data into UART-based designs.

### Features

- Configurable baud rate (via `clks_per_bit`)
- Automatic start/stop bit generation
- String and byte transmission
- Non-blocking async transmission
- Transaction logging

### Usage

```python
from CocoTBFramework.components.uart import UARTMaster

class MyTestbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)

        # Initialize UART master
        self.uart_tx = UARTMaster(
            entity=dut,
            title="UART_TX",
            signal_name="i_uart_rx",  # DUT input signal name
            clock=dut.aclk,
            clks_per_bit=868,  # 100 MHz / 115200 baud
            log=self.log
        )

    async def send_command(self, cmd):
        """Send UART command string"""
        await self.uart_tx.send_string(cmd)

    async def send_byte(self, byte_val):
        """Send single byte"""
        await self.uart_tx.send(byte_val)
```

### API

#### Constructor
```python
UARTMaster(
    entity,           # CocoTB DUT entity
    title,            # String for logging (e.g., "UART_TX")
    signal_name,      # DUT signal name (e.g., "i_uart_rx")
    clock,            # Clock signal handle
    clks_per_bit=868, # Clocks per UART bit
    log=None          # Logger instance (optional)
)
```

#### Methods

**`async send(data)`**
- Transmits single byte over UART
- `data`: 8-bit value (0-255) or single character
- Automatically adds start/stop bits
- Returns a `UARTPacket` describing the transmitted byte

**`async send_bytes(data_list)`**
- Transmits a list of bytes (or characters) sequentially
- Returns a list of `UARTPacket` objects

**`async send_string(string)`**
- Transmits ASCII string over UART
- `string`: String to transmit
- Sends each character sequentially
- Returns a list of `UARTPacket` objects

### Timing

**Per-Byte Transmission Time:**
```
T_byte = clks_per_bit * 10 clock cycles
       = (1 start) + (8 data) + (1 stop) bits

Example (115200 baud, 100 MHz clock):
clks_per_bit = 868
T_byte = 868 * 10 = 8680 clocks = 86.8 µs
```

### Example

```python
@cocotb.test()
async def test_uart_commands(dut):
    tb = UARTBridgeTB(dut)
    await tb.setup_clocks_and_reset()

    # Send write command
    await tb.uart_tx.send_string("W 1000 DEADBEEF\n")

    # Wait for response
    await tb.wait_clocks('clk', 100000)

    # Check UART response via monitor
    # (see UARTMonitor section)
```

---

## UARTMonitor

### Purpose

Monitors UART output from DUT transmitters. Captures transmitted data for verification and analysis.

### Features

- Configurable baud rate (via `clks_per_bit`)
- Automatic start/stop bit detection
- Queue-based transaction capture (`_recvQ`)
- Transaction logging
- Data validation

### Usage

```python
from CocoTBFramework.components.uart import UARTMonitor

class MyTestbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)

        # Initialize UART monitor
        self.uart_rx_monitor = UARTMonitor(
            entity=dut,
            title="UART_RX_MON",
            signal_name="o_uart_tx",  # DUT output signal name
            clock=dut.aclk,
            clks_per_bit=868,  # 100 MHz / 115200 baud
            direction='RX',
            log=self.log
        )

    async def check_response(self, expected_str):
        """Verify UART response"""
        # Wait for data
        await self.wait_clocks('clk', 10000)

        # Check queue
        if len(self.uart_rx_monitor._recvQ) >= len(expected_str):
            received = ""
            for _ in range(len(expected_str)):
                pkt = self.uart_rx_monitor._recvQ.popleft()
                received += chr(pkt.data)

            assert received == expected_str, f"Expected '{expected_str}', got '{received}'"
            return True
        return False
```

### API

#### Constructor
```python
UARTMonitor(
    entity,           # CocoTB DUT entity
    title,            # String for logging (e.g., "UART_RX_MON")
    signal_name,      # DUT signal name (e.g., "o_uart_tx")
    clock,            # Clock signal handle
    clks_per_bit=868, # Clocks per UART bit
    direction='RX',   # Direction label ('TX' or 'RX', for packet tagging)
    log=None          # Logger instance (optional)
)
```

#### Attributes

**`_recvQ`** - `collections.deque`
- Queue of received UART packets
- Access with `.popleft()` to retrieve oldest packet
- Each packet is a `UARTPacket` object

**`UARTPacket` Structure (key fields):**
```python
@dataclass
class UARTPacket:
    start_time: float     # Simulation time when transmission started (ns)
    count: int            # Transaction counter
    data: int             # 8-bit data value
    parity: Optional[int] # Parity bit (None for 8N1)
    parity_error: bool    # Parity error flag
    framing_error: bool   # Framing error flag (stop bit not high)
    direction: str        # 'TX' or 'RX'
```

#### Methods

Monitor runs automatically in background. Access received data via `_recvQ`.

**Common Patterns:**
```python
# Check if data available
if len(self.uart_rx_monitor._recvQ) > 0:
    pkt = self.uart_rx_monitor._recvQ.popleft()
    byte_val = pkt.data
    timestamp = pkt.start_time

# Clear queue
self.uart_rx_monitor._recvQ.clear()

# Collect string response
response = ""
while len(self.uart_rx_monitor._recvQ) > 0:
    pkt = self.uart_rx_monitor._recvQ.popleft()
    response += chr(pkt.data)
```

### Example

```python
@cocotb.test()
async def test_uart_echo(dut):
    tb = UARTTestbench(dut)
    await tb.setup_clocks_and_reset()

    # Clear any stale data
    tb.uart_rx_monitor._recvQ.clear()

    # Send command
    await tb.uart_tx.send_string("HELLO\n")

    # Wait for response
    await tb.wait_clocks('clk', 50000)

    # Collect response
    response = ""
    while len(tb.uart_rx_monitor._recvQ) > 0:
        pkt = tb.uart_rx_monitor._recvQ.popleft()
        response += chr(pkt.data)
        tb.log.debug(f"Received: 0x{pkt.data:02X} ({chr(pkt.data)})")

    # Verify
    assert response == "HELLO\n", f"Echo failed: {response}"
```

---

## UARTSlave

### Purpose

Simulates UART slave device that can respond to received commands. Useful for testing UART masters.

### Features

- Receives bytes via UART into `rx_queue`
- Byte-triggered auto-responses (`add_response`)
- Non-blocking receive checking (`get_received`)
- Byte matching with timeout (`wait_for_byte`)

### Usage

```python
from CocoTBFramework.components.uart import UARTSlave

class MyTestbench(TBBase):
    def __init__(self, dut):
        super().__init__(dut)

        # Initialize UART slave
        self.uart_slave = UARTSlave(
            entity=dut,
            title="UART_SLAVE",
            rx_signal_name="o_uart_tx",  # Receive from DUT TX
            tx_signal_name="i_uart_rx",  # Transmit to DUT RX
            clock=dut.aclk,
            clks_per_bit=868,
            log=self.log
        )

    def setup_responses(self):
        """Configure byte-triggered auto-responses"""
        self.uart_slave.add_response(ord('?'), "READY\n")
        self.uart_slave.add_response(ord('V'), "VERSION 1.0\n")
```

### API

#### Constructor
```python
UARTSlave(
    entity,           # CocoTB DUT entity
    title,            # String for logging
    rx_signal_name,   # Signal the slave listens on (typically DUT TX output)
    tx_signal_name,   # Signal the slave drives (typically DUT RX input)
    clock,            # Clock signal handle
    clks_per_bit=868, # Clocks per UART bit
    log=None          # Logger instance
)
```

#### Attributes

**`rx_queue`** - `collections.deque` of received byte values (integers 0-255)

**`response_map`** - Dictionary mapping trigger bytes to response sequences

#### Methods

**`add_response(trigger, response)`**
- Register an auto-response for a received byte
- `trigger`: byte value (0-255) or single character
- `response`: byte, list of bytes, or string to transmit when triggered

**`get_received()`**
- Non-blocking; returns the next received byte (0-255) or `None` if the queue is empty

**`async wait_for_byte(expected, timeout_cycles=1000)`**
- Wait for a specific byte with a clock-cycle timeout
- Returns `True` if received, `False` on timeout
- Raises `AssertionError` if a different byte is received

### Example

```python
@cocotb.test()
async def test_uart_slave(dut):
    tb = UARTTestbench(dut)
    await tb.setup_clocks_and_reset()

    # Configure slave auto-responses
    tb.uart_slave.add_response(ord('R'), "READ_OK\n")
    tb.uart_slave.add_response(ord('W'), "WRITE_OK\n")

    # When the DUT transmits 'R' or 'W', the slave automatically
    # sends the corresponding response string back
```

---

## Protocol Details

### UART 8N1 Protocol

**Frame Format:**

```wavedrom
{ signal: [
  { name: "UART Frame", wave: "x0.2345678.1x", data: ["Start","D0","D1","D2","D3","D4","D5","D6","D7","Stop"] }
],
  head: { text: "UART 8N1 Frame: Start (0) + 8 Data (LSB first) + Stop (1) = 10 bits" }
}
```

| Bit | Name | Description |
|-----|------|-------------|
| 1 | Start | Always 0 |
| 2-9 | D0-D7 | Data (LSB first) |
| 10 | Stop | Always 1 |

*Total: 10 bits per byte*

**Bit Timing:**
```
Bit Duration = clks_per_bit clock cycles

Baud Rate = Clock_Frequency / clks_per_bit

Common Baud Rates:
- 9600:   clks_per_bit = 10417 (100 MHz clock)
- 115200: clks_per_bit = 868   (100 MHz clock)
- 230400: clks_per_bit = 434   (100 MHz clock)
```

### Timing Constraints

**Minimum Requirements:**
- Clock frequency >> baud rate (at least 16x recommended)
- Stable clock during transmission
- Proper CDC for async UART inputs

**Typical Timing:**
| Baud Rate | Bit Time | Byte Time |
|-----------|----------|-----------|
| 9600 | 104.2 µs | 1.042 ms |
| 115200 | 8.68 µs | 86.8 µs |
| 230400 | 4.34 µs | 43.4 µs |

---

## Integration Examples

### Complete UART Bridge Testbench

```python
# TBBase is located in the RTLDesignSherpa main repo (tbclasses/shared/tbbase.py)
from CocoTBFramework.tbclasses.shared.tbbase import TBBase
from CocoTBFramework.components.uart import UARTMaster, UARTMonitor

class UARTBridgeTB(TBBase):
    """Testbench for UART to AXI4-Lite bridge"""

    def __init__(self, dut):
        super().__init__(dut)

        # UART master (sends commands to bridge)
        self.uart_tx = UARTMaster(
            entity=dut,
            title="UART_TX",
            signal_name="i_uart_rx",
            clock=dut.aclk,
            clks_per_bit=868,
            log=self.log
        )

        # UART monitor (captures responses from bridge)
        self.uart_rx_monitor = UARTMonitor(
            entity=dut,
            title="UART_RX_MON",
            signal_name="o_uart_tx",
            clock=dut.aclk,
            clks_per_bit=868,
            direction='RX',
            log=self.log
        )

    async def send_write_command(self, addr, data):
        """Send UART write command"""
        cmd = f"W {addr:X} {data:X}\n"
        self.uart_rx_monitor._recvQ.clear()
        await self.uart_tx.send_string(cmd)

        # Wait for response
        await self.wait_clocks('clk', 200000)

        # Check for "OK\n"
        if len(self.uart_rx_monitor._recvQ) >= 3:
            response = ""
            for _ in range(3):
                pkt = self.uart_rx_monitor._recvQ.popleft()
                response += chr(pkt.data)
            return response == "OK\n"
        return False

    async def send_read_command(self, addr):
        """Send UART read command"""
        cmd = f"R {addr:X}\n"
        self.uart_rx_monitor._recvQ.clear()
        await self.uart_tx.send_string(cmd)

        # Wait for response
        await self.wait_clocks('clk', 200000)

        # Parse "0x<hex>\n"
        if len(self.uart_rx_monitor._recvQ) >= 11:
            response = ""
            for _ in range(11):
                pkt = self.uart_rx_monitor._recvQ.popleft()
                response += chr(pkt.data)

            if response.startswith("0x") and response.endswith("\n"):
                data_hex = response[2:-1]
                return int(data_hex, 16)
        return None
```

---

## Testing UART Components

### Unit Tests

Located in: `tests/` directory

**Test Coverage:**
- Byte transmission accuracy
- Start/stop bit generation
- Baud rate timing
- String transmission
- Monitor capture accuracy
- Queue management

### Running Tests

```bash
cd tests
pytest test_uart_components.py -v
```

---

## Design Notes

### Clock Domain Crossing

UART inputs are asynchronous and require CDC:
- Use 2-FF synchronizer for RX input
- Implemented in UART RX modules (e.g., `uart_rx.sv`)
- BFM assumes single clock domain (testbench synchronous)

### Baud Rate Calculation

```python
def calculate_clks_per_bit(clock_mhz, baud_rate):
    """Calculate clks_per_bit parameter"""
    clock_hz = clock_mhz * 1_000_000
    return int(clock_hz / baud_rate)

# Examples
clks_per_bit_100mhz_115200 = calculate_clks_per_bit(100, 115200)  # 868
clks_per_bit_50mhz_115200 = calculate_clks_per_bit(50, 115200)    # 434
```

### Performance Considerations

**Testbench Performance:**
- UART is slow - expect long test times
- 115200 baud ≈ 11.5 KB/s max throughput
- Use higher baud rates for faster tests (if DUT supports)
- Consider parallel testing for throughput-intensive tests

**Simulation Optimization:**
```python
# For faster testing, use higher baud rate
FAST_CLKS_PER_BIT = 100  # ~1 Mbaud at 100 MHz

# Or skip UART BFM for bulk data
# Use direct AXI4-Lite transaction injection
```

---

## Known Issues

None currently documented.

---

## Future Enhancements

1. **Parity Support** - 8E1, 8O1 modes
2. **Flow Control** - RTS/CTS hardware handshaking
3. **Break Detection** - Extended low period detection
4. **Configurable Stop Bits** - 1, 1.5, 2 stop bits

(Framing error detection — invalid stop bit — is already implemented in `UARTMonitor`.)

---

## References

**Internal:**
- Converters Project - Usage example
- [CocoTB Framework Overview](../components_overview.md)
- TBBase (located in the [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) repo under `tbclasses/shared/tbbase.py`)

**External:**
- [UART Wikipedia](https://en.wikipedia.org/wiki/Universal_asynchronous_receiver-transmitter)
- [CocoTB Documentation](https://docs.cocotb.org/)

---

**Version:** 1.0
**Last Review:** 2025-11-09
**Maintained By:** RTL Design Sherpa Project
