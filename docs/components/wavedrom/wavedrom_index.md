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

# WaveDrom Timing Diagram Generation

**Version:** 3.0 (Auto-Binding + Protocol Presets)
**Status:** ✅ Production Ready
**Last Updated:** 2025-10-06

---

## Overview

The WaveDrom infrastructure provides automated timing diagram generation for digital protocols using constraint-based pattern detection and the WaveDrom JSON format. The system uses CP-SAT constraint solving to identify specific protocol behaviors and generate publication-quality timing diagrams.

### Key Features

✅ **Automatic Signal Discovery** - Uses SignalResolver to find signals without manual binding
✅ **Protocol-Specific Presets** - Pre-configured constraints for GAXI, APB, AXI4, AXI4-Lite, AXI-Stream
✅ **Segmented Capture** - Isolate specific scenarios for clean, deterministic waveforms
✅ **Field-Based Formatting** - Automatic hex/dec/bin formatting based on signal type
✅ **Arrow Annotations** - Show signal relationships and data flow
✅ **Labeled Groups** - Organize signals into logical interface groups

---

## Documentation Structure

### Getting Started
- **[Quick Start Guide](wavedrom_quick_start.md)** - Get running in 5 minutes
- **[Protocol Presets](wavedrom_protocol_presets.md)** - GAXI, APB, AXI4, AXIL4, AXIS examples
- **Wavedrom GAXI Example *(see TestTutorial)*** - Complete walkthrough with 6 scenarios

### Core Concepts
- **[Auto-Binding Guide](wavedrom_auto_binding.md)** - SignalResolver integration
- **[Segmented Capture](wavedrom_segmented_capture.md)** - Isolation pattern for clean waveforms
- **[Requirements & Best Practices](wavedrom_requirements.md)** - Design rules for quality diagrams

### Advanced Topics
- **Wavedrom Troubleshooting *(documentation planned)*** - Common issues and solutions
- **vcd2wavedrom2 Script *(see Scripts)*** - Convert VCD files to WaveJSON

---

## Quick Example

```python
# Import from the RTLDesignSherpa main repo (tbclasses/wavedrom_user/gaxi.py)
from CocoTBFramework.tbclasses.wavedrom_user.gaxi import GAXIWaveDromTemplate

@cocotb.test()
async def my_test(dut):
    # One-line setup with automatic signal discovery
    gaxi_wave = GAXIWaveDromTemplate(
        dut=dut,
        signal_prefix="wr_",     # Finds: wr_valid, wr_ready, wr_data
        data_width=32,
        preset="comprehensive"    # Detects: handshake, back2back, stall, idle
    )

    await gaxi_wave.start_sampling()

    # Run your test transactions...
    # ...

    results = await gaxi_wave.stop_sampling()
    # WaveJSON files automatically generated in sim_build/
```

**Output:** Publication-quality timing diagrams in PNG/SVG format showing protocol behavior.

---

## Supported Protocols

| Protocol | Template Class | Status | Presets Available |
|----------|---------------|--------|-------------------|
| **GAXI** | `GAXIWaveDromTemplate` | ✅ Production | basic_handshake, comprehensive, performance, debug |
| **APB** | `APBWaveDromTemplate` | ✅ Production | basic_rw, comprehensive, debug, timing, error |
| **AXI4** | `AXI4Presets` (manual setup) | ✅ Ready | write_basic, read_basic, comprehensive, debug |
| **AXI4-Lite** | `AXIL4Presets` (manual setup) | ✅ Ready | write_basic, read_basic, comprehensive, debug |
| **AXI-Stream** | `AXISPresets` (manual setup) | ✅ Ready | basic_handshake, comprehensive, performance, debug |

*Note: AXI4/AXIL4/AXIS do not yet have Template classes but use the same setup pattern with `setup_*_constraints_with_boundaries()`*

!!! note "Wavedrom User Examples"
    The protocol-specific wavedrom user examples (gaxi.py, apb.py, etc.) are located in the [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) repository under `tbclasses/wavedrom_user/`.

---

## Architecture

### Component Stack

```mermaid
graph TB
    subgraph Stack["WaveDrom Component Stack"]
        Templates["Template Classes<br/>(GAXIWaveDromTemplate)"]
        Presets["Protocol Presets<br/>(GAXIPresets, etc.)"]
        AutoBind["Auto-Binding<br/>(SignalResolver)"]
        Solver["Constraint Solver<br/>(CP-SAT)"]
        Generator["WaveJSON Generator"]
    end

    Templates -->|"Easiest (One-line setup)"| Presets
    Presets -->|"Pre-configured constraints"| AutoBind
    AutoBind -->|"Automatic signal discovery"| Solver
    Solver -->|"Pattern detection engine"| Generator
    Generator -->|"Format conversion"| Output["WaveJSON/PNG/SVG"]
```

### Workflow

1. **Setup** - Create template or configure solver manually
2. **Signal Binding** - Automatic discovery via SignalResolver or manual binding
3. **Constraint Definition** - Use presets or create custom temporal patterns
4. **Capture** - Segmented sampling for each scenario
5. **Solve** - CP-SAT finds matching patterns in signal data
6. **Generate** - Create WaveJSON with formatting, arrows, groups
7. **Render** - Convert to PNG/SVG with `wavedrom-cli`

---

## Transaction Boundaries & Scenario Isolation

The constraint solver supports isolating a match to a single transaction using
boundary constraints and an idle-cycle filter. Both are enforced during CP-SAT
solving.

### Boundary Constraints (enforced in the solver)

Boundaries declared with `add_transaction_boundary()` (manual, by cycle) or
`auto_detect_boundaries()` (signal transition, e.g. `valid` 1→0) are translated
into real CP-SAT constraints: **a match may not straddle a boundary** — all of a
constraint's events must fall entirely before the boundary cycle or entirely
at/after it.

```python
# Manual boundary at window cycle 25
wave_solver.add_transaction_boundary("write_handshake", boundary_cycle=25)

# Auto-detected boundary: two cycles after every wr_valid 1->0 transition
wave_solver.auto_detect_boundaries("write_handshake",
                                   transition_signal="wr_valid",
                                   transition_value=(1, 0))
```

Per-constraint boundary handling can be disabled with
`TemporalConstraint(skip_boundary_detection=True)` (skips the boundary
detect/solve/flush cycle during sampling for that constraint).

### Idle-Cycle Filter (`boundary_min_idle_cycles`)

When `TemporalConstraint.boundary_min_idle_cycles > 0`, matches are only kept if
the N cycles before the match start are idle. What "idle" means is now
configurable per constraint:

```python
constraint = TemporalConstraint(
    name="isolated_write",
    events=[...],
    boundary_min_idle_cycles=3,
    # Explicit idle definition: signal_name -> value when idle
    idle_signals={"wr_valid": 0, "rd_ready": 0},
)
```

Resolution order:

1. **`idle_signals` set** — used as-is (configured signals missing from the
   captured data are ignored with a warning).
2. **`idle_signals` empty** — the solver derives an idle set from the
   constraint's own events: control/handshake signals (names containing
   `valid`, `ready`, `req`, `ack`, `gnt`, `psel`, `penable`, `enable`) are
   assumed idle at 0.
3. **Nothing derivable** — filtering is skipped with an explicit log message
   (it never passes vacuously). Set `idle_signals` to enable it.

> **Migration note:** earlier versions hardcoded idle as
> `wr_valid == 0 AND rd_ready == 0`. If you relied on those exact names on a
> constraint whose events do not reference them, set
> `idle_signals={"wr_valid": 0, "rd_ready": 0}` explicitly.

### Post-Match Window Extension

`TemporalConstraint(post_match_cycles=N)` extends the rendered window by N
cycles after the matched sequence (in addition to `context_cycles_after`).

---

## File Locations

### Source Code
- **Constraint Solver**: `src/CocoTBFramework/components/wavedrom/constraint_solver.py` (this repo)
- **WaveJSON Generator**: `src/CocoTBFramework/components/wavedrom/wavejson_gen.py` (this repo)
- **Signal Binder**: `src/CocoTBFramework/components/wavedrom/signal_binder.py` (this repo)
- **Protocol Presets** (located in the [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) repo):
  - `tbclasses/wavedrom_user/gaxi.py`
  - `tbclasses/wavedrom_user/apb.py`
  - `tbclasses/wavedrom_user/axi4.py`
  - `tbclasses/wavedrom_user/axil4.py`
  - `tbclasses/wavedrom_user/axis.py`

### Example Tests
- **GAXI Comprehensive**: `val/amba/test_gaxi_wavedrom_example.py`
- **Script for PNG/SVG generation**: `val/amba/wd_cmd.sh`

### Documentation
- **This directory**: `docs/components/wavedrom/`
- **Assets**: generated PNG/SVG files (in the [RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) repo under `docs/markdown/assets/WAVES/`)

---

## Next Steps

1. **New Users**: Start with [Quick Start Guide](wavedrom_quick_start.md)
2. **GAXI Users**: Follow Wavedrom GAXI Example *(see TestTutorial)*
3. **Other Protocols**: See [Protocol Presets](wavedrom_protocol_presets.md)
4. **Troubleshooting**: Check Wavedrom Troubleshooting *(documentation planned)*

---

## Version History

- **v3.1 (2026-07)**: Boundary constraints now enforced in CP-SAT solving (matches cannot straddle a transaction boundary); configurable `idle_signals` for `boundary_min_idle_cycles` filtering (auto-derived from constraint events when unset, explicit skip otherwise); `skip_boundary_detection` / `post_match_cycles` promoted to proper `TemporalConstraint` fields; signals bound after `add_constraint()` no longer kill sampling; sampling errors are logged with tracebacks; switched to the non-deprecated `enumerate_all_solutions` CP-SAT API
- **v3.0 (2025-10-06)**: Added AXI4/AXIL4/AXIS protocol presets, arrow annotations, labeled groups
- **v2.0 (2025-10-04)**: SignalResolver auto-binding integration
- **v1.5 (2025-10-05)**: Segmented capture implementation
- **v1.0 (2025-09)**: Initial constraint-based WaveDrom generation

---

## Related Documentation

- [CocoTB Framework Overview](../components_overview.md)
- [Field Configuration](../shared/components_shared_field_config.md)
- [Signal Mapping Helper](../shared/components_shared_signal_mapping_helper.md)
- TestTutorial Index *(documentation planned)*
