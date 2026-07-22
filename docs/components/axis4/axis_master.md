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

# AXISMaster

`AXISMaster` is the stream source: it drives the AXI4-Stream T channel as a master. All of the actual bus driving is done by the GAXI transmit pipeline it inherits — this class is the stream-shaped layer on top. It gives you `send_stream_data` and friends, handles TLAST so frames end where they should, and counts packets and frames as they go out.

## Class Overview

```python
class AXISMaster(GAXIMaster):
    """
    AXIS Master component for driving AXI4-Stream protocol.

    Inherits the transmit pipeline from GAXIMaster:
    - Signal resolution and data driving setup
    - Structured transmit pipeline with handshake/timeout handling
    - Unified field configuration handling
    - Statistics and logging patterns

    AXIS-specific features added by this subclass:
    - Stream/frame conveniences (send_stream_data, send_frame,
      send_single_beat)
    - Packet/frame boundary handling with TLAST
    - Frame-level statistics (packets_sent / frames_sent)
    """
```

### Delegation to the GAXI Pipeline

All bus driving is performed by `GAXIMaster`'s structured transmit pipeline. `send_packet` queues one packet on that pipeline and awaits completion; `send_stream_data` (and therefore `send_frame`) queues **every beat up front** so they stream back-to-back — the GAXI pipeline keeps TVALID asserted between queued beats for zero-bubble operation when the slave holds TREADY high — and then waits for the pipeline to drain.

`AXISMaster` keeps no send queue, busy flag, or drive loop of its own. `is_busy()` and `get_queue_depth()` report the state of the inherited GAXI transmit queue (`self.transmit_queue` / `self.transfer_busy`).

**Timeout behavior** — worth knowing before you write your first test: a TREADY handshake timeout does not come back as `False`. The GAXI pipeline detects it and raises cocotb's `TestFailure` after `timeout_cycles`. The `send_*` methods return `True` on success precisely because there is no `False` path — failure is an exception, so write your test accordingly.

## Constructor

### `__init__(dut, title, prefix, clock, **kwargs)`

Construct the master and resolve the bus signals sitting under `prefix`.

**Parameters:**
- **`dut`** - Device under test instance
- **`title`** (str) - Component title/name for identification and logging
- **`prefix`** (str) - Signal prefix (e.g., "m_axis_", "fub_axis_")
- **`clock`** - Clock signal reference

**Optional Parameters:**
- **`field_config`** (AXISFieldConfigs) - Field configuration (creates default if None)
- **`timeout_cycles`** (int) - Maximum cycles to wait for ready (default: 1000)
- **`mode`** (str) - Protocol mode ('skid', 'blocking', etc.)
- **`bus_name`** (str) - Bus/channel name for identification
- **`pkt_prefix`** (str) - Packet field prefix
- **`multi_sig`** (bool) - Whether using multi-signal mode
- **`randomizer`** - Optional randomizer for timing variations
- **`memory_model`** - Optional memory model integration
- **`log`** - Logger instance for debug output
- **`super_debug`** (bool) - Enable detailed debugging
- **`pipeline_debug`** (bool) - Enable pipeline debugging
- **`signal_map`** (dict) - Optional manual signal mapping

**Example:**
```python
master = AXISMaster(
    dut=dut,
    title="StreamSource",
    prefix="m_axis_",
    clock=clk,
    timeout_cycles=2000,
    super_debug=True
)
```

## Core Methods

### Stream Data Transmission

#### `send_stream_data(data_list, **kwargs)` (async)

The workhorse. Hand it a list of data values and it sends them down the stream as one frame, with TLAST handled for you.

**Parameters:**
- **`data_list`** (list) - List of data values to send
- **`id`** (int) - Stream ID for all transfers (default: 0)
- **`dest`** (int) - Destination for all transfers (default: 0)
- **`user`** (int) - User signal for all transfers (default: 0)
- **`auto_last`** (bool) - Automatically set TLAST on final transfer (default: True)
- **`strb_list`** (list) - Optional list of strobe values

**Returns:** `bool` - True if successful (a TREADY timeout raises from the GAXI pipeline)

**Example:**
```python
# Send a stream of data with automatic TLAST
data = [0x11111111, 0x22222222, 0x33333333, 0x44444444]
success = await master.send_stream_data(
    data_list=data,
    id=5,
    dest=2,
    user=0xABCD
)
```

#### `send_packet(packet)` (async)

Send one packet exactly as you built it — every field on the wire comes from the packet object, so this is the method to use when you need control the conveniences don't give you.

**Parameters:**
- **`packet`** (AXISPacket) - Configured packet to send

**Returns:** `bool` - True if successful (a TREADY timeout raises from the GAXI pipeline)

**Example:**
```python
# Create and send a custom packet
packet = AXISPacket(field_config=master.field_config)
packet.data = 0x12345678
packet.last = 1
packet.id = 3
packet.dest = 1
packet.user = 0x1000

success = await master.send_packet(packet)
```

#### `send_frame(frame_data, **kwargs)` (async)

Send a complete frame: multiple beats, TLAST on the final one. A thin wrapper over `send_stream_data` with frame-flavored argument names.

**Parameters:**
- **`frame_data`** (list) - List of data values for the frame
- **`frame_id`** (int) - Frame ID (default: 0)
- **`dest`** (int) - Destination (default: 0)
- **`user`** (int) - User signal (default: 0)

**Returns:** `bool` - True if successful

**Example:**
```python
# Send a complete frame
frame = [0xDEADBEEF, 0xCAFEBABE, 0x12345678]
success = await master.send_frame(
    frame_data=frame,
    frame_id=7,
    dest=3
)
```

#### `send_single_beat(data, **kwargs)` (async)

Send one beat. TLAST defaults to asserted, so out of the box this is a complete one-beat frame — set `last=0` explicitly if more beats are coming.

**Parameters:**
- **`data`** - Data value to send
- **`last`** (int) - TLAST value (default: 1)
- **`id`** (int) - Stream ID (default: 0)
- **`dest`** (int) - Destination (default: 0)
- **`user`** (int) - User signal (default: 0)
- **`strb`** (int) - Strobe value (auto-generated if None)

**Returns:** `bool` - True if successful

**Example:**
```python
# Send single beat with custom fields
success = await master.send_single_beat(
    data=0xABCDEF01,
    last=0,  # Not end of packet
    id=2,
    dest=1,
    user=0x5555,
    strb=0xF  # All bytes valid
)
```

## Status and Control Methods

### `is_busy()`

True while anything is queued or mid-transfer on the inherited transmit pipeline.

**Returns:** `bool` - True if transactions are queued or active

### `get_queue_depth()`

How many packets are still waiting in the inherited GAXI transmit queue.

**Returns:** `int` - Number of packets waiting in the inherited GAXI transmit queue

### `get_stats()`

The counters, in one dict:

**Returns:** `dict` - Statistics dictionary containing:
- `packets_sent` - Total packets transmitted
- `frames_sent` - Total frames transmitted
- `total_data_bytes` - Total bytes transferred
- `timeouts` - Number of timeout events
- `errors` - Number of failed transactions
- `queue_depth` - Current queue depth
- `is_busy` - Current busy status

**Example:**
```python
stats = master.get_stats()
print(f"Sent {stats['packets_sent']} packets, {stats['frames_sent']} frames")
print(f"Queue depth: {stats['queue_depth']}, Busy: {stats['is_busy']}")
```

## Advanced Features

### Flow Control and Timing

Things the master handles without being asked:

- **TREADY backpressure**: the pipeline holds TVALID and waits — it never drops a beat because the slave wasn't ready.
- **Timeout protection**: if TREADY stays low for `timeout_cycles`, the pipeline raises instead of hanging your test forever.
- **Zero-bubble streaming**: beats queued back-to-back go out back-to-back when TREADY stays high.
- **Timing randomization**: pass a randomizer at construction if you want a less perfectly-behaved source.

### Memory Model Integration

```python
from CocoTBFramework.components.shared.memory_model import MemoryModel

# Attach a memory model at construction time
memory = MemoryModel(num_lines=256, bytes_per_line=4)
master = AXISMaster(dut, "Source", "m_axis_", clk, memory_model=memory)

# Memory is automatically updated with sent data
await master.send_stream_data([0x1000, 0x2000, 0x3000])
```

### Statistics and Monitoring

The counters are the honest kind — they count what actually completed on the bus:

- Packet and frame counters
- Byte transfer tracking
- Timeout and error monitoring
- Queue depth monitoring
- Performance metrics

### Debug and Logging

```python
# Enable detailed debugging
master = AXISMaster(
    dut=dut,
    title="DebugMaster",
    prefix="m_axis_",
    clock=clk,
    super_debug=True,
    pipeline_debug=True
)

# All transactions are logged with detailed information
```

## Integration Examples

### Basic Stream Generation

```python
async def test_stream_generation():
    # Create master
    master = AXISMaster(dut, "Generator", "m_axis_", clk)

    # Generate test data
    test_data = [i * 0x11111111 for i in range(1, 17)]

    # Send as stream
    success = await master.send_stream_data(
        data_list=test_data,
        id=1,
        dest=0
    )

    assert success, "Stream transmission failed"

    # Verify statistics
    stats = master.get_stats()
    assert stats['packets_sent'] == 16
    assert stats['frames_sent'] == 1
```

### Multi-Stream Scenario

```python
async def test_multi_stream():
    master = AXISMaster(dut, "MultiStream", "m_axis_", clk)

    # Send multiple concurrent streams
    for stream_id in range(4):
        stream_data = [0x1000 + stream_id + i for i in range(8)]
        await master.send_stream_data(
            data_list=stream_data,
            id=stream_id,
            dest=stream_id % 2
        )

    # Wait for completion
    while master.is_busy():
        await RisingEdge(clk)
```

### Custom Packet Construction

```python
async def test_custom_packets():
    master = AXISMaster(dut, "CustomSender", "m_axis_", clk)

    # Create packet with specific strobe pattern
    packet = AXISPacket(field_config=master.field_config)
    packet.data = 0x12345678
    packet.strb = 0xC  # Only upper 2 bytes valid
    packet.last = 1
    packet.id = 10
    packet.user = 0xABCD

    success = await master.send_packet(packet)
    assert success
```

## Error Handling

Failures surface as exceptions rather than silent drops — the TREADY timeout described above is the one you'll meet first. Beyond that, the component logs what it catches, tracks failed transactions in the statistics, and recovers so the test can continue or fail cleanly.

**Common error scenarios:**
- TREADY timeout — the slave never accepted a beat (usually a dead DUT, a ready-generation bug, or a slave that was never configured)
- Invalid packet configuration — a field value that doesn't fit its configured width
- Memory model write failures
- Clock domain issues — driving from the wrong clock

## Performance Considerations

- **Queueing**: the transmit queue is a deque inherited from GAXI — cheap to append, cheap to drain.
- **Back-to-back transfers**: queued beats cost no extra cycles between them when the slave keeps TREADY high.
- **Memory efficiency**: data structures sized for high-throughput streams.
- **Statistics overhead**: counters increment on completion; you won't notice them in your simulation time.

If you remember one thing from this page: `send_stream_data` is the workhorse. The other `send_*` methods are conveniences that all end up in the same queue, driven by the same pipeline — pick whichever makes your test read best.

---
