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

# apb_components.py

The signal-level heart of the APB family: a monitor that watches the bus, a slave that answers it, and a master that drives it. Everything else in this directory — packets, sequences, factories — exists to keep these three fed.

## Overview

Three classes, one per seat on the bus:
- **APBMonitor**: watches the bus and turns completed transfers into `APBPacket` objects
- **APBSlave**: answers requests from a real memory model, with tunable timing and error behavior
- **APBMaster**: drives packets from a queue, with randomized setup/access timing

### Key Features
- **Full APB4 signal support**, with PPROT/PSLVERR/PSTRB bound as optional so leaner DUTs still attach
- **Memory-backed slave** — reads return what earlier writes actually wrote
- **FlexRandomizer timing** on both ends, from "no wait states, ever" to "go find the corners"
- **Error injection**, random or triggered by out-of-range addresses
- **Master-side transaction queue**, so stimulus isn't gated on your testbench loop

## Constants and Mappings

### Signal Definitions

The lists every component binds against, plus the PWRITE decode used in logging:

```python
# APB PWRITE mapping
pwrite = ['READ', 'WRITE']

# Required APB signals
apb_signals = [
    "PSEL",      # Peripheral select
    "PWRITE",    # Write enable
    "PENABLE",   # Enable signal
    "PADDR",     # Address bus
    "PWDATA",    # Write data bus
    "PRDATA",    # Read data bus
    "PREADY"     # Ready signal
]

# Optional APB signals
apb_optional_signals = [
    "PPROT",     # Protection control
    "PSLVERR",   # Slave error
    "PSTRB"      # Write strobes
]
```

### Required vs Optional Signal Binding

`cocotb_bus` draws a hard line here: anything in a BFM's `_signals` list must exist on the DUT or bus binding fails outright, while `_optional_signals` are best-effort — a signal that isn't there is skipped and simply never appears on `self.bus`.

APBMonitor, APBSlave, and APBMaster bind `apb_signals` as required and `apb_optional_signals` as optional. That's what lets an APB3-era DUT — no strobes, no error output, no protection bits — bind cleanly against these BFMs. Every access to the optional trio is guarded by `is_signal_present()`, so nothing blows up when they're absent. The APB5 BFMs in this framework play the same trick: all AMBA5 extensions (USER / WAKEUP / parity) are optional.

Pass an explicit `signals=[...]` list and you take over: your list becomes the required set, with no optional signals at all. Full control, full responsibility.

## Core Classes

### APBMonitor

A passive observer — it never drives a pin. It watches for completed transfers, rebuilds each one as an `APBPacket`, and hands it to whatever callbacks you've registered.

#### Constructor

```python
APBMonitor(entity, title, prefix, clock, signals=None, bus_width=32, addr_width=12, log=None, **kwargs)
```

**Parameters:**
- `entity`: DUT entity to monitor
- `title`: Monitor identifier for logging
- `prefix`: Signal prefix for bus connection
- `clock`: Clock signal for synchronization
- `signals`: Custom signal list (default: standard APB signals)
- `bus_width`: Data bus width in bits (default: 32)
- `addr_width`: Address bus width in bits (default: 12)
- `log`: Logger instance (default: entity logger)

```python
# Create APB monitor
monitor = APBMonitor(
    entity=dut,
    title="APB_Monitor",
    prefix="apb_",
    clock=dut.clk,
    bus_width=32,
    addr_width=16
)
```

#### Methods

##### `is_signal_present(signal_name) -> bool`
Returns True when the named signal actually exists on the bound bus. Call it before touching any of the optional signals — an APB3 DUT won't have PSTRB, PSLVERR, or PPROT, and the attribute simply won't be there.

```python
if monitor.is_signal_present('PSLVERR'):
    # Handle slave error signal
    pass
```

##### `print(transaction)`
Write a formatted dump of an `APBPacket` to the log.

**Parameters:**
- `transaction`: APBPacket transaction to display

```python
monitor.print(packet)  # Logs transaction details
```

#### Transaction Detection

A transfer is sampled on the clock edge where PSEL, PENABLE, and PREADY are all high — the moment the APB access phase completes. If any relevant signal carries an X or Z, the cycle is skipped rather than logged as garbage, which saves you from phantom transactions during reset.

### APBSlave

An APB responder with real storage behind it. Writes land in the memory model, reads come back out of it, and how quickly PREADY rises (and how often PSLVERR does) is yours to tune.

#### Constructor

```python
APBSlave(entity, title, prefix, clock, registers, signals=None, bus_width=32, addr_width=12, randomizer=None, log=None, error_overflow=False, **kwargs)
```

**Parameters:**
- `entity`: DUT entity to connect to
- `title`: Slave identifier for logging
- `prefix`: Signal prefix for bus connection
- `clock`: Clock signal for synchronization
- `registers`: Initial register values or register count
- `signals`: Custom signal list (default: standard APB signals)
- `bus_width`: Data bus width in bits (default: 32)
- `addr_width`: Address bus width in bits (default: 12)
- `randomizer`: Timing randomizer (default: FlexRandomizer)
- `log`: Logger instance (default: entity logger)
- `error_overflow`: Generate errors on address overflow (default: False)

```python
# Create APB slave with 256 registers
registers = [0] * 1024  # 256 32-bit registers
slave = APBSlave(
    entity=dut,
    title="APB_Slave",
    prefix="apb_",
    clock=dut.clk,
    registers=registers,
    bus_width=32,
    addr_width=16,
    error_overflow=True
)
```

One sizing note: `registers` counts bytes, not words — the `[0] * 1024` above backs 256 32-bit registers.

#### Methods

##### `set_randomizer(randomizer)`
Swap the FlexRandomizer that drives PREADY delay and error injection. Fine to call mid-test when you want the slave to change personalities between phases.

```python
new_randomizer = FlexRandomizer({
    'ready': ([(0, 2), (5, 10)], [8, 1]),
    'error': ([(0, 0), (1, 1)], [20, 1])
})
slave.set_randomizer(new_randomizer)
```

##### `dump_registers()`
Log the entire register file. First thing to reach for when a readback comes back wrong.

```python
slave.dump_registers()  # Shows memory dump
```

##### `reset_bus()`
Drive all slave outputs back to idle.

```python
await slave.reset_bus()
```

##### `reset_registers()`
Restore the register file to the values passed in at construction.

```python
slave.reset_registers()
```

#### Response Behavior

Three knobs shape how the slave answers:
- **Ready delay**: how many cycles PREADY holds off, drawn from the randomizer's `ready` bins
- **Error injection**: PSLVERR generation, either random (the `error` bins) or address-triggered
- **Memory expansion**: with `error_overflow=False` (the default), accesses past the end of the backing store grow it instead of faulting. Set `error_overflow=True` and those same accesses come back with slave errors — which is exactly what the overflow portion of the error-injection example below relies on.

### APBMaster

The driver. Hand it `APBPacket` objects and it walks each one through setup and access, with PSEL/PENABLE timing as relaxed or as nasty as your randomizer says.

#### Constructor

```python
APBMaster(entity, title, prefix, clock, signals=None, bus_width=32, addr_width=12, randomizer=None, log=None, **kwargs)
```

**Parameters:**
- `entity`: DUT entity to drive
- `title`: Master identifier for logging
- `prefix`: Signal prefix for bus connection
- `clock`: Clock signal for synchronization
- `signals`: Custom signal list (default: standard APB signals)
- `bus_width`: Data bus width in bits (default: 32)
- `addr_width`: Address bus width in bits (default: 12)
- `randomizer`: Timing randomizer (default: FlexRandomizer)
- `log`: Logger instance (default: entity logger)

```python
# Create APB master
master = APBMaster(
    entity=dut,
    title="APB_Master",
    prefix="apb_",
    clock=dut.clk,
    bus_width=32,
    addr_width=16
)
```

#### Methods

##### `set_randomizer(randomizer)`
Swap the FlexRandomizer that controls PSEL and PENABLE delay.

```python
timing_randomizer = FlexRandomizer({
    'psel': ([(0, 0), (1, 5)], [6, 1]),      # Mostly immediate PSEL
    'penable': ([(0, 0), (1, 2)], [4, 1])    # Minimal PENABLE delay
})
master.set_randomizer(timing_randomizer)
```

##### `reset_bus()`
Drive all master outputs to idle and flush the transaction queue.

```python
await master.reset_bus()
```

##### `send(transaction)`
Queue a packet for transmission and return immediately — the driver works through the queue on its own.

**Parameters:**
- `transaction`: APBPacket to transmit

```python
packet = APBPacket(pwrite=1, paddr=0x100, pwdata=0xDEADBEEF)
await master.send(packet)
```

##### `busy_send(transaction)`
Queue a packet and block until it completes. Use it when the next line of your test depends on the result.

```python
await master.busy_send(packet)  # Blocks until transaction completes
```

#### Transaction Pipeline

Every queued packet goes through the same four steps:
1. **Queue Management**: packets wait in line; the driver pulls the next one when the bus goes idle
2. **Signal Setup**: address, write data, and control driven for the setup phase
3. **Protocol Phases**: PSEL first, PENABLE a cycle (or more, per the randomizer) later
4. **Completion**: wait for PREADY, then sample PRDATA and PSLVERR into the packet

## Usage Patterns

### Basic Monitor Setup

The monitor starts watching as soon as it's constructed — you register a callback and let the clock run.

```python
import cocotb
from cocotb.triggers import RisingEdge, Timer
from CocoTBFramework.components.apb.apb_components import APBMonitor

@cocotb.test()
async def monitor_test(dut):
    # Create monitor
    monitor = APBMonitor(
        entity=dut,
        title="Protocol_Monitor", 
        prefix="apb_",
        clock=dut.clk,
        bus_width=32
    )
    
    # Add callback for transaction observation
    def transaction_callback(packet):
        print(f"Observed: {packet.formatted(compact=True)}")
    
    monitor.add_callback(transaction_callback)
    
    # Monitor runs automatically
    await Timer(1000, units='ns')
```

### Master-Slave Communication

Two components, two prefixes, one DUT wiring them together:

```python
async def master_slave_test(dut):
    # Create master and slave
    master = APBMaster(dut, "Master", "m_apb_", dut.clk)
    slave = APBSlave(dut, "Slave", "s_apb_", dut.clk, registers=[0] * 256)
    
    # Reset both components
    await master.reset_bus()
    await slave.reset_bus()
    
    # Write operation
    write_packet = APBPacket(
        pwrite=1,
        paddr=0x100,
        pwdata=0x12345678,
        pstrb=0xF
    )
    await master.send(write_packet)
    
    # Read operation
    read_packet = APBPacket(
        pwrite=0,
        paddr=0x100
    )
    await master.send(read_packet)
    
    # Wait for completion
    while master.transfer_busy:
        await RisingEdge(dut.clk)
```

### Advanced Timing Configuration

A timing profile is just a FlexRandomizer config, so changing personalities mid-test is a method call. Build a fast profile for bring-up and a nasty one for when you've learned to trust the DUT.

```python
def setup_timing_profiles():
    # Fast profile for performance testing
    fast_profile = FlexRandomizer({
        'psel': ([(0, 0)], [1]),           # No PSEL delay
        'penable': ([(0, 0)], [1]),        # No PENABLE delay
        'ready': ([(0, 0)], [1]),          # Immediate ready
        'error': ([(0, 0)], [1])           # No errors
    })
    
    # Stress profile for robustness testing
    stress_profile = FlexRandomizer({
        'psel': ([(0, 0), (1, 10)], [3, 1]),     # Variable PSEL delay
        'penable': ([(0, 1), (2, 5)], [2, 1]),   # Variable PENABLE delay
        'ready': ([(0, 5), (10, 20)], [4, 1]),   # Variable ready delay
        'error': ([(0, 0), (1, 1)], [10, 1])     # 10% error rate
    })
    
    return fast_profile, stress_profile

async def timing_test(dut):
    fast_profile, stress_profile = setup_timing_profiles()
    
    master = APBMaster(dut, "Master", "apb_", dut.clk)
    slave = APBSlave(dut, "Slave", "apb_", dut.clk, registers=[0] * 1024)
    
    # Test with fast timing
    master.set_randomizer(fast_profile)
    slave.set_randomizer(fast_profile)
    
    # Run fast test sequence
    await run_test_sequence(master, fast_transactions)
    
    # Switch to stress timing
    master.set_randomizer(stress_profile)
    slave.set_randomizer(stress_profile)
    
    # Run stress test sequence
    await run_test_sequence(master, stress_transactions)
```

### Error Injection Testing

Two error sources on display here: random PSLVERR from the slave's `error` bins, and deterministic errors from `error_overflow` when addresses run past the register file.

```python
async def error_injection_test(dut):
    # Create slave with error injection
    error_randomizer = FlexRandomizer({
        'ready': ([(1, 3), (5, 10)], [3, 1]),
        'error': ([(0, 0), (1, 1)], [4, 1])  # 20% error rate
    })
    
    slave = APBSlave(
        dut, "Error_Slave", "apb_", dut.clk,
        registers=[0] * 256,
        randomizer=error_randomizer,
        error_overflow=True
    )
    
    master = APBMaster(dut, "Master", "apb_", dut.clk)
    
    # Test normal addresses
    for addr in range(0, 64, 4):
        packet = APBPacket(pwrite=1, paddr=addr, pwdata=addr*2)
        await master.send(packet)
    
    # Test overflow addresses (should generate errors)
    for addr in range(0x1000, 0x1040, 4):
        packet = APBPacket(pwrite=1, paddr=addr, pwdata=0xBAADF00D)
        await master.send(packet)
```

### Register Verification

Walk patterns through the register file, then dump the slave's memory to see what actually landed:

```python
async def register_verification(dut):
    slave = APBSlave(dut, "Register_Slave", "apb_", dut.clk, registers=[0] * 1024)
    master = APBMaster(dut, "Master", "apb_", dut.clk)
    
    # Test register read/write
    test_patterns = [0x00000000, 0xFFFFFFFF, 0x55555555, 0xAAAAAAAA]
    
    for i, pattern in enumerate(test_patterns):
        addr = i * 4
        
        # Write pattern
        write_packet = APBPacket(pwrite=1, paddr=addr, pwdata=pattern)
        await master.send(write_packet)
        
        # Read back
        read_packet = APBPacket(pwrite=0, paddr=addr)
        await master.send(read_packet)
        
        # Verify in slave memory
        await Timer(100, units='ns')
        slave.dump_registers()
```

### Performance Testing

Pin every delay to zero and push a thousand transfers through. APB's two-phase handshake caps you at one transfer per two cycles no matter what, so this really measures your BFM/DUT loop — still useful when you're comparing configurations.

```python
async def performance_test(dut):
    # Configure for maximum performance
    fast_randomizer = FlexRandomizer({
        'psel': ([(0, 0)], [1]),
        'penable': ([(0, 0)], [1]),
        'ready': ([(0, 0)], [1]),
        'error': ([(0, 0)], [1])
    })
    
    master = APBMaster(dut, "Perf_Master", "apb_", dut.clk, randomizer=fast_randomizer)
    slave = APBSlave(dut, "Perf_Slave", "apb_", dut.clk, registers=[0] * 1024, randomizer=fast_randomizer)
    
    # Measure transaction throughput
    start_time = get_sim_time('ns')
    
    # Send 1000 back-to-back transactions
    for i in range(1000):
        packet = APBPacket(pwrite=1, paddr=(i*4) % 1024, pwdata=i)
        await master.send(packet)
    
    # Wait for completion
    while master.transfer_busy:
        await RisingEdge(dut.clk)
    
    end_time = get_sim_time('ns')
    duration = end_time - start_time
    
    print(f"1000 transactions completed in {duration} ns")
    print(f"Throughput: {1000 * 1e9 / duration:.2f} transactions/second")
```

## Integration with Framework

### Memory Model Integration

The slave doesn't fake read data — it sits on the framework's shared MemoryModel:

```python
# Memory model provides:
# - Byte-level access control
# - Strobe mask support
# - Access tracking and coverage
# - Boundary checking
# - Memory expansion
```

### Packet Integration

Everything on the bus is an `APBPacket`, so all the base-class machinery applies:

```python
# Automatic field extraction and validation
# Protocol compliance checking
# Transaction correlation and tracking
```

### Randomization Integration

Timing comes from FlexRandomizer, the same weighted-bin engine the other protocol families use:

```python
# Configurable delay distributions
# Error injection patterns
# Protocol timing stress testing
```

## Best Practices

### 1. **Use Appropriate Randomization**
Bring tests up with delays pinned near zero — a waveform you can read beats coverage you can't explain. Turn the knobs once it passes.

```python
# Development/debug: minimal delays
debug_randomizer = FlexRandomizer({
    'psel': ([(0, 0)], [1]),
    'penable': ([(0, 0)], [1]),
    'ready': ([(0, 1)], [1])
})

# Stress testing: variable delays
stress_randomizer = FlexRandomizer({
    'psel': ([(0, 0), (1, 10)], [7, 1]),
    'penable': ([(0, 1), (2, 5)], [3, 1]),
    'ready': ([(0, 5), (10, 25)], [5, 1])
})
```

### 2. **Handle Optional Signals**
If the DUT doesn't export PSTRB or PSLVERR the component still binds, but the attribute won't exist. Guard every access.

```python
# Always check signal presence
if slave.is_signal_present('PSLVERR'):
    # Handle slave error
    pass

if master.is_signal_present('PSTRB'):
    # Use write strobes
    packet.pstrb = 0xF
```

### 3. **Reset Components Properly**
Idle the buses first, then restore register state. Same order, every time.

```python
# Reset in correct order
await master.reset_bus()
await slave.reset_bus()
slave.reset_registers()
```

### 4. **Monitor Transaction Completion**
`busy_send()` when you need the result before moving on; `send()` plus polling `transfer_busy` when you're exercising the pipeline.

```python
# For performance-critical tests
await master.busy_send(packet)

# For pipelined operation
await master.send(packet)
while master.transfer_busy:
    await RisingEdge(dut.clk)
```

### 5. **Use Memory Dumps for Debug**
When a readback mismatches, dump the slave's memory before you open the waveform viewer. Nine times out of ten the answer is already in the log.

```python
# Regular memory verification
slave.dump_registers()

# After test completion
print(f"Slave processed {slave.count} transactions")
```

Three components, one packet type, one randomizer — that's the whole toolbox. The `apb_packet.py` and `apb_sequence.py` pages cover what to feed it.

---
