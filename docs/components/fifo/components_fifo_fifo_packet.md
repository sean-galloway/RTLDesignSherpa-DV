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

# fifo_packet.py

FIFOPacket is deliberately boring. It's the base Packet class with exactly one addition: a pair of timing randomizers, one for the write side and one for the read side. Everything else — fields, masking, pack/unpack, formatting — is inherited.

## Overview

FIFOPacket adds master and slave randomizer slots to Packet so that timing policy can travel with the transaction it belongs to. A packet rolls its delay once and caches it, so the master, the slave, and any monitor that inspects the packet all see the same number. Field management, validation, `pack_for_fifo()`, `formatted()`, comparison, copying — all of that is Packet behavior, and it all works here.

### Key Features
- **Minimal by design**: the only new surface is timing — everything else is Packet
- **Two randomizers**: master (write) and slave (read) delays ride along with the packet
- **Cached delays**: call the getter twice, get the same value; no randomizer means 0
- **Full Packet API**: formatting, validation, FIFO pack/unpack, the works

## Core Class

### FIFOPacket

Packet class for FIFO protocol transactions.

#### Constructor

```python
FIFOPacket(field_config=None,
           master_randomizer=None,
           slave_randomizer=None, 
           **kwargs)
```

**Parameters:**
- `field_config`: Field configuration (FieldConfig object or dict that will be converted)
- `master_randomizer`: Optional randomizer for master interface timing
- `slave_randomizer`: Optional randomizer for slave interface timing  
- `**kwargs`: Initial field values passed to parent Packet constructor

**Example:**
```python
# Basic packet creation
packet = FIFOPacket(field_config, data=0x12345678)

# Packet with randomizers
packet = FIFOPacket(
    field_config=field_config,
    master_randomizer=write_randomizer,
    slave_randomizer=read_randomizer,
    addr=0x1000,
    data=0xDEADBEEF,
    cmd=0x2
)
```

## Core Methods

### Randomizer Management

#### `set_master_randomizer(randomizer)`

Attach the randomizer that shapes this packet's write-side gaps.

**Parameters:**
- `randomizer`: FlexRandomizer instance for master interface

```python
# Set master randomizer
write_randomizer = FlexRandomizer({
    'write_delay': ([(0, 0), (1, 5), (10, 20)], [0.6, 0.3, 0.1])
})
packet.set_master_randomizer(write_randomizer)
```

#### `set_slave_randomizer(randomizer)`

Same, for the read side.

**Parameters:**
- `randomizer`: FlexRandomizer instance for slave interface

```python
# Set slave randomizer
read_randomizer = FlexRandomizer({
    'read_delay': ([(0, 1), (2, 8), (9, 30)], [5, 2, 1])
})
packet.set_slave_randomizer(read_randomizer)
```

### Timing Access

#### `get_master_delay()`

The write-side delay in cycles. Rolled once per packet and cached — call it twice and you get the same value, which is what lets multiple components agree on the packet's timing.

**Returns:** Delay in cycles (0 if no randomizer)

```python
# Get write delay
write_delay = packet.get_master_delay()
print(f"Write delay: {write_delay} cycles")

# Use in timing control
for _ in range(write_delay):
    await RisingEdge(clock)
```

#### `get_slave_delay()`

The read-side delay in cycles, same caching behavior.

**Returns:** Delay in cycles (0 if no randomizer)

```python
# Get read delay
read_delay = packet.get_slave_delay()
print(f"Read delay: {read_delay} cycles")

# Use in timing control
for _ in range(read_delay):
    await RisingEdge(clock)
```

## Inherited Functionality

Everything below is Packet behavior. It's listed here so you remember it's there — none of it needed FIFO-specific changes.

### Field Access
```python
# Direct field access with validation
packet.addr = 0x1000
packet.data = 0xDEADBEEF
packet.cmd = 0x2

# Field values are automatically validated and masked
print(f"Address: 0x{packet.addr:X}")
print(f"Data: 0x{packet.data:X}")
```

### FIFO Operations
```python
# Pack for FIFO transmission
fifo_data = packet.pack_for_fifo()
print(fifo_data)  # {'addr': 0x200, 'data': 0xDEADBEEF} (with bit shifting)

# Unpack from FIFO reception
packet.unpack_from_fifo({'addr': 0x200, 'data': 0x12345678})
```

### Formatting and Display
```python
# Rich formatting
print(packet.formatted())
print(packet.formatted(compact=True))
print(packet.formatted(show_fifo=True))

# String representation
print(packet)  # Detailed format with all fields
```

### Comparison and Copying
```python
# Packet comparison
packet1 = FIFOPacket(field_config, data=0x1234)
packet2 = FIFOPacket(field_config, data=0x1234)
assert packet1 == packet2

# Packet copying
packet_copy = packet.copy()
```

## Usage Patterns

### Basic Packet Creation and Usage

Nothing FIFO-specific here yet — that's the point.

```python
# Define field configuration
field_config = FieldConfig()
field_config.add_field(FieldDefinition("addr", 32, format="hex"))
field_config.add_field(FieldDefinition("data", 32, format="hex"))
field_config.add_field(FieldDefinition("cmd", 4, format="hex"))

# Create packet with initial values
packet = FIFOPacket(field_config, addr=0x1000, data=0xDEADBEEF, cmd=0x2)

# Access fields
print(f"Command: {packet.cmd}, Address: 0x{packet.addr:X}, Data: 0x{packet.data:X}")
```

### Timing-Controlled Packets

Randomizers ride along with the packet, so the components don't each need their own copy:

```python
# Create randomizers for timing control
write_randomizer = FlexRandomizer({
    'write_delay': ([(0, 0), (1, 5), (10, 20)], [0.6, 0.3, 0.1])
})

read_randomizer = FlexRandomizer({
    'read_delay': ([(0, 1), (2, 8), (9, 30)], [5, 2, 1])
})

# Create packet with timing control
packet = FIFOPacket(
    field_config=field_config,
    master_randomizer=write_randomizer,
    slave_randomizer=read_randomizer,
    data=0x12345678
)

# Use timing in master component
class TimingMaster:
    async def send_packet(self, packet):
        # Apply master delay
        delay = packet.get_master_delay()
        for _ in range(delay):
            await RisingEdge(self.clock)
        
        # Drive packet
        self.drive_packet_data(packet)
        await RisingEdge(self.clock)

# Use timing in slave component  
class TimingSlave:
    async def receive_packet(self, packet):
        # Apply slave delay
        delay = packet.get_slave_delay()
        for _ in range(delay):
            await RisingEdge(self.clock)
        
        # Read packet
        self.read_packet_data(packet)
```

### Packet Factory Integration

The factory builds packets; you attach timing after creation, or fold it into your sequence:

```python
# Use with PacketFactory for consistent creation
factory = PacketFactory(FIFOPacket, field_config)

# Create packet with factory
packet = factory.create_packet(addr=0x2000, data=0xCAFEBABE)

# Add randomizers after creation
packet.set_master_randomizer(write_randomizer)
packet.set_slave_randomizer(read_randomizer)

# Or create with timing
timed_packet = factory.create_timed_packet(
    start_time=cocotb.utils.get_sim_time(),
    addr=0x3000,
    data=0x87654321
)
```

### Sequence Integration

A sequence that carries its own timing makes total-delay questions answerable:

```python
class TimedFIFOSequence:
    def __init__(self, field_config, master_randomizer=None, slave_randomizer=None):
        self.field_config = field_config
        self.master_randomizer = master_randomizer
        self.slave_randomizer = slave_randomizer
        self.packets = []
    
    def add_packet(self, **field_values):
        """Add packet with timing randomizers"""
        packet = FIFOPacket(
            field_config=self.field_config,
            master_randomizer=self.master_randomizer,
            slave_randomizer=self.slave_randomizer,
            **field_values
        )
        self.packets.append(packet)
        return packet
    
    def generate_burst(self, count, base_addr=0x1000, base_data=0x1000):
        """Generate burst with consistent timing"""
        for i in range(count):
            self.add_packet(
                addr=base_addr + i * 4,
                data=base_data + i,
                cmd=0x2  # WRITE
            )
    
    def get_total_delay(self, interface='master'):
        """Calculate total delay for sequence"""
        total_delay = 0
        for packet in self.packets:
            if interface == 'master':
                total_delay += packet.get_master_delay()
            else:
                total_delay += packet.get_slave_delay()
        return total_delay

# Usage
sequence = TimedFIFOSequence(field_config, write_randomizer, read_randomizer)
sequence.generate_burst(count=10)

print(f"Total write delay: {sequence.get_total_delay('master')} cycles")
print(f"Total read delay: {sequence.get_total_delay('slave')} cycles")
```

### Advanced Timing Control

Because the randomizer is per-packet, you can swap it in response to conditions. Congestion-adaptive pacing in about twenty lines:

```python
class AdaptiveTimingPacket:
    """Packet with adaptive timing based on conditions"""
    
    def __init__(self, field_config):
        self.packet = FIFOPacket(field_config)
        self.timing_mode = 'normal'
        
        # Create different randomizers for different modes
        self.fast_randomizer = FlexRandomizer({
            'write_delay': ([(0, 0), (1, 1)], [9, 1])
        })
        
        self.normal_randomizer = FlexRandomizer({
            'write_delay': ([(0, 0), (1, 5), (6, 15)], [5, 3, 2])
        })
        
        self.slow_randomizer = FlexRandomizer({
            'write_delay': ([(5, 10), (11, 25), (26, 50)], [3, 2, 1])
        })
        
        # Set default
        self.set_timing_mode('normal')
    
    def set_timing_mode(self, mode):
        """Set timing mode and update randomizer"""
        self.timing_mode = mode
        
        if mode == 'fast':
            self.packet.set_master_randomizer(self.fast_randomizer)
        elif mode == 'normal':
            self.packet.set_master_randomizer(self.normal_randomizer)
        elif mode == 'slow':
            self.packet.set_master_randomizer(self.slow_randomizer)
    
    def adapt_timing_to_congestion(self, congestion_level):
        """Adapt timing based on system congestion"""
        if congestion_level < 0.3:
            self.set_timing_mode('fast')
        elif congestion_level < 0.7:
            self.set_timing_mode('normal')
        else:
            self.set_timing_mode('slow')
    
    def get_delay_for_mode(self):
        """Get delay for current timing mode"""
        return self.packet.get_master_delay()

# Usage
adaptive_packet = AdaptiveTimingPacket(field_config)
adaptive_packet.packet.addr = 0x4000
adaptive_packet.packet.data = 0xABCDEF00

# Adapt to system conditions
congestion = 0.8  # High congestion
adaptive_packet.adapt_timing_to_congestion(congestion)

delay = adaptive_packet.get_delay_for_mode()
print(f"Adaptive delay for high congestion: {delay} cycles")
```

### Performance Analysis with Timing

Since delays are queryable, you can characterize a whole sequence's timing before you run it:

```python
class TimingAnalyzer:
    """Analyze packet timing characteristics"""
    
    def __init__(self):
        self.timing_data = []
    
    def analyze_packet_timing(self, packets, interface='master'):
        """Analyze timing distribution for packet list"""
        delays = []
        
        for packet in packets:
            if interface == 'master':
                delay = packet.get_master_delay()
            else:
                delay = packet.get_slave_delay()
            delays.append(delay)
        
        if not delays:
            return {}
        
        return {
            'count': len(delays),
            'min_delay': min(delays),
            'max_delay': max(delays),
            'avg_delay': sum(delays) / len(delays),
            'total_delay': sum(delays),
            'delay_distribution': self._analyze_distribution(delays)
        }
    
    def _analyze_distribution(self, delays):
        """Analyze delay distribution"""
        from collections import Counter
        distribution = Counter(delays)
        
        return {
            'unique_delays': len(distribution),
            'most_common_delay': distribution.most_common(1)[0] if distribution else (0, 0),
            'distribution': dict(distribution)
        }
    
    def compare_interfaces(self, packets):
        """Compare master vs slave timing"""
        master_analysis = self.analyze_packet_timing(packets, 'master')
        slave_analysis = self.analyze_packet_timing(packets, 'slave')
        
        return {
            'master': master_analysis,
            'slave': slave_analysis,
            'total_master_delay': master_analysis.get('total_delay', 0),
            'total_slave_delay': slave_analysis.get('total_delay', 0)
        }

# Usage
analyzer = TimingAnalyzer()

# Create packets with timing
packets = []
for i in range(100):
    packet = FIFOPacket(field_config, data=0x5000 + i)
    packet.set_master_randomizer(write_randomizer)
    packet.set_slave_randomizer(read_randomizer)
    packets.append(packet)

# Analyze timing characteristics
analysis = analyzer.compare_interfaces(packets)
print(f"Timing analysis: {analysis}")
```

### Validation and Testing

A sanity checker for packets — handy when you're debugging a custom randomizer:

```python
def validate_fifo_packet(packet):
    """Validate FIFO packet integrity"""
    errors = []
    
    # Check that packet has required FIFO functionality
    if not hasattr(packet, 'get_master_delay'):
        errors.append("Missing get_master_delay method")
    
    if not hasattr(packet, 'get_slave_delay'):
        errors.append("Missing get_slave_delay method")
    
    # Test randomizer functionality
    if hasattr(packet, 'master_randomizer') and packet.master_randomizer:
        try:
            delay = packet.get_master_delay()
            if not isinstance(delay, int) or delay < 0:
                errors.append(f"Invalid master delay: {delay}")
        except Exception as e:
            errors.append(f"Master delay error: {e}")
    
    # Check inherited Packet functionality
    try:
        fifo_data = packet.pack_for_fifo()
        if not isinstance(fifo_data, dict):
            errors.append("pack_for_fifo should return dict")
    except Exception as e:
        errors.append(f"FIFO pack error: {e}")
    
    return errors

# Usage in tests
def test_fifo_packet_creation():
    """Test FIFOPacket creation and functionality"""
    packet = FIFOPacket(field_config, data=0x12345678)
    
    # Validate basic functionality
    errors = validate_fifo_packet(packet)
    assert not errors, f"Packet validation failed: {errors}"
    
    # Test timing functionality
    packet.set_master_randomizer(write_randomizer)
    delay1 = packet.get_master_delay()
    delay2 = packet.get_master_delay()
    
    # Delays should be cached (same value)
    assert delay1 == delay2, "Delay should be cached"
    
    # Test randomizer reset
    packet.set_master_randomizer(write_randomizer)
    delay3 = packet.get_master_delay()
    # New randomizer should potentially give different delay
    
    print("FIFOPacket validation passed")
```

## Best Practices

### 1. **Use Factory Functions for Creation**
The factory keeps field handling consistent across your testbench:
```python
# Recommended
factory = PacketFactory(FIFOPacket, field_config)
packet = factory.create_packet(data=0x12345678)

# Rather than direct instantiation
```

### 2. **Set Randomizers Early**
Attach them right after creation. A packet without randomizers has zero delays, which is rarely the test you meant to write:
```python
# Set randomizers immediately after creation
packet = FIFOPacket(field_config, data=0x1000)
packet.set_master_randomizer(write_randomizer)
packet.set_slave_randomizer(read_randomizer)
```

### 3. **Cache Delay Values**
Delays are rolled once per packet. If you want a fresh roll, set the randomizer again:
```python
# Delays are cached within a packet instance
delay = packet.get_master_delay()  # Calculated once
same_delay = packet.get_master_delay()  # Returns cached value
assert delay == same_delay
```

### 4. **Use Appropriate Randomizers**
Keep separate, named randomizers per scenario instead of rebuilding them inline:
```python
# Different randomizers for different scenarios
fast_randomizer = FlexRandomizer({'write_delay': [(0, 1)]})  # Fast
stress_randomizer = FlexRandomizer({'write_delay': [(0, 50)]})  # Stress
```

### 5. **Leverage Inherited Functionality**
`formatted()` alone will save you from writing a dozen print statements:
```python
# Use all base Packet capabilities
packet.formatted()  # Rich formatting
packet.pack_for_fifo()  # FIFO operations
packet == other_packet  # Comparison
packet.copy()  # Copying
```

The packet stays dumb on purpose. Timing policy lives in the randomizers, sequencing lives in FIFOSequence — the packet just carries both.
