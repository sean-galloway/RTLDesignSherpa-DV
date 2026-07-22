# AXIS5 Component Classes

The AXIS5 classes are the AXIS4 classes with the two AMBA5 additions wired in: TWAKEUP for power-state coordination and TPARITY for per-byte data protection. They inherit directly from their AXIS4 counterparts, so every AXIS4 API keeps working — the AXI5-Stream extras are purely additive.

## AXIS5Master

The stream master, extended to drive TWAKEUP ahead of transfers and to generate TPARITY on outgoing data.

### Class Signature

```python
class AXIS5Master(AXISMaster):
    def __init__(self, dut, title, prefix, clock, field_config=None,
                 timeout_cycles=1000, mode='skid',
                 bus_name='', pkt_prefix='',
                 multi_sig=False, randomizer=None, memory_model=None,
                 log=None, super_debug=False, pipeline_debug=False,
                 signal_map=None, enable_wakeup=True, enable_parity=False,
                 wakeup_cycles=3, **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `dut` | object | Device under test | (required) |
| `title` | str | Component title/name | (required) |
| `prefix` | str | Bus prefix (e.g., `"m_axis5_"`) | (required) |
| `clock` | Signal | Clock signal | (required) |
| `field_config` | FieldConfig | Field configuration (auto-created if None) | `None` |
| `timeout_cycles` | int | Maximum cycles to wait for ready | `1000` |
| `mode` | str | Protocol mode (`'skid'`, `'blocking'`, etc.) | `'skid'` |
| `bus_name` | str | Bus/channel name | `''` |
| `pkt_prefix` | str | Packet field prefix | `''` |
| `multi_sig` | bool | Whether using multi-signal mode | `False` |
| `randomizer` | object | Optional randomizer for timing | `None` |
| `memory_model` | object | Optional memory model | `None` |
| `log` | Logger | Logger instance | `None` |
| `super_debug` | bool | Enable detailed debugging | `False` |
| `pipeline_debug` | bool | Enable pipeline debugging | `False` |
| `signal_map` | dict | Optional manual signal mapping | `None` |
| `enable_wakeup` | bool | Drive TWAKEUP signaling | `True` |
| `enable_parity` | bool | Generate TPARITY on outgoing data | `False` |
| `wakeup_cycles` | int | Cycles TWAKEUP stays asserted ahead of a transfer | `3` |

### Key Methods

#### `send_packet(packet) -> bool`

Sends one AXIS5 packet, handling wakeup assertion and parity calculation automatically.

| Parameter | Type | Description |
|-----------|------|-------------|
| `packet` | AXIS5Packet | Packet to send |

**Returns**: `True` if successful, `False` if timeout.

#### `request_wakeup()`

Arms wakeup for the next transfer — TWAKEUP is asserted for `wakeup_cycles` clock cycles ahead of the next `send_packet()` call.

#### `send_stream_data_with_wakeup(data_list, id=0, dest=0, user=0, auto_last=True, strb_list=None) -> bool`

Sends a list of data values as a stream, asserting TWAKEUP automatically at the start of the transfer.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `data_list` | List[int] | List of data values to send | (required) |
| `id` | int | Stream ID for all transfers | `0` |
| `dest` | int | Destination for all transfers | `0` |
| `user` | int | User signal for all transfers | `0` |
| `auto_last` | bool | Automatically set TLAST on final transfer | `True` |
| `strb_list` | List[int] | Optional list of strobe values | `None` |

**Returns**: `True` if all packets sent successfully.

#### `send_single_beat_axis5(data, last=1, id=0, dest=0, user=0, strb=None, wakeup=False) -> bool`

Sends a single AXIS5 beat, with wakeup on request.

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `data` | int | Data value | (required) |
| `last` | int | TLAST value | `1` |
| `id` | int | Stream ID | `0` |
| `dest` | int | Destination | `0` |
| `user` | int | User signal | `0` |
| `strb` | int | Strobe value (auto-generated if None) | `None` |
| `wakeup` | bool | Assert TWAKEUP for this beat | `False` |

#### `inject_parity_error(enable=True)`

Turns parity error injection on or off — this is how you exercise the DUT's error handling. While enabled, every packet sent through `send_packet` (and the stream/single-beat helpers that build on it) has its odd-parity TPARITY value corrupted — bit 0 flipped — before it's driven, and the `parity_errors_generated` counter ticks up once per corrupted packet. Only effective when `enable_parity` is `True`; call `inject_parity_error(enable=False)` to go back to correct parity.

#### `is_wakeup_active() -> bool`

True while TWAKEUP is asserted.

#### `get_stats() -> Dict`

All the inherited AXIS4 statistics, plus the AXIS5 counters.

**Returns**: Dictionary with all inherited AXIS4 statistics plus:

| Key | Type | Description |
|-----|------|-------------|
| `wakeup_enabled` | bool | Whether wakeup is enabled |
| `parity_enabled` | bool | Whether parity is enabled |
| `wakeup_events` | int | Number of wakeup assertions |
| `parity_errors_generated` | int | Number of parity errors injected |
| `wakeup_active` | bool | Current wakeup state |
| `wakeup_pending` | bool | Whether wakeup is pending |

### Usage Examples

```python
# Example 1: Basic master with wakeup
master = AXIS5Master(
    dut, "Master", "m_axis5_", clk,
    enable_wakeup=True, enable_parity=False, wakeup_cycles=3
)
await master.send_single_beat_axis5(0xDEADBEEF, last=1, wakeup=True)

# Example 2: Stream with auto wakeup and parity
master = AXIS5Master(
    dut, "Master", "m_axis5_", clk,
    enable_wakeup=True, enable_parity=True
)
await master.send_stream_data_with_wakeup(
    [0x11111111, 0x22222222, 0x33333333],
    id=1, auto_last=True
)

# Example 3: Parity error injection
master.inject_parity_error(enable=True)
await master.send_single_beat_axis5(0xABCDEF01, last=1)
master.inject_parity_error(enable=False)
```

---

## AXIS5Slave

The stream slave, extended to watch TWAKEUP and to verify TPARITY on incoming data.

Packet capture — and all TREADY driving — comes from the GAXI receive pipeline inherited through `AXISSlave`. AXIS5 adds TPARITY verification on top via the same packet callback hook that `AXISSlave` uses for frame tracking, checking **odd** parity per byte to match `AXIS5Packet.calculate_parity()`.

`_build_packet` is overridden so the pipeline constructs real `AXIS5Packet` instances carrying this slave's `enable_wakeup` / `enable_parity` settings and the data width taken from the field config. The parity check can therefore call `packet.check_parity()` directly instead of recomputing odd parity from raw field values.

### Class Signature

```python
class AXIS5Slave(AXISSlave):
    def __init__(self, dut, title, prefix, clock, field_config=None,
                 timeout_cycles=1000, mode='skid',
                 bus_name='', pkt_prefix='', multi_sig=False,
                 randomizer=None, memory_model=None, log=None,
                 super_debug=False, pipeline_debug=False,
                 signal_map=None, enable_wakeup=True, enable_parity=False,
                 **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `dut` | object | Device under test | (required) |
| `title` | str | Component title/name | (required) |
| `prefix` | str | Bus prefix (e.g., `"s_axis5_"`) | (required) |
| `clock` | Signal | Clock signal | (required) |
| `field_config` | FieldConfig | Field configuration (auto-created if None) | `None` |
| `timeout_cycles` | int | Maximum cycles for operations | `1000` |
| `mode` | str | Protocol mode | `'skid'` |
| `bus_name` | str | Bus/channel name | `''` |
| `pkt_prefix` | str | Packet field prefix | `''` |
| `multi_sig` | bool | Multi-signal mode | `False` |
| `randomizer` | object | Optional timing randomizer | `None` |
| `memory_model` | object | Optional memory model | `None` |
| `log` | Logger | Logger instance | `None` |
| `super_debug` | bool | Detailed debugging | `False` |
| `pipeline_debug` | bool | Pipeline debugging | `False` |
| `signal_map` | dict | Manual signal mapping | `None` |
| `enable_wakeup` | bool | Enable TWAKEUP detection | `True` |
| `enable_parity` | bool | Enable TPARITY checking | `False` |

### Key Methods

#### `is_wakeup_active() -> bool`

True while TWAKEUP is detected as asserted.

#### `get_last_wakeup_time() -> Optional[float]`

Simulation timestamp (in ns) of the most recent wakeup event.

#### `get_stats() -> Dict`

The inherited AXIS4 statistics, plus wakeup and parity bookkeeping.

**Returns**: Dictionary with all inherited AXIS4 statistics plus:

| Key | Type | Description |
|-----|------|-------------|
| `wakeup_enabled` | bool | Whether wakeup detection is enabled |
| `parity_enabled` | bool | Whether parity checking is enabled |
| `wakeup_events` | int | Number of wakeup events detected |
| `wakeup_active` | bool | Current wakeup state |
| `last_wakeup_time` | float | Timestamp of last wakeup (ns) |
| `parity_errors_detected` | int | Number of parity errors detected |
| `parity_checks_passed` | int | Number of parity checks passed |
| `parity_error_rate` | float | Ratio of errors to total checks |

### Usage Examples

```python
# Example 1: Basic slave with parity checking
slave = AXIS5Slave(
    dut, "Slave", "s_axis5_", clk,
    enable_wakeup=True, enable_parity=True
)

# After receiving data, check parity statistics
stats = slave.get_stats()
assert stats['parity_errors_detected'] == 0
print(f"Parity checks passed: {stats['parity_checks_passed']}")

# Example 2: Wakeup monitoring
slave = AXIS5Slave(dut, "Slave", "s_axis5_", clk, enable_wakeup=True)
# Wakeup monitoring starts automatically in background
# ...run test...
print(f"Wakeup events: {slave.wakeup_events}")
print(f"Last wakeup at: {slave.get_last_wakeup_time()} ns")
```

---

## AXIS5Monitor

The passive monitor — observes TWAKEUP and verifies TPARITY without touching the handshake.

Transactions are captured by the GAXI receive loop inherited through `AXISMonitor` (which extends `GAXIMonitor`); `AXIS5Monitor` has no receive loop of its own. AXIS5 layers TPARITY verification and AXIS5 protocol checks on top via the same `_axis_packet_observed` hook that `AXISMonitor` uses for TLAST frame tracking.

`_build_packet` is overridden so the pipeline constructs real `AXIS5Packet` instances carrying this monitor's `enable_wakeup` / `enable_parity` settings and the data width taken from the field config. That is what lets the parity check simply call `packet.check_parity()` instead of recomputing odd parity from raw field values.

### Class Signature

```python
class AXIS5Monitor(AXISMonitor):
    def __init__(self, dut, title, prefix, clock, field_config=None,
                 is_slave=False, mode='skid',
                 bus_name='', pkt_prefix='', multi_sig=False,
                 log=None, super_debug=False, signal_map=None,
                 enable_wakeup=True, enable_parity=False, **kwargs)
```

### Constructor Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `dut` | object | Device under test | (required) |
| `title` | str | Component title/name | (required) |
| `prefix` | str | Bus prefix | (required) |
| `clock` | Signal | Clock signal | (required) |
| `field_config` | FieldConfig | Field configuration (auto-created if None) | `None` |
| `is_slave` | bool | True if monitoring slave side | `False` |
| `mode` | str | Protocol mode | `'skid'` |
| `bus_name` | str | Bus/channel name | `''` |
| `pkt_prefix` | str | Packet field prefix | `''` |
| `multi_sig` | bool | Multi-signal mode | `False` |
| `log` | Logger | Logger instance | `None` |
| `super_debug` | bool | Detailed debugging | `False` |
| `signal_map` | dict | Manual signal mapping | `None` |
| `enable_wakeup` | bool | Enable TWAKEUP observation | `True` |
| `enable_parity` | bool | Enable TPARITY verification | `False` |

### Key Methods

#### `get_wakeup_history() -> List[Dict]`

The complete TWAKEUP timeline.

**Returns**: List of dictionaries with `'time'` (float, ns) and `'type'` (`'assert'` or `'deassert'`).

#### `is_wakeup_active() -> bool`

True while TWAKEUP is active.

#### `get_parity_stats() -> Dict`

The parity pass/fail counters.

**Returns**:

| Key | Type | Description |
|-----|------|-------------|
| `parity_enabled` | bool | Whether parity verification is enabled |
| `parity_errors` | int | Number of parity errors observed |
| `parity_passed` | int | Number of parity checks passed |
| `total_checks` | int | Total parity checks performed |
| `error_rate` | float | Ratio of errors to total checks |

#### `get_wakeup_stats() -> Dict`

Wakeup event and violation counters.

**Returns**:

| Key | Type | Description |
|-----|------|-------------|
| `wakeup_enabled` | bool | Whether wakeup observation is enabled |
| `wakeup_events` | int | Number of wakeup events observed |
| `wakeup_violations` | int | Protocol violations related to wakeup |
| `wakeup_active` | bool | Current wakeup state |
| `wakeup_history_count` | int | Number of wakeup history entries |

#### `get_stats() -> Dict`

The inherited AXIS4 statistics plus a roll-up of the AXIS5 checks.

**Returns**: Dictionary with inherited AXIS4 statistics plus:

| Key | Type | Description |
|-----|------|-------------|
| `axis5_protocol_violations` | int | AXIS5-specific violations detected |
| `parity_stats` | Dict | Result of `get_parity_stats()` |
| `wakeup_stats` | Dict | Result of `get_wakeup_stats()` |

### Usage Examples

```python
# Example 1: Monitor with full observation
monitor = AXIS5Monitor(
    dut, "Monitor", "s_axis5_", clk,
    is_slave=True, enable_wakeup=True, enable_parity=True
)

# After test completion, analyze results
stats = monitor.get_stats()
print(f"Packets observed: {stats.get('packets_observed', 0)}")
print(f"AXIS5 violations: {stats['axis5_protocol_violations']}")
print(f"Parity error rate: {stats['parity_stats']['error_rate']:.4f}")

# Example 2: Wakeup timeline analysis
history = monitor.get_wakeup_history()
for event in history:
    print(f"Wakeup {event['type']} at {event['time']}ns")

# Example 3: Dual-side monitoring
master_mon = AXIS5Monitor(
    dut, "MasterMon", "m_axis5_", clk,
    is_slave=False, enable_wakeup=True, enable_parity=True
)
slave_mon = AXIS5Monitor(
    dut, "SlaveMon", "s_axis5_", clk,
    is_slave=True, enable_wakeup=True, enable_parity=True
)
```

---

## Factory Functions

Use the factories — they're the recommended way to build AXIS5 components. Each one creates the field configuration for you and returns a dictionary holding the component under a few convenience aliases, so testbench infrastructure can grab whichever key it expects.

### `create_axis5_master(dut, clock, prefix, data_width, id_width, dest_width, user_width, enable_wakeup, enable_parity, wakeup_cycles, log, **kwargs) -> Dict`

**Returns**: `{'T': master, 'interface': master, 'master': master}`

### `create_axis5_slave(dut, clock, prefix, data_width, id_width, dest_width, user_width, enable_wakeup, enable_parity, log, **kwargs) -> Dict`

**Returns**: `{'T': slave, 'interface': slave, 'slave': slave}`

### `create_axis5_monitor(dut, clock, prefix, data_width, id_width, dest_width, user_width, is_slave, enable_wakeup, enable_parity, log, **kwargs) -> Dict`

**Returns**: `{'T': monitor, 'interface': monitor, 'monitor': monitor}`

### `create_axis5_testbench(dut, clock, master_prefix, slave_prefix, data_width, id_width, dest_width, user_width, enable_wakeup, enable_parity, log, **kwargs) -> Dict`

Builds a complete bench in one call: master, slave, and monitors for both sides.

**Returns**: Dictionary with keys `'master'`, `'slave'`, `'master_monitor'`, `'slave_monitor'` (each present only if corresponding DUT signals exist).

### `create_simple_axis5_master(dut, clock, prefix, data_width, enable_wakeup, enable_parity, log, **kwargs) -> AXIS5Master`

A master with minimal sideband signals (no TID, TDEST, TUSER) — the data-pipe configuration.

### `create_simple_axis5_slave(dut, clock, prefix, data_width, enable_wakeup, enable_parity, log, **kwargs) -> AXIS5Slave`

The matching slave, with minimal sideband signals.

### Utility Functions

#### `get_axis5_signal_map(prefix, direction) -> Dict`

The standard AXIS5 signal name mapping, for when you need to override signal resolution manually.

#### `print_axis5_stats_to_log(components, log)`

Prints statistics for all AXIS5 components to a logger.

#### `get_axis5_stats_summary(components) -> Dict`

Aggregates statistics from all AXIS5 components into one summary.
