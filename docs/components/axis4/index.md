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

**[← Back to Components Index](../components_index.md)** | **[CocoTBFramework Index](../components_index.md)** | **[Main Index](../components_index.md)**

# AXIS4 Components

Everything you need to verify an AXI4-Stream interface: drive it, sink it, watch it. The components sit on the GAXI layer, so the heavy lifting — signal resolution, pipelines, statistics — is shared with the rest of the framework, and what's here is the stream-specific part: frames, TLAST, backpressure, and sidebands.

## Component Overview

The AXIS4 family:

### Core Components

- **[AXISMaster](axis_master.md)** - Stream source: single beats, lists, or whole frames
- **[AXISSlave](axis_slave.md)** - Stream sink with backpressure control and frame tracking
- **AXISMonitor** - Protocol compliance monitoring and analysis. Extends `GAXIMonitor` and delegates all sampling to its receive loop; see [the overview](components_axis4_overview.md) for the `_build_packet` / `_finish_packet` extension points. *(Dedicated page planned.)*
- **[AXISPacket](axis_packet.md)** - The beat object: field access, byte packing, TLAST queries

### Configuration System

- **[AXISFieldConfigs](axis_field_configs.md)** - Builds the field configuration that keeps BFMs and RTL in agreement on signal widths

## Key Features

### Stream Protocol Specialization
- Single channel (T-channel) focus with TVALID/TREADY handshaking
- Native packet boundary management with TLAST signaling
- Advanced flow control and backpressure handling
- Complete sideband signal support (TID, TDEST, TUSER, TSTRB)

### GAXI Infrastructure Integration
- Unified field configuration system
- Memory model integration for data verification
- Statistics and performance metrics maintained by the pipelines
- Multi-level debugging and transaction logging
- Automatic signal resolution across naming conventions

### Advanced Capabilities
- Multi-stream support with TID-based routing
- Real-time performance monitoring and analysis
- Protocol compliance verification
- Configurable timing randomization
- Memory-efficient streaming for large datasets

## Getting Started

```python
from CocoTBFramework.components.axis4 import (
    AXISFieldConfigs, AXISMaster, AXISMonitor, AXISPacket, AXISSlave,
)

# Configure stream properties
config = AXISFieldConfigs.create_t_field_config(
    data_width=32, id_width=8, dest_width=4)

# Create AXIS components
master = AXISMaster(dut, "StreamSource", "m_axis_", clk, field_config=config)
slave = AXISSlave(dut, "StreamSink", "s_axis_", clk, field_config=config)
monitor = AXISMonitor(dut, "StreamMon", "s_axis_", clk, field_config=config)

# Generate and send packets
packet = AXISPacket(field_config=master.field_config)
packet.data = 0x12345678
packet.last = 1
packet.id = 5
packet.dest = 2
await master.send_packet(packet)
```

## Documentation Structure

- **[Overview](components_axis4_overview.md)** - Architecture and how the pieces fit together
- **Component References** - Per-class details, linked above
- **Usage Examples *(documentation planned)*** - Practical implementation patterns and scenarios
- **Configuration Guide *(documentation planned)*** - Field configuration and customization options

Start with the [overview](components_axis4_overview.md) if you want the architecture, or jump straight to the class you need — each page stands on its own.
