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

# AXISSlave

`AXISSlave` is the stream sink. It drives TREADY, captures beats as they handshake off the bus, and keeps count at the frame level — where a frame is the run of beats ending with TLAST. Like the master, it's a thin AXIS-flavored layer over the GAXI receive pipeline, which is where the real work happens.

## Class Overview

```python
class AXISSlave(GAXISlave):
    """
    AXIS Slave component for receiving AXI4-Stream protocol.

    Inherits from GAXISlave to reuse the structured pipeline state
    machine, ready-signal driving, statistics, and base initialization
    plumbing.

    AXIS-specific features added by this subclass:
    - Frame boundary detection via TLAST
    - Packet and frame statistics
    - apply_backpressure and wait_for_frame extensions
    """
```

### Delegation to the GAXI Pipeline

The inherited `GAXISlave` receive pipeline performs all handshake detection, data capture, memory-model writes, and — importantly — **all TREADY driving**, including randomized ready delays taken from the slave randomizer. `AXISSlave` does not run a competing monitor loop or drive TREADY itself, so there is no contention over the ready signal. One driver, one owner.

AXIS-level frame tracking is layered on through the standard cocotb callback mechanism: every packet the GAXI pipeline captures is also passed to `_axis_packet_callback`, which maintains `packets_received`, `frames_received`, `total_data_bytes`, and the current-frame state used by `get_current_frame_info()` and `wait_for_frame()`.

`AXISSlave` sets `_default_packet_class = AXISPacket`, so the packets the pipeline hands to that callback are real `AXISPacket` objects (see `GAXIComponentBase._build_packet`). An explicit `packet_class=` argument still takes precedence.

> **Note:** here's the part that bites people. Registering a callback changes cocotb's delivery path — `Monitor._recv()` only appends to `_recvQ` when no callback is registered. So consume `AXISSlave` traffic through `_axis_packet_callback`, your own `add_callback()`, or the frame statistics — not `slave._recvQ`, which will sit there looking stubbornly empty. `AXISMonitor` sidesteps this by hooking `_finish_packet` instead of adding a callback, which is why its `_recvQ` still works.

## Constructor

### `__init__(dut, title, prefix, clock, **kwargs)`

Construct the slave and resolve the bus signals sitting under `prefix`.

**Parameters:**
- **`dut`** - Device under test instance
- **`title`** (str) - Component title/name for identification and logging
- **`prefix`** (str) - Signal prefix (e.g., "s_axis_", "axis_")
- **`clock`** - Clock signal reference

**Optional Parameters:**
- **`field_config`** (AXISFieldConfigs) - Field configuration (creates default if None)
- **`timeout_cycles`** (int) - Maximum cycles for operations (default: 1000)
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
slave = AXISSlave(
    dut=dut,
    title="StreamSink",
    prefix="s_axis_",
    clock=clk,
    timeout_cycles=2000,
    super_debug=True
)
```

## Core Methods

### Flow Control and Ready Management

#### `set_ready_always(ready=True)`

Poke TREADY to a fixed value, right now.

> **Note**: the GAXI receive pipeline actively manages TREADY around each
> handshake, so this override only holds between pipeline actions (for
> example while the pipeline is waiting for TVALID). For sustained or
> randomized backpressure, use `apply_backpressure()` — which feeds the
> randomizer the pipeline actually consults — rather than pinning the
> signal here.

**Parameters:**
- **`ready`** (bool) - True to assert ready, False to deassert

**Example:**
```python
# Nudge ready high right now
slave.set_ready_always(True)

# Nudge ready low right now
slave.set_ready_always(False)
```

#### `apply_backpressure(probability=0.2, min_cycles=1, max_cycles=5)`

This is how you do real backpressure. Instead of pinning TREADY yourself, you adjust the ready-delay constraints the receive pipeline consults — and the pipeline does the driving, so the backpressure survives across beats instead of being overwritten by the next pipeline action.

**Parameters:**
- **`probability`** (float) - Probability of applying backpressure (0.0 to 1.0)
- **`min_cycles`** (int) - Minimum cycles to hold ready low
- **`max_cycles`** (int) - Maximum cycles to hold ready low

**Example:**
```python
# Apply 30% chance of 1-3 cycle backpressure
slave.apply_backpressure(
    probability=0.3,
    min_cycles=1,
    max_cycles=3
)
```

### Frame Monitoring and Reception

#### `wait_for_frame(timeout_cycles=None)` (async)

Block until a complete frame lands — that is, until a beat arrives with TLAST set.

**Parameters:**
- **`timeout_cycles`** (int) - Maximum cycles to wait (uses instance default if None)

**Returns:** `bool` - True if frame completed, False if timeout

**Example:**
```python
# Wait for next frame with default timeout
frame_received = await slave.wait_for_frame()

# Wait with custom timeout
frame_received = await slave.wait_for_frame(timeout_cycles=5000)

if frame_received:
    stats = slave.get_stats()
    print(f"Frame received! Total frames: {stats['frames_received']}")
```

#### `get_current_frame_info()`

A snapshot of the frame currently in flight — useful for progress logging while a long frame is arriving.

**Returns:** `dict` - Frame information containing:
- `packets_in_frame` - Number of packets received in current frame
- `frame_id` - ID of the current frame (from first packet)
- `total_bytes` - Total bytes received in current frame
- `is_receiving` - Whether currently receiving a frame

**Example:**
```python
frame_info = slave.get_current_frame_info()
print(f"Current frame: {frame_info['packets_in_frame']} packets, "
      f"{frame_info['total_bytes']} bytes, ID={frame_info['frame_id']}")
```

## Status and Statistics Methods

### `get_stats()`

The counters, in one dict:

**Returns:** `dict` - Statistics dictionary containing:
- `packets_received` - Total packets received
- `frames_received` - Total frames received (sequences ending with TLAST)
- `total_data_bytes` - Total bytes received
- `errors` - Number of error events
- `current_frame_info` - Information about current frame being received

**Example:**
```python
stats = slave.get_stats()
print(f"Received {stats['packets_received']} packets in {stats['frames_received']} frames")
print(f"Total data: {stats['total_data_bytes']} bytes")
print(f"Current frame: {stats['current_frame_info']['packets_in_frame']} packets")
```

## Automatic Monitoring Features

### Stream Reception Monitoring

Once constructed, the slave is already watching the bus. No explicit start, no polling loop in your test:

- **Handshake detection**: the pipeline watches TVALID/TREADY and acts on completed handshakes.
- **Packet capture**: valid transfers become `AXISPacket` objects automatically.
- **Frame assembly**: beats are grouped by TLAST boundaries.
- **Statistics tracking**: counters update as packets land.

### Frame Boundary Processing

- **Automatic TLAST detection**: frame boundaries are recognized, not polled for.
- **Frame statistics**: complete frames are counted as they close.
- **Multi-frame support**: back-to-back frames are tracked without you stitching anything together.
- **Frame ID tracking**: each frame is associated with the ID of its first beat.

### Memory Model Integration

```python
from CocoTBFramework.components.shared.memory_model import MemoryModel

# Attach a memory model at construction time
memory = MemoryModel(num_lines=256, bytes_per_line=4)
slave = AXISSlave(dut, "Sink", "s_axis_", clk, memory_model=memory)

# All received data is automatically written to memory
# Memory addresses are calculated based on packet fields
```

## Advanced Features

### Protocol Compliance Monitoring

Along the way, the component also keeps an eye on protocol health:

- Validates TVALID/TREADY handshake timing
- Checks protocol specification compliance
- Detects and reports protocol violations
- Monitors sideband signal consistency

### Timing Randomization

```python
# Create randomizer for realistic ready timing
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer

randomizer = FlexRandomizer({
    'ready_delay': ([(0, 0), (1, 5)], [0.8, 0.2])
})
slave = AXISSlave(
    dut=dut,
    title="RealisticSink",
    prefix="s_axis_",
    clock=clk,
    randomizer=randomizer
)

# Randomizer automatically applies ready timing variations
```

### Debug and Analysis

```python
# Enable comprehensive debugging
slave = AXISSlave(
    dut=dut,
    title="DebugSlave",
    prefix="s_axis_",
    clock=clk,
    super_debug=True,
    pipeline_debug=True
)

# All received packets are logged with detailed information
```

## Integration Examples

### Basic Stream Reception

```python
async def test_stream_reception():
    # Create slave
    slave = AXISSlave(dut, "Receiver", "s_axis_", clk)

    # Set to always ready
    slave.set_ready_always(True)

    # Wait for data
    await slave.wait_for_frame(timeout_cycles=1000)

    # Check results
    stats = slave.get_stats()
    assert stats['frames_received'] > 0, "No frames received"
    print(f"Successfully received {stats['packets_received']} packets")
```

### Backpressure Testing

```python
async def test_backpressure():
    slave = AXISSlave(dut, "BackpressureSink", "s_axis_", clk)

    # Apply moderate backpressure
    slave.apply_backpressure(
        probability=0.4,  # 40% chance
        min_cycles=1,
        max_cycles=4
    )

    # Monitor reception with backpressure
    initial_time = get_sim_time()
    await slave.wait_for_frame(timeout_cycles=5000)
    reception_time = get_sim_time() - initial_time

    print(f"Reception time with backpressure: {reception_time}")
```

### Multi-Stream Monitoring

```python
async def test_multi_stream():
    slave = AXISSlave(dut, "MultiStreamSink", "s_axis_", clk)
    slave.set_ready_always(True)

    # Monitor multiple frames
    frame_count = 0
    target_frames = 4

    while frame_count < target_frames:
        if await slave.wait_for_frame(timeout_cycles=2000):
            frame_count += 1
            frame_info = slave.get_current_frame_info()
            print(f"Frame {frame_count}: ID={frame_info['frame_id']}")
        else:
            break

    stats = slave.get_stats()
    assert stats['frames_received'] == target_frames
```

### Memory Verification

```python
async def test_memory_verification():
    # Create memory model
    from CocoTBFramework.components.shared.memory_model import MemoryModel
    memory = MemoryModel(num_lines=512, bytes_per_line=4)

    # Create slave with memory integration
    slave = AXISSlave(
        dut, "MemorySink", "s_axis_", clk,
        memory_model=memory
    )

    # Receive data (automatically written to memory)
    await slave.wait_for_frame()

    # Verify memory contents
    received_data = memory.read(0x0, 64)  # Read first 64 bytes
    expected_data = generate_expected_pattern()

    assert received_data == expected_data, "Memory verification failed"
```

## Error Handling and Recovery

Failures surface the way they should — as timeouts you can catch and exceptions that get logged, not as silently missing data:

- **Timeout detection**: configurable timeout for operations
- **Exception recovery**: graceful handling of simulation exceptions
- **Protocol error detection**: identification of protocol violations
- **Logging integration**: detailed error reporting through the component logger

**Common error scenarios:**
- TVALID timeout — no data ever arrived (dead master, wrong prefix, or a DUT that never started)
- Protocol violations — an invalid handshake sequence
- Memory model write failures
- Clock domain issues

## Performance Monitoring

### Reception Statistics

The counters give you the raw material for throughput analysis:

- **Throughput**: packets and bytes received — divide by simulation time yourself, as in the example below
- **Frame statistics**: frame completion counts and sizes
- **Backpressure impact**: ready signal timing behavior
- **Protocol efficiency**: handshake success rates

### Real-time Analysis

```python
# Monitor real-time performance
stats = slave.get_stats()
frame_info = slave.get_current_frame_info()

print(f"Throughput: {stats['total_data_bytes'] / simulation_time} MB/s")
print(f"Frame completion rate: {stats['frames_received'] / elapsed_frames}")
print(f"Current frame progress: {frame_info['packets_in_frame']} packets")
```

## Integration with Other Components

### Master-Slave Pairs

```python
# Create matched master-slave pair
master = AXISMaster(dut, "Source", "m_axis_", clk)
slave = AXISSlave(dut, "Sink", "s_axis_", clk)

# Configure matching parameters
config = AXISFieldConfigs.create_default_axis_config()
master.field_config = config
slave.field_config = config
```

### Monitor Integration

```python
# Add monitor for comprehensive analysis
monitor = AXISMonitor(dut, "StreamMonitor", "s_axis_", clk)
slave = AXISSlave(dut, "StreamSink", "s_axis_", clk)

# Both components monitor the same signals
# Monitor provides protocol analysis
# Slave provides reception functionality
```

For most tests the pattern is short: construct the slave, maybe call `apply_backpressure(...)`, `await wait_for_frame()`, then check `get_stats()`. Everything else on this page is there for the day that isn't enough.

---
