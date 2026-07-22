# AXIL4 Packet

The transaction object for AXIL4 (AXI4-Lite): a `Packet` subclass with channel detection, Lite-specific protocol validation, and factory methods for each of the five channels. Built for register-style single-beat traffic -- no burst fields, no IDs.

## Overview

`AXIL4Packet` gives you:

- **Factory methods** for creating packets on each AXIL4 channel (AW, W, B, AR, R)
- **Channel type detection** based on which fields are present
- **Protocol validation** against AXIL4 rules -- address alignment, response codes, strobe patterns
- **Channel classification helpers** (`is_address_channel`, `is_data_channel`, `is_response_channel`)
- **Response decoding** for response-channel packets
- **Generic field names** (`addr`, `data`, `resp`, `prot`, `strb`), with `pkt_prefix` handling the mapping to real signal names

Compared to `AXI4Packet`:

- No ID fields on any channel
- None of the burst baggage (len, size, burst, lock, cache, qos, region)
- Always single-transfer
- Word-alignment validation on addresses
- Field sets trimmed for register access

---

## Class

### AXIL4Packet

```python
class AXIL4Packet(Packet):
    def __init__(self, field_config, **kwargs)
```

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `field_config` | `FieldConfig` | Field configuration object for the specific AXIL4 channel | (required) |
| `**kwargs` | `Any` | Initial field values using generic names (`addr`, `data`, `resp`, etc.) | -- |

---

## Factory Methods

### `AXIL4Packet.create_aw_packet(addr_width=32, user_width=0, **field_values) -> AXIL4Packet`

Builds a Write Address (AW) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `addr_width` | `int` | Width of address field in bits | `32` |
| `user_width` | `int` | Ignored (AXIL4 has no user signals; kept for API compatibility) | `0` |
| `**field_values` | `Any` | AW field values: `addr`, `prot` | -- |

**Returns:** `AXIL4Packet` configured for the AW channel.

```python
packet = AXIL4Packet.create_aw_packet(addr=0x1000, prot=0)
```

### `AXIL4Packet.create_w_packet(data_width=32, user_width=0, **field_values) -> AXIL4Packet`

Builds a Write Data (W) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `data_width` | `int` | Width of data field in bits | `32` |
| `user_width` | `int` | Ignored (AXIL4 has no user signals; kept for API compatibility) | `0` |
| `**field_values` | `Any` | W field values: `data`, `strb` | -- |

**Returns:** `AXIL4Packet` configured for the W channel.

```python
packet = AXIL4Packet.create_w_packet(data=0x12345678, strb=0xF)
```

### `AXIL4Packet.create_b_packet(user_width=0, **field_values) -> AXIL4Packet`

Builds a Write Response (B) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `user_width` | `int` | Ignored (AXIL4 has no user signals; kept for API compatibility) | `0` |
| `**field_values` | `Any` | B field values: `resp` | -- |

**Returns:** `AXIL4Packet` configured for the B channel.

```python
packet = AXIL4Packet.create_b_packet(resp=0)  # OKAY response
```

### `AXIL4Packet.create_ar_packet(addr_width=32, user_width=0, **field_values) -> AXIL4Packet`

Builds a Read Address (AR) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `addr_width` | `int` | Width of address field in bits | `32` |
| `user_width` | `int` | Ignored (AXIL4 has no user signals; kept for API compatibility) | `0` |
| `**field_values` | `Any` | AR field values: `addr`, `prot` | -- |

**Returns:** `AXIL4Packet` configured for the AR channel.

```python
packet = AXIL4Packet.create_ar_packet(addr=0x2000, prot=0)
```

### `AXIL4Packet.create_r_packet(data_width=32, user_width=0, **field_values) -> AXIL4Packet`

Builds a Read Data (R) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `data_width` | `int` | Width of data field in bits | `32` |
| `user_width` | `int` | Ignored (AXIL4 has no user signals; kept for API compatibility) | `0` |
| `**field_values` | `Any` | R field values: `data`, `resp` | -- |

**Returns:** `AXIL4Packet` configured for the R channel.

```python
packet = AXIL4Packet.create_r_packet(data=0xABCDEF00, resp=0)
```

---

## Instance Methods

### `get_channel_type() -> str`

Works out which AXIL4 channel this packet belongs to from the fields it carries.

**Returns:** One of `'AW'`, `'W'`, `'B'`, `'AR'`, `'R'`, or `'UNKNOWN'`.

### `is_address_channel() -> bool`

`True` for AW or AR packets.

### `is_data_channel() -> bool`

`True` for W or R packets.

### `is_response_channel() -> bool`

`True` for B or R packets.

### `get_address() -> Optional[int]`

The address, for address-channel packets.

**Returns:** Address value, or `None` if not an address channel.

### `get_data() -> Optional[int]`

The data payload, for data or response channel packets.

**Returns:** Data value, or `None` if not a data/response channel.

### `get_response() -> Optional[int]`

The response code, for response channel packets.

**Returns:** Response code, or `None` if not a response channel.

### `get_response_info() -> Dict[str, Any]`

Decodes a B or R packet's response into something readable.

**Returns:** Dictionary with response details, or empty dict if not a response packet.

| Key | Type | Description |
|-----|------|-------------|
| `response_code` | `int` | Raw response code |
| `response_name` | `str` | Human-readable name (OKAY, EXOKAY, SLVERR, DECERR) |
| `is_error` | `bool` | `True` if response is SLVERR or DECERR |
| `data` | `int` or `None` | Data value (R channel) or `None` (B channel) |

### `validate_axil4_protocol() -> Tuple[bool, str]`

Checks the packet against the Lite protocol rules.

**Returns:** Tuple of `(is_valid, error_message)`.

What it checks:

- **Address channels (AW/AR):** address must be word-aligned (multiple of 4)
- **Response channels (B/R):** response code must be 0-3
- **W channel:** strobe pattern must fit the data width's byte count
- **Unrecognized channels:** flagged as invalid

```python
is_valid, msg = packet.validate_axil4_protocol()
if not is_valid:
    log.error(f"AXIL4 protocol violation: {msg}")
```

---

## Usage Examples

### Creating and Inspecting Packets

Everything starts at the factories:

```python
from CocoTBFramework.components.axil4.axil4_packet import AXIL4Packet

# Create an AW packet for a register write
aw = AXIL4Packet.create_aw_packet(addr=0x1000, prot=0)
print(f"Channel: {aw.get_channel_type()}")  # 'AW'
print(f"Address: 0x{aw.get_address():08X}")
print(f"Is address channel: {aw.is_address_channel()}")

# Create a W packet
w = AXIL4Packet.create_w_packet(data=0xDEADBEEF, strb=0xF)
print(f"Data: 0x{w.get_data():08X}")

# Create an R packet and check response
r = AXIL4Packet.create_r_packet(data=0x12345678, resp=2)
info = r.get_response_info()
print(f"Response: {info['response_name']}")  # 'SLVERR'
print(f"Is error: {info['is_error']}")       # True
```

### Protocol Validation

The validator is cheap -- run it on anything you build or receive:

```python
# Valid packet
aw_valid = AXIL4Packet.create_aw_packet(addr=0x1000, prot=0)
is_valid, msg = aw_valid.validate_axil4_protocol()
assert is_valid  # True - address is word-aligned

# Invalid packet (misaligned address)
aw_invalid = AXIL4Packet.create_aw_packet(addr=0x1002, prot=0)
is_valid, msg = aw_invalid.validate_axil4_protocol()
assert not is_valid  # False
print(msg)  # "Address 0x1002 is not word-aligned"
```

### Iterating Over Response Channels

Response packets decode themselves:

```python
packets = [
    AXIL4Packet.create_r_packet(data=0x100, resp=0),
    AXIL4Packet.create_r_packet(data=0x200, resp=0),
    AXIL4Packet.create_r_packet(data=0x300, resp=2),  # SLVERR
]

for pkt in packets:
    info = pkt.get_response_info()
    if info['is_error']:
        print(f"ERROR: {info['response_name']} with data 0x{info['data']:X}")
    else:
        print(f"OK: data=0x{info['data']:X}")
```

---
