# AXIL4 Interface Classes

AXIL4 (AXI4-Lite) master and slave interface classes that compose GAXI channel components to implement complete AXI4-Lite read and write functionality with integrated compliance checking. Specification-compliant with no user signal support and single-transfer-only operation.

## Overview

The AXIL4 interface module provides four high-level classes:

- **AXIL4MasterRead** -- Drives read address (AR) requests and receives read data (R) responses
- **AXIL4MasterWrite** -- Drives write address (AW) requests, write data (W), and receives write responses (B)
- **AXIL4SlaveRead** -- Receives read address (AR) requests and generates read data (R) responses
- **AXIL4SlaveWrite** -- Receives write address (AW) and write data (W), generates write responses (B)

Key differences from AXI4 interfaces:
- **No burst support** -- always single transfer operations
- **No ID fields** -- simplified transaction tracking
- **No user signals** -- AXIL4 specification compliant
- **Register-oriented design** -- optimized for embedded register access
- **API consistency** -- identical method names to AXI4 for protocol-agnostic test code

---

## Classes

### AXIL4MasterRead

```python
class AXIL4MasterRead:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

Manages single-transfer read transactions for register access. Provides identical API to `AXI4MasterRead` for protocol-agnostic test development.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for AXIL4 bus signals (e.g., `"s_axil_"`) | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `False` |
| `timeout_cycles` | `int` | Timeout for waiting on R response | `1000` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `ar_channel` | `GAXIMaster` | AR channel master component (drives address requests) |
| `r_channel` | `GAXISlave` | R channel slave component (receives read data) |
| `compliance_checker` | `AXIL4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

#### Core Methods

##### `async read_transaction(address, **transaction_kwargs) -> int`

Execute a single-transfer read transaction: send AR request and wait for R response.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `address` | `int` | Read address (must be word-aligned) | (required) |
| `prot` | `int` | Protection type | `0` |

**Returns:** `int` -- The data value from the R response.

**Raises:** `TimeoutError` if R response does not arrive within `timeout_cycles`. `RuntimeError` if an error response (SLVERR/DECERR) is received.

##### `async simple_read(address, **kwargs) -> int`

Original AXIL4 read method. Kept for backward compatibility.

**Returns:** `int` -- The data value.

##### `async single_read(address, **kwargs) -> int`

API consistency method matching `AXI4MasterRead.single_read()`.

**Returns:** `int` -- The data value.

##### `async read_register(address, **kwargs) -> int`

Semantic alias for register access operations.

**Returns:** `int` -- The register value.

##### `create_ar_packet(**kwargs) -> AXIL4Packet`

Create an AR packet with the current field configuration.

**Returns:** `AXIL4Packet` configured for the AR channel.

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Get the compliance report if compliance checking is enabled.

##### `print_compliance_report()`

Print the compliance report to the log if compliance checking is enabled.

---

### AXIL4MasterWrite

```python
class AXIL4MasterWrite:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

Manages single-transfer write transactions for register access. Provides identical API to `AXI4MasterWrite` for protocol-agnostic test development.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for AXIL4 bus signals | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `False` |
| `timeout_cycles` | `int` | Timeout for waiting on B response | `1000` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `aw_channel` | `GAXIMaster` | AW channel master component (drives write address) |
| `w_channel` | `GAXIMaster` | W channel master component (drives write data) |
| `b_channel` | `GAXISlave` | B channel slave component (receives write response) |
| `compliance_checker` | `AXIL4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

#### Core Methods

##### `async write_transaction(address, data, strb=None, **transaction_kwargs) -> int`

Execute a single-transfer write transaction: send AW address and W data, wait for B response.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `address` | `int` | Write address (must be word-aligned) | (required) |
| `data` | `int` | Write data value | (required) |
| `strb` | `int` or `None` | Write strobe / byte enables (`None` = all bytes) | `None` |
| `prot` | `int` | Protection type | `0` |

**Returns:** `int` -- The response code from the B channel (0 = OKAY).

**Raises:** `TimeoutError` if B response does not arrive. `RuntimeError` if an error response is received.

##### `async simple_write(address, data, strb=None, **kwargs) -> int`

Original AXIL4 write method. Kept for backward compatibility.

##### `async single_write(address, data, strb=None, **kwargs) -> int`

API consistency method matching `AXI4MasterWrite.single_write()`.

##### `async write_register(address, data, strb=None, **kwargs) -> int`

Semantic alias for register access operations.

##### `create_aw_packet(**kwargs) -> AXIL4Packet`

Create an AW packet with the current field configuration.

##### `create_w_packet(**kwargs) -> AXIL4Packet`

Create a W packet with the current field configuration.

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Get the compliance report if compliance checking is enabled.

##### `print_compliance_report()`

Print the compliance report to the log if compliance checking is enabled.

---

### AXIL4SlaveRead

```python
class AXIL4SlaveRead:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

Responds to read requests by receiving AR channel addresses and generating R channel data responses. Uses a callback from the AR slave to trigger response generation.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for AXIL4 bus signals | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `False` |
| `memory_model` | `MemoryModel` or `None` | Memory model for data generation | `None` |
| `response_delay` | `int` | Delay cycles before sending R response | `1` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `ar_channel` | `GAXISlave` | AR channel slave component (receives address requests) |
| `r_channel` | `GAXIMaster` | R channel master component (drives read data responses) |
| `compliance_checker` | `AXIL4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

When no memory model is provided, the slave returns a default data pattern of `(address & 0xFFFFFFFF) ^ 0xDEADBEEF`. When a memory model read fails, it returns `0xDEADDEAD` with a SLVERR response.

#### Core Methods

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Get the compliance report if compliance checking is enabled.

##### `print_compliance_report()`

Print the compliance report to the log if compliance checking is enabled.

Note: The slave automatically generates R responses via an internal callback when AR requests are received.

---

### AXIL4SlaveWrite

```python
class AXIL4SlaveWrite:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

Responds to write requests by receiving AW address and W data, then generating B channel responses. Both AW and W must be received before a B response is generated.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for AXIL4 bus signals | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `False` |
| `memory_model` | `MemoryModel` or `None` | Memory model for write storage | `None` |
| `response_delay` | `int` | Delay cycles before sending B response | `1` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `aw_channel` | `GAXISlave` | AW channel slave component (receives write address) |
| `w_channel` | `GAXISlave` | W channel slave component (receives write data) |
| `b_channel` | `GAXIMaster` | B channel master component (drives write responses) |
| `compliance_checker` | `AXIL4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

Write strobes are applied per-byte when writing to the memory model. If a memory write fails, the slave responds with SLVERR.

#### Core Methods

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Get the compliance report if compliance checking is enabled.

##### `print_compliance_report()`

Print the compliance report to the log if compliance checking is enabled.

Note: The slave automatically generates B responses via internal callbacks when both AW and W data have been received.

---

## Usage Examples

### Basic Register Read and Write

```python
import cocotb
from CocoTBFramework.components.axil4.axil4_interfaces import (
    AXIL4MasterRead, AXIL4MasterWrite
)

@cocotb.test()
async def test_register_access(dut):
    reader = AXIL4MasterRead(
        dut=dut,
        clock=dut.aclk,
        prefix="s_axil_",
        log=dut._log,
        data_width=32,
        addr_width=32
    )

    writer = AXIL4MasterWrite(
        dut=dut,
        clock=dut.aclk,
        prefix="s_axil_",
        log=dut._log,
        data_width=32,
        addr_width=32
    )

    # Write a register
    resp = await writer.write_register(0x0000, 0x12345678)
    assert resp == 0  # OKAY

    # Read back the register
    data = await reader.read_register(0x0000)
    assert data == 0x12345678
```

### Slave with Memory Model

```python
from CocoTBFramework.components.axil4.axil4_interfaces import (
    AXIL4SlaveRead, AXIL4SlaveWrite
)
from CocoTBFramework.components.shared.memory_model import MemoryModel

@cocotb.test()
async def test_axil4_slave(dut):
    memory = MemoryModel(num_lines=256, bytes_per_line=4, log=dut._log)

    slave_write = AXIL4SlaveWrite(
        dut=dut,
        clock=dut.aclk,
        prefix="m_axil_",
        log=dut._log,
        memory_model=memory,
        response_delay=2
    )

    slave_read = AXIL4SlaveRead(
        dut=dut,
        clock=dut.aclk,
        prefix="m_axil_",
        log=dut._log,
        memory_model=memory,
        response_delay=1
    )

    # Slaves auto-respond to master transactions via callbacks
    # Drive stimulus from master side and verify results...
```

### Protocol-Agnostic Test Code

```python
async def test_register_map(master_factory, dut, clock):
    """This test works identically for both AXI4 and AXIL4."""
    master = master_factory(dut, clock)

    # These method names are identical across both protocols
    data = await master['single_read'](0x1000)
    resp = await master['single_write'](0x2000, data)

    # Semantic aliases also work identically
    reg_val = await master['read_register'](0x3000)
    reg_resp = await master['write_register'](0x4000, reg_val)

    # Unified compliance reporting
    from CocoTBFramework.components.axil4.axil4_factories import (
        print_unified_compliance_reports
    )
    print_unified_compliance_reports(master)
```
