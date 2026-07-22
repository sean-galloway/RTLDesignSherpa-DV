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

# gaxi_command_handler.py

The piece that connects a GAXI master to a GAXI slave inside the testbench. It runs one of two ways: forwarding mode pushes the master's transactions down to the slave, and response-generation mode answers from the slave side — inventing sequential read data when the memory model has nothing for that address, so the test stays predictable either way.

## Overview

`GAXICommandHandler` owns a processing task that moves transactions between one master and one slave. In forwarding mode it watches the master's outbound traffic, resolves dependencies between transactions, and hands each one to the slave in an order that respects those dependencies. In response-generation mode it works the other direction: it watches the slave's receive queue and builds responses — writes land in the memory model, reads come back out of it, and a read that hits an address the model has never seen gets made-up sequential data instead of an error.

That fallback is the feature you'll lean on most. Tests get deterministic read data without anyone preloading memory, and the stats tell you afterwards how much of the traffic was real versus invented.

### Key Features
- **Two modes**: forward master→slave traffic, or generate slave→master responses
- **Sequential read data**: predictable values for addresses the memory model doesn't cover
- **Format-tolerant field extraction**: reads both GAXI-style field dictionaries and APB-style attribute packets
- **Memory model with fallback**: unmapped reads produce generated data, not failures
- **Dependency tracking**: transactions declare what they wait on, and the handler enforces it
- **Statistics**: transaction counts, latency, memory operations, sequential-read totals

## Core Class

### GAXICommandHandler

One handler per master/slave pair. It owns the background processing task and all the bookkeeping — pending, completed, and generated transactions — in whichever direction the mode selects.

#### Constructor

```python
GAXICommandHandler(master, slave, memory_model=None, log=None,
                   response_generation_mode=False, **kwargs)
```

**Parameters:**
- `master`: Master component instance
- `slave`: Slave component instance
- `memory_model`: Optional memory model for transactions (uses base MemoryModel)
- `log`: Logger instance (defaults to master's logger)
- `response_generation_mode`: If True, generate responses; if False, forward transactions
- `**kwargs`: Additional configuration options

```python
# Forwarding mode (master → slave)
handler = GAXICommandHandler(
    master=gaxi_master,
    slave=gaxi_slave,
    memory_model=memory_model,
    log=log,
    response_generation_mode=False
)

# Response generation mode (slave → master)
handler = GAXICommandHandler(
    master=gaxi_master,
    slave=gaxi_slave,
    memory_model=memory_model,
    log=log,
    response_generation_mode=True
)
```

#### Core Properties

- `master`: Master component
- `slave`: Slave component
- `memory_model`: Memory model for transactions
- `response_generation_mode`: Current operational mode
- `sequential_data_counter`: Counter for sequential data generation
- `pending_transactions`: Dictionary of pending transactions
- `completed_transactions`: Dictionary of completed transactions
- `pending_responses`: Dictionary of pending responses (response mode)
- `generated_responses`: Dictionary of generated responses (response mode)

## Lifecycle Management

### `async start()`

Start the command handler processing task. Nothing moves until this runs.

**Returns:** Self for chaining

```python
# Start the handler
await handler.start()
```

### `async stop()`

Stop the command handler processing task.

**Returns:** Self for chaining

```python
# Stop the handler
await handler.stop()
```

## Transaction Processing (Forwarding Mode)

### `async _forward_transactions()`

Walk the master's outbound transactions and send each one to the slave once its dependencies have cleared.

**Internal method** - called automatically in forwarding mode

### `_is_dependency_satisfied(txn_id)`

Check whether everything a transaction waits on has completed.

**Parameters:**
- `txn_id`: Transaction ID to check

**Returns:** True if dependencies are satisfied

### `async _send_to_slave(txn_id)`

Hand a single transaction to the slave. Assumes dependencies were already checked.

**Parameters:**
- `txn_id`: Transaction ID to send

## Response Generation (Response Mode)

### `async _generate_response_for_transaction(cmd_transaction)`

Build a response for a command the slave received.

**Parameters:**
- `cmd_transaction`: Command transaction to respond to

**What it does:**
- Reads pull from the memory model when the model has data for that address
- Otherwise the value comes from the sequential generator, so the test still knows what to expect
- Field extraction copes with both packet formats (see below)
- Failures get logged and counted rather than propagated — one malformed transaction doesn't stall the queue

```python
# This method is called automatically in response generation mode
# when slave receives transactions
```

### `_generate_sequential_data(address)`

Produce the invented read value for an address the memory model doesn't cover.

**Parameters:**
- `address`: Address being read

**Returns:** Sequential data value

**Algorithm:**
- Combines a per-generation counter with the word-aligned address (`address >> 2`)
- Keeps results inside the 32-bit data range
- Deterministic, so the test can compute what it expects

```python
# Generates predictable data patterns:
# Address 0x1000 → 0x10000400 (first read)
# Address 0x1004 → 0x10000401 (next read)
# Address 0x1000 → 0x10000800 (later read)
```

## Field Extraction and Response Handling

Packets arrive in two shapes in this framework: GAXI packets carry their fields in a dictionary, APB-style packets carry them as plain attributes. These two helpers hide that difference — they try the primary name, an alternate name, lowercase variants, and finally a default. You write the handler-facing code once and stop caring which side produced the packet.

### `_extract_field_value(transaction, field_name, alt_field_name=None, default=0)`

Extract a field value from a transaction supporting both storage methods.

**Parameters:**
- `transaction`: Transaction object
- `field_name`: Primary field name
- `alt_field_name`: Alternative field name
- `default`: Default value if field not found

**Returns:** Field value or default

**Supports:**
- GAXI-style fields dictionary
- APB-style attributes
- Lowercase field names
- Alternative field names

```python
# Extracts from multiple field formats:
pwrite = handler._extract_field_value(transaction, 'pwrite', 'cmd_pwrite')
address = handler._extract_field_value(transaction, 'paddr', 'cmd_paddr')
data = handler._extract_field_value(transaction, 'pwdata', 'cmd_pwdata')
```

### `_set_response_field(response_packet, field_name, alt_field_name=None, value=0)`

Set a field value in a response packet supporting both storage methods.

**Parameters:**
- `response_packet`: Response packet to modify
- `field_name`: Primary field name
- `alt_field_name`: Alternative field name
- `value`: Value to set

```python
# Sets response fields in multiple formats:
handler._set_response_field(response_packet, 'prdata', 'rsp_prdata', read_data)
handler._set_response_field(response_packet, 'pslverr', 'rsp_pslverr', 0)
```

## Memory Operations

### `async _handle_memory_write(address, data, strobe)`

Write into the memory model with error handling.

**Parameters:**
- `address`: Target address
- `data`: Data to write
- `strobe`: Write strobe mask

**Returns:** Success status

```python
# Memory write with proper address masking and error handling
success = await handler._handle_memory_write(0x1000, 0xDEADBEEF, 0xF)
```

### `async _handle_memory_read(address)`

Read from the memory model with error handling.

**Parameters:**
- `address`: Address to read from

**Returns:** Tuple of (success, data)

```python
# Memory read with automatic fallback to sequential data
success, data = await handler._handle_memory_read(0x1000)
if not success:
    # Will use sequential data generation
    pass
```

## Sequence Processing

### `async process_sequence(sequence)`

Run a whole GAXISequence through the master/slave pair.

**Parameters:**
- `sequence`: GAXISequence to process

**Returns:** Dictionary of responses by transaction index

**What it does:**
- Waits on each transaction's dependencies before issuing it
- Blocks until the sequence completes
- Keys the response map by sequence index, so `response_map[i]` lines up with the i-th transaction you added

```python
# Process sequence with dependencies
sequence = GAXISequence("test_sequence")
sequence.add_data_transaction(0x1000)
sequence.add_data_transaction(0x2000, depends_on=0)

response_map = await handler.process_sequence(sequence)
print(f"Response 0: {response_map[0]}")
print(f"Response 1: {response_map[1]}")
```

## Statistics and Monitoring

### `get_stats()`

Everything the handler has been counting.

**Returns:** Dictionary with statistics including:
- Transaction counts and timing
- Memory operation statistics
- Sequential data generation stats
- Component statistics
- Error tracking

```python
stats = handler.get_stats()
print(f"Completed transactions: {stats['completed_transactions']}")
print(f"Sequential reads: {stats['sequential_reads']}")
print(f"Memory operations: {stats['memory_operations']}")
print(f"Average latency: {stats['avg_latency']} ns")
```

### `get_transaction_status(txn_id=None)`

Status of one transaction, or of all of them.

**Parameters:**
- `txn_id`: Transaction ID to check (None for all)

**Returns:** Transaction status information

```python
# Get status of all transactions
status = handler.get_transaction_status()
print(f"Pending: {status['pending']}")
print(f"Completed: {status['completed']}")

# Get status of specific transaction
specific_status = handler.get_transaction_status(txn_id)
```

### `reset()`

Reset the command handler to initial state.

```python
# Reset all tracking and statistics
handler.reset()
```

## Usage Patterns

### Basic Forwarding Setup

```python
async def setup_forwarding_handler():
    """Set up command handler for master→slave forwarding"""
    
    # Create memory model
    memory = MemoryModel(num_lines=1024, bytes_per_line=4, log=log)
    
    # Create handler in forwarding mode
    handler = GAXICommandHandler(
        master=gaxi_master,
        slave=gaxi_slave,
        memory_model=memory,
        log=log,
        response_generation_mode=False
    )
    
    # Start processing
    await handler.start()
    
    return handler

async def test_forwarding():
    handler = await setup_forwarding_handler()
    
    # Send transactions through master
    for i in range(10):
        packet = gaxi_master.create_packet(addr=0x1000 + i*4, data=i*0x100)
        await gaxi_master.send(packet)
    
    # Wait for completion
    while handler.get_transaction_status()['pending'] > 0:
        await RisingEdge(dut.clk)
    
    # Get statistics
    stats = handler.get_stats()
    log.info(f"Forwarding test completed: {stats}")
    
    await handler.stop()
```

### Response Generation Setup

Preload the memory with what you care about; the sequential generator covers everything else.

```python
async def setup_response_handler():
    """Set up command handler for slave→master response generation"""
    
    # Create memory model with initial data
    memory = MemoryModel(num_lines=1024, bytes_per_line=4, log=log)
    
    # Populate memory with test data
    for addr in range(0, 0x1000, 4):
        data = bytearray([(addr + i) & 0xFF for i in range(4)])
        memory.write(addr, data)
    
    # Create handler in response generation mode
    handler = GAXICommandHandler(
        master=gaxi_master,
        slave=gaxi_slave,
        memory_model=memory,
        log=log,
        response_generation_mode=True
    )
    
    await handler.start()
    return handler

async def test_response_generation():
    handler = await setup_response_handler()
    
    # Send commands to slave
    for i in range(10):
        # Write command
        write_cmd = create_write_command(addr=0x1000 + i*4, data=i*0x100)
        gaxi_slave._recvQ.append(write_cmd)
        
        # Read command
        read_cmd = create_read_command(addr=0x1000 + i*4)
        gaxi_slave._recvQ.append(read_cmd)
    
    # Wait for responses
    await Timer(1000, units='ns')
    
    # Check response statistics
    stats = handler.get_stats()
    log.info(f"Generated {stats['generated_responses']} responses")
    log.info(f"Sequential reads: {stats['sequential_reads']}")
    
    await handler.stop()
```

### Advanced Dependency Testing

```python
async def test_dependency_handling():
    """Test transaction dependency handling"""
    
    handler = await setup_forwarding_handler()
    
    # Create sequence with dependencies
    sequence = GAXISequence("dependency_test")
    
    # Transaction 0: Base transaction
    sequence.add_data_transaction(0x1000, delay=0)
    
    # Transaction 1: Depends on transaction 0
    sequence.add_data_transaction(0x2000, delay=0, depends_on=0)
    
    # Transaction 2: Also depends on transaction 0
    sequence.add_data_transaction(0x3000, delay=0, depends_on=0)
    
    # Transaction 3: Depends on transaction 1
    sequence.add_data_transaction(0x4000, delay=0, depends_on=1)
    
    # Process sequence with dependency resolution
    response_map = await handler.process_sequence(sequence)
    
    # Verify responses
    assert len(response_map) == 4
    log.info("Dependency test completed successfully")
    
    # Check dependency statistics
    stats = handler.get_stats()
    assert stats['dependency_violations'] == 0
    
    await handler.stop()
```

### Memory Integration Testing

Mapped reads come from memory, unmapped reads come from the generator — this test exercises both paths and then checks the stats to confirm which is which.

```python
async def test_memory_integration():
    """Test memory model integration with fallback"""
    
    # Create memory with limited data
    memory = MemoryModel(num_lines=64, bytes_per_line=4, log=log)
    
    # Only populate some addresses
    for addr in range(0x0000, 0x0100, 4):
        data = bytearray([addr & 0xFF, (addr >> 8) & 0xFF, 0x00, 0x00])
        memory.write(addr, data)
    
    handler = GAXICommandHandler(
        master=gaxi_master,
        slave=gaxi_slave,
        memory_model=memory,
        log=log,
        response_generation_mode=True
    )
    
    await handler.start()
    
    # Test memory reads (should use memory data)
    memory_read_cmd = create_read_command(addr=0x0010)
    gaxi_slave._recvQ.append(memory_read_cmd)
    
    # Test unmapped reads (should use sequential data)
    sequential_read_cmd = create_read_command(addr=0x8000)
    gaxi_slave._recvQ.append(sequential_read_cmd)
    
    await Timer(1000, units='ns')
    
    # Check statistics
    stats = handler.get_stats()
    log.info(f"Memory reads: {stats['memory_reads']}")
    log.info(f"Sequential reads: {stats['sequential_reads']}")
    
    await handler.stop()
```

### Performance Monitoring

```python
class PerformanceMonitor:
    def __init__(self, handler):
        self.handler = handler
        self.monitoring = True
        
    async def monitor_performance(self):
        """Continuously monitor handler performance"""
        while self.monitoring:
            await Timer(1000000, units='ns')  # Every 1ms
            
            stats = self.handler.get_stats()
            
            # Check performance metrics
            if stats['completed_transactions'] > 0:
                avg_latency = stats['avg_latency']
                if avg_latency > 10000:  # > 10µs
                    log.warning(f"High latency detected: {avg_latency:.1f}ns")
            
            # Check error rates
            if stats.get('dependency_violations', 0) > 0:
                log.warning(f"Dependency violations: {stats['dependency_violations']}")
            
            # Report throughput
            if stats['completed_transactions'] % 100 == 0:
                log.info(f"Processed {stats['completed_transactions']} transactions")

async def test_with_monitoring():
    handler = await setup_forwarding_handler()
    monitor = PerformanceMonitor(handler)
    
    # Start monitoring
    monitor_task = cocotb.start_soon(monitor.monitor_performance())
    
    # Run test
    await run_high_throughput_test(handler)
    
    # Stop monitoring
    monitor.monitoring = False
    monitor_task.kill()
    
    await handler.stop()
```

## Error Handling and Recovery

### Automatic Error Recovery

Response generation catches its own exceptions: the error gets logged with context, the error counters tick up, and the handler moves on to the next transaction. One bad packet doesn't take the queue down with it.

```python
try:
    # Process transaction with automatic error handling
    await handler._generate_response_for_transaction(transaction)
except Exception as e:
    # Handler automatically:
    # - Logs detailed error information
    # - Updates error statistics
    # - Continues processing other transactions
    # - Maintains system stability
    pass
```

### Field Extraction Fallbacks

The extraction helpers walk a fixed search order, so a packet from either side of the family works without special-casing.

```python
# Handler automatically tries multiple field extraction methods:
# 1. Fields dictionary (GAXI style)
# 2. Direct attributes (APB style)
# 3. Alternative field names
# 4. Lowercase versions
# 5. Returns default value if none found

value = handler._extract_field_value(
    transaction, 
    'paddr',           # Primary name
    'cmd_paddr',       # Alternative name
    default=0x0        # Safe default
)
```

### Memory Operation Fallbacks

```python
# For read operations:
# 1. Try memory model read
# 2. On failure, generate sequential data
# 3. Log the fallback for debugging
# 4. Continue operation seamlessly

success, data = await handler._handle_memory_read(address)
if not success:
    # Automatic fallback to sequential data generation
    data = handler._generate_sequential_data(address)
```

## Integration with Other Components

### Master Integration

Give the handler a master and it takes it from there — transactions the master sends are picked up and forwarded without further involvement from the test.

```python
# Handler integrates seamlessly with GAXIMaster
master = GAXIMaster(dut, "TestMaster", "", clock, field_config)
handler = GAXICommandHandler(master, slave, response_generation_mode=False)

# Transactions from master are automatically forwarded
await master.send(packet)
```

### Slave Integration

In response mode the handler lives on the slave's receive queue: whatever shows up there gets a response.

```python
# Handler monitors slave receive queue for transactions
slave = GAXISlave(dut, "TestSlave", "", clock, field_config)
handler = GAXICommandHandler(master, slave, response_generation_mode=True)

# Received transactions automatically generate responses
```

### Memory Model Integration

The plain base MemoryModel, used directly — no wrapper, no adapter. Pass one in or the handler works without memory at all (every read becomes sequential data).

```python
# Uses base MemoryModel directly for maximum compatibility
memory = MemoryModel(num_lines=1024, bytes_per_line=4, log=log)
handler = GAXICommandHandler(master, slave, memory_model=memory)

# Automatic memory operations with proper error handling
```

## Best Practices

### 1. **Pick the Right Mode**
```python
# Use forwarding mode for master→slave testing
handler = GAXICommandHandler(master, slave, response_generation_mode=False)

# Use response generation mode for slave→master testing
handler = GAXICommandHandler(master, slave, response_generation_mode=True)
```

### 2. **Give It a Memory Model**

Without one, every read returns invented data. That's fine for smoke tests; it's not fine for anything that checks read-after-write.

```python
# Always provide memory model for realistic testing
memory = MemoryModel(num_lines=1024, bytes_per_line=4, log=log)
handler = GAXICommandHandler(master, slave, memory_model=memory)
```

### 3. **Watch the Statistics**
```python
# Regular statistics monitoring
async def monitor_handler():
    while True:
        await Timer(1000000, units='ns')
        stats = handler.get_stats()
        if stats['error_count'] > 0:
            log.warning(f"Errors detected: {stats}")
```

### 4. **Validate Dependencies Up Front**

Cheaper to catch a broken dependency graph before the simulation runs than to debug a hung one.

```python
# Always validate dependencies in sequences
sequence.validate_dependencies()
response_map = await handler.process_sequence(sequence)
```

### 5. **Let Sequential Data Work for You**

Invented read data is a feature, not a wart: it's address-based and counter-based, so different addresses give different patterns and repeated reads keep moving. When a read value looks made up, check `sequential_reads` in the stats before blaming the DUT.

```python
# Sequential data generation provides predictable test patterns
# Address-based: Different addresses generate different patterns
# Counter-based: Each read increments the pattern
# Useful for debugging and verification
```

That covers the handler. Day to day you'll call `start()`, `process_sequence()`, and `get_stats()`; the underscore-prefixed machinery exists so the two modes can share one implementation, and most tests never touch it directly.
