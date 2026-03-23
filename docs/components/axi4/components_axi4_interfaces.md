# AXI4 Interface Classes

AXI4 master and slave interface classes that compose GAXI channel components to implement complete AXI4 read and write functionality with integrated compliance checking.

## Overview

The AXI4 interface module provides four high-level classes:

- **AXI4MasterRead** -- Drives read address (AR) requests and receives read data (R) responses
- **AXI4MasterWrite** -- Drives write address (AW) requests, write data (W), and receives write responses (B)
- **AXI4SlaveRead** -- Receives read address (AR) requests and generates read data (R) responses
- **AXI4SlaveWrite** -- Receives write address (AW) and write data (W), generates write responses (B)

Each class composes underlying `GAXIMaster` and `GAXISlave` channel components, providing transaction-level APIs while maintaining full AXI4 protocol compliance. Compliance checking is automatically integrated when the `AXI4_COMPLIANCE_CHECK=1` environment variable is set.

---

## Classes

### AXI4MasterRead

```python
class AXI4MasterRead:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

Manages read transactions by driving AR channel requests and collecting R channel responses.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for AXI4 bus signals (e.g., `"m_axi_"`) | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Interface name for debug identification (e.g., `"rdeng"`) | `""` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `id_width` | `int` | Width of transaction ID field in bits | `8` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `user_width` | `int` | Width of user signal in bits | `1` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `True` |
| `timeout_cycles` | `int` | Timeout for waiting on R responses | `5000` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `ar_channel` | `GAXIMaster` | AR channel master component (drives address requests) |
| `r_channel` | `GAXISlave` | R channel slave component (receives read data) |
| `compliance_checker` | `AXI4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

#### Core Methods

##### `async read_transaction(address, burst_len=1, **transaction_kwargs) -> List[int]`

Execute a complete read transaction: send AR request and wait for all R data beats.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `address` | `int` | Read address | (required) |
| `burst_len` | `int` | Number of data beats to read (1-256) | `1` |
| `id` | `int` | Transaction ID | `0` |
| `size` | `int` | Transfer size encoding (log2 of bytes per beat) | `2` |
| `burst_type` | `int` | Burst type (0=FIXED, 1=INCR, 2=WRAP) | `1` |
| `lock` | `int` | Lock type (0=Normal, 1=Exclusive) | `0` |
| `cache` | `int` | Cache hint | `0` |
| `prot` | `int` | Protection type | `0` |
| `qos` | `int` | Quality of service | `0` |
| `region` | `int` | Region identifier | `0` |

**Returns:** `List[int]` -- List of data values, one per beat.

**Raises:** `TimeoutError` if R responses do not arrive within `timeout_cycles`. `RuntimeError` if an error response (SLVERR/DECERR) is received.

##### `async single_read(address, **kwargs) -> int`

Convenience method for a single-beat read.

**Returns:** `int` -- The data value from the single R response.

##### `create_ar_packet(**kwargs) -> AXI4Packet`

Create an AR packet with the current field configuration.

**Returns:** `AXI4Packet` configured for the AR channel.

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Get the compliance report if compliance checking is enabled.

**Returns:** Compliance report dictionary, or `None` if disabled.

##### `print_compliance_report()`

Print the compliance report to the log if compliance checking is enabled.

---

### AXI4MasterWrite

```python
class AXI4MasterWrite:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

Manages write transactions by driving AW and W channels and collecting B channel responses.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for AXI4 bus signals | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Interface name for debug identification | `""` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `id_width` | `int` | Width of transaction ID field in bits | `8` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `user_width` | `int` | Width of user signal in bits | `1` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `True` |
| `timeout_cycles` | `int` | Timeout for waiting on B response | `5000` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `aw_channel` | `GAXIMaster` | AW channel master component (drives write address) |
| `w_channel` | `GAXIMaster` | W channel master component (drives write data) |
| `b_channel` | `GAXISlave` | B channel slave component (receives write response) |
| `compliance_checker` | `AXI4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

#### Core Methods

##### `async write_transaction(address, data, burst_len=None, **transaction_kwargs) -> Dict[str, Any]`

Execute a complete write transaction: send AW address, W data beats, and wait for B response.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `address` | `int` | Write address | (required) |
| `data` | `int` or `List[int]` | Write data (single value or list for burst) | (required) |
| `burst_len` | `int` or `None` | Number of data beats (inferred from data list if `None`) | `None` |
| `id` | `int` | Transaction ID | `0` |
| `size` | `int` | Transfer size encoding | `2` |
| `burst_type` | `int` | Burst type (0=FIXED, 1=INCR, 2=WRAP) | `1` |
| `strb` | `int` | Write strobe (byte enables) | all bytes enabled |

**Returns:** `Dict[str, Any]` with keys:
- `success` (`bool`) -- Whether the transaction completed successfully
- `response` (`int` or `None`) -- Response code from B channel
- `id` (`int` or `None`) -- Response ID from B channel
- `error` (`str`, only on failure) -- Error message

**Raises:** `TimeoutError` if B response does not arrive. `RuntimeError` if an error response is received.

##### `async single_write(address, data, **kwargs) -> Dict[str, Any]`

Convenience method for a single-beat write.

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Get the compliance report if compliance checking is enabled.

##### `print_compliance_report()`

Print the compliance report to the log if compliance checking is enabled.

---

### AXI4SlaveRead

```python
class AXI4SlaveRead:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

Responds to read requests by receiving AR channel addresses and generating R channel data responses. Supports both in-order and out-of-order (OOO) response modes.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for AXI4 bus signals | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Interface name for debug identification | `""` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `id_width` | `int` | Width of transaction ID field in bits | `8` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `user_width` | `int` | Width of user signal in bits | `1` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `True` |
| `memory_model` | `MemoryModel` or `None` | Memory model for data generation | `None` |
| `base_addr` | `int` | Base address offset for memory-mapped slaves | `0` |
| `response_delay` | `int` | Delay cycles before sending R response | `1` |
| `enable_ooo` | `bool` | Enable out-of-order response mode | `False` |
| `ooo_config` | `dict` | OOO configuration (see below) | (defaults) |

**OOO Configuration Dictionary:**

| Key | Type | Description | Default |
|-----|------|-------------|---------|
| `mode` | `str` | `"random"` or `"deterministic"` | `"random"` |
| `reorder_probability` | `float` | Probability to delay a transaction (0.0-1.0) | `0.3` |
| `min_delay_cycles` | `int` | Minimum delay before response | `1` |
| `max_delay_cycles` | `int` | Maximum delay before response | `50` |
| `pattern` | `list` or `None` | Sequence order for deterministic mode | `None` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `ar_channel` | `GAXISlave` | AR channel slave component (receives address requests) |
| `r_channel` | `GAXIMaster` | R channel master component (drives read data responses) |
| `compliance_checker` | `AXI4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

#### Core Methods

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Get the compliance report if compliance checking is enabled.

##### `print_compliance_report()`

Print the compliance report to the log if compliance checking is enabled.

Note: The slave automatically generates R responses via an internal callback when AR requests are received. No explicit send method is needed.

---

### AXI4SlaveWrite

```python
class AXI4SlaveWrite:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

Responds to write requests by receiving AW address and W data, then generating B channel responses. Properly handles the AXI4 specification requirement that W data can arrive before AW address.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for AXI4 bus signals | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Interface name for debug identification | `""` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `id_width` | `int` | Width of transaction ID field in bits | `8` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `user_width` | `int` | Width of user signal in bits | `1` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `True` |
| `memory_model` | `MemoryModel` or `None` | Memory model for write storage | `None` |
| `base_addr` | `int` | Base address offset for memory-mapped slaves | `0` |
| `response_delay` | `int` | Delay cycles before sending B response | `1` |
| `enable_ooo` | `bool` | Enable out-of-order response mode | `False` |
| `ooo_config` | `dict` | OOO configuration (same as AXI4SlaveRead) | (defaults) |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `aw_channel` | `GAXISlave` | AW channel slave component (receives write address) |
| `w_channel` | `GAXISlave` | W channel slave component (receives write data) |
| `b_channel` | `GAXIMaster` | B channel master component (drives write responses) |
| `compliance_checker` | `AXI4ComplianceChecker` or `None` | Compliance checker (enabled via environment) |

#### Core Methods

##### `get_compliance_report() -> Optional[Dict[str, Any]]`

Get the compliance report if compliance checking is enabled.

##### `print_compliance_report()`

Print the compliance report to the log if compliance checking is enabled.

Note: The slave automatically generates B responses via internal callbacks when both AW and W data have been received. W-before-AW buffering is handled transparently.

---

## Usage Examples

### Basic Read Transaction

```python
import cocotb
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4MasterRead

@cocotb.test()
async def test_axi4_read(dut):
    master_read = AXI4MasterRead(
        dut=dut,
        clock=dut.aclk,
        prefix="m_axi_",
        log=dut._log,
        data_width=32,
        id_width=4,
        addr_width=32
    )

    # Single-beat read
    data = await master_read.single_read(0x1000, id=1)
    assert data == expected_value

    # Burst read (4 beats)
    data_list = await master_read.read_transaction(
        address=0x2000,
        burst_len=4,
        id=2,
        size=2,
        burst_type=1  # INCR
    )
    for i, d in enumerate(data_list):
        print(f"Beat {i}: 0x{d:08X}")
```

### Basic Write Transaction

```python
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4MasterWrite

@cocotb.test()
async def test_axi4_write(dut):
    master_write = AXI4MasterWrite(
        dut=dut,
        clock=dut.aclk,
        prefix="m_axi_",
        log=dut._log,
        data_width=32,
        id_width=4
    )

    # Single-beat write
    result = await master_write.single_write(0x1000, 0xDEADBEEF, id=1)
    assert result['success']

    # Burst write (3 beats)
    result = await master_write.write_transaction(
        address=0x2000,
        data=[0x11111111, 0x22222222, 0x33333333],
        id=2,
        size=2,
        burst_type=1
    )
    assert result['success']
```

### Slave with Memory Model and OOO Responses

```python
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4SlaveRead
from CocoTBFramework.components.shared.memory_model import MemoryModel

@cocotb.test()
async def test_axi4_slave_ooo(dut):
    memory = MemoryModel(num_lines=4096, bytes_per_line=4, log=dut._log)

    slave_read = AXI4SlaveRead(
        dut=dut,
        clock=dut.aclk,
        prefix="s_axi_",
        log=dut._log,
        memory_model=memory,
        enable_ooo=True,
        ooo_config={
            'mode': 'random',
            'reorder_probability': 0.5,
            'min_delay_cycles': 2,
            'max_delay_cycles': 30
        }
    )

    # Slave automatically responds to AR requests via callbacks
    # Run test stimulus and check results...
```
