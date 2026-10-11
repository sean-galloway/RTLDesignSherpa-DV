# AXI3 Interface Classes

The four high-level AXI3 interface classes. Each composes GAXI channel components into a read or write path, and is implemented as a standalone protocol family — not a subclass of AXI4 — so the AXI3 deltas are enforced.

## Classes

### AXI3MasterRead

```python
class AXI3MasterRead:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

Drives AR requests and receives R responses.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `dut` | `SimHandleBase` | Device under test | (required) |
| `clock` | `SimHandleBase` | Clock signal | (required) |
| `prefix` | `str` | Signal prefix (e.g. `"m_axi_"`) | `""` |
| `log` | `logging.Logger` | Logger instance | `None` |
| `ifc_name` | `str` | Debug name suffix | `""` |
| `data_width` | `int` | Data bus width | `32` |
| `id_width` | `int` | ID width | `8` |
| `addr_width` | `int` | Address width | `32` |
| `user_width` | `int` | User signal width | `1` |
| `multi_sig` | `bool` | Individual signal mode | `True` |
| `timeout_cycles` | `int` | R response timeout | `5000` |

**Core Methods:**

- `async read_transaction(address, burst_len=1, **transaction_kwargs) -> List[int]`
- `async single_read(address, **kwargs) -> int`

`burst_len` must be 1-16. Accepted `transaction_kwargs` include `id`, `size`, `burst_type`, `lock`, `cache`, `prot`, and `user`.

### AXI3MasterWrite

```python
class AXI3MasterWrite:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

Drives AW and W requests and receives B responses. The master sets `WID = AWID` on every beat and does not interleave write data.

**Core Methods:**

- `async write_transaction(address, data, burst_len=None, **transaction_kwargs) -> Dict[str, Any]`
- `async single_write(address, data, **kwargs) -> Dict[str, Any]`

`data` may be an `int` or `List[int]`. `burst_len` must be 1-16.

### AXI3SlaveRead

```python
class AXI3SlaveRead:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

Receives AR requests and generates R responses. Supports in-order and out-of-order modes via `enable_ooo`.

### AXI3SlaveWrite

```python
class AXI3SlaveWrite:
    def __init__(self, dut, clock, prefix="", log=None, ifc_name="", **kwargs)
```

Receives AW and W requests and generates B responses. W beats are demuxed by `WID`, so interleaved write data is accepted.

## Example

```python
import cocotb
from CocoTBFramework.components.axi3 import create_axi3_master_wr

@cocotb.test()
async def test_axi3_write(dut):
    master = create_axi3_master_wr(dut, dut.aclk, "m_axi_", log=dut._log)
    result = await master['interface'].single_write(0x1000, 0xDEADBEEF, id=1)
    assert result['success']
```
