# CocoTB Framework

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Reusable CocoTB verification infrastructure for RTL testing. Provides protocol-specific Bus Functional Models (BFMs), transaction scoreboards, and shared utilities for AMBA and other standard interfaces.

Extracted from the [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) project as a standalone, pip-installable package.

---

## Installation

```bash
pip install cocotb-framework
```

With all optional dependencies:

```bash
pip install cocotb-framework[all]
```

For development:

```bash
git clone https://github.com/sean-galloway/RTLDesignSherpa-DV.git
cd RTLDesignSherpa-DV
pip install -e ".[dev,all]"
```

---

## Package Structure

```
CocoTBFramework/
├── components/           # Protocol-specific BFMs and drivers
│   ├── axi4/            # AXI4 full protocol
│   ├── axi5/            # AXI5 (AMBA5) protocol
│   ├── axil4/           # AXI4-Lite
│   ├── apb/             # APB protocol
│   ├── apb5/            # APB5 protocol
│   ├── axis4/           # AXI-Stream
│   ├── axis5/           # AXI-Stream v5
│   ├── fifo/            # Generic FIFO
│   ├── gaxi/            # GAXI — validate FIFO-based interfaces on small blocks
│   ├── smbus/           # System Management Bus
│   ├── uart/            # UART serial
│   ├── wavedrom/        # Waveform visualization
│   └── shared/          # Common utilities
└── scoreboards/         # Transaction verification
    ├── base_scoreboard  # Base class for all scoreboards
    └── axi4/            # AXI4-specific scoreboards
```

---

## Protocol BFMs

Each protocol package provides a complete set of verification components: **masters** (drivers), **slaves** (responders), **monitors** (passive observers), and **packets** (transaction representations).

### AMBA Protocols

#### AXI4 (Advanced eXtensible Interface)

Full AXI4 protocol implementation with compliance checking and constrained randomization.

```python
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4MasterRead, AXI4MasterWrite
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4SlaveRead, AXI4SlaveWrite
from CocoTBFramework.components.axi4.axi4_packet import AXI4Packet
from CocoTBFramework.components.axi4.axi4_compliance_checker import AXI4ComplianceChecker
from CocoTBFramework.components.axi4.axi4_randomization_manager import AXI4RandomizationManager
```

**Key classes:**
- `AXI4MasterRead` / `AXI4MasterWrite` — Full-duplex master with integrated compliance
- `AXI4SlaveRead` / `AXI4SlaveWrite` — Slave responder with configurable timing
- `AXI4ComplianceChecker` — Protocol violation detection and tracking
- `AXI4RandomizationManager` — Constrained-random transaction generation
- `AXI4Packet` — Complete transaction representation with field formatting

#### AXI5

AMBA5-generation AXI with extended signals and features. Same class structure as AXI4.

```python
from CocoTBFramework.components.axi5.axi5_interfaces import AXI5MasterRead, AXI5MasterWrite
from CocoTBFramework.components.axi5.axi5_compliance_checker import AXI5ComplianceChecker
```

#### AXI4-Lite

Simplified AXI for register-mapped peripherals.

```python
from CocoTBFramework.components.axil4.axil4_interfaces import AXIL4MasterRead, AXIL4MasterWrite
from CocoTBFramework.components.axil4.axil4_compliance_checker import AXIL4ComplianceChecker
```

#### APB / APB5 (Advanced Peripheral Bus)

Simple bus protocol for low-bandwidth peripherals.

```python
from CocoTBFramework.components.apb.apb_components import APBMaster, APBSlave, APBMonitor
from CocoTBFramework.components.apb.apb_packet import APBPacket
from CocoTBFramework.components.apb.apb_sequence import APBSequence
from CocoTBFramework.components.apb.apb_factories import create_apb_monitor, create_apb_scoreboard
```

#### AXI-Stream (AXIS4 / AXIS5)

Unidirectional streaming with handshake.

```python
from CocoTBFramework.components.axis4.axis_master import AXISMaster
from CocoTBFramework.components.axis4.axis_slave import AXISSlave
from CocoTBFramework.components.axis4.axis_monitor import AXISMonitor
from CocoTBFramework.components.axis4.axis_packet import AXISPacket
```

### Generic AXI (GAXI)

Lightweight valid/ready handshake protocol for validating individual FIFO-based interfaces on very small internal blocks. Interfaces can carry data packed into fields within a single bus, or have many discrete signals. Includes built-in coverage hooks and statistics tracking.

```python
from CocoTBFramework.components.gaxi import GAXIMaster, GAXISlave, GAXIMonitor
from CocoTBFramework.components.gaxi import GaxiCoverageHook, register_coverage_hooks
from CocoTBFramework.components.gaxi.gaxi_packet import GAXIPacket
from CocoTBFramework.components.gaxi.gaxi_sequence import GAXISequence
```

### Other Protocols

#### FIFO

Generic FIFO verification with masters, slaves, monitors, and command handling.

```python
from CocoTBFramework.components.fifo.fifo_master import FIFOMaster
from CocoTBFramework.components.fifo.fifo_slave import FIFOSlave
from CocoTBFramework.components.fifo.fifo_monitor import FIFOMonitor
```

#### SMBus (System Management Bus)

SMBus/I2C protocol verification with open-drain tristate signal handling and CRC-8 PEC.

```python
from CocoTBFramework.components.smbus.smbus_components import SMBusMaster, SMBusSlave, SMBusMonitor
```

#### UART

Serial UART protocol at the bit level.

```python
from CocoTBFramework.components.uart.uart_components import UARTMaster, UARTSlave, UARTMonitor
```

---

## Shared Utilities

Common infrastructure used across all protocol implementations.

```python
from CocoTBFramework.components.shared.packet import Packet
from CocoTBFramework.components.shared.field_config import FieldConfig, FieldDefinition
from CocoTBFramework.components.shared.memory_model import MemoryModel
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer
from CocoTBFramework.components.shared.packet_factory import PacketFactory
```

| Module | Purpose |
|--------|---------|
| `packet.py` | Base class for all protocol packets with thread-safe field caching |
| `field_config.py` | Type-safe field configuration and definition system |
| `memory_model.py` | High-performance memory model with NumPy backend and region management |
| `flex_randomizer.py` | Constrained randomization with ranges, sequences, and function-based generators |
| `packet_factory.py` | Generic factory for creating packets across any protocol |
| `master_statistics.py` | Master component metrics (throughput, latency, violations) |
| `monitor_statistics.py` | Passive monitor statistics collection |
| `arbiter_master.py` | Universal arbiter master with weighted/unweighted support |
| `arbiter_monitor.py` | Round-robin and weighted arbitration monitoring |
| `arbiter_compliance.py` | Arbiter protocol correctness validation |
| `data_strategies.py` | Data collection and driving strategies |
| `signal_mapping_helper.py` | Signal-to-field mapping and resolution |
| `debug_object.py` | Base debugging utilities |
| `protocol_error_handler.py` | Protocol error handling and reporting |

---

## Scoreboards

Queue-based transaction verification with protocol-specific comparators and cross-protocol adapters.

```python
from CocoTBFramework.scoreboards.base_scoreboard import BaseScoreboard
from CocoTBFramework.scoreboards.gaxi_scoreboard import GAXIScoreboard
from CocoTBFramework.scoreboards.fifo_scoreboard import FIFOScoreboard
from CocoTBFramework.scoreboards.apb_scoreboard import APBScoreboard
from CocoTBFramework.scoreboards.apb_gaxi_scoreboard import APBGAXIScoreboard
```

| Scoreboard | Purpose |
|------------|---------|
| `BaseScoreboard` | Foundation with queue-based expected vs actual comparison |
| `GAXIScoreboard` | GAXI transaction verification with field configuration |
| `APBScoreboard` | APB transaction verification |
| `APBGAXIScoreboard` | APB-to-GAXI cross-protocol transformation verification |
| `FIFOScoreboard` | FIFO transaction verification with memory adapters |
| `AXI4DWidthConverterScoreboard` | AXI4 data width converter validation |

### Cross-Protocol Adapters

```python
from CocoTBFramework.scoreboards.apb_gaxi_transformer import APBtoGAXITransformer
```

The scoreboard system includes transformers and adapters for verifying protocol bridges and converters (APB ↔ GAXI, GAXI ↔ Memory, etc.).

---

## Waveform Visualization

Generate WaveJSON timing diagrams from simulation signals.

```python
from CocoTBFramework.components.wavedrom.wavejson_gen import WaveJSONGenerator
from CocoTBFramework.components.wavedrom.signal_binder import SignalBinder
from CocoTBFramework.components.wavedrom.constraint_solver import ConstraintSolver
```

---

## Dependencies

### Required

| Package | Purpose |
|---------|---------|
| `cocotb>=1.9.0` | Core simulation framework |
| `cocotb-bus>=0.2.1` | BusDriver/BusMonitor base classes |
| `cocotb-coverage>=1.2.0` | Coverage-driven verification |
| `psutil>=5.9.0` | System resource monitoring |
| `rich>=14.0.0` | Table display and formatting |
| `numpy>=2.0.0` | High-performance memory model backend |

### Optional Extras

```bash
pip install cocotb-framework[wavedrom]   # OR-Tools for constraint solving
pip install cocotb-framework[crc]        # CRC computation
pip install cocotb-framework[all]        # All optional dependencies
```

---

## Development

```bash
# Install in development mode
pip install -e ".[dev,all]"

# Lint
ruff check src/

# Build distributable
python -m build
```

---

## Related Projects

- [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) — Parent project with 350+ RTL modules, testbenches, and verification infrastructure
- [cocotb](https://github.com/cocotb/cocotb) — Coroutine-based cosimulation framework
- [cocotb-bus](https://github.com/cocotb/cocotb-bus) — Bus driver and monitor base classes

---

## License

MIT License. See [LICENSE](LICENSE) for details.
