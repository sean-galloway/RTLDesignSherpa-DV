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

# WaveDrom Protocol Presets Reference

**Complete guide to all protocol-specific constraint libraries**

---

## Overview

Presets are the reason wavedrom setup is measured in minutes instead of days. Each one bundles the field configuration, constraint patterns, and boundary detection for one bus protocol, so "draw me an APB write with wait states" is a preset name, not an afternoon of hand-writing temporal constraints.

### Available Protocols

| Protocol | File | Template Class | Status |
|----------|------|----------------|--------|
| **GAXI** | `gaxi.py` | `GAXIWaveDromTemplate` | Production |
| **APB** | `apb.py` | `APBWaveDromTemplate` | Production |
| **AXI4** | `axi4.py` | *(manual setup)* | Ready |
| **AXI4-Lite** | `axil4.py` | *(manual setup)* | Ready |
| **AXI-Stream** | `axis.py` | *(manual setup)* | Ready |

!!! note "Wavedrom User Examples"
    The protocol-specific wavedrom user examples (gaxi.py, apb.py, etc.) are located in the [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) repository under `tbclasses/wavedrom_user/`.

---

## GAXI (Generic AXI) Protocol

**The plain valid/ready handshake the rest of the framework is built on — and the simplest place to start.**

### Presets

#### `basic_handshake`
**Constraints:** 1
- `handshake`: Detects valid→ready sequences

**Use Case:** Sanity check that transactions are happening at all.

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/gaxi.py)
from CocoTBFramework.tbclasses.wavedrom_user.gaxi import GAXIWaveDromTemplate

gaxi_wave = GAXIWaveDromTemplate(
    dut=dut,
    signal_prefix="wr_",
    data_width=32,
    preset="basic_handshake"
)
```

#### `comprehensive`
**Constraints:** 4
- `handshake`: Valid→ready sequences
- `back2back`: Continuous transfers (no idle)
- `stall`: Backpressure (valid=1, ready=0)
- `idle`: Both signals low

**Use Case:** The default for a reason — it covers the behaviors you almost always want to see.

```python
preset="comprehensive"  # Most common choice
```

#### `performance`
**Constraints:** 3
- `handshake`: Valid→ready sequences
- `back2back`: Continuous transfers
- `stall`: Extended window (100 cycles)

**Use Case:** Finding where throughput goes to die — the long stall window catches backpressure that shorter windows clip.

```python
preset="performance"
```

#### `debug`
**Constraints:** 3 (all with extended windows)
- `handshake`: 100 cycle window
- `stall`: 200 cycle window
- `idle`: 50 cycle window

**Use Case:** The interface is stuck and you don't know why yet. Long windows catch the slow failure.

```python
preset="debug"
```

### Field Configuration

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/gaxi.py)
from CocoTBFramework.tbclasses.wavedrom_user.gaxi import get_gaxi_field_config

# Simple data-only
config = get_gaxi_field_config(data_width=32)

# With address
config = get_gaxi_field_config(data_width=32, addr_width=16)

# Multi-field (like APB)
config = get_gaxi_field_config(
    data_width=32,
    addr_width=16,
    ctrl_width=4,
    num_data_fields=2  # Creates data0, data1
)
```

---

## APB (AMBA Peripheral Bus) Protocol

**Register access with setup and access phases — two cycles minimum, wait states when the slave needs them.**

### Presets

#### `basic_rw`
**Constraints:** 2
- `apb_write_sequence`: PSEL→PWRITE=1→PENABLE→PREADY
- `apb_read_sequence`: PSEL→PWRITE=0→PENABLE→PREADY

**Use Case:** Prove reads and writes work before you care about anything fancier.

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/apb.py)
from CocoTBFramework.tbclasses.wavedrom_user.apb import APBWaveDromTemplate

apb_wave = APBWaveDromTemplate(
    dut=dut,
    signal_prefix="apb_",
    data_width=32,
    addr_width=32,
    preset="basic_rw"
)
```

#### `comprehensive`
**Constraints:** 8
- Write/read sequences
- Setup/access phases
- Write/read completion
- Complete transactions
- Error responses

**Use Case:** Full protocol visibility — phases, completions, and error responses in one run.

```python
preset="comprehensive"
```

#### `debug`
**Constraints:** 5
- PSEL activity detection
- PREADY activity detection
- PENABLE activity detection
- Write data changes
- Read data capture

**Use Case:** "Is anything even toggling?" troubleshooting. Start here when the bench is quiet.

```python
preset="debug"
```

#### `timing`
**Constraints:** 6
- Write/read transactions
- Setup/access phases
- Wait state sequences
- Complete transactions

**Use Case:** Wait state behavior and phase timing — the preset you want when the slave's PREADY is the suspect.

```python
preset="timing"
```

#### `error`
**Constraints:** 4
- Write/read transactions (optional)
- Error transaction (PSLVERR)
- Wait state sequences

**Use Case:** Verifying PSLVERR handling actually fires when it should.

```python
preset="error"
```

### Field Configuration

APB uses a utility function:

```python
from CocoTBFramework.components.wavedrom.utility import get_apb_field_config

config = get_apb_field_config(
    data_width=32,
    addr_width=32,
    strb_width=4,
    use_signal_names=True  # Use signal names vs descriptions
)
```

---

## AXI4 (Full) Protocol

**Five channels, bursts, ID-based reordering — the constraints track each channel's handshake plus WLAST/RLAST.**

### Presets

#### `write_basic`
**Constraints:** 3 (AW + W + B channels)
- `aw_handshake`: Write address channel
- `w_handshake`: Write data channel (with WLAST)
- `b_handshake`: Write response channel

**Use Case:** The write path end to end — address, data, response.

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/axi4.py)
from CocoTBFramework.tbclasses.wavedrom_user.axi4 import setup_axi4_constraints_with_boundaries

setup_axi4_constraints_with_boundaries(
    wave_solver=wave_solver,
    preset_name="write_basic",
    signal_prefix="m_axi_",
    id_width=4,
    data_width=64
)
```

#### `read_basic`
**Constraints:** 2 (AR + R channels)
- `ar_handshake`: Read address channel
- `r_handshake`: Read data channel (with RLAST)

**Use Case:** The read path — address out, data back with RLAST.

```python
preset_name="read_basic"
```

#### `comprehensive`
**Constraints:** 5 (all channels)
- All write_basic constraints
- All read_basic constraints

**Use Case:** All five channels in one run. Expect a lot of output; that's the point.

```python
preset_name="comprehensive"
```

#### `debug`
**Constraints:** 5 (all with 100 cycle windows)
- Extended windows for all channels

**Use Case:** Hung transactions — the long windows catch the handshake that never completes.

```python
preset_name="debug"
```

### Field Configuration

AXI4 has its own field config helper, one config per channel:

```python
from CocoTBFramework.components.axi4.axi4_field_configs import get_axi4_field_configs

field_configs = get_axi4_field_configs(
    id_width=8,
    addr_width=32,
    data_width=64,
    user_width=0,  # 0 to disable user signals
    channels=['AW', 'W', 'B', 'AR', 'R']
)

aw_config = field_configs['AW']
w_config = field_configs['W']
# etc.
```

### Manual Setup (No Template Class Yet)

AXI4 doesn't have a template wrapper, so you wire the solver yourself. One sharp edge to know about: auto-binding currently only supports the read channels (`axi4_read`), so write-channel signals get bound by hand:

```python
from CocoTBFramework.components.wavedrom.constraint_solver import TemporalConstraintSolver
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/axi4.py)
from CocoTBFramework.tbclasses.wavedrom_user.axi4 import setup_axi4_constraints_with_boundaries

wave_solver = TemporalConstraintSolver(dut=dut, log=dut._log)
wave_solver.add_clock_group('default', dut.axi_aclk)

# Auto-bind the read channels (AR + R). Note: 'axi4_read' is currently the
# only AXI4 protocol type supported by auto_bind_signals(); bind write-channel
# signals manually with add_signal_binding() or add_interface().
wave_solver.auto_bind_signals('axi4_read', signal_prefix='m_axi_',
                              field_config=field_configs['AR'])

# Setup constraints
setup_axi4_constraints_with_boundaries(
    wave_solver=wave_solver,
    preset_name="comprehensive",
    signal_prefix="m_axi_",
    id_width=4,
    data_width=64
)
```

---

## AXI4-Lite Protocol

**AXI4 with the interesting parts removed: no bursts, no IDs, one outstanding transaction.**

### Presets

Same as AXI4: `write_basic`, `read_basic`, `comprehensive`, `debug`

**Key Differences from AXI4:**
- No ID signals
- No burst support (LEN, SIZE, BURST removed)
- No LOCK, CACHE, QOS, REGION
- Only PROT remains
- Simpler field configuration

### Field Configuration

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/axil4.py)
from CocoTBFramework.tbclasses.wavedrom_user.axil4 import get_axil4_channel_field_config

aw_config = get_axil4_channel_field_config('AW', addr_width=32, data_width=32)
w_config = get_axil4_channel_field_config('W', addr_width=32, data_width=32)
b_config = get_axil4_channel_field_config('B', addr_width=32, data_width=32)
ar_config = get_axil4_channel_field_config('AR', addr_width=32, data_width=32)
r_config = get_axil4_channel_field_config('R', addr_width=32, data_width=32)
```

### Setup Function

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/axil4.py)
from CocoTBFramework.tbclasses.wavedrom_user.axil4 import setup_axil4_constraints_with_boundaries

setup_axil4_constraints_with_boundaries(
    wave_solver=wave_solver,
    preset_name="comprehensive",
    signal_prefix="m_axil_",
    addr_width=32,
    data_width=32
)
```

---

## AXI-Stream (AXIS) Protocol

**Data streaming with optional packet boundaries — TLAST is where one packet ends and the next begins.**

### Presets

#### `basic_handshake`
**Constraints:** 1
- `handshake`: TVALID→TREADY sequences

**Use Case:** Confirm the stream is flowing at all.

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/axis.py)
from CocoTBFramework.tbclasses.wavedrom_user.axis import setup_axis_constraints_with_boundaries

setup_axis_constraints_with_boundaries(
    wave_solver=wave_solver,
    preset_name="basic_handshake",
    signal_prefix="axis_",
    data_width=64,
    include_tlast=True
)
```

#### `comprehensive`
**Constraints:** 5
- `handshake`: TVALID→TREADY
- `packet`: TVALID=1, TREADY=1, TLAST=1
- `back2back`: Continuous transfers
- `stall`: Backpressure
- `idle`: Both low

**Use Case:** Stream behavior including packet boundaries — the preset that shows you TLAST placement, not just data movement.

```python
preset_name="comprehensive"
```

#### `performance`
**Constraints:** 3
- `handshake`: TVALID→TREADY
- `back2back`: Continuous transfers
- `stall`: Extended window (100 cycles)

**Use Case:** Throughput work — where the stream stalls and for how long.

```python
preset_name="performance"
```

#### `debug`
**Constraints:** 3 (all extended windows)
- `handshake`: 100 cycles
- `stall`: 200 cycles
- `idle`: 50 cycles

**Use Case:** A stream that's backed up or dead, cause unknown.

```python
preset_name="debug"
```

### Field Configuration

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/axis.py)
from CocoTBFramework.tbclasses.wavedrom_user.axis import get_axis_field_config

# Simple stream
config = get_axis_field_config(
    data_width=64,
    include_tlast=True,
    include_tkeep=True
)

# Full stream with routing
config = get_axis_field_config(
    data_width=128,
    id_width=4,      # TID for stream routing
    dest_width=4,    # TDEST for destination
    user_width=8,    # TUSER sideband
    include_tkeep=True,
    include_tlast=True
)
```

---

## Comparison Table

| Feature | GAXI | APB | AXI4 | AXIL4 | AXIS |
|---------|------|-----|------|-------|------|
| **Channels** | 1 | 1 | 5 | 5 | 1 |
| **Handshake** | valid/ready | psel/penable/pready | valid/ready per channel | valid/ready per channel | tvalid/tready |
| **Addressing** | Optional | Yes | Yes | Yes | No (stream) |
| **Bursts** | No | No | Yes | No | Implicit |
| **Out-of-Order** | No | No | Yes (ID-based) | No | Optional (TID) |
| **Packet Boundary** | No | No | WLAST/RLAST | No | TLAST |
| **Complexity** | Simple | Moderate | High | Moderate | Low |
| **Template Class** | Yes | Yes | No | No | No |

---

## Creating Custom Presets

A preset is just a dictionary of constraints — the factory functions do the tedious part. Building your own mix is unglamorous but easy:

### Example: Custom GAXI Preset

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/gaxi.py)
from CocoTBFramework.tbclasses.wavedrom_user.gaxi import (
    create_gaxi_handshake_constraint,
    create_gaxi_stall_constraint
)

# Create custom constraints
my_constraints = {
    'fast_handshake': create_gaxi_handshake_constraint(
        signal_prefix="cmd_",
        max_window=10,  # Expect fast response
        field_config=field_config
    ),
    'long_stall': create_gaxi_stall_constraint(
        signal_prefix="cmd_",
        max_window=500,  # Detect long stalls
        field_config=field_config
    )
}

# Add to solver
for name, constraint in my_constraints.items():
    wave_solver.add_constraint(constraint)
```

---

## Next Steps

- **Try it out**: [Quick Start Guide](wavedrom_quick_start.md)
- **Full example**: Wavedrom GAXI Example *(see TestTutorial)*
- **Troubleshooting**: Wavedrom Troubleshooting *(documentation planned)*
- **Auto-binding**: [Auto-Binding Guide](wavedrom_auto_binding.md)
