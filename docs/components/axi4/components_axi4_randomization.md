# AXI4 Randomization

Unified AXI4 randomization infrastructure providing protocol-aware field value generation and timing delay management. Includes industry-specific profiles, constraint management, and integration with all AXI4 components.

## Overview

The AXI4 randomization module provides two primary classes:

- **AXI4RandomizationConfig** -- Protocol-level randomization for AXI4 field values (addresses, burst parameters, IDs, data patterns, response codes)
- **AXI4RandomizationManager** -- Unified manager that combines protocol and timing randomization with convenient configuration presets

Together these classes enable sophisticated constraint-random verification of AXI4 interfaces with support for compliance testing, performance stress testing, error injection, and industry-specific verification profiles.

---

## Supporting Types

### AXI4RandomizationProfile

```python
class AXI4RandomizationProfile(Enum)
```

Predefined randomization profiles for different verification scenarios.

| Value | Description |
|-------|-------------|
| `BASIC` | Default settings, moderate constraints |
| `COMPLIANCE` | Protocol-compliant, predictable patterns |
| `PERFORMANCE` | Large bursts, minimal delays, high throughput |
| `STRESS` | All burst types, error injection, variable timing |
| `AUTOMOTIVE` | Safety-critical, deterministic, conservative |
| `DATACENTER` | Cache-line aligned, large bursts, high throughput |
| `MOBILE` | Power-efficient, moderate bursts, balanced timing |
| `CUSTOM` | User-defined constraints |

### AXI4ProtocolMode

```python
class AXI4ProtocolMode(Enum)
```

AXI4 protocol operation modes.

| Value | Description |
|-------|-------------|
| `STANDARD` | Normal AXI4 operation |
| `EXCLUSIVE_ACCESS` | Exclusive access transactions |
| `LOCKED_ACCESS` | Locked access transactions |
| `CACHE_COHERENT` | Cache-coherent operation |
| `LOW_POWER` | Low-power mode |
| `HIGH_PERFORMANCE` | High-performance mode |

### AXI4ConstraintSet

```python
@dataclass
class AXI4ConstraintSet
```

Enhanced constraint set controlling all randomization parameters.

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `addr_min` | `int` | Minimum address | `0x1000` |
| `addr_max` | `int` | Maximum address | `0xFFFF000` |
| `addr_alignment` | `int` | Address alignment in bytes | `4` |
| `addr_ranges` | `List[Tuple[int, int]]` or `None` | Valid address ranges | `None` |
| `burst_len_min` | `int` | Minimum burst length (beats) | `1` |
| `burst_len_max` | `int` | Maximum burst length (beats) | `16` |
| `burst_len_weights` | `Dict[int, float]` or `None` | Weighted burst length selection | `None` |
| `burst_types` | `List[int]` | Allowed burst types | `[0, 1, 2]` |
| `burst_size_max` | `int` | Maximum burst size encoding | `3` |
| `id_min` | `int` | Minimum transaction ID | `0` |
| `id_max` | `int` | Maximum transaction ID | `15` |
| `id_weights` | `Dict[int, float]` or `None` | Weighted ID selection | `None` |
| `exclusive_access_rate` | `float` | Probability of exclusive access | `0.0` |
| `locked_access_rate` | `float` | Probability of locked access | `0.0` |
| `error_injection_rate` | `float` | Probability of error responses | `0.0` |
| `data_patterns` | `List[str]` | Data generation patterns | `['random', 'incremental', 'pattern']` |
| `strobe_patterns` | `List[str]` | Strobe generation patterns | `['all', 'partial', 'sparse']` |
| `min_delay_cycles` | `int` | Minimum inter-transaction delay | `0` |
| `max_delay_cycles` | `int` | Maximum inter-transaction delay | `10` |
| `ready_probability` | `float` | Probability of ready assertion | `0.8` |

---

## Classes

### AXI4RandomizationConfig

```python
class AXI4RandomizationConfig:
    def __init__(self, profile=AXI4RandomizationProfile.BASIC,
                 data_width=32, id_width=8, addr_width=32,
                 user_width=1, log=None)
```

Protocol-aware randomization for AXI4 field values with industry-specific profiles and intelligent constraint management.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `profile` | `AXI4RandomizationProfile` | Predefined randomization profile | `BASIC` |
| `data_width` | `int` | Data bus width in bits | `32` |
| `id_width` | `int` | ID field width in bits | `8` |
| `addr_width` | `int` | Address bus width in bits | `32` |
| `user_width` | `int` | User signal width in bits | `1` |
| `log` | `logging.Logger` | Logger instance | `None` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `profile` | `AXI4RandomizationProfile` | Active randomization profile |
| `constraints` | `AXI4ConstraintSet` | Active constraint set |
| `protocol_mode` | `AXI4ProtocolMode` | Current protocol mode |
| `master_mode` | `bool` | `True` for master, `False` for slave |
| `enabled_features` | `set` | Set of enabled advanced features |
| `stats` | `Dict[str, Any]` | Randomization statistics |

#### Core Methods

##### `randomize_fields(field_requests) -> Dict[str, Any]`

Randomize AXI4 fields according to constraints and protocol rules. This is the primary randomization entry point.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `field_requests` | `Dict[str, Any]` | Dictionary of field names and constraints |

**Returns:** `Dict[str, Any]` -- Dictionary of randomized field values.

The method applies:
1. Per-field randomization with type-specific intelligence (address alignment, burst constraints, etc.)
2. Cross-field protocol constraints (address/size alignment, burst boundary checks)
3. Industry-specific optimizations

##### `set_profile(profile)`

Change the active randomization profile and update constraints accordingly.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `profile` | `AXI4RandomizationProfile` | New profile to activate |

##### `set_data_width(width)`

Update the data width and reconfigure field definitions.

##### `set_master_mode(is_master)`

Configure for master or slave operation. Masters have error injection disabled by default; slaves default to 1% error rate.

##### `set_error_injection_rate(rate)`

Set the error injection rate (0.0 to 1.0) for response generation.

##### `set_exclusive_access_mode(enabled)`

Enable or disable exclusive access mode and associated constraints.

##### `set_burst_constraints(max_len=None, preferred_sizes=None)`

Set burst length constraints and preferred size weighting.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `max_len` | `int` or `None` | Maximum burst length |
| `preferred_sizes` | `List[int]` or `None` | Preferred burst sizes (higher weight) |

##### `enable_advanced_features()`

Enable advanced AXI4 features including exclusive access, locked access, and cache hints.

##### `enable_error_scenarios()`

Enable enhanced error injection scenarios with a 5% default rate.

##### `get_statistics() -> Dict[str, Any]`

Get comprehensive randomization statistics including profile info, protocol mode, and performance metrics.

##### `reset_statistics()`

Reset all statistics counters and caches.

---

### AXI4RandomizationManager

```python
class AXI4RandomizationManager:
    def __init__(self, protocol_config=None, timing_config=None,
                 channels=None, data_width=32, performance_mode='normal')
```

Unified manager combining protocol and timing randomization for AXI4 components.

**Parameters:**

| Name | Type | Description | Default |
|------|------|-------------|---------|
| `protocol_config` | `AXI4RandomizationConfig` or `None` | Protocol randomization config | `None` (creates default) |
| `timing_config` | `AXI4TimingConfig` or `None` | Timing randomization config | `None` (creates default) |
| `channels` | `List[str]` or `None` | AXI4 channels to configure | `['AW', 'W', 'B', 'AR', 'R']` |
| `data_width` | `int` | Data bus width in bits | `32` |
| `performance_mode` | `str` | Initial performance mode | `'normal'` |

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `protocol` | `AXI4RandomizationConfig` | Protocol randomization instance |
| `timing` | `AXI4TimingConfig` | Timing randomization instance |
| `channels` | `List[str]` | Configured channel list |
| `performance_mode` | `str` | Current performance mode |
| `stats` | `Dict[str, Any]` | Usage statistics |

#### Core Methods

##### `get_protocol_values(fields) -> Dict[str, Any]`

Get randomized protocol field values.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `fields` | `Dict[str, Any]` | Field names and constraints |

**Returns:** `Dict[str, Any]` -- Randomized field values.

##### `get_timing_delays(channels=None) -> Dict[str, Any]`

Get timing delay patterns for specified channels.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `channels` | `List[str]` or `None` | Channel names (uses default if `None`) |

**Returns:** `Dict[str, Any]` -- Timing configurations per channel.

##### `create_master_config(**kwargs) -> Dict[str, Any]`

Create optimized configuration for an AXI4 master. Sets master mode with zero error injection.

**Returns:** Dictionary with `protocol_randomizer`, `timing_randomizer`, and `timing_config` keys.

##### `create_slave_config(**kwargs) -> Dict[str, Any]`

Create optimized configuration for an AXI4 slave. Sets slave mode with 1% error injection.

**Returns:** Dictionary with `protocol_randomizer`, `timing_randomizer`, and `timing_config` keys.

##### `create_monitor_config(**kwargs) -> Dict[str, Any]`

Create optimized configuration for an AXI4 monitor. Includes only timing configuration.

**Returns:** Dictionary with `timing_config` key.

##### `set_performance_mode(mode)`

Update the performance mode for timing randomization.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `mode` | `str` | One of `'fast'`, `'normal'`, `'bursty'`, `'throttled'`, `'stress'` |

##### `set_error_injection_rate(rate)`

Set the error injection rate for protocol randomization.

##### `configure_for_compliance_testing()`

Configure for strict AXI4 protocol compliance testing with predictable timing and no error injection.

##### `configure_for_performance_testing()`

Configure for high-performance stress testing with large bursts and aggressive timing.

##### `configure_for_error_injection(error_rate=0.05)`

Configure for error injection testing with variable timing and enhanced error scenarios.

##### `get_statistics() -> Dict[str, Any]`

Get combined usage statistics from both protocol and timing randomization.

##### `reset_statistics()`

Reset all statistics counters.

---

## Factory Functions

### `create_unified_randomization(data_width=32, channels=None, performance_mode='normal') -> AXI4RandomizationManager`

Create a unified randomization manager with sensible defaults.

### `create_compliance_randomization(data_width=32) -> AXI4RandomizationManager`

Create a manager configured for compliance testing.

### `create_performance_randomization(data_width=32) -> AXI4RandomizationManager`

Create a manager configured for performance stress testing.

### `create_error_injection_randomization(data_width=32, error_rate=0.05) -> AXI4RandomizationManager`

Create a manager configured for error injection testing.

### `create_automotive_randomization_config(data_width=32) -> AXI4RandomizationConfig`

Create a protocol config optimized for automotive (safety-critical, deterministic).

### `create_datacenter_randomization_config(data_width=64) -> AXI4RandomizationConfig`

Create a protocol config optimized for datacenter (cache-aligned, high-performance).

### `create_mobile_randomization_config(data_width=32) -> AXI4RandomizationConfig`

Create a protocol config optimized for mobile (power-efficient, moderate bursts).

### `create_compliance_randomization_config(data_width=32) -> AXI4RandomizationConfig`

Create a protocol config for AXI4 compliance testing (no errors, predictable).

---

## Usage Examples

### Basic Randomization with Profiles

```python
from CocoTBFramework.components.axi4.axi4_randomization_config import (
    AXI4RandomizationConfig, AXI4RandomizationProfile
)

# Create config with performance profile
config = AXI4RandomizationConfig(
    profile=AXI4RandomizationProfile.PERFORMANCE,
    data_width=64,
    id_width=4
)

# Randomize address and burst fields
values = config.randomize_fields({
    'awaddr': {'min': 0x1000, 'max': 0x8000, 'align': 64},
    'awlen': {'min': 4, 'max': 64},
    'awsize': {'max': 3},
    'awburst': {'types': [1]},  # INCR only
    'awid': {'min': 0, 'max': 3}
})

print(f"Address: 0x{values['awaddr']:X}")
print(f"Burst length: {values['awlen'] + 1} beats")
```

### Unified Randomization Manager

```python
from CocoTBFramework.components.axi4.axi4_randomization_manager import (
    AXI4RandomizationManager, create_unified_randomization
)

# Create manager with defaults
manager = create_unified_randomization(data_width=32)

# Get master-optimized configuration
master_config = manager.create_master_config()

# Get slave-optimized configuration
slave_config = manager.create_slave_config()

# Switch to compliance testing mode
manager.configure_for_compliance_testing()

# Get statistics
stats = manager.get_statistics()
print(f"Protocol calls: {stats['protocol_calls']}")
print(f"Timing calls: {stats['timing_calls']}")
```

### Industry-Specific Testing

```python
from CocoTBFramework.components.axi4.axi4_randomization_config import (
    create_automotive_randomization_config,
    create_datacenter_randomization_config
)

# Automotive verification (safety-critical)
auto_config = create_automotive_randomization_config(data_width=32)
auto_values = auto_config.randomize_fields({
    'awaddr': None,
    'awlen': None,
    'awid': None
})
# Result: conservative burst lengths, strict alignment, minimal errors

# Datacenter verification (high-performance)
dc_config = create_datacenter_randomization_config(data_width=64)
dc_values = dc_config.randomize_fields({
    'awaddr': None,
    'awlen': None,
    'awid': None
})
# Result: large bursts, 64-byte alignment, advanced features enabled
```
