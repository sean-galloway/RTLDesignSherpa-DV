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

# GAXI Components Index

GAXI (Generic AXI) is the framework's base layer: a valid/ready handshake protocol plus the components that drive it, receive it, and watch it. It was built for validating FIFO-based interfaces on small internal blocks, where the interface might be one bus with fields packed into it or a pile of discrete signals — the field configuration system covers both. It's also the layer the AXI4/AXI5, AXI-Lite, AXI-Stream and FIFO BFMs are built on, so most of what happens anywhere in this framework passes through code in this directory.

## Directory Structure

### Core Components
- [**gaxi_component_base.py**](components_gaxi_gaxi_component_base.md) - Base class every GAXI component inherits from
- [**gaxi_master.py**](components_gaxi_gaxi_master.md) - The driver: sends packets, applies valid timing
- [**gaxi_slave.py**](components_gaxi_gaxi_slave.md) - The receiver: drives ready, captures data per mode
- [**gaxi_monitor.py**](components_gaxi_gaxi_monitor.md) - Passive observer for either side of the interface
- [**gaxi_monitor_base.py**](components_gaxi_gaxi_monitor_base.md) - Shared observe-side machinery for slave and monitor

### Data and Protocol Support
- [**gaxi_packet.py**](components_gaxi_gaxi_packet.md) - Packet class: fields from base Packet, timing randomizers added
- [**gaxi_sequence.py**](components_gaxi_gaxi_sequence.md) - Build transaction sequences with delays, dependencies, randomization
- [**gaxi_command_handler.py**](components_gaxi_gaxi_command_handler.md) - Connects a master and slave: forwards traffic or generates responses

### Factory and Utilities
- [**gaxi_factories.py**](components_gaxi_gaxi_factories.md) - One-call creation of components and whole systems

## Quick Start

### Basic Usage
```python
from CocoTBFramework.components.gaxi.gaxi_factories import create_gaxi_system

# Create complete GAXI system (log is required by the underlying components)
system = create_gaxi_system(dut, clock, log=log)
master = system['master']
slave = system['slave']

# Send data
await master.send(master.create_packet(data=0xDEADBEEF))
```

### Advanced Usage
```python
from CocoTBFramework.components.gaxi import GAXIMaster, GAXISlave, GAXIMonitor
from CocoTBFramework.components.gaxi.gaxi_sequence import GAXISequence

# Create individual components (log is required)
master = GAXIMaster(dut, "TestMaster", "", clock, field_config, log=log)
slave = GAXISlave(dut, "TestSlave", "", clock, field_config, log=log)
monitor = GAXIMonitor(dut, "Monitor", "", clock, field_config, log=log)

# Create test sequence
sequence = GAXISequence("test_pattern", field_config)
sequence.add_burst(count=10, start_data=0x1000)
packets = sequence.generate_packets()
```

## Component Overview

### GAXIMaster
- Drives transactions with randomized valid timing
- Single-signal and multi-signal field modes
- Three-phase send pipeline with debugging and per-phase statistics
- Memory model helpers for testbench-side read/write

### GAXISlave  
- Receives transactions and drives ready with randomized delay
- Three capture modes (skid, fifo_mux, fifo_flop) to match the DUT's implementation
- Automatic memory storage for received writes
- Callbacks into your test when packets land

### GAXIMonitor
- Watches either side of the interface, drives nothing
- Mode-aware sampling (fifo_flop captures one cycle late, on purpose)
- Protocol violation and X/Z tracking
- Plugs straight into scoreboards via callbacks

### Supporting Classes
- **GAXIPacket**: base Packet fields plus per-packet timing randomizers
- **GAXISequence**: ordered transactions with delays, dependencies, and randomized values
- **GAXICommandHandler**: master/slave coordination, response generation, memory fallback
- **GAXIComponentBase**: signal resolution, data strategies, memory access, statistics — the shared core

## Features

### Signal Resolution
- Automatic signal discovery by pattern matching
- Manual `signal_map` override for creative DUT naming
- Conventional prefix conventions recognized out of the box
- Single-signal (packed fields) and multi-signal (discrete) modes

### Performance
- Signals resolved once and cached — not re-looked-up per transaction
- Thread-safe caching for parallel test execution
- Data collection and driving go through pre-built strategies, not per-call discovery

### Debugging
- Pipeline state tracking with transition logging
- Statistics at the component, pipeline, and memory levels
- Protocol violation and X/Z counters
- Debug output you can toggle at runtime and leave off in regressions

### Flexibility
- Field definitions you configure, packet structure follows
- FlexRandomizer constraints for timing and data
- Dependency tracking in sequences
- Memory model integration everywhere it makes sense

## Integration

The GAXI components build on and plug into:
- **Shared infrastructure**: field configuration, memory models, statistics, randomization
- **Scoreboards**: expected/actual wiring via monitor callbacks
- **CocoTB**: standard BusDriver/BusMonitor inheritance
- **The protocol BFMs**: AXI4/AXI5, AXI-Lite, AXI-Stream and FIFO components delegate to these pipelines

## Navigation
- [**Overview**](components_gaxi_overview.md) - Detailed component overview and architecture
- [**Back to Components**](../components_index.md) - Return to components index
- [**Back to CocoTBFramework**](../components_index.md) - Return to main framework index
