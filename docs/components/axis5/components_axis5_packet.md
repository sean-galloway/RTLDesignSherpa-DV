# AXIS5Packet Class

`AXIS5Packet` is `AXISPacket` plus the AMBA5 fields: a wakeup bit, per-byte parity, and a `parity_error` flag for recording check results. This page also covers `AXIS5Transaction`, the randomized generator that produces these packets.

## Key Differences from AXIS4 Packet

- **Added fields**: `wakeup` (1 bit), `parity` (1 bit per data byte), `parity_error` (1 bit)
- **Parity support**: automatic per-byte odd parity calculation and verification, per the AMBA AXI5-Stream TPARITY convention
- **Wakeup support**: the wake-up signal state travels with the packet
- **Backward compatibility**: all AXIS4 fields (data, strb, last, id, dest, user) are unchanged
- **Conversion**: `to_axis4_packet()` drops the AXIS5 extras when you need a plain AXIS4 packet

## AXIS5Packet

### Class Signature

```python
class AXIS5Packet(AXISPacket):
    def __init__(self, field_config=None, skip_compare_fields=None,
                 data_width=32, enable_wakeup=True, enable_parity=False, **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `field_config` | FieldConfig | Field configuration (auto-created if None) | `None` |
| `skip_compare_fields` | List[str] | Fields to skip in packet comparison | `['start_time', 'end_time', 'count', 'parity_error']` |
| `data_width` | int | Data width in bits | `32` |
| `enable_wakeup` | bool | Enable wakeup signal field | `True` |
| `enable_parity` | bool | Enable parity signal field | `False` |
| `**kwargs` | Any | Initial field values | -- |

### Static Methods

#### `create_axis5_field_config(data_width, id_width, dest_width, user_width, enable_wakeup, enable_parity) -> FieldConfig`

Builds a field configuration for AXIS5 packets.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `data_width` | int | Data width in bits | `32` |
| `id_width` | int | ID width in bits | `8` |
| `dest_width` | int | Destination width in bits | `4` |
| `user_width` | int | User width in bits | `1` |
| `enable_wakeup` | bool | Enable wakeup field | `True` |
| `enable_parity` | bool | Enable parity field | `False` |

**Returns**: `FieldConfig` with the following fields:

| Field | Bits | Description | Condition |
|-------|------|-------------|-----------|
| `data` | data_width | Stream data | Always |
| `strb` | data_width/8 | Byte strobes | Always |
| `last` | 1 | Last transfer indicator | Always |
| `id` | id_width | Stream ID | id_width > 0 |
| `dest` | dest_width | Destination | dest_width > 0 |
| `user` | user_width | User signal | user_width > 0 |
| `wakeup` | 1 | Wake-up signal | enable_wakeup |
| `parity` | data_width/8 | Data parity (1 bit per byte) | enable_parity |
| `parity_error` | 1 | Parity error indicator | enable_parity |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `wakeup` | int | Wake-up signal value (0 or 1) |
| `parity` | int | Parity value (bit per byte) |
| `parity_error` | int | Parity error indicator (0 or 1) |

### Key Methods

#### `calculate_parity() -> int`

The expected TPARITY for the current data field value: per-byte **odd** parity, one parity bit per data byte, matching the AMBA AXI5-Stream specification.

**Returns**: Calculated parity value.

**Algorithm**: For each byte of data, count the set bits. The parity bit is chosen so the byte plus its parity bit carry an odd total number of ones — it is the inverted XOR of the byte's bits (0 when the byte already has an odd number of ones, 1 when it has an even number). The standalone helper `calculate_odd_parity(data_value, num_bytes)` (exported from `axis5_packet`) does the same math and is reused by the slave and monitor.

#### `check_parity() -> bool`

Compares the stored parity against the calculated odd parity for the current data.

**Returns**: `True` if parity is correct (or parity is disabled), `False` on mismatch.

#### `copy() -> AXIS5Packet`

Copies the packet. Unlike the base `Packet.copy()`, this override **keeps the AXIS5 constructor options** (`data_width`, `enable_wakeup`, `enable_parity`) along with all field values and timing. That matters for parity: copy a packet whose parity was deliberately corrupted and the copy still reports `check_parity() == False`, because it keeps `enable_parity` enabled.

#### `set_wakeup(enable=True)`

Sets the wakeup signal state.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | True to assert wakeup | `True` |

#### `is_wakeup_active() -> bool`

True if wakeup is asserted in this packet.

#### `to_axis4_packet() -> AXISPacket`

Converts to an AXIS4 packet by dropping the AXIS5-specific fields (wakeup, parity, parity_error).

**Returns**: `AXISPacket` with the core fields copied over.

## Usage Examples

### Example 1: Basic Packet Creation

```python
from CocoTBFramework.components.axis5 import AXIS5Packet

# Create packet with wakeup only
pkt = AXIS5Packet(data_width=32, enable_wakeup=True, enable_parity=False)
pkt.data = 0xDEADBEEF
pkt.strb = 0xF
pkt.last = 1
pkt.id = 5
pkt.dest = 2
pkt.wakeup = 1

print(pkt)
# AXIS5 Packet:
#   Data:     0xDEADBEEF
#   Strobe:   0b1111
#   Last:     1
#   ID:       0x5
#   Dest:     0x2
#   User:     0x0
#   Wakeup:   1
```

### Example 2: Parity Calculation and Checking

```python
# Create packet with parity enabled
pkt = AXIS5Packet(data_width=32, enable_wakeup=False, enable_parity=True)
pkt.data = 0x12345678

# Auto-calculate parity
pkt.parity = pkt.calculate_parity()
print(f"Parity: 0b{pkt.parity:04b}")

# Verify parity
assert pkt.check_parity() is True

# Corrupt data and re-check
pkt.data = 0x12345679  # Changed last byte
assert pkt.check_parity() is False  # Parity no longer matches
```

### Example 3: Conversion to AXIS4

```python
# Create AXIS5 packet
axis5_pkt = AXIS5Packet(
    data_width=64, enable_wakeup=True, enable_parity=True
)
axis5_pkt.data = 0xCAFEBABEDEADBEEF
axis5_pkt.last = 1
axis5_pkt.id = 3
axis5_pkt.wakeup = 1
axis5_pkt.parity = axis5_pkt.calculate_parity()

# Convert to AXIS4 (drops wakeup and parity)
axis4_pkt = axis5_pkt.to_axis4_packet()
assert axis4_pkt.data == 0xCAFEBABEDEADBEEF
assert axis4_pkt.id == 3
assert not hasattr(axis4_pkt, 'wakeup')  # AXIS5 field removed
```

---

## AXIS5Transaction

A randomized generator for AXIS5 traffic — call `next()` and it hands you packets, so you don't have to hand-write each one.

### Class Signature

```python
class AXIS5Transaction:
    def __init__(self, data_width=32, id_width=8, dest_width=4, user_width=1,
                 enable_wakeup=True, enable_parity=False, randomizer=None)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `data_width` | int | Data width in bits | `32` |
| `id_width` | int | ID width in bits | `8` |
| `dest_width` | int | Destination width in bits | `4` |
| `user_width` | int | User width in bits | `1` |
| `enable_wakeup` | bool | Enable wakeup randomization | `True` |
| `enable_parity` | bool | Enable parity generation | `False` |
| `randomizer` | FlexRandomizer or dict | Optional randomizer for value generation | `None` |

When no randomizer is provided, a default `FlexRandomizer` is created with:
- `data`: Full range random
- `strb`: All bytes enabled
- `last`: 75% not-last, 25% last
- `id`, `dest`, `user`: Full range random
- `wakeup`: 90% inactive, 10% active

### Key Methods

#### `next() -> AXIS5Packet`

Generates the next random transaction packet. If parity is enabled, it's calculated automatically.

**Returns**: New `AXIS5Packet` with randomized values.

#### `create_packet(data, last=0, id=0, dest=0, user=0, wakeup=0, strb=None) -> AXIS5Packet`

Builds a packet with specific values instead of random ones — the directed-test counterpart to `next()`.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `data` | int | Data value | (required) |
| `last` | int | Last transfer flag | `0` |
| `id` | int | Stream ID | `0` |
| `dest` | int | Destination | `0` |
| `user` | int | User signal | `0` |
| `wakeup` | int | Wakeup signal | `0` |
| `strb` | int | Strobe value (full strobe if None) | `None` |

**Returns**: `AXIS5Packet` with the specified values and auto-calculated parity (if enabled).

### Usage Examples

```python
from CocoTBFramework.components.axis5 import AXIS5Transaction

# Example 1: Random transaction generation
txn_gen = AXIS5Transaction(
    data_width=32, enable_wakeup=True, enable_parity=True
)

# Generate 10 random packets
packets = [txn_gen.next() for _ in range(10)]
for pkt in packets:
    print(f"data=0x{pkt.data:08X}, last={pkt.last}, wakeup={pkt.wakeup}")

# Example 2: Specific packet creation
txn_gen = AXIS5Transaction(data_width=64, enable_parity=True)

pkt = txn_gen.create_packet(
    data=0x1122334455667788,
    last=1, id=3, dest=1, wakeup=0
)
assert pkt.check_parity() is True

# Example 3: Custom randomizer
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer

custom_rand = FlexRandomizer({
    'data': ([(0, 0xFF)], [1]),           # Small data values
    'strb': ([(0xF, 0xF)], [1]),          # Full strobe
    'last': ([(0, 0), (1, 1)], [1, 1]),   # 50/50 last
    'id': ([(0, 3)], [1]),                # 4 stream IDs
    'dest': ([(0, 0)], [1]),              # Single destination
    'user': ([(0, 0)], [1]),              # No user data
    'wakeup': ([(0, 0), (1, 1)], [4, 1]),  # 20% wakeup
})

txn_gen = AXIS5Transaction(
    data_width=32, enable_wakeup=True,
    enable_parity=True, randomizer=custom_rand
)
```
