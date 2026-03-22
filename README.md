# CocoTB Framework

Reusable CocoTB verification infrastructure for RTL testing. Provides protocol-specific Bus Functional Models (BFMs), testbench base classes, and transaction scoreboards for AMBA and other standard interfaces.

## Installation

```bash
pip install cocotb-framework
```

With all optional dependencies:

```bash
pip install cocotb-framework[all]
```

## Features

- **Protocol BFMs:** AXI4, AXI5, AXI4-Lite, APB, APB5, AXI-Stream, FIFO, GAXI, SMBus, UART
- **Transaction Scoreboards:** Queue-based verification with protocol-specific comparators
- **Flexible Randomization:** Configurable randomization framework for constrained-random verification
- **Wavedrom Integration:** Waveform visualization and constraint-based signal generation
- **Three-Layer Architecture:** TB infrastructure + Test intelligence + Scoreboard verification

## Quick Start

```python
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4Master
from CocoTBFramework.components.shared.memory_model import MemoryModel
from CocoTBFramework.scoreboards.base_scoreboard import BaseScoreboard

# Use AXI4 BFM in your testbench
master = AXI4Master(dut=dut, name="axi_m", clock=dut.aclk)
```

## Package Structure

```
CocoTBFramework/
├── components/       # Protocol-specific BFMs and drivers
│   ├── axi4/        # AXI4 full protocol
│   ├── axi5/        # AXI5 protocol
│   ├── axil4/       # AXI4-Lite
│   ├── apb/         # APB protocol
│   ├── apb5/        # APB5 protocol
│   ├── axis4/       # AXI-Stream
│   ├── axis5/       # AXI-Stream v5
│   ├── fifo/        # FIFO controllers
│   ├── gaxi/        # Generic AXI
│   ├── smbus/       # System Management Bus
│   ├── uart/        # UART
│   ├── wavedrom/    # Waveform visualization
│   └── shared/      # Common utilities (packet, field_config, memory_model, randomizer)
└── scoreboards/     # Transaction verification
```

## Dependencies

**Required:** cocotb, cocotb-bus, cocotb-coverage, psutil, rich, numpy

**Optional:**
- `cocotb-framework[wavedrom]` — OR-Tools for wavedrom constraint solving
- `cocotb-framework[crc]` — CRC computation for CRC testing
- `cocotb-framework[all]` — All optional dependencies

## License

MIT License. See [LICENSE](LICENSE) for details.
