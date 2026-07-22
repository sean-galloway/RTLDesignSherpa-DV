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

UART is the simplest serial link still in daily use, and it's everywhere — boot consoles, debug ports, command bridges into register maps. This package gives you the three pieces you need to verify a UART interface without bit-banging waveforms by hand: a transmitter (`UARTMaster`), a receiver (`UARTMonitor`), and a small responder (`UARTSlave`). All three speak plain 8N1 — 8 data bits, no parity, 1 stop bit — with the baud rate set by a single `clks_per_bit` parameter, so the same components work from 9600 baud up to whatever your DUT will tolerate.

### Package Contents

| Component | Purpose | Direction |
|-----------|---------|-----------|
| **UARTMaster** | Drives UART traffic into the DUT's receiver | TX (sends data) |
| **UARTMonitor** | Decodes and captures the DUT's transmit output | RX (captures data) |
| **UARTSlave** | Responder with byte-triggered replies | RX/TX (echo, respond) |

---

## UARTMaster

### Purpose

The master is your transmit path: it drives the DUT's RX pin with properly framed UART bytes. Reach for it whenever you need to push commands or test data into a design that takes orders over a serial port.

### Features

- Baud rate set by one parameter (`clks_per_bit`)
- Start and stop bits generated for you
- Sends single bytes, byte lists, or whole strings
- Async transmit methods that won't hold up the rest of your testbench
- Transaction logging built in

### Usage

Wire it to the DUT's receive pin — from the DUT's point of view, the master *is* the external device talking to it:

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
- Sends a single byte over UART
- `data`: 8-bit value (0-255) or single character
- Start and stop bits are added automatically
- Returns a `UARTPacket` describing the byte that went out

**`async send_bytes(data_list)`**
- Sends a list of bytes (or characters) back to back
- Returns a list of `UARTPacket` objects, one per byte

**`async send_string(string)`**
- Sends an ASCII string, one character at a time
- `string`: String to transmit
- Returns a list of `UARTPacket` objects

### Timing

Every byte costs ten bit-times — one start bit, eight data bits, one stop bit — so the math is about as simple as timing math gets:

**Per-Byte Transmission Time:**
```
T_byte = clks_per_bit * 10 clock cycles
       = (1 start) + (8 data) + (1 stop) bits

Example (115200 baud, 100 MHz clock):
clks_per_bit = 868
T_byte = 868 * 10 = 8680 clocks = 86.8 µs
```

### Example

Sending a command string into a UART bridge looks like this:

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

The monitor is the receive side. It watches the DUT's TX pin, decodes each frame at the configured baud rate, and queues up every byte it catches for your test to inspect when it's ready. It also checks the stop bit on every frame and flags framing errors, so a DUT with sloppy line discipline won't slip past you.

### Features

- Baud rate set by one parameter (`clks_per_bit`)
- Start/stop bit detection handled internally
- Received bytes land in a queue (`_recvQ`) you drain at your own pace
- Per-packet error flags, so bad frames are visible rather than silent
- Transaction logging built in

### Usage

Point it at the DUT's transmit pin:

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

**`_recvQ`** — a `collections.deque` of received `UARTPacket` objects, oldest first. Pull packets out with `.popleft()`.

**`UARTPacket` — the fields you'll actually read:**
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

There aren't any to call. The monitor starts capturing as soon as it's constructed and runs in the background on its own — reading `_recvQ` is the whole interface. The patterns you'll use constantly:

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

A typical echo test — clear the queue, send a string, give the DUT time to answer, then drain whatever came back:

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

The slave plays the far end of the link: it receives whatever the DUT transmits and can drive bytes back into the DUT's receiver. Its useful trick is byte-triggered auto-response — register a trigger byte and a reply, and the moment the DUT sends that byte, the slave transmits the reply without your test lifting a finger. If you're verifying a UART master, this is what saves you from writing a responder by hand.

### Features

- Receives bytes into `rx_queue`
- Byte-triggered auto-responses via `add_response`
- Non-blocking receive checking with `get_received`
- Byte matching with timeout via `wait_for_byte`

### Usage

Note the signal names are from the DUT's perspective — the slave listens on the DUT's TX output and drives the DUT's RX input:

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

**`rx_queue`** — `collections.deque` of received byte values (integers 0-255)

**`response_map`** — dictionary mapping trigger bytes to the responses they'll send

#### Methods

**`add_response(trigger, response)`**
- Registers an auto-response for a received byte
- `trigger`: byte value (0-255) or single character
- `response`: a byte, a list of bytes, or a string to transmit when the trigger arrives

**`get_received()`**
- Non-blocking; returns the next received byte (0-255) or `None` if nothing has arrived

**`async wait_for_byte(expected, timeout_cycles=1000)`**
- Waits for a specific byte, giving up after `timeout_cycles` clocks
- Returns `True` if the byte arrived, `False` on timeout
- Raises `AssertionError` if a *different* byte shows up first — it's a strict check, not a filter

### Example

Two lines of setup and the slave handles the protocol chatter on its own:

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

Ten bits on the wire per byte: start low, eight data bits, stop high. The one detail that bites everyone exactly once — me included — is that data goes out least-significant bit first.

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

Nothing exotic here, but three things matter:

- Run the testbench clock well above the baud rate — 16x oversampling is the usual floor.
- Keep the clock stable for the duration of a transfer; the BFM counts clock edges, not wall time.
- Treat the real RX pin as asynchronous and give it a proper synchronizer (see Clock Domain Crossing below).

**Typical Timing:**
| Baud Rate | Bit Time | Byte Time |
|-----------|----------|-----------|
| 9600 | 104.2 µs | 1.042 ms |
| 115200 | 8.68 µs | 86.8 µs |
| 230400 | 4.34 µs | 43.4 µs |

---

## Integration Examples

### Complete UART Bridge Testbench

Here's a full testbench putting master and monitor together against a UART-to-AXI4-Lite bridge — the DUT takes ASCII commands like `W 1000 DEADBEEF` and answers with `OK\n` or a hex readback. It's the shape most UART tests end up taking: clear the queue, send the command, wait, then pick the response apart.

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

Unit tests live in the `tests/` directory.

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

A UART RX pin is asynchronous to your system clock by definition — there's no shared clock on the wire, that's the whole point. A real design needs a two-flop synchronizer on that input before the bit sampler, and the RTL side already does this (see `uart_rx.sv`). The BFM has it easier: it drives and samples synchronously with the testbench clock, so CDC is the DUT's problem, not yours.

### Baud Rate Calculation

`clks_per_bit` is just your clock frequency divided by the baud rate, rounded down to an integer:

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

UART is slow, and simulation makes you feel every bit of it. At 115200 baud you're moving roughly 11.5 KB/s, each byte costs ten bit-times, and each bit-time is `clks_per_bit` clock edges your simulator has to walk through. The practical consequences:

- Expect long test times for anything chatty.
- If the DUT allows it, run the UART faster than production baud — the protocol doesn't care.
- If you're only using the UART as a side door to reach internal registers, skip it for bulk setup and inject transactions directly on the internal bus instead. Save the UART traffic for the tests that are actually about the UART.

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

On the list, in no particular order:

1. **Parity Support** — 8E1 and 8O1 modes
2. **Flow Control** — RTS/CTS hardware handshaking
3. **Break Detection** — flagging an extended low period on the line
4. **Configurable Stop Bits** — 1, 1.5, or 2 stop bits

Framing error detection — catching an invalid stop bit — is already implemented in `UARTMonitor`, which is why it's not on the list.

---

## References

**Internal:**
- Converters Project — a real-world usage example
- [CocoTB Framework Overview](../components_overview.md)
- TBBase (located in the [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) repo under `tbclasses/shared/tbbase.py`)

**External:**
- [UART Wikipedia](https://en.wikipedia.org/wiki/Universal_asynchronous_receiver-transmitter)
- [CocoTB Documentation](https://docs.cocotb.org/)

---

**Version:** 1.0
**Last Review:** 2025-11-09
**Maintained By:** RTL Design Sherpa Project
