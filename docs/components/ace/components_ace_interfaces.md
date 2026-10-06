# AXI4-ACE Interface Classes

The four high-level ACE interface classes. Each one composes GAXI channel components into a complete front-side or snoop-side path — you talk in transactions, the channels handle the handshakes.

## Overview

The ACE interface module provides four classes:

- **AXI4ACEMasterRead** -- Drives coherent read address (AR) requests with `ARSNOOP` and receives read data (R) responses; auto-pulses RACK.
- **AXI4ACEMasterWrite** -- Drives coherent write address (AW) requests with `AWSNOOP`, write data (W), and receives write responses (B); auto-pulses WACK.
- **AXI4ACESnoopSlave** -- Receives snoop addresses (AC) and generates snoop responses (CR) and snoop data (CD).
- **AXI4ACESnoopMaster** -- Drives snoop addresses (AC) and receives snoop responses (CR) and snoop data (CD).

Every front-side class subclasses the corresponding AXI4 master class and inherits its transaction API (`single_read`, `read_transaction`, `single_write`, `write_transaction`). The snoop classes are new because AC/CR/CD have no AXI4 equivalent.

---

## Classes

### AXI4ACEMasterRead

```python
class AXI4ACEMasterRead(AXI4MasterRead):
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

The coherent read master: drives AR requests with `ARSNOOP` and collects R responses. RACK is auto-pulsed when the BFM is master and `{prefix}rack` exists on the DUT.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for ACE bus signals (e.g., `"m_axi_"`) | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Interface name for debug identification (e.g., `"rdeng"`) | `""` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `id_width` | `int` | Width of transaction ID field in bits | `8` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `user_width` | `int` | Width of user signal in bits | `1` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `True` |
| `timeout_cycles` | `int` | Timeout for waiting on R responses | `5000` |
| `auto_ack` | `bool` | Whether to start the RACK pulser when `{prefix}rack` exists | `True` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `ar_channel` | `GAXIMaster` | AR channel master component (drives address requests) |
| `r_channel` | `GAXISlave` | R channel slave component (receives read data) |
| `rack_sig` | `SimHandleBase` or `None` | Resolved `{prefix}rack` signal, if present |
| `compliance_checker` | `None` | Inherited AXI4 compliance-reporting API is present, but no AXI4 checker is instantiated for ACE interfaces |

#### Core Methods

##### `async read_transaction(address, burst_len=1, **transaction_kwargs) -> List[int]`

Execute a complete coherent read transaction: send the AR request and wait for all R data beats.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `address` | `int` | Read address | (required) |
| `burst_len` | `int` | Number of data beats to read (1-256) | `1` |
| `snoop_type` | `ACETransactionType` | Coherent transaction type for ARSNOOP | `ACETransactionType.READ_SHARED` |
| `id` | `int` | Transaction ID | `0` |
| `size` | `int` | Transfer size encoding (log2 of bytes per beat) | full-bus size |
| `burst_type` | `int` | Burst type (0=FIXED, 1=INCR, 2=WRAP) | `1` |
| `lock` | `int` | Lock type (0=Normal, 1=Exclusive) | `0` |
| `cache` | `int` | Cache hint | `0` |
| `prot` | `int` | Protection type | `0` |
| `qos` | `int` | Quality of service | `0` |
| `region` | `int` | Region identifier | `0` |
| `user` | `int` | User value, if USER is present | — |

**Returns:** `List[int]` -- List of data values, one per beat.

**Raises:** `TimeoutError` if R responses do not arrive within `timeout_cycles`. `RuntimeError` if an error response (SLVERR/DECERR) is received.

##### `async single_read(address, **kwargs) -> int`

Convenience method for a single-beat read.

**Returns:** `int` -- The data value from the single R response.

##### `create_ar_packet(**kwargs) -> ACEPacket`

Create an AR packet with the current ACE field configuration.

**Returns:** `ACEPacket` configured for the AR channel.

---

### AXI4ACEMasterWrite

```python
class AXI4ACEMasterWrite(AXI4MasterWrite):
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

The coherent write master: drives AW requests with `AWSNOOP`, W data, and collects B responses. WACK is auto-pulsed when the BFM is master and `{prefix}wack` exists on the DUT.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for ACE bus signals | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Interface name for debug identification | `""` |
| `data_width` | `int` | Width of data bus in bits | `32` |
| `id_width` | `int` | Width of transaction ID field in bits | `8` |
| `addr_width` | `int` | Width of address bus in bits | `32` |
| `user_width` | `int` | Width of user signal in bits | `1` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `True` |
| `timeout_cycles` | `int` | Timeout for waiting on B response | `5000` |
| `auto_ack` | `bool` | Whether to start the WACK pulser when `{prefix}wack` exists | `True` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `aw_channel` | `GAXIMaster` | AW channel master component (drives write address) |
| `w_channel` | `GAXIMaster` | W channel master component (drives write data) |
| `b_channel` | `GAXISlave` | B channel slave component (receives write response) |
| `wack_sig` | `SimHandleBase` or `None` | Resolved `{prefix}wack` signal, if present |
| `compliance_checker` | `None` | Inherited AXI4 compliance-reporting API is present, but no AXI4 checker is instantiated for ACE interfaces |

#### Core Methods

##### `async write_transaction(address, data, burst_len=None, **transaction_kwargs) -> Dict[str, Any]`

Execute a complete coherent write transaction: send the AW address, W data beats, and wait for the B response.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `address` | `int` | Write address | (required) |
| `data` | `int` or `List[int]` | Write data (single value or list for burst) | (required) |
| `burst_len` | `int` or `None` | Number of data beats (inferred from data list if `None`) | `None` |
| `snoop_type` | `ACETransactionType` | Coherent transaction type for AWSNOOP | `ACETransactionType.WRITE_UNIQUE` |
| `id` | `int` | Transaction ID | `0` |
| `size` | `int` | Transfer size encoding | full-bus size |
| `burst_type` | `int` | Burst type (0=FIXED, 1=INCR, 2=WRAP) | `1` |
| `strb` | `int` | Write strobe (byte enables) applied to every beat | per-beat default |
| `user` | `int` | User value, if USER is present | — |

**Returns:** `Dict[str, Any]` with keys:
- `success` (`bool`) -- Whether the transaction completed successfully
- `response` (`int` or `None`) -- Response code from B channel
- `id` (`int` or `None`) -- Response ID from B channel
- `error` (`str`, only on failure) -- Error message

Note: `write_transaction` does not raise on a missing B response; it returns `success=False` with the error message. An error B (SLVERR/DECERR) is a completed transaction: the dict carries `success=False`, `error=<message>` AND the actual `response` code. Always check `result['success']`.

##### `async single_write(address, data, **kwargs) -> Dict[str, Any]`

Convenience method for a single-beat write.

---

### AXI4ACESnoopSlave

```python
class AXI4ACESnoopSlave:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

The cache-side snoop responder: receives AC requests and answers with CD beats followed by a CR response. Supports a default MESI responder model and custom handler injection.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for ACE snoop signals (e.g., `"m_axi_"` or `"fub_"`) | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Interface name for debug identification | `""` |
| `data_width` | `int` | Width of CD data bus in bits | `32` |
| `addr_width` | `int` | Width of AC address bus in bits | `32` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `True` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `ac_channel` | `GAXISlave` | AC channel slave component (receives snoop addresses) |
| `cr_channel` | `GAXIMaster` | CR channel master component (drives snoop responses) |
| `cd_channel` | `GAXIMaster` | CD channel master component (drives snoop data) |
| `line_behaviors` | `Dict[int, CacheState]` | Per-address cache-line state map |
| `user_handler` | `Callable` or `None` | Optional custom handler installed via `set_handler` |

#### Core Methods

##### `set_line_behavior(addr: int, state: CacheState) -> None`

Set the expected cache-line state for `addr`. The default responder uses this state to choose the CRRESP and data.

```python
slave.set_line_behavior(0x1000, CacheState.MODIFIED)
```

##### `set_handler(handler: Callable[[int, SnoopType, CacheState], tuple]) -> None`

Install a custom snoop handler. The handler receives `(addr, snoop_type, state)` and must return `(crresp, data_or_None)`. `data_or_None` may be a single `int` for one beat or a `list[int]` for a multi-beat response.

```python
def handler(addr, snoop_type, state):
    if state == CacheState.MODIFIED and snoop_type == SnoopType.READ_SHARED:
        return CRRESP.from_bits(data_transfer=True, pass_dirty=True, is_shared=True), 0xDEADBEEF
    return CRRESP(0), None

slave.set_handler(handler)
```

If the returned `CRRESP` is invalid for the snoop type, the slave logs an error and continues when a logger is attached; without a logger it raises `RuntimeError`.

##### `_default_handler(addr, snoop_type, state) -> tuple`

The built-in MESI responder matrix. Returns `(CRRESP, data_or_None)`. See [components_ace_overview.md](components_ace_overview.md#default-mesi-responder-matrix) for the full table.

---

### AXI4ACESnoopMaster

```python
class AXI4ACESnoopMaster:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

The CCU-side snoop initiator: drives AC requests and gathers CR/CD responses in AC-issue order.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix for ACE snoop signals | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Interface name for debug identification | `""` |
| `data_width` | `int` | Width of CD data bus in bits | `32` |
| `addr_width` | `int` | Width of AC address bus in bits | `32` |
| `multi_sig` | `bool` | Whether to use individual signal mode | `True` |
| `timeout_cycles` | `int` | Timeout for waiting on CR/CD responses | `5000` |
| `allow_multiple_outstanding` | `bool` | Allow more than one snoop in flight at a time | `False` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `ac_channel` | `GAXIMaster` | AC channel master component (drives snoop addresses) |
| `cr_channel` | `GAXISlave` | CR channel slave component (receives snoop responses) |
| `cd_channel` | `GAXISlave` | CD channel slave component (receives snoop data) |

#### Core Methods

##### `async issue_snoop(addr: int, snoop_type: SnoopType) -> SnoopResult`

Issue one snoop and return its CR/CD result.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `addr` | `int` | Snoop address |
| `snoop_type` | `SnoopType` | Type of snoop to issue |

**Returns:** `SnoopResult` with attributes:
- `crresp` (`CRRESP`) -- The snoop response
- `data` (`List[int]`) -- Collected CD data beats
- `latency` (`int`) -- Reserved; currently `0`

**Raises:** `RuntimeError` if `allow_multiple_outstanding=False` and a snoop is already in flight. `TimeoutError` if CR or CD responses do not arrive within `timeout_cycles`.

---

## Factory Functions

The ACE package provides one-line constructors for common setups.

### `create_axi4ace_master_rd(dut, clock, prefix="", log=None, ifc_name="", **kwargs) -> Dict[str, Any]`

Create an ACE master read interface. Returns a dict with keys `"AR"`, `"R"`, and `"interface"`.

### `create_axi4ace_master_wr(dut, clock, prefix="", log=None, ifc_name="", **kwargs) -> Dict[str, Any]`

Create an ACE master write interface. Returns a dict with keys `"AW"`, `"W"`, `"B"`, and `"interface"`.

### `create_axi4ace_snoop_slave(dut, clock, prefix="", log=None, ifc_name="", **kwargs) -> Dict[str, Any]`

Create an ACE snoop slave (cache-side responder). Returns a dict with keys `"AC"`, `"CR"`, `"CD"`, and `"interface"`.

### `create_axi4ace_snoop_master(dut, clock, prefix="", log=None, ifc_name="", **kwargs) -> Dict[str, Any]`

Create an ACE snoop master (CCU-side initiator). Returns a dict with keys `"AC"`, `"CR"`, `"CD"`, and `"interface"`.

### `create_axi4ace_master_interface(dut, clock, prefix="", log=None, **kwargs) -> Tuple[AXI4ACEMasterWrite, AXI4ACEMasterRead]`

Create both ACE read and write master interfaces.

### `create_axi4ace_snoop_interface(dut, clock, prefix="", log=None, **kwargs) -> Tuple[AXI4ACESnoopMaster, AXI4ACESnoopSlave]`

Create both ACE snoop master and slave interfaces.

### `create_complete_axi4ace_testbench_components(dut, clock, master_prefix="m_axi_", slave_prefix="s_axi_", log=None, **kwargs) -> Dict[str, Any]`

Create a complete set of ACE components for a testbench by probing the DUT. Only components whose control signals are present are created:

- `master_read` if `{master_prefix}arvalid` exists
- `master_write` if `{master_prefix}awvalid` exists
- `snoop_slave` if `{slave_prefix}acvalid` exists
- `slave_read` if `{slave_prefix}arready` exists
- `slave_write` if `{slave_prefix}awready` exists

---

## Usage Examples

### Coherent Read with Snoop Type

```python
from CocoTBFramework.components.ace.ace_interfaces import AXI4ACEMasterRead
from CocoTBFramework.components.ace.ace_transaction import ACETransactionType

@cocotb.test()
async def test_ace_read(dut):
    master_read = AXI4ACEMasterRead(
        dut=dut,
        clock=dut.aclk,
        prefix="m_axi_",
        log=dut._log,
        data_width=64,
        id_width=4,
        addr_width=32,
    )

    data = await master_read.read_transaction(
        address=0x1000,
        burst_len=1,
        snoop_type=ACETransactionType.READ_SHARED,
        id=1,
    )
    assert data[0] == expected_value
```

### Coherent Write with Snoop Type

```python
from CocoTBFramework.components.ace.ace_interfaces import AXI4ACEMasterWrite
from CocoTBFramework.components.ace.ace_transaction import ACETransactionType

@cocotb.test()
async def test_ace_write(dut):
    master_write = AXI4ACEMasterWrite(
        dut=dut,
        clock=dut.aclk,
        prefix="m_axi_",
        log=dut._log,
        data_width=64,
        id_width=4,
    )

    result = await master_write.write_transaction(
        address=0x1000,
        data=[0xDEADBEEF, 0xCAFEBABE],
        snoop_type=ACETransactionType.WRITE_UNIQUE,
        id=1,
    )
    assert result['success']
```

### Snoop Slave with Custom Handler

```python
from CocoTBFramework.components.ace.ace_interfaces import AXI4ACESnoopSlave
from CocoTBFramework.components.ace.ace_transaction import (
    CRRESP, CacheState, SnoopType,
)

@cocotb.test()
async def test_snoop_slave(dut):
    slave = AXI4ACESnoopSlave(
        dut=dut,
        clock=dut.aclk,
        prefix="fub_",
        log=dut._log,
        data_width=32,
        addr_width=32,
    )

    slave.set_line_behavior(0x2000, CacheState.EXCLUSIVE)

    # The slave automatically responds to AC requests via callbacks.
    # Run test stimulus and check results...
```

### Snoop Master Issuing a Snoop

```python
from CocoTBFramework.components.ace.ace_interfaces import AXI4ACESnoopMaster
from CocoTBFramework.components.ace.ace_transaction import SnoopType

@cocotb.test()
async def test_snoop_master(dut):
    master = AXI4ACESnoopMaster(
        dut=dut,
        clock=dut.aclk,
        prefix="m_axi_",
        log=dut._log,
        data_width=32,
        addr_width=32,
    )

    result = await master.issue_snoop(0x1000, SnoopType.READ_SHARED)
    print(f"CRRESP: {result.crresp}")
    print(f"Data: {result.data}")
```
