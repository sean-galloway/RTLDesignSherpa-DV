# AXI5Packet Class

`AXI5Packet` is what actually travels across the channels — the base `Packet` extended with the AXI5 field set. Fields use generic names (`id`, `addr`, `data`, and friends) that match the field configuration, so the packet code doesn't change when your widths do. Atomics, memory tagging, chunking, poison: all just fields on the packet.

## Key Differences from AXI4

- **Removed fields**: `region` (ARREGION/AWREGION are gone)
- **Added fields**: `atop`, `nsaid`, `trace`, `mpam`, `mecid`, `unique`, `tagop`, `tag`, `chunken`, `chunkv`, `chunknum`, `chunkstrb`, `poison`, `tagupdate`, `tagmatch`
- **Channel detection**: inferred from the AXI5 fields present — `atop` says AW, `chunken` says AR
- **Protocol validation**: AXI5-specific checks for ATOP encodings, TAGOP values, and chunking rules

## Class Signature

```python
class AXI5Packet(Packet):
    def __init__(self, field_config, **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `field_config` | FieldConfig | Field configuration for the specific AXI5 channel | (required) |
| `**kwargs` | Any | Initial field values using generic names (`id`, `addr`, `data`, etc.) | -- |

## Class Methods (Packet Factories)

One factory per channel.

### `create_aw_packet(id_width, addr_width, user_width, data_width, **field_values) -> AXI5Packet`

Create a Write Address (AW) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `id_width` | int | Width of ID field | `8` |
| `addr_width` | int | Width of ADDR field | `32` |
| `user_width` | int | Width of USER field | `1` |
| `data_width` | int | Data width for tag calculation | `32` |
| `**field_values` | Any | AW field values (`id`, `addr`, `len`, `atop`, `tagop`, etc.) | -- |

### `create_w_packet(data_width, user_width, **field_values) -> AXI5Packet`

Create a Write Data (W) channel packet — one per beat, if you're assembling a burst.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `data_width` | int | Width of DATA field | `32` |
| `user_width` | int | Width of USER field | `1` |
| `**field_values` | Any | W field values (`data`, `last`, `strb`, `poison`, `tag`, `tagupdate`) | -- |

### `create_b_packet(id_width, user_width, data_width, **field_values) -> AXI5Packet`

Create a Write Response (B) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `id_width` | int | Width of ID field | `8` |
| `user_width` | int | Width of USER field | `1` |
| `data_width` | int | Data width for tag calculation | `32` |
| `**field_values` | Any | B field values (`id`, `resp`, `trace`, `tag`, `tagmatch`) | -- |

### `create_ar_packet(id_width, addr_width, user_width, **field_values) -> AXI5Packet`

Create a Read Address (AR) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `id_width` | int | Width of ID field | `8` |
| `addr_width` | int | Width of ADDR field | `32` |
| `user_width` | int | Width of USER field | `1` |
| `**field_values` | Any | AR field values (`id`, `addr`, `len`, `chunken`, `tagop`, etc.) | -- |

### `create_r_packet(id_width, data_width, user_width, **field_values) -> AXI5Packet`

Create a Read Data (R) channel packet.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `id_width` | int | Width of ID field | `8` |
| `data_width` | int | Width of DATA field | `32` |
| `user_width` | int | Width of USER field | `1` |
| `**field_values` | Any | R field values (`id`, `data`, `resp`, `last`, `poison`, `chunkv`, `chunknum`, etc.) | -- |

## Instance Methods

### `get_channel_type() -> str`

Tells you which AXI5 channel this packet belongs on, worked out from the fields it carries.

**Returns**: `'AW'`, `'W'`, `'B'`, `'AR'`, `'R'`, or `'UNKNOWN'` when nothing matched.

### `validate_axi5_protocol() -> Tuple[bool, str]`

Checks the packet against the AXI5 protocol rules.

**Checks performed**:
- Burst length range (0-255)
- Burst size range (0-7)
- Burst type validity (0, 1, 2)
- ATOP encoding validity (AW channel)
- TAGOP range (0-3)
- Response code validity (B, R channels)
- Chunk field consistency (R channel)
- WLAST / RLAST presence

**Returns**: `(is_valid, error_message)` — the message is empty when the packet passes.

### `get_burst_info() -> Dict[str, Any]`

Burst details from an address packet (AW/AR).

**Returns**: dictionary with `burst_type`, `burst_length`, `burst_size`, `bytes_per_beat`, `total_bytes`, `address`. Empty dict for non-address packets.

### `get_response_info() -> Dict[str, Any]`

Response details from a response packet (B/R).

**Returns**: dictionary with `response_code`, `response_name`, `is_error`, `is_exclusive`, `tagmatch`. R packets add `is_last`, `poison`, `chunkv`, `chunknum`; B packets add `trace`.

### `get_axi5_features() -> Dict[str, Any]`

Pulls out just the AXI5-specific state — usually the first thing you want when a test misbehaves.

**Returns**: dictionary of feature status, including:
- `is_atomic`, `atomic_type` — atomic operation info
- `tagop`, `tag`, `tagmatch`, `tagupdate` — MTE info
- `nsaid`, `mpam`, `mecid` — security context
- `trace` — tracing status
- `unique` — unique access
- `chunken`, `chunkv`, `chunknum`, `chunkstrb` — chunking info
- `poison` — poison indicator

## Convenience Functions

Small builders for the common cases.

### `create_simple_write_packets(id_val, addr, data, id_width, addr_width, data_width) -> Tuple[AXI5Packet, AXI5Packet]`

AW and W packets for a single-beat write.

### `create_simple_read_packet(id_val, addr, id_width, addr_width) -> AXI5Packet`

An AR packet for a single-beat read.

### `create_atomic_write_packets(id_val, addr, data, atop, id_width, addr_width, data_width) -> Tuple[AXI5Packet, AXI5Packet]`

AW and W packets for an atomic operation.

| Parameter | Type | Description |
|-----------|------|-------------|
| `atop` | int | Atomic operation type: `0x10`=Store, `0x20`=Load, `0x30`=Swap, `0x31`=Compare |

### `create_tagged_write_packets(id_val, addr, data, tag, tagop, id_width, addr_width, data_width) -> Tuple[AXI5Packet, AXI5Packet]`

AW and W packets with Memory Tagging Extension fields populated.

| Parameter | Type | Description |
|-----------|------|-------------|
| `tag` | int | Memory tag value |
| `tagop` | int | Tag operation: `0`=Invalid, `1`=Transfer, `2`=Update, `3`=Match |

## Packet Utility Functions

The `axi5_packet_utils` module rounds this out with a larger set of helpers, grouped by what you're building:

### Address Packets
- `create_simple_read_packet(address, id_val, burst_len, size, burst_type, **kwargs)` — AR packet
- `create_simple_write_address_packet(address, id_val, burst_len, size, burst_type, **kwargs)` — AW packet

### Data Packets
- `create_simple_write_data_packet(data, last, strb, data_width, **kwargs)` — W packet
- `create_simple_read_response_packet(data, resp, last, id_val, data_width, **kwargs)` — R packet
- `create_simple_write_response_packet(resp, id_val, **kwargs)` — B packet

### Burst Packets
- `create_burst_write_packets(id_val, start_addr, data_list, size, burst_type, **kwargs)` — AW + W list
- `create_burst_read_response_packets(id_val, data_list, resp, **kwargs)` — R list

### AXI5-Specific Packets
- `create_atomic_transaction_packets(id_val, addr, data, atop, data_width, **kwargs)` — Atomic AW + W
- `create_tagged_write_packets(id_val, addr, data_list, tag, tagop, data_width, **kwargs)` — MTE AW + W list
- `create_tagged_read_packet(id_val, addr, burst_len, tagop, **kwargs)` — MTE AR
- `create_chunked_read_packet(id_val, addr, burst_len, **kwargs)` — Chunked AR
- `create_secure_write_packets(id_val, addr, data, nsaid, mpam, mecid, data_width, **kwargs)` — Security AW + W
- `create_traced_write_packets(id_val, addr, data, data_width, **kwargs)` — Traced AW + W

## Usage Examples

### Example 1: Creating and Validating Packets

Build an atomic AW, validate it, and read the feature set back — all before it goes near a channel:

```python
from CocoTBFramework.components.axi5 import AXI5Packet

# Create an AW packet with atomic operation
aw = AXI5Packet.create_aw_packet(
    id=1, addr=0x1000, len=0, size=2, burst=1, atop=0x30
)
print(aw)  # "AXI5Packet(AW: id=1, addr=0x1000, len=0, atomic=AtomicSwap)"

# Validate protocol compliance
is_valid, errors = aw.validate_axi5_protocol()
assert is_valid, f"Protocol errors: {errors}"

# Get AXI5-specific feature info
features = aw.get_axi5_features()
assert features['is_atomic'] is True
assert features['atomic_type'] == 'AtomicSwap'
```

### Example 2: Working with MTE Packets

Tagged traffic in both directions:

```python
from CocoTBFramework.components.axi5 import (
    create_tagged_write_packets, create_tagged_read_packet
)

# Create tagged write (MTE)
aw_pkt, w_pkts = create_tagged_write_packets(
    id_val=2, addr=0x3000,
    data_list=[0x11111111, 0x22222222],
    tag=0xA, tagop=2  # Update operation
)

# Create tagged read
ar_pkt = create_tagged_read_packet(
    id_val=3, addr=0x3000, burst_len=2, tagop=1  # Transfer operation
)
```

### Example 3: Security and Tracing Packets

The security-context and tracing variants:

```python
from CocoTBFramework.components.axi5 import (
    create_secure_write_packets, create_traced_write_packets
)

# Write with security context
aw_sec, w_sec = create_secure_write_packets(
    id_val=4, addr=0x5000, data=0xABCDEF01,
    nsaid=2, mpam=0x100, mecid=0x1234
)

# Write with tracing enabled
aw_trace, w_trace = create_traced_write_packets(
    id_val=5, addr=0x6000, data=0xFEEDFACE
)
```
