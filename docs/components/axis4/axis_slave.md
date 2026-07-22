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

The `AXISSlave` class provides comprehensive AXI4-Stream protocol slave (sink) functionality. Built on the GAXI infrastructure, it offers advanced stream data reception, backpressure control, and automatic frame assembly with complete protocol monitoring capabilities.

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

The inherited `GAXISlave` receive pipeline performs all handshake detection, data capture, memory-model writes, and — importantly — **all TREADY driving**, including randomized ready delays taken from the slave randomizer. `AXISSlave` does not run a competing monitor loop or drive TREADY itself, so there is no contention over the ready signal.

AXIS-level frame tracking is layered on through the standard cocotb callback mechanism: every packet the GAXI pipeline captures is also passed to `_axis_packet_callback`, which maintains `packets_received`, `frames_received`, `total_data_bytes`, and the current-frame state used by `get_current_frame_info()` and `wait_for_frame()`.

`AXISSlave` sets `_default_packet_class = AXISPacket`, so the packets the pipeline hands to that callback are real `AXISPacket` objects (see `GAXIComponentBase._build_packet`). An explicit `packet_class=` argument still takes precedence.

> **Note:** registering a callback changes cocotb's delivery path — `Monitor._recv()` only appends to `_recvQ` when no callback is registered. Consume `AXISSlave` traffic through `_axis_packet_callback`, your own `add_callback()`, or the frame statistics, not `slave._recvQ`. `AXISMonitor` keeps `_recvQ` intact by hooking `_finish_packet` instead of adding a callback.

## Constructor

### `__init__(dut, title, prefix, clock, **kwargs)`

Initialize the AXIS Slave component.

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

Force the TREADY signal to a fixed value immediately.

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

Apply random backpressure by updating the ready-delay constraints that the GAXI receive pipeline uses when driving TREADY. This is the supported way to create sustained backpressure.

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

Wait for a complete frame to be received (packet sequence ending with TLAST).

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

Get information about the currently receiving frame.

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

Get comprehensive reception statistics.

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

The AXISSlave automatically monitors the bus and:
- **Handshake Detection**: Monitors TVALID/TREADY handshakes
- **Packet Capture**: Automatically captures valid transfers
- **Frame Assembly**: Groups packets by TLAST boundaries
- **Statistics Tracking**: Updates counters and performance metrics

### Frame Boundary Processing

- **Automatic TLAST Detection**: Identifies frame boundaries
- **Frame Statistics**: Tracks complete frame reception
- **Multi-Frame Support**: Handles concurrent or sequential frames
- **Frame ID Tracking**: Associates packets with frame IDs

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

The component automatically:
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

The AXISSlave provides robust error handling:
- **Timeout Detection**: Configurable timeout for operations
- **Exception Recovery**: Graceful handling of simulation exceptions
- **Protocol Error Detection**: Identification of protocol violations
- **Logging Integration**: Comprehensive error reporting

**Common error scenarios:**
- TVALID timeout (no data received)
- Protocol violations (invalid handshake)
- Memory model write failures
- Clock domain issues

## Performance Monitoring

### Reception Statistics

The component tracks:
- **Throughput**: Packets and bytes per time unit
- **Frame Statistics**: Frame completion rates and sizes
- **Backpressure Impact**: Ready signal timing analysis
- **Protocol Efficiency**: Handshake success rates

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

The AXISSlave component provides a complete solution for AXI4-Stream data reception, combining automatic monitoring with flexible flow control and comprehensive statistics for verification scenarios.