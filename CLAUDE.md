# Claude Code Guide: CocoTB Framework

**Version:** 1.0
**Purpose:** AI-specific guidance for working with the CocoTBFramework package

---

## Quick Context

**What:** Pip-installable CocoTB verification infrastructure for RTL testing
**PyPI Name:** `cocotb-framework`
**Import Name:** `CocoTBFramework`
**Structure:** Core RTL-agnostic verification infrastructure — BFMs, scoreboards, and shared testbench base
**Layout:** `src/` layout — all source under `src/CocoTBFramework/`

---

## Project Structure

```
RTLDesignSherpa-DV/
├── src/CocoTBFramework/     # Package source
│   ├── components/          # Protocol-specific BFMs and drivers
│   └── scoreboards/         # Transaction verification
├── tests/                   # Framework unit tests
├── pyproject.toml           # Package configuration
└── CLAUDE.md                # This file
```

**Note:** Testbench classes (tbclasses/, including shared/TBBase) remain in the main RTLDesignSherpa repo — they are tied to RTL project structure. Only core RTL-agnostic BFMs and scoreboards live here.

---

## Framework Architecture

### Component Hierarchy

```
components/
├── axi4/    # AXI4 full protocol (master, slave, monitor, packet, compliance)
├── axi5/    # AXI5 protocol
├── axil4/   # AXI4-Lite
├── apb/     # APB protocol
├── apb5/    # APB5 protocol
├── axis4/   # AXI-Stream
├── axis5/   # AXI-Stream v5
├── fifo/    # FIFO controllers
├── gaxi/    # Generic AXI infrastructure
├── smbus/   # System Management Bus
├── uart/    # UART
├── wavedrom/ # Waveform visualization
└── shared/  # Common utilities (packet, field_config, memory_model, randomizer)
```

---

## Critical Rules

### Rule #1: Search Before Creating
Always check if a component exists before creating a new one. The framework has extensive protocol support.

### Rule #2: 100% Test Success Required
All tests must achieve 100% success rate. RTL is deterministic — partial success indicates bugs.

### Rule #3: Queue-Based Verification
Use `monitor._recvQ.popleft()` for simple transaction verification, not memory models.

---

## Common Imports

```python
from CocoTBFramework.components.shared.memory_model import MemoryModel
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer
from CocoTBFramework.components.shared.field_config import FieldConfig
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4Master
from CocoTBFramework.components.apb.apb_components import APBSlave
from CocoTBFramework.scoreboards.base_scoreboard import BaseScoreboard
```

---

## Development

```bash
# Install in development mode
pip install -e ".[dev,all]"

# Run tests
pytest

# Lint
ruff check src/

# Build distributable
python -m build
```
