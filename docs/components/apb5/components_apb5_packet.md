# apb5_packet.py

Two classes live here: APB5Packet, the record of a single bus transfer with all the AMBA5 extras attached, and APB5Transaction, a constrained-random generator that stamps out packets for stimulus. Everything else in the APB5 family passes these objects around.

## Overview

- **APB5Packet**: the transfer record — every APB4 field plus the user sidebands, wake-up state, and parity error flags
- **APB5Transaction**: the stimulus generator, with constraints that cover the user signals

### Key Features

- All APB4 fields, plus the four AMBA5 user channels (PAUSER, PWUSER, PRUSER, PBUSER)
- Wake-up tracking via the `wakeup` field
- Parity error flags for write data, read data, and control
- Two-way APB4 conversion
- Built-in constrained randomization for user signals
- Direction-aware equality that compares user signals too

## Core Classes

### APB5Packet

One APB5Packet is one bus transfer. It extends the framework's base Packet with the APB field set and the AMBA5 extensions.

#### Constructor

```python
APB5Packet(field_config=None, skip_compare_fields=None,
           data_width=32, addr_width=32, strb_width=4,
           auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
           **kwargs)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `field_config` | FieldConfig | None | Field configuration (default: auto-generated APB5 config) |
| `skip_compare_fields` | list[str] | None | Fields to skip during equality comparison |
| `data_width` | int | 32 | Width of data fields in bits |
| `addr_width` | int | 32 | Width of address field in bits |
| `strb_width` | int | 4 | Width of strobe field in bits |
| `auser_width` | int | 4 | Width of PAUSER field in bits |
| `wuser_width` | int | 4 | Width of PWUSER field in bits |
| `ruser_width` | int | 4 | Width of PRUSER field in bits |
| `buser_width` | int | 4 | Width of PBUSER field in bits |
| `**kwargs` | | | Initial field values (e.g., paddr=0x123, pwrite=1, pauser=0x5) |

```python
# Create APB5 packet with default configuration
packet = APB5Packet(
    pwrite=1,
    paddr=0x1000,
    pwdata=0xDEADBEEF,
    pstrb=0xF,
    pauser=0x5,
    pwuser=0xA
)

# Create with custom widths
wide_packet = APB5Packet(
    data_width=64,
    addr_width=16,
    strb_width=8,
    auser_width=8,
    wuser_width=8,
    ruser_width=8,
    buser_width=8,
    pwrite=0,
    paddr=0x200,
    pauser=0xAB
)
```

#### Properties

- `direction`: transaction direction as a string ('READ' or 'WRITE')
- `data_width`: data field width in bits
- `addr_width`: address field width in bits
- `strb_width`: strobe field width in bits
- `auser_width`: PAUSER field width in bits
- `wuser_width`: PWUSER field width in bits
- `ruser_width`: PRUSER field width in bits
- `buser_width`: PBUSER field width in bits
- `count`: transaction counter for identification
- `cycle`: self-reference for backward compatibility

#### Default Skip Compare Fields

Equality ignores a handful of fields by default — exactly the ones you'd never want a comparison to fail on:

- `start_time`, `end_time`, `count` (timing/metadata)
- `wakeup` (transient state)
- `parity_error_wdata`, `parity_error_rdata`, `parity_error_ctrl` (diagnostic flags)

#### APB5 Field Configuration

The generated field config covers the APB4 base plus every AMBA5 extension:

| Field | Bits | Format | Description |
|-------|------|--------|-------------|
| pwrite | 1 | dec | Write Enable (0=Read, 1=Write) |
| paddr | addr_width | hex | Address |
| pwdata | data_width | hex | Write Data |
| prdata | data_width | hex | Read Data |
| pstrb | strb_width | bin | Write Strobes |
| pprot | 3 | hex | Protection Control |
| pslverr | 1 | dec | Slave Error |
| pauser | auser_width | hex | Request User Attributes |
| pwuser | wuser_width | hex | Write Data User Attributes |
| pruser | ruser_width | hex | Read Data User Attributes |
| pbuser | buser_width | hex | Response User Attributes |
| wakeup | 1 | dec | Wake-up Request (requester-driven, observed by completer) |
| parity_error_wdata | 1 | dec | Write Data Parity Error |
| parity_error_rdata | 1 | dec | Read Data Parity Error |
| parity_error_ctrl | 1 | dec | Control Signal Parity Error |

#### Methods

##### `create_apb5_field_config(addr_width, data_width, strb_width, auser_width=4, wuser_width=4, ruser_width=4, buser_width=4)` [Static]

Builds the default field configuration for a given set of widths. Most tests never call this directly — the constructor generates it for you when you don't pass `field_config` — but it's there when you need a custom layout.

**Parameters:**
- `addr_width`: Address field width in bits
- `data_width`: Data field width in bits
- `strb_width`: Strobe field width in bits
- `auser_width`: PAUSER width in bits (default: 4)
- `wuser_width`: PWUSER width in bits (default: 4)
- `ruser_width`: PRUSER width in bits (default: 4)
- `buser_width`: PBUSER width in bits (default: 4)

**Returns:** FieldConfig object with APB5 fields

```python
# Create custom field configuration
config = APB5Packet.create_apb5_field_config(
    addr_width=16,
    data_width=64,
    strb_width=8,
    auser_width=8,
    wuser_width=8
)

# Use in packet creation
packet = APB5Packet(field_config=config, data_width=64, addr_width=16, strb_width=8)
```

##### `__str__() -> str`

The full dump, formatted for humans:

```python
print(packet)
# Output:
# APB5 Packet:
#   Direction:  WRITE
#   Address:    0x00001000
#   Write Data: 0xDEADBEEF
#   Strobes:    1111
#   PWUSER:     0x0A
#   Protection: 0x0
#   PAUSER:     0x05
#   PBUSER:     0x00
#   Slave Err:  0
#   Wake-up:    0
#   Start Time: 1000 ns
#   End Time:   2000 ns
#   Duration:   1000 ns
#   Count:      1
```

Read transfers show PRDATA and PRUSER in place of PWDATA, PSTRB, and PWUSER, and the parity flags only appear when one is actually set — no noise when nothing is wrong.

##### `formatted(compact=False) -> str`

Same information, your choice of layout. Pass `compact=True` for a one-liner — what you want in a log full of transactions.

**Parameters:**
- `compact`: If True, return compact one-line format

```python
# Detailed format
print(packet.formatted())

# Compact format
print(packet.formatted(compact=True))
# Output: APB5Packet(time=1000, dir=WRITE, addr=0x00001000, wdata=0xDEADBEEF,
#                     strb=1111, prot=0x0, auser=0x05)
```

The compact line only mentions `wakeup=1` when the wake-up flag is set, and `err=1` when PSLVERR is asserted.

##### `__eq__(other) -> bool`

Equality is direction-aware and includes the sidebands: a write never equals a read, and two writes with different PWUSER values don't compare equal either.

The comparison checks:

- Direction (pwrite)
- Address (paddr)
- Data (pwdata for writes, prdata for reads)
- Protection (pprot) and slave error (pslverr)
- Strobes (pstrb, for writes only)
- User signals: pauser, pbuser, and direction-dependent pwuser or pruser

```python
pkt1 = APB5Packet(pwrite=1, paddr=0x100, pwdata=0x123, pauser=0x5, pwuser=0xA)
pkt2 = APB5Packet(pwrite=1, paddr=0x100, pwdata=0x123, pauser=0x5, pwuser=0xA)
assert pkt1 == pkt2  # True

pkt3 = APB5Packet(pwrite=1, paddr=0x100, pwdata=0x123, pauser=0x5, pwuser=0xB)
assert pkt1 != pkt3  # Different pwuser
```

##### `to_apb4_packet() -> APBPacket`

Drops the AMBA5 extensions and returns a plain APBPacket. For the extensions, this is a one-way trip.

**Returns:** APBPacket with APB4 fields only

```python
apb5_pkt = APB5Packet(pwrite=1, paddr=0x100, pwdata=0xABCD, pauser=0x5)
apb4_pkt = apb5_pkt.to_apb4_packet()
# apb4_pkt has pwrite, paddr, pwdata, prdata, pstrb, pprot, pslverr
# pauser, pwuser, pruser, pbuser, wakeup are dropped
```

##### `from_apb4_packet(apb4_pkt, auser_width=4, wuser_width=4, ruser_width=4, buser_width=4) -> APB5Packet` [Class Method]

Upgrades an APB4 packet. The APB4 fields carry over; the APB5 extensions come in zeroed, ready for you to set.

**Parameters:**
- `apb4_pkt`: Source APBPacket
- `auser_width`: Width of PAUSER field (default: 4)
- `wuser_width`: Width of PWUSER field (default: 4)
- `ruser_width`: Width of PRUSER field (default: 4)
- `buser_width`: Width of PBUSER field (default: 4)

**Returns:** APB5Packet with APB5 extensions set to zero defaults

```python
from CocoTBFramework.components.apb.apb_packet import APBPacket

apb4_pkt = APBPacket(pwrite=1, paddr=0x100, pwdata=0xABCD)
apb5_pkt = APB5Packet.from_apb4_packet(apb4_pkt, auser_width=8)
# apb5_pkt.fields['pauser'] == 0
# apb5_pkt.fields['pwuser'] == 0
# apb5_pkt.auser_width == 8
```

### APB5Transaction

Your stimulus engine. Each call to `next()` returns a freshly randomized APB5Packet, with constraints from a FlexRandomizer and user-signal ranges that automatically match the widths you configure.

#### Constructor

```python
APB5Transaction(data_width=32, addr_width=32, strb_width=4,
                auser_width=4, wuser_width=4, ruser_width=4, buser_width=4,
                randomizer=None, **kwargs)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data_width` | int | 32 | Data width in bits |
| `addr_width` | int | 32 | Address width in bits |
| `strb_width` | int | 4 | Strobe width in bits |
| `auser_width` | int | 4 | PAUSER width in bits |
| `wuser_width` | int | 4 | PWUSER width in bits |
| `ruser_width` | int | 4 | PRUSER width in bits |
| `buser_width` | int | 4 | PBUSER width in bits |
| `randomizer` | FlexRandomizer/dict | None | Randomizer instance or constraint dictionary |
| `**kwargs` | | | Initial field values |

```python
# Create with default randomization
transaction = APB5Transaction()

# Create with custom user signal widths
transaction = APB5Transaction(
    auser_width=8,
    wuser_width=8,
    ruser_width=8,
    buser_width=8
)

# Create with custom randomization
custom_randomizer = FlexRandomizer({
    'pwrite': ([(0, 0), (1, 1)], [1, 2]),
    'paddr': ([(0x1000, 0x1FFF)], [1]),
    'pstrb': ([(0xF, 0xF)], [1]),
    'pprot': ([(0, 0)], [1]),
    'pauser': ([(0, 0xFF)], [1]),
    'pwuser': ([(0, 0xFF)], [1]),
})
transaction = APB5Transaction(
    auser_width=8, wuser_width=8,
    randomizer=custom_randomizer
)
```

#### Default Randomization

Out of the box you get a plausible traffic mix — reads and writes equally likely, mostly full strobes, and user values spread across the full configured width:

```python
{
    'pwrite': ([(0, 0), (1, 1)], [1, 1]),           # Equal read/write
    'paddr': ([(0, addr_min), (addr_max_lo, addr_max_hi)], [4, 1]),
    'pstrb': ([(15, 15), (0, 14)], [4, 1]),         # Mostly full strobes
    'pprot': ([(0, 0), (1, 7)], [4, 1]),             # Mostly normal protection
    'pauser': ([(0, (1 << auser_width) - 1)], [1]),  # Full PAUSER range
    'pwuser': ([(0, (1 << wuser_width) - 1)], [1]),  # Full PWUSER range
}
```

#### Methods

##### `next() -> APB5Packet`

Returns the next randomized packet.

**Returns:** APB5Packet with randomized field values including user signals

```python
# Generate random transactions
for i in range(10):
    packet = transaction.next()
    print(f"Transaction {i}: {packet.formatted(compact=True)}")
    print(f"  PAUSER: 0x{packet.fields['pauser']:X}")
    print(f"  PWUSER: 0x{packet.fields['pwuser']:X}")
```

Each generated packet has:

- Randomized pwrite, paddr (aligned to strobe width), pstrb, pprot
- Randomized pauser and pwuser from configured ranges
- Random pwdata for write transactions
- Address alignment enforced via addr_mask

##### `set_constrained_random() -> APB5Transaction`

Randomizes the transaction in place; the result is available via `.packet`.

**Returns:** Self for method chaining

```python
# Randomize in place; the generated packet is available via .packet
transaction.set_constrained_random()
packet = transaction.packet
```

##### `formatted(compact=False) -> str`

Formatted view of the transaction, detailed or one-line.

```python
print(transaction.formatted())
print(transaction.formatted(compact=True))
```

## Usage Patterns

### Basic Packet Creation

Hand-build packets when you want exact values on the bus:

```python
from CocoTBFramework.components.apb5.apb5_packet import APB5Packet

# Create write packet with user signals
write_packet = APB5Packet(
    pwrite=1,
    paddr=0x2000,
    pwdata=0x12345678,
    pstrb=0xF,
    pprot=0,
    pauser=0x5,
    pwuser=0xA
)

# Create read packet
read_packet = APB5Packet(
    pwrite=0,
    paddr=0x2000,
    pprot=0,
    pauser=0x5
)

print(f"Write: {write_packet.formatted(compact=True)}")
print(f"Read: {read_packet.formatted(compact=True)}")
```

### APB4/APB5 Conversion

Round-tripping through APB4 keeps the base fields and resets the extensions — handy when you're reusing legacy stimulus:

```python
from CocoTBFramework.components.apb.apb_packet import APBPacket
from CocoTBFramework.components.apb5.apb5_packet import APB5Packet

# Upgrade APB4 packet to APB5
apb4_pkt = APBPacket(pwrite=1, paddr=0x100, pwdata=0xCAFE)
apb5_pkt = APB5Packet.from_apb4_packet(apb4_pkt, auser_width=8, wuser_width=8)

# Set APB5-specific fields
apb5_pkt.fields['pauser'] = 0xAB
apb5_pkt.fields['pwuser'] = 0xCD

# Downgrade back to APB4
apb4_again = apb5_pkt.to_apb4_packet()
# User signals are dropped
```

### Transaction Generation with User Signals

Bias the constraints toward the traffic your DUT actually sees:

```python
from CocoTBFramework.components.apb5.apb5_packet import APB5Transaction
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer

# Create transaction generator with specific user signal patterns
randomizer = FlexRandomizer({
    'pwrite': ([(0, 0), (1, 1)], [1, 1]),
    'paddr': ([(0x1000, 0x1FFF), (0x8000, 0x8FFF)], [3, 1]),
    'pstrb': ([(0xF, 0xF)], [1]),
    'pprot': ([(0, 0)], [1]),
    'pauser': ([(0x00, 0x0F), (0xF0, 0xFF)], [3, 1]),  # Biased PAUSER
    'pwuser': ([(0x00, 0xFF)], [1]),
})

transaction = APB5Transaction(
    auser_width=8, wuser_width=8,
    randomizer=randomizer
)

# Generate test sequence
packets = []
for i in range(100):
    packet = transaction.next()
    packets.append(packet)

# Analyze generated patterns
write_count = sum(1 for p in packets if p.direction == 'WRITE')
read_count = len(packets) - write_count
print(f"Generated {write_count} writes, {read_count} reads")
```

## Best Practices

### 1. **Use Matching Widths Across Components**

Same rule as the component layer — define the widths once and pass them everywhere:

```python
# Define widths once, use everywhere
AUSER_W, WUSER_W, RUSER_W, BUSER_W = 8, 8, 8, 8

packet = APB5Packet(
    auser_width=AUSER_W, wuser_width=WUSER_W,
    ruser_width=RUSER_W, buser_width=BUSER_W,
    pwrite=1, paddr=0x100, pwdata=0xABCD
)
```

### 2. **Check Parity Error Flags**

Parity flags are recorded, not raised — nothing fails on its own when one sets. If your test cares, look:

```python
# After receiving a monitored packet
if (packet.fields.get('parity_error_wdata', 0) or
    packet.fields.get('parity_error_rdata', 0) or
    packet.fields.get('parity_error_ctrl', 0)):
    print("Parity error detected!")
    print(packet)  # Full output includes parity error details
```

### 3. **Use Compact Format for Logging**

Long runs produce a lot of packets. The compact format keeps the log readable:

```python
for packet in packet_sequence:
    print(f"Processing: {packet.formatted(compact=True)}")
```

### 4. **Validate Conversion Round-Trips**

If a test converts between formats, assert what you expect to survive the trip:

```python
original = APB5Packet(pwrite=1, paddr=0x100, pwdata=0x123, pstrb=0xF)
apb4 = original.to_apb4_packet()
restored = APB5Packet.from_apb4_packet(apb4)
# APB4 fields match; APB5 extensions reset to defaults
```

Between these two classes, this module is the common currency of the APB5 family — master, slave, monitor, and scoreboard all speak it, and the conversion methods keep your older APB4 tests in the conversation.
