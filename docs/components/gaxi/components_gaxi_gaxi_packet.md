<!-- RTL Design Sherpa Documentation Header -->
<table>
<tr>
<td width="80">
  <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">
    <img src="https://raw.githubusercontent.com/sean-galloway/RTLDesignSherpa/main/docs/logos/Logo_200px.png" alt="RTL Design Sherpa" width="70">
  </a>
</td>
<td>
  <strong>CocoTB Framework</strong> · <em>Verification Infrastructure for RTL Testing</em><br>
  <sub>
    <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">GitHub</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/docs/DOCUMENTATION_INDEX.md">Documentation Index</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/LICENSE">MIT License</a>
  </sub>
</td>
</tr>
</table>

---

<!-- End Header -->

# gaxi_packet.py

GAXIPacket is thin on purpose. Everything that makes a packet useful — field validation, masking, pack/unpack, formatting — lives in the base Packet class and works here unchanged. What this subclass adds is timing: a packet can carry a master randomizer and a slave randomizer, and when a driver asks, it hands back the number of cycles to wait before touching valid or ready.

## Overview

The `GAXIPacket` class provides:
- **All field operations inherited** from base Packet, unmodified
- **Per-packet master/slave randomizers** for timing control
- **Valid-delay and ready-delay generation** via FlexRandomizer
- **Delays generated once and cached per packet** — reuse the packet and you reuse its delays (this is the part that surprises people)

All field management, masking, pack/unpack, and formatting functionality is inherited from the base Packet class without modification.

## Class

### GAXIPacket

```python
class GAXIPacket(Packet):
    def __init__(self, field_config=None, master_randomizer=None,
                 slave_randomizer=None, **kwargs)
```

**Parameters:**
- `field_config`: Field configuration (FieldConfig object or dict)
- `master_randomizer`: Optional randomizer for master interface timing
- `slave_randomizer`: Optional randomizer for slave interface timing  
- `**kwargs`: Initial field values passed to parent Packet class

**Inherited from Packet:**
- All field access via attributes (e.g., `packet.addr`, `packet.data`)
- Automatic field validation and masking
- FIFO packing/unpacking support
- Rich formatting and comparison capabilities
- Thread-safe field caching

## GAXI-Specific Methods

### Randomizer Management

#### `set_master_randomizer(randomizer)`
Attach (or replace) the randomizer that produces valid delays.

**Parameters:**
- `randomizer`: FlexRandomizer instance for master timing

```python
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer

# Create master randomizer
master_randomizer = FlexRandomizer({
    'valid_delay': ([(0, 0), (1, 5), (10, 20)], [0.6, 0.3, 0.1])
})

packet.set_master_randomizer(master_randomizer)
```

#### `set_slave_randomizer(randomizer)`
Attach (or replace) the randomizer that produces ready delays.

**Parameters:**
- `randomizer`: FlexRandomizer instance for slave timing

```python
# Create slave randomizer
slave_randomizer = FlexRandomizer({
    'ready_delay': ([(0, 1), (2, 8), (9, 30)], [0.5, 0.3, 0.2])
})

packet.set_slave_randomizer(slave_randomizer)
```

### Delay Generation

#### `get_master_delay()`
The valid delay for this packet, in cycles. First call rolls the randomizer and caches the result; later calls return the cached value. Returns 0 if no master randomizer is set.

**Returns:** Delay in cycles (0 if no randomizer)

```python
# Get valid delay for master
valid_delay = packet.get_master_delay()
print(f"Master should wait {valid_delay} cycles before asserting valid")
```

#### `get_slave_delay()`
The ready delay for this packet, in cycles. Same caching behavior as the master side.

**Returns:** Delay in cycles (0 if no randomizer)

```python
# Get ready delay for slave
ready_delay = packet.get_slave_delay()
print(f"Slave should wait {ready_delay} cycles before asserting ready")
```

## Usage Patterns

### Basic Packet Creation

```python
from CocoTBFramework.components.gaxi.gaxi_packet import GAXIPacket
from CocoTBFramework.components.shared.field_config import FieldConfig

# Create field configuration
field_config = FieldConfig()
field_config.add_field(FieldDefinition("addr", 32, format="hex"))
field_config.add_field(FieldDefinition("data", 32, format="hex"))
field_config.add_field(FieldDefinition("cmd", 4, format="hex"))

# Create packet with initial values
packet = GAXIPacket(
    field_config=field_config,
    addr=0x1000,
    data=0xDEADBEEF,
    cmd=0x2  # WRITE command
)

# Access fields directly (inherited from base Packet)
print(f"Address: 0x{packet.addr:X}")
print(f"Data: 0x{packet.data:X}")
print(f"Command: {packet.cmd}")
```

### Packet with Timing Randomizers

```python
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer

# Create randomizers for timing
master_randomizer = FlexRandomizer({
    'valid_delay': ([(0, 0), (1, 3), (5, 10)], [0.7, 0.2, 0.1])
})

slave_randomizer = FlexRandomizer({
    'ready_delay': ([(0, 0), (1, 5)], [0.8, 0.2])
})

# Create packet with randomizers
packet = GAXIPacket(
    field_config=field_config,
    master_randomizer=master_randomizer,
    slave_randomizer=slave_randomizer,
    addr=0x2000,
    data=0xCAFEBABE
)

# Get timing delays
valid_delay = packet.get_master_delay()
ready_delay = packet.get_slave_delay()

print(f"Master valid delay: {valid_delay} cycles")
print(f"Slave ready delay: {ready_delay} cycles")
```

### Field Operations (Inherited)

Nothing here is GAXI-specific — it's the base Packet contract, shown because it's what you'll actually use most.

```python
# All field operations inherited from base Packet class

# Field validation and masking (automatic)
packet.addr = 0x123456789  # Automatically masked to 32 bits -> 0x23456789
packet.data = 0xDEADBEEF   # Valid 32-bit value

# FIFO packing/unpacking (inherited)
fifo_data = packet.pack_for_fifo()
print(f"FIFO data: {fifo_data}")

# Create new packet from FIFO data
new_packet = GAXIPacket(field_config)
new_packet.unpack_from_fifo(fifo_data)

# Formatting (inherited)
print(packet.formatted())          # Detailed format
print(packet.formatted(compact=True))  # Compact format
```

### Transaction Timing Integration

How a driver might consume the packet's delay when pushing it onto the bus:

```python
import cocotb
from cocotb.triggers import RisingEdge, Timer

class TimedGAXIMaster:
    def __init__(self, dut, clock, field_config):
        self.dut = dut
        self.clock = clock
        self.field_config = field_config
        
        # Create timing randomizers
        self.master_randomizer = FlexRandomizer({
            'valid_delay': ([(0, 0), (1, 5)], [0.8, 0.2])
        })
    
    async def send_packet(self, **field_values):
        """Send packet with randomized timing"""
        # Create packet with randomizer
        packet = GAXIPacket(
            field_config=self.field_config,
            master_randomizer=self.master_randomizer,
            **field_values
        )
        
        # Get timing delay
        valid_delay = packet.get_master_delay()
        
        # Apply delay before driving
        if valid_delay > 0:
            await Timer(valid_delay, units='clk')
        
        # Drive packet fields
        self.dut.addr.value = packet.addr
        self.dut.data.value = packet.data
        self.dut.valid.value = 1
        
        # Wait for handshake
        while self.dut.ready.value != 1:
            await RisingEdge(self.clock)
        
        await RisingEdge(self.clock)
        self.dut.valid.value = 0
        
        return packet

# Usage
master = TimedGAXIMaster(dut, clock, field_config)
packet = await master.send_packet(addr=0x1000, data=0x12345678, cmd=0x2)
```

### Slave Timing Integration

And the mirror image on the receive side — delay before raising ready:

```python
class TimedGAXISlave:
    def __init__(self, dut, clock, field_config):
        self.dut = dut
        self.clock = clock
        self.field_config = field_config
        
        # Create slave timing randomizer
        self.slave_randomizer = FlexRandomizer({
            'ready_delay': ([(0, 0), (1, 3), (5, 10)], [0.6, 0.3, 0.1])
        })
    
    async def receive_packet(self):
        """Receive packet with randomized ready timing"""
        # Wait for valid
        while self.dut.valid.value != 1:
            await RisingEdge(self.clock)
        
        # Create packet for timing
        packet = GAXIPacket(
            field_config=self.field_config,
            slave_randomizer=self.slave_randomizer
        )
        
        # Get ready delay
        ready_delay = packet.get_slave_delay()
        
        # Apply delay before asserting ready
        if ready_delay > 0:
            await Timer(ready_delay, units='clk')
        
        # Assert ready and capture data
        self.dut.ready.value = 1
        await RisingEdge(self.clock)
        
        # Capture packet data
        packet.addr = int(self.dut.addr.value)
        packet.data = int(self.dut.data.value)
        if hasattr(self.dut, 'cmd'):
            packet.cmd = int(self.dut.cmd.value)
        
        # Deassert ready
        self.dut.ready.value = 0
        
        return packet

# Usage
slave = TimedGAXISlave(dut, clock, field_config)
received_packet = await slave.receive_packet()
```

### Batch Packet Creation

```python
def create_test_packets(field_config, count=10):
    """Create a batch of test packets with varied data"""
    packets = []
    
    # Create common randomizers
    master_randomizer = FlexRandomizer({
        'valid_delay': ([(0, 0), (1, 2)], [0.9, 0.1])
    })
    
    slave_randomizer = FlexRandomizer({
        'ready_delay': ([(0, 1), (2, 5)], [0.7, 0.3])
    })
    
    for i in range(count):
        packet = GAXIPacket(
            field_config=field_config,
            master_randomizer=master_randomizer,
            slave_randomizer=slave_randomizer,
            addr=0x1000 + i*4,
            data=0x10000000 + i,
            cmd=0x2 if i % 2 == 0 else 0x1  # Alternate READ/write
        )
        packets.append(packet)
    
    return packets

# Usage
test_packets = create_test_packets(field_config, count=20)
for i, packet in enumerate(test_packets):
    print(f"Packet {i}: {packet.formatted(compact=True)}")
    print(f"  Master delay: {packet.get_master_delay()}")
    print(f"  Slave delay: {packet.get_slave_delay()}")
```

### Packet Comparison and Validation

```python
def validate_packet_sequence(sent_packets, received_packets):
    """Validate that received packets match sent packets"""
    assert len(sent_packets) == len(received_packets), \
        f"Packet count mismatch: sent {len(sent_packets)}, received {len(received_packets)}"
    
    for i, (sent, received) in enumerate(zip(sent_packets, received_packets)):
        # Use inherited comparison (ignores timing fields)
        if sent != received:
            print(f"Packet {i} mismatch:")
            print(f"  Sent:     {sent.formatted(compact=True)}")
            print(f"  Received: {received.formatted(compact=True)}")
            assert False, f"Packet {i} data mismatch"
        else:
            print(f"Packet {i}: ✓ Match")
    
    print(f"All {len(sent_packets)} packets validated successfully")

# Usage
sent_packets = create_test_packets(field_config, 10)
# ... send packets through DUT ...
received_packets = capture_received_packets()
validate_packet_sequence(sent_packets, received_packets)
```

### Multi-Field Packets

```python
# Create complex field configuration
complex_field_config = FieldConfig()
complex_field_config.add_field(FieldDefinition("addr", 32, format="hex"))
complex_field_config.add_field(FieldDefinition("data", 64, format="hex"))
complex_field_config.add_field(FieldDefinition("cmd", 4, format="hex"))
complex_field_config.add_field(FieldDefinition("id", 8, format="hex"))
complex_field_config.add_field(FieldDefinition("size", 3, format="hex"))

# Create packet with all fields
complex_packet = GAXIPacket(
    field_config=complex_field_config,
    addr=0x12345678,
    data=0xDEADBEEFCAFEBABE,
    cmd=0x3,
    id=0x55,
    size=0x4
)

# All field operations work automatically
print(f"Total packet bits: {complex_packet.get_total_bits()}")
print(f"Formatted packet:\n{complex_packet.formatted()}")

# FIFO operations handle all fields
fifo_data = complex_packet.pack_for_fifo()
print(f"FIFO data: {fifo_data}")
```

### Randomizer Delay Caching

Worth understanding before it confuses you: the delay is rolled once per packet and then frozen. The cache exists so a driver can ask for the delay more than once without re-rolling — the flip side is that reusing a packet reuses its timing. New transaction, new random delay? Build a new packet.

```python
def test_delay_caching():
    """Test that delays are cached until randomizer is reset"""
    packet = GAXIPacket(field_config)
    
    # Set randomizer
    randomizer = FlexRandomizer({
        'valid_delay': ([(1, 5)], [1.0])
    })
    packet.set_master_randomizer(randomizer)
    
    # First call generates and caches delay
    delay1 = packet.get_master_delay()
    
    # Subsequent calls return cached value
    delay2 = packet.get_master_delay()
    delay3 = packet.get_master_delay()
    
    assert delay1 == delay2 == delay3, "Delay should be cached"
    print(f"Cached delay: {delay1} cycles")
    
    # Setting new randomizer resets cache
    new_randomizer = FlexRandomizer({
        'valid_delay': ([(10, 20)], [1.0])
    })
    packet.set_master_randomizer(new_randomizer)
    
    # New delay generated
    new_delay = packet.get_master_delay()
    print(f"New delay after randomizer change: {new_delay} cycles")
    
    # This new delay is now cached
    cached_new_delay = packet.get_master_delay()
    assert new_delay == cached_new_delay, "New delay should be cached"

test_delay_caching()
```

## Error Handling

### Field Validation Errors
```python
# Field validation handled by base Packet class
try:
    packet = GAXIPacket(field_config, addr="invalid")
except ValueError as e:
    print(f"Invalid field value: {e}")
```

### Missing Randomizers

No randomizer attached means zero delay, not an error — a packet without timing constraints just transfers as fast as the handshake allows.

```python
# Graceful handling when randomizers not set
packet = GAXIPacket(field_config)

# Returns 0 when no randomizer
master_delay = packet.get_master_delay()  # Returns 0
slave_delay = packet.get_slave_delay()    # Returns 0

print(f"Delays without randomizers: master={master_delay}, slave={slave_delay}")
```

### Randomizer Errors
```python
# Handle randomizer generation errors
try:
    delay = packet.get_master_delay()
except Exception as e:
    print(f"Randomizer error: {e}")
    delay = 0  # Use default delay
```

## Best Practices

### 1. **Separate Randomizers for Each Direction**

Valid timing and ready timing are different knobs. Keep them in different FlexRandomizer instances so you can tune backpressure without touching launch timing.

```python
# Master randomizer for valid delays
master_randomizer = FlexRandomizer({'valid_delay': ([(0, 5)], [1.0])})

# Slave randomizer for ready delays  
slave_randomizer = FlexRandomizer({'ready_delay': ([(0, 3)], [1.0])})

packet = GAXIPacket(field_config, 
                   master_randomizer=master_randomizer,
                   slave_randomizer=slave_randomizer)
```

### 2. **Use the Inherited Machinery**
```python
# Use inherited field operations
packet.addr = 0x1000           # Field validation automatic
fifo_data = packet.pack_for_fifo()  # FIFO conversion automatic
formatted = packet.formatted()      # Rich formatting automatic
```

### 3. **Respect the Delay Cache**

One packet, one delay. Create a fresh packet per transaction when you want fresh randomization.

```python
# Delays are cached per packet - appropriate for single transaction
master_delay = packet.get_master_delay()  # Generated and cached
same_delay = packet.get_master_delay()    # Returns cached value

# Create new packet for new transaction with fresh delays
new_packet = GAXIPacket(field_config, master_randomizer=randomizer)
new_delay = new_packet.get_master_delay()  # Fresh delay
```

### 4. **Let the Components Attach Timing**

Masters and slaves own their randomizers; packets created through them pick up the right one automatically.

```python
# Integrate timing into master/slave components
class TimingAwareMaster:
    def create_packet(self, **fields):
        return GAXIPacket(self.field_config, 
                         master_randomizer=self.randomizer,
                         **fields)
    
    async def send(self, packet):
        delay = packet.get_master_delay()
        # Apply delay and send
```

### 5. **Validate with the Inherited Comparison**
```python
# Use inherited comparison for validation
assert sent_packet == received_packet, "Packet data mismatch"

# Use inherited formatting for debugging
if sent_packet != received_packet:
    print(f"Sent: {sent_packet.formatted(compact=True)}")
    print(f"Received: {received_packet.formatted(compact=True)}")
```

Use GAXIPacket like a plain Packet and only think about the randomizers when you wire up a driver. The one rule to remember is the caching: ask twice, get the same number; want a new number, build a new packet.
