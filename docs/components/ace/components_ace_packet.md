# AXI4-ACE Packet and Transaction Types

`ACEPacket` extends `AXI4Packet` with the ACE-specific pieces: snoop-channel factory methods, snoop-type detection, and CRRESP decoding. This is the object that travels through the channel components. The transaction-type enumerations and the `CRRESP` bitfield helper live in `ace_transaction.py`.

## Overview

The `ACEPacket` class provides:

- **Factory methods** for creating packets on each ACE channel (AW, W, B, AR, R, AC, CR, CD)
- **Channel type detection** based on which fields are present
- **ACE feature extraction** including snoop type and CRRESP decoding
- **String representation** tailored to the snoop channels

`SnoopPacket` is a convenience container for a complete snoop transaction result: address, snoop type, CRRESP, and data beats.

The enumerations define:

- `ARSnoop` / `AWSnoop` -- values carried on ARSNOOP / AWSNOOP (`ACETransactionType` is the deprecated combined form)
- `SnoopType` -- values carried on ACSNOOP
- `CacheState` -- Gem5-style stable cache-line states
- `CRRESP` / `CRRESPBit` -- the snoop-response bitfield

---

## ACEPacket

```python
class ACEPacket(AXI4Packet):
    def __init__(self, field_config, **kwargs)
```

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `field_config` | `FieldConfig` | Field configuration object for the specific ACE channel | (required) |
| `**kwargs` | `Any` | Initial field values using generic names (`id`, `addr`, `data`, `snoop`, etc.) | -- |

---

## Factory Methods

### `ACEPacket.create_aw_packet(id_width=8, addr_width=32, user_width=1, **field_values) -> ACEPacket`

Create a Write Address (AW) channel packet with `AWSNOOP` appended after the user field.

**Field values:** `id`, `addr`, `len`, `size`, `burst`, `lock`, `cache`, `prot`, `qos`, `region`, `user`, `snoop`.

```python
packet = ACEPacket.create_aw_packet(
    id=1, addr=0x1000, len=0, size=2, burst=1,
    snoop=int(AWSnoop.WRITE_UNIQUE),
)
```

### `ACEPacket.create_w_packet(data_width=32, user_width=1, **field_values) -> ACEPacket`

Create a Write Data (W) channel packet. Delegates to the AXI4 W config.

**Field values:** `data`, `strb`, `last`, `user`.

### `ACEPacket.create_b_packet(id_width=8, user_width=1, **field_values) -> ACEPacket`

Create a Write Response (B) channel packet. Delegates to the AXI4 B config.

**Field values:** `id`, `resp`, `user`.

### `ACEPacket.create_ar_packet(id_width=8, addr_width=32, user_width=1, **field_values) -> ACEPacket`

Create a Read Address (AR) channel packet with `ARSNOOP` appended after the user field.

**Field values:** `id`, `addr`, `len`, `size`, `burst`, `lock`, `cache`, `prot`, `qos`, `region`, `user`, `snoop`.

```python
packet = ACEPacket.create_ar_packet(
    id=2, addr=0x2000, len=7, size=3, burst=1,
    snoop=int(ARSnoop.READ_SHARED),
)
```

### `ACEPacket.create_r_packet(id_width=8, data_width=32, user_width=1, **field_values) -> ACEPacket`

Create a Read Data (R) channel packet. Delegates to the AXI4 R config.

**Field values:** `id`, `data`, `resp`, `last`, `user`.

### `ACEPacket.create_ac_packet(addr_width=32, **field_values) -> ACEPacket`

Create a Snoop Address (AC) channel packet.

**Field values:** `addr`, `snoop`, `prot`.

```python
packet = ACEPacket.create_ac_packet(
    addr=0x1000,
    snoop=int(SnoopType.READ_SHARED),
    prot=0,
)
```

### `ACEPacket.create_cr_packet(**field_values) -> ACEPacket`

Create a Snoop Response (CR) channel packet.

**Field values:** `resp`.

```python
packet = ACEPacket.create_cr_packet(resp=int(CRRESP.from_bits(data_transfer=True)))
```

### `ACEPacket.create_cd_packet(data_width=32, **field_values) -> ACEPacket`

Create a Snoop Data (CD) channel packet.

**Field values:** `data`, `last`.

```python
packet = ACEPacket.create_cd_packet(data=0x12345678, last=1)
```

---

## Instance Methods

### `get_channel_type() -> str`

Works out which ACE channel the packet belongs to from the fields it carries.

**Returns:** One of `'AW'`, `'W'`, `'B'`, `'AR'`, `'R'`, `'AC'`, `'CR'`, `'CD'`, or `'UNKNOWN'`.

```python
packet = ACEPacket.create_ac_packet(addr=0x1000, snoop=1, prot=0)
assert packet.get_channel_type() == 'AC'
```

### `get_ace_features() -> Dict[str, Any]`

Returns ACE-specific feature information. If the packet has a `snoop` field, it is included. If the channel is CR, the `resp` field is decoded into a `CRRESP` object.

---

## Convenience Functions

### `create_simple_read_packet(id_val, addr, snoop_type=ARSnoop.READ_SHARED, id_width=8, addr_width=32) -> ACEPacket`

Create a simple single-beat ACE read address packet.

### `create_simple_write_packet(id_val, addr, data, snoop_type=AWSnoop.WRITE_UNIQUE, id_width=8, addr_width=32, data_width=32) -> Tuple[ACEPacket, ACEPacket]`

Create simple single-beat ACE write address and data packets.

### `create_snoop_address_packet(addr, snoop_type, prot=0, addr_width=32) -> ACEPacket`

Create a snoop address (AC) packet.

### `create_snoop_response_packet(crresp: CRRESP) -> ACEPacket`

Create a snoop response (CR) packet.

### `create_snoop_data_packet(data, last=True, data_width=32) -> ACEPacket`

Create a snoop data (CD) packet.

---

## SnoopPacket

```python
class SnoopPacket:
    def __init__(self, addr, snoop_type, crresp, data=None, beats=0)
```

A convenience container for a complete snoop transaction result.

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `addr` | `int` | Snoop address |
| `snoop_type` | `SnoopType` | Snoop type issued |
| `crresp` | `CRRESP` | Snoop response |
| `data` | `List[int]` | CD data beats |
| `beats` | `int` | Number of data beats |

---

## Enumerations

### ARSnoop and AWSnoop

The read and write snoop encodings overlap numerically (`0b0011` is ReadNotSharedDirty on AR and WriteBack on AW), so they are two enums. Pass an `ARSnoop` member as `snoop_type` on reads and an `AWSnoop` member on writes.

`ARSnoop` -- `ARSNOOP[3:0]`, Arm IHI 0022H.c Table D3-7:

| Member | Value | Transaction |
|--------|-------|-------------|
| `READ_ONCE` | `0b0000` | ReadOnce (ReadNoSnoop when ARDOMAIN is Non-shareable/System; Barrier when ARBAR[0]=1) |
| `READ_SHARED` | `0b0001` | ReadShared |
| `READ_CLEAN` | `0b0010` | ReadClean |
| `READ_NOT_SHARED_DIRTY` | `0b0011` | ReadNotSharedDirty |
| `READ_UNIQUE` | `0b0111` | ReadUnique |
| `CLEAN_SHARED` | `0b1000` | CleanShared |
| `CLEAN_INVALID` | `0b1001` | CleanInvalid |
| `CLEAN_UNIQUE` | `0b1011` | CleanUnique |
| `MAKE_UNIQUE` | `0b1100` | MakeUnique |
| `MAKE_INVALID` | `0b1101` | MakeInvalid |
| `DVM_COMPLETE` | `0b1110` | DVM Complete |
| `DVM_MESSAGE` | `0b1111` | DVM Message |

`AWSnoop` -- `AWSNOOP[2:0]`, Arm IHI 0022H.c Table D3-8:

| Member | Value | Transaction |
|--------|-------|-------------|
| `WRITE_UNIQUE` | `0b000` | WriteUnique (WriteNoSnoop when AWDOMAIN is Non-shareable/System; Barrier when AWBAR[0]=1) |
| `WRITE_LINE_UNIQUE` | `0b001` | WriteLineUnique |
| `WRITE_CLEAN` | `0b010` | WriteClean |
| `WRITE_BACK` | `0b011` | WriteBack |
| `EVICT` | `0b100` | Evict |
| `WRITE_EVICT` | `0b101` | WriteEvict |

All other encodings are Reserved.

### ACETransactionType (deprecated)

The old combined type. It was one IntEnum holding both encodings, so the write-side names aliased read-side members, and two values were wrong (ReadNotSharedDirty was `0x4`, Evict was `0x5`). It is now a compatibility namespace: every old name resolves to the correct `ARSnoop` or `AWSnoop` member (`ACETransactionType.WRITE_BACK is AWSnoop.WRITE_BACK`), iteration yields the twelve old names, and `ACETransactionType(value)` raises `TypeError` because a bare value does not say which channel it is for. New code should use `ARSnoop` / `AWSnoop`.

### SnoopType

Snoop transaction types carried on `ACSNOOP[3:0]`.

| Member | Value |
|--------|-------|
| `READ_ONCE` | `0x0` |
| `READ_SHARED` | `0x1` |
| `READ_UNIQUE` | `0x7` |
| `CLEAN_SHARED` | `0x8` |
| `CLEAN_INVALID` | `0x9` |
| `MAKE_INVALID` | `0xC` |

### CacheState

Gem5-style stable cache-line states for the snoop responder model.

| Member | Letter |
|--------|--------|
| `INVALID` | `I` |
| `SHARED` | `S` |
| `EXCLUSIVE` | `E` |
| `MODIFIED` | `M` |
| `OWNED` | `O` |

---

## CRRESP

```python
class CRRESP:
    def __init__(self, value: int = 0)
```

Bitfield helper for the CRRESP[4:0] snoop response, per Arm IHI 0022H.

### CRRESPBit

| Member | Bit |
|--------|-----|
| `DATA_TRANSFER` | `0` |
| `ERROR` | `1` |
| `PASS_DIRTY` | `2` |
| `IS_SHARED` | `3` |
| `WAS_UNIQUE` | `4` |

### Construction

```python
# From a raw 5-bit value
cr = CRRESP(0x05)

# From named bits
cr = CRRESP.from_bits(
    data_transfer=True,
    pass_dirty=True,
    is_shared=True,
)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `data_transfer` | `bool` | DataTransfer bit |
| `error` | `bool` | Error bit |
| `pass_dirty` | `bool` | PassDirty bit |
| `is_shared` | `bool` | IsShared bit |
| `was_unique` | `bool` | WasUnique bit |

### Methods

#### `has(bit: CRRESPBit) -> bool`

Check whether a specific CRRESP bit is set.

#### `validate_for_snoop(snoop_type: SnoopType) -> Tuple[bool, Optional[str]]`

Check CRRESP validity for a given snoop type.

**Rules enforced:**
- `MAKE_INVALID` forbids `DataTransfer`.
- `PassDirty` requires `DataTransfer`.

**Returns:** `(is_valid, error_message_or_None)`.

```python
valid, msg = crresp.validate_for_snoop(SnoopType.READ_SHARED)
if not valid:
    log.error(f"Protocol violation: {msg}")
```

### Convenience Aliases

```python
CRRESP_DATA_TRANSFER = 1 << CRRESPBit.DATA_TRANSFER
CRRESP_ERROR = 1 << CRRESPBit.ERROR
CRRESP_PASS_DIRTY = 1 << CRRESPBit.PASS_DIRTY
CRRESP_IS_SHARED = 1 << CRRESPBit.IS_SHARED
CRRESP_WAS_UNIQUE = 1 << CRRESPBit.WAS_UNIQUE
```

---

## Usage Examples

### Creating and Validating Packets

```python
from CocoTBFramework.components.ace.ace_packet import ACEPacket
from CocoTBFramework.components.ace.ace_transaction import (
    ARSnoop, AWSnoop, SnoopType, CRRESP,
)

# Front-side coherent read
ar = ACEPacket.create_ar_packet(
    id_width=4, addr_width=32,
    id=1, addr=0x1000, len=3, size=2, burst=1,
    snoop=int(ARSnoop.READ_SHARED),
)
print(f"Channel: {ar.get_channel_type()}")  # 'AR'

# Snoop address
ac = ACEPacket.create_ac_packet(
    addr_width=32,
    addr=0x2000, snoop=int(SnoopType.READ_UNIQUE), prot=0,
)
print(f"Channel: {ac.get_channel_type()}")  # 'AC'

# Snoop response
cr = ACEPacket.create_cr_packet(resp=int(CRRESP.from_bits(data_transfer=True)))
print(f"Channel: {cr.get_channel_type()}")  # 'CR'
```

### Using Convenience Builders

```python
from CocoTBFramework.components.ace.ace_packet import (
    create_simple_read_packet,
    create_simple_write_packet,
    create_snoop_address_packet,
)

ar_pkt = create_simple_read_packet(id_val=5, addr=0x3000)
aw_pkt, w_pkt = create_simple_write_packet(
    id_val=6, addr=0x4000, data=0x12345678
)
ac_pkt = create_snoop_address_packet(
    addr=0x5000, snoop_type=SnoopType.READ_SHARED
)
```

### Working with SnoopPacket

```python
from CocoTBFramework.components.ace.ace_packet import SnoopPacket
from CocoTBFramework.components.ace.ace_transaction import (
    CRRESP, SnoopType,
)

result = SnoopPacket(
    addr=0x1000,
    snoop_type=SnoopType.READ_SHARED,
    crresp=CRRESP.from_bits(is_shared=True),
)
print(result)  # SnoopPacket(addr=0x1000, snoop=READ_SHARED, ...)
```

### CRRESP Validation

```python
from CocoTBFramework.components.ace.ace_transaction import CRRESP, SnoopType

# Legal: MakeInvalid with no data transfer
cr = CRRESP(0)
valid, msg = cr.validate_for_snoop(SnoopType.MAKE_INVALID)
assert valid

# Illegal: PassDirty without DataTransfer
cr = CRRESP.from_bits(pass_dirty=True)
valid, msg = cr.validate_for_snoop(SnoopType.READ_SHARED)
assert not valid
print(msg)  # "PassDirty set without DataTransfer"
```
