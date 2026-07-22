# AXIL4 Interface Classes

AXIL4 (AXI4-Lite) master and slave interfaces, assembled from GAXI channel components into complete read and write paths, with compliance checking built in. They follow the Lite spec strictly: no user signals, one transfer per transaction.

## Overview

Four classes cover both ends of both directions:

- **AXIL4MasterRead** -- drives read address (AR) requests, receives read data (R) responses
- **AXIL4MasterWrite** -- drives write address (AW) and write data (W), receives write responses (B)
- **AXIL4SlaveRead** -- receives AR requests, answers on R
- **AXIL4SlaveWrite** -- receives AW and W, answers on B

How they differ from the full AXI4 interfaces:

- **No burst support** -- every transaction is a single beat
- **No ID fields** -- nothing to tag or reorder
- **No user signals** -- the Lite spec doesn't define them
- **Register-oriented design** -- shaped for control/status register access
- **API consistency** -- same method names as AXI4, so test code can be protocol-agnostic

---

## Classes

### AXIL4MasterRead

```python
class AXIL4MasterRead:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

Drives single-beat reads: one AR out, one R back. The API mirrors `AXI4MasterRead` method-for-method, so test code written against full AXI4 carries over unchanged.

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

Execute a complete read: send the AR request, wait for the R response, return the data.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `address` | `int` | Read address (must be word-aligned) | (required) |
| `prot` | `int` | Protection type | `0` |

**Returns:** `int` -- The data value from the R response.

**Raises:** `TimeoutError` if R response does not arrive within `timeout_cycles`. `RuntimeError` if an error response (SLVERR/DECERR) is received.

##### `async simple_read(address, **kwargs) -> int`

The original AXIL4 read method, kept for backward compatibility.

**Returns:** `int` -- The data value.

##### `async single_read(address, **kwargs) -> int`

Matches `AXI4MasterRead.single_read()` so protocol-agnostic tests call the same name on either interface.

**Returns:** `int` -- The data value.

##### `async read_register(address, **kwargs) -> int`

The same read under a name that says what you mean -- reading a register.

**Returns:** `int` -- The register value.

##### `create_ar_packet(**kwargs) -> AXIL4Packet`

Builds an AR packet from the current field configuration.

**Returns:** `AXIL4Packet` configured for the AR channel.

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Returns the compliance report if checking is enabled, otherwise `None`.

##### `print_compliance_report()`

Logs the compliance report if checking is enabled.

---

### AXIL4MasterWrite

```python
class AXIL4MasterWrite:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

Drives single-beat writes: AW and W out, B back. Mirrors `AXI4MasterWrite` the same way the read side mirrors `AXI4MasterRead`.

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

Execute a complete write: send the AW address and W data, wait for the B response.

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

The original AXIL4 write method, kept for backward compatibility.

##### `async single_write(address, data, strb=None, **kwargs) -> int`

Matches `AXI4MasterWrite.single_write()` for protocol-agnostic test code.

##### `async write_register(address, data, strb=None, **kwargs) -> int`

The same write under a register-oriented name.

##### `create_aw_packet(**kwargs) -> AXIL4Packet`

Builds an AW packet from the current field configuration.

##### `create_w_packet(**kwargs) -> AXIL4Packet`

Builds a W packet from the current field configuration.

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Returns the compliance report if checking is enabled, otherwise `None`.

##### `print_compliance_report()`

Logs the compliance report if checking is enabled.

---

### AXIL4SlaveRead

```python
class AXIL4SlaveRead:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

The responding end of a read: AR requests come in, R responses go out. A callback on the AR channel kicks off response generation, so once constructed the slave runs on its own.

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
| `base_addr` | `int` | Base address subtracted from incoming ARADDR before indexing the memory model | `0` |
| `response_delay` | `int` | Delay cycles before sending R response | `1` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `ar_channel` | `GAXISlave` | AR channel slave component (receives address requests) |
| `r_channel` | `GAXIMaster` | R channel master component (drives read data responses) |
| `compliance_checker` | `AXIL4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

With no memory model attached, the slave answers with a canned pattern -- `(address & 0xFFFFFFFF) ^ 0xDEADBEEF` -- which at least is easy to spot in a waveform. A failed memory-model read returns `0xDEADDEAD` with a SLVERR.

#### Core Methods

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Returns the compliance report if checking is enabled, otherwise `None`.

##### `print_compliance_report()`

Logs the compliance report if checking is enabled.

Note: there's nothing to call to make responses happen -- the internal AR callback generates them as requests arrive.

---

### AXIL4SlaveWrite

```python
class AXIL4SlaveWrite:
    def __init__(self, dut, clock, prefix="", log=None, **kwargs)
```

The responding end of a write: AW and W come in, B goes out. Both the address and the data have to arrive before the B response is generated -- the slave waits for both halves, as it should.

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
| `base_addr` | `int` | Base address subtracted from incoming AWADDR before indexing the memory model | `0` |
| `response_delay` | `int` | Delay cycles before sending B response | `1` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `aw_channel` | `GAXISlave` | AW channel slave component (receives write address) |
| `w_channel` | `GAXISlave` | W channel slave component (receives write data) |
| `b_channel` | `GAXIMaster` | B channel master component (drives write responses) |
| `compliance_checker` | `AXIL4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

Write strobes are applied per byte when updating the memory model. A failed memory write gets a SLVERR.

#### Core Methods

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Returns the compliance report if checking is enabled, otherwise `None`.

##### `print_compliance_report()`

Logs the compliance report if checking is enabled.

Note: B responses are automatic -- internal callbacks fire once both AW and W have been received.

---

## Usage Examples

### Basic Register Read and Write

The two masters are separate objects that share a prefix -- instantiate both and drive them:

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

Point both slave halves at one `MemoryModel` and writes become visible to subsequent reads:

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

### Convenience-Method Access via Factory Dictionaries

The AXIL4 factories return dictionaries that also expose the transaction methods as keys -- handy for protocol-agnostic test code:

```python
async def test_register_map(master_factory, dut, clock):
    """Works with AXIL4 factories (create_axil4_master / create_axil4_master_rd/wr),
    whose returned dictionaries expose the transaction methods as keys.
    Note: the AXI4 factories return only channel components and 'interface',
    so this dictionary-style method access is AXIL4-specific."""
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

---
