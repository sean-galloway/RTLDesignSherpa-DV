# AXI4 Packet

AXI4 packet implementation extending the base `Packet` class with AXI4-specific channel detection, protocol validation, burst information extraction, and factory methods for each AXI4 channel type.

## Overview

The `AXI4Packet` class provides:

- **Factory methods** for creating packets on each AXI4 channel (AW, W, B, AR, R)
- **Channel type detection** based on field presence
- **Protocol validation** against AXI4 specification rules
- **Burst information extraction** from address channel packets
- **Response information extraction** from response channel packets
- **Generic field naming** (id, addr, data, resp) with `pkt_prefix` handling signal mapping

All field names use a generic naming convention (e.g., `id`, `addr`, `len`, `data`, `resp`, `last`) that matches the `FieldConfig` definitions. The AXI4 signal-level prefixes (e.g., `ar`, `aw`, `w`, `r`, `b`) are handled by the `pkt_prefix` parameter in the GAXI component layer.

---

## Class

### AXI4Packet

```python
class AXI4Packet(Packet):
    def __init__(self, field_config, **kwargs)
```

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `field_config` | `FieldConfig` | Field configuration object for the specific AXI4 channel | (required) |
| `**kwargs` | `Any` | Initial field values using generic names (`id`, `addr`, `data`, etc.) | -- |

---

## Factory Methods

### `AXI4Packet.create_aw_packet(id_width=8, addr_width=32, user_width=1, **field_values) -> AXI4Packet`

Create a Write Address (AW) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `id_width` | `int` | Width of ID field in bits | `8` |
| `addr_width` | `int` | Width of ADDR field in bits | `32` |
| `user_width` | `int` | Width of USER field in bits | `1` |
| `**field_values` | `Any` | AW field values: `id`, `addr`, `len`, `size`, `burst`, `lock`, `cache`, `prot`, `qos`, `region`, `user` | -- |

**Returns:** `AXI4Packet` configured for the AW channel.

```python
packet = AXI4Packet.create_aw_packet(id=1, addr=0x1000, len=3, size=2, burst=1)
```

### `AXI4Packet.create_w_packet(data_width=32, user_width=1, **field_values) -> AXI4Packet`

Create a Write Data (W) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `data_width` | `int` | Width of DATA field in bits | `32` |
| `user_width` | `int` | Width of USER field in bits | `1` |
| `**field_values` | `Any` | W field values: `data`, `strb`, `last`, `user` | -- |

**Returns:** `AXI4Packet` configured for the W channel.

```python
packet = AXI4Packet.create_w_packet(data=0xDEADBEEF, strb=0xF, last=1)
```

### `AXI4Packet.create_b_packet(id_width=8, user_width=1, **field_values) -> AXI4Packet`

Create a Write Response (B) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `id_width` | `int` | Width of ID field in bits | `8` |
| `user_width` | `int` | Width of USER field in bits | `1` |
| `**field_values` | `Any` | B field values: `id`, `resp`, `user` | -- |

**Returns:** `AXI4Packet` configured for the B channel.

```python
packet = AXI4Packet.create_b_packet(id=1, resp=0)  # OKAY response
```

### `AXI4Packet.create_ar_packet(id_width=8, addr_width=32, user_width=1, **field_values) -> AXI4Packet`

Create a Read Address (AR) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `id_width` | `int` | Width of ID field in bits | `8` |
| `addr_width` | `int` | Width of ADDR field in bits | `32` |
| `user_width` | `int` | Width of USER field in bits | `1` |
| `**field_values` | `Any` | AR field values: `id`, `addr`, `len`, `size`, `burst`, `lock`, `cache`, `prot`, `qos`, `region`, `user` | -- |

**Returns:** `AXI4Packet` configured for the AR channel.

```python
packet = AXI4Packet.create_ar_packet(id=2, addr=0x2000, len=7, size=2, burst=1)
```

### `AXI4Packet.create_r_packet(id_width=8, data_width=32, user_width=1, **field_values) -> AXI4Packet`

Create a Read Data (R) channel packet.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `id_width` | `int` | Width of ID field in bits | `8` |
| `data_width` | `int` | Width of DATA field in bits | `32` |
| `user_width` | `int` | Width of USER field in bits | `1` |
| `**field_values` | `Any` | R field values: `id`, `data`, `resp`, `last`, `user` | -- |

**Returns:** `AXI4Packet` configured for the R channel.

```python
packet = AXI4Packet.create_r_packet(id=2, data=0x12345678, resp=0, last=1)
```

---

## Instance Methods

### `get_channel_type() -> str`

Determine which AXI4 channel this packet belongs to based on field presence.

**Returns:** One of `'AW'`, `'W'`, `'B'`, `'AR'`, `'R'`, or `'UNKNOWN'`.

```python
packet = AXI4Packet.create_aw_packet(id=1, addr=0x1000)
assert packet.get_channel_type() == 'AW'
```

### `validate_axi4_protocol() -> Tuple[bool, str]`

Validate the packet against AXI4 protocol rules.

**Returns:** Tuple of `(is_valid, error_message)`. The error message is empty when valid.

Checks performed:
- **AW/AR channels:** Burst length (0-255), size (0-7), burst type (0, 1, or 2)
- **W channel:** Presence of `last` field
- **R channel:** Presence of `last` field, response code (0-3)
- **B channel:** Response code (0-3)

```python
is_valid, error_msg = packet.validate_axi4_protocol()
if not is_valid:
    log.error(f"Protocol violation: {error_msg}")
```

### `get_burst_info() -> Dict[str, Any]`

Get burst information from address channel packets (AW or AR).

**Returns:** Dictionary with burst details, or empty dict if not an address packet.

| Key | Type | Description |
|-----|------|-------------|
| `burst_type` | `int` | Burst type (0=FIXED, 1=INCR, 2=WRAP) |
| `burst_length` | `int` | Actual number of beats (len + 1) |
| `burst_size` | `int` | Size encoding |
| `bytes_per_beat` | `int` | Bytes transferred per beat (2^size) |
| `total_bytes` | `int` | Total bytes in burst |
| `address` | `int` | Start address |

```python
info = aw_packet.get_burst_info()
print(f"Burst: {info['burst_length']} beats, {info['total_bytes']} bytes total")
```

### `get_response_info() -> Dict[str, Any]`

Get response information from response channel packets (B or R).

**Returns:** Dictionary with response details, or empty dict if not a response packet.

| Key | Type | Description |
|-----|------|-------------|
| `response_code` | `int` | Raw response code |
| `response_name` | `str` | Human-readable name (OKAY, EXOKAY, SLVERR, DECERR) |
| `is_error` | `bool` | `True` if response is SLVERR or DECERR |
| `is_exclusive` | `bool` | `True` if response is EXOKAY |
| `is_last` | `bool` | (R channel only) Whether this is the last beat |

```python
info = r_packet.get_response_info()
if info['is_error']:
    log.error(f"Read error: {info['response_name']}")
```

---

## Convenience Functions

### `create_simple_write_packets(id_val, addr, data, id_width=8, addr_width=32, data_width=32) -> Tuple[AXI4Packet, AXI4Packet]`

Create AW and W packets for a single-beat write.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `id_val` | `int` | Write transaction ID | (required) |
| `addr` | `int` | Write address | (required) |
| `data` | `int` | Write data value | (required) |
| `id_width` | `int` | ID field width in bits | `8` |
| `addr_width` | `int` | Address field width in bits | `32` |
| `data_width` | `int` | Data field width in bits | `32` |

**Returns:** Tuple of `(aw_packet, w_packet)`.

### `create_simple_read_packet(id_val, addr, id_width=8, addr_width=32) -> AXI4Packet`

Create an AR packet for a single-beat read.

**Returns:** `AXI4Packet` configured for the AR channel.

---

## Usage Examples

### Creating and Validating Packets

```python
from CocoTBFramework.components.axi4.axi4_packet import (
    AXI4Packet, create_simple_write_packets, create_simple_read_packet
)

# Create AW packet for a 4-beat burst write
aw = AXI4Packet.create_aw_packet(
    id_width=4, addr_width=32,
    id=1, addr=0x1000, len=3, size=2, burst=1
)
print(f"Channel: {aw.get_channel_type()}")  # 'AW'
print(f"Burst: {aw.get_burst_info()}")

# Validate protocol compliance
is_valid, msg = aw.validate_axi4_protocol()
assert is_valid, msg

# Create R packet and inspect response
r = AXI4Packet.create_r_packet(id=1, data=0xCAFEBABE, resp=0, last=1)
info = r.get_response_info()
print(f"Response: {info['response_name']}, last={info['is_last']}")
```

### Using Convenience Functions

```python
# Quick single-beat write
aw_pkt, w_pkt = create_simple_write_packets(id_val=5, addr=0x2000, data=0x12345678)
print(f"AW: {aw_pkt}")
print(f"W: {w_pkt}")

# Quick single-beat read
ar_pkt = create_simple_read_packet(id_val=6, addr=0x3000)
print(f"AR: {ar_pkt}")
```

### Working with Burst Information

```python
# Create a burst read request
ar = AXI4Packet.create_ar_packet(id=3, addr=0x4000, len=15, size=3, burst=1)
burst = ar.get_burst_info()

print(f"Address: 0x{burst['address']:X}")
print(f"Beats: {burst['burst_length']}")
print(f"Bytes per beat: {burst['bytes_per_beat']}")
print(f"Total bytes: {burst['total_bytes']}")
# Address: 0x4000, Beats: 16, Bytes per beat: 8, Total bytes: 128
```
