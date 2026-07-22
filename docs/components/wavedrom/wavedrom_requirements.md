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

# WaveDrom Requirements and Best Practices

**Version:** 1.2
**Last Updated:** 2025-10-07
**Purpose:** Define mandatory requirements for wavedrom timing diagram generation

---

These are the rules the wavedrom tests in this repo follow. Every one of them exists because a diagram that breaks it looked wrong in a review and eroded trust in all the others. A waveform a designer can't read in five seconds is worse than no waveform.

## Critical Requirements

### 1. **Clock Signal — ALWAYS Required**

**Rule:** Every waveform MUST include the clock signal as the first signal.

**Rationale:** A waveform without a timing reference is abstract art. The clock is what turns "valid went high" into "valid went high three cycles after reset deasserted."

**Implementation:**
```python
# ALWAYS bind clock first
wave_solver.add_signal_binding('clk', 'axi_aclk')  # or appropriate clock

# ALWAYS include in signals_to_show
signals_to_show=['clk', 'rst_n', ...]  # clk first
```

**WaveJSON Output:**
```json
"signal": [
  {
    "name": "clk",
    "wave": "p............"  // Clock pattern
  },
  ...
]
```

### 2. **Initial Setup Cycles — Never Start at Time 0**

**Rule:** Waveforms MUST have 2-3 cycles of stable initial state before events begin.

**Rationale:** If the first transition happens at cycle 0, nobody can tell initial state from the first event. Give the reader a baseline.

**Implementation:**
```python
# === Start Sampling ===
await wave_solver.start_sampling()

# === Initial Setup ===
# CRITICAL: Provide stable initial state
dut.signal1.value = 0
dut.signal2.value = 0
await RisingEdge(dut.clk)
await RisingEdge(dut.clk)
await RisingEdge(dut.clk)  # 3 cycles minimum

# NOW start actual test events
dut.signal1.value = 1
...
```

**Context Cycles:** The `context_cycles_before` parameter adds dead cycles BEFORE the matched pattern. To keep arrows from starting at cycle 0:
- **Initial setup (3 cycles):** stable state at the start of the whole simulation
- **Context before (≥3):** MUST be at least 3, to push the pattern start beyond the initial cycles
- **Example:** `context_cycles_before=5` puts the pattern start at cycle 8 or later (3 setup + 5 context)

### 3. **Arrows Must Show Meaningful Relationships**

**Rule:** Arrows MUST connect events that have a causal or temporal relationship. An arrow asserts "this caused that" — if the relationship is just how the handshake normally works, the arrow mislabels normal behavior as a problem.

**Good arrow usage:**
- Good: `psel → penable` (APB: setup causes enable)
- Good: `wr_valid → wr_ready` (GAXI: write request causes ready response)
- Good: `fifo_full → backpressure` (full condition causes flow control)
- Good: `write → read_valid` (data written propagates to the read side)

**Bad arrow usage:**
- Bad: `ready asserted → valid asserts` (that's a normal handshake, not a stall)
- Bad: arrows between unrelated signals
- Bad: arrows without a clear meaning

**Implementation:**
```python
# Good: Shows backpressure (writer blocked)
TemporalEvent("write_blocked", SignalTransition("wr_ready", 1, 0)),
TemporalEvent("writer_waiting", SignalTransition("wr_valid", 1, 1)),
# Concurrent = both happen at same time = stall/backpressure

# Bad: Misinterprets normal operation
TemporalEvent("ready_high", SignalTransition("wr_ready", 1, 1)),
TemporalEvent("then_write", SignalTransition("wr_valid", 0, 1)),
# Sequence = write after ready = NORMAL, not a problem!
```

### 4. **Arrow Types — Use Appropriately**

**Available Arrow Types:**
- `~>` - Squiggly: async/handshake relationships (GAXI, AXI)
- `->` - Direct: sequential/causal relationships (APB, state machines)
- `<->` - Bidirectional: duration/span of a sequence
- `->>` - Double: strong dependency (use sparingly)
- `=>` - Thick: critical path (use sparingly)

**Auto-Selection Logic:**
```python
if has_valid and has_ready:
    # GAXI/AXI handshake - async
    arrow = f"{start}~>{end} {label}"
elif is_apb:
    # APB sequential
    arrow = f"{start}->{end} {label}"
else:
    # Generic duration
    arrow = f"{start}<->{end} Sequence: {duration} cycles"
```

### 5. **Internal Signals — Show Critical State**

**Rule:** Include the internal signals that explain the behavior.

**Critical Internals to Show:**
- **FIFO/Buffer:** `count`, `full`, `empty`, `wr_ptr`, `rd_ptr`
- **State Machines:** `state`, `next_state`
- **Arbiters:** `grant`, `request_pending`
- **Monitors:** `transaction_active`, `error_flag`

**Implementation:**
```python
# Bind internal signals
wave_solver.add_signal_binding('count', 'fifo_count')
wave_solver.add_signal_binding('full', 'fifo_full')

# Include in waveform
signals_to_show=['clk', 'wr_valid', 'wr_ready', 'count', 'full']
```

**Rationale:** Interface signals show *what* happened. Internals show *why* — and "why" is the question anyone looking at a waveform is actually asking.

### 6. **Signal Naming — Preserve Interface Prefixes**

**Rule:** Signal names MUST keep their interface prefixes (`wr_`, `rd_`, etc.) so `wr_valid` and `rd_valid` don't collapse into two traces both called "valid."

**Implementation:** Display names preserve prefixes automatically:
```python
# Binding creates unique display names
wave_solver.add_signal_binding('wr_valid', 'wr_valid')
wave_solver.add_signal_binding('rd_valid', 'rd_valid')
wave_solver.add_signal_binding('count', 'count')

signals_to_show=['clk', 'wr_valid', 'wr_ready', 'rd_valid', 'rd_ready', 'count']
```

**WaveJSON Output:**
```json
"signal": [
  {"name": "clk", ...},
  {"name": "wr_valid", ...},  // NOT "valid"
  {"name": "wr_ready", ...},  // NOT "ready"
  {"name": "rd_valid", ...},  // Distinct from wr_valid
  {"name": "count", ...}
]
```

**Grouping (Optional):** Use '|' in signals_to_show for visual organization:
```python
signals_to_show=['clk', 'rst_n', '|', 'wr_valid', 'wr_ready', '|', 'count']
# Separators help organize: Clock/Reset | Write Interface | Internals
```

### 7. **Reset Signal — Include for Clocked Blocks**

**Rule:** Synchronous designs show their reset.

**Implementation:**
```python
wave_solver.add_signal_binding('rst_n', 'aresetn')  # Active-low reset
# or
wave_solver.add_signal_binding('rst', 'reset')      # Active-high reset

signals_to_show=['clk', 'rst_n', ...]  # After clock, before data
```

### 8. **Trim/Context Margins — Configurable**

**Rule:** Context cycles are configurable, with sensible defaults.

**Options:**
- **Minimal (1,1):** tight waveforms for simple patterns
- **Moderate (3,3):** balanced view with some context
- **Default (None,None):** auto-calculate (~25% of window)

**Implementation:**
```python
# Allow user to configure
context_before = {'minimal': 1, 'moderate': 3, 'default': None}[mode]
context_after = {'minimal': 1, 'moderate': 3, 'default': None}[mode]

constraint = TemporalConstraint(
    ...
    context_cycles_before=context_before,
    context_cycles_after=context_after,
)
```

### 9. **Signal Grouping — MANDATORY for ALL Waveforms**

**Rule:** ALL signals MUST be grouped logically by function/bus using WaveDrom labeled groups.

**Rationale:**
- Groups make waveforms faster to read
- Logical grouping shows which signals belong together
- Consistent grouping across scenarios makes them comparable at a glance

**Group Order (Standard):**
1. **Clock/Reset** — timing reference (ALWAYS FIRST)
2. **Control Signals** — transaction control (psel, penable, valid, ready, etc.)
3. **Address** — address information
4. **Data** — data payload (separate write/read if applicable)
5. **Qualifiers/Status** — additional control (strb, prot, error flags, etc.)
6. **Internal State** — debug/observability (count, state, pointers, etc.)

**Implementation:**
```python
# Use nested arrays for WaveDrom labeled groups
common_signals = [
    ['Clock/Reset', 'clk', 'rst_n'],
    '|',  # Visual separator
    ['APB Control', 'psel', 'penable', 'pwrite', 'pready'],
    '|',
    ['APB Address', 'paddr'],
    '|',
    ['APB Data', 'pwdata', 'prdata'],
    '|',
    ['APB Qualifiers', 'pstrb', 'pprot', 'pslverr']
]

constraint = TemporalConstraint(
    name="scenario",
    events=[...],
    signals_to_show=common_signals  # Use same grouping for ALL scenarios
)
```

**WaveJSON Output:**
```json
"signal": [
  ["Clock/Reset",
    {"name": "clk", "wave": "p...."},
    {"name": "rst_n", "wave": "1...."}
  ],
  {},
  ["APB Control",
    {"name": "psel", "wave": "01..."},
    {"name": "penable", "wave": "0.1.."}
  ],
  ...
]
```

**Key Requirements:**
- ALL waveforms in a test MUST use the SAME grouped signal list
- The Clock/Reset group ALWAYS comes first
- Every signal lives in a labeled group — no orphans
- Use `'|'` separators between groups for visual clarity
- Define the grouping ONCE per test, reuse it for every constraint

### 10. **Quality Over Quantity — Focus on Meaningful Scenarios**

**Rule:** Generate 3-4 waveforms that each tell a clear story, rather than 12+ where most are noise.

**Rationale:**
- A pile of waveforms overwhelms the reader; each one should earn its place
- A waveform built on a wrong constraint — one that matches something nonsensical — is worse than none, because it teaches the wrong thing

**Selection Criteria for Scenarios:**
1. **Coverage:** does it show an aspect of the design the others don't?
2. **Clarity:** will a designer understand what's being shown without a caption?
3. **Relevance:** does it show normal operation OR an edge case that matters?
4. **Completeness:** does it show the full transaction, not a fragment?

**Good Scenario Examples:**
- Good: APB write with wait states (shows backpressure handling)
- Good: APB read with immediate response (shows zero-wait operation)
- Good: back-to-back transactions (shows back-pressure release and pipelining)
- Good: FIFO full→empty sequence (shows a complete buffer cycle)

**Bad Scenario Examples:**
- Bad: partial transactions (missing setup or completion)
- Bad: signal transitions that can't occur (constraint doesn't match reality)
- Bad: redundant scenarios (the same behavior three ways)
- Bad: scenarios that never occur in normal operation

**Implementation Checklist:**
```python
# Before adding a new scenario, ask:
# 1. Does this show something the other scenarios don't?
# 2. Will the constraint actually match real signal behavior?
# 3. Can I explain in one sentence what this waveform demonstrates?
# 4. Would I want to see this in design documentation?

# If any answer is "no" or "unsure", reconsider the scenario
```

**Recommended Scenario Count:**
- Simple modules (FIFO, skid buffer): **3-4 scenarios**
- Complex modules (AXI, APB): **4-6 scenarios**
- Maximum for any module: **8 scenarios** (and only if you can defend every one)

---

## Common Patterns

### Pattern 1: GAXI/FIFO Waveforms

```python
# Clock and reset
wave_solver.add_signal_binding('clk', 'axi_aclk')
wave_solver.add_signal_binding('rst_n', 'axi_aresetn')

# Write interface
wave_solver.add_signal_binding('wr_valid', 'wr_valid')
wave_solver.add_signal_binding('wr_ready', 'wr_ready')
wave_solver.add_signal_binding('wr_data', 'wr_data')

# Read interface (for combined view)
wave_solver.add_signal_binding('rd_valid', 'rd_valid')
wave_solver.add_signal_binding('rd_ready', 'rd_ready')
wave_solver.add_signal_binding('rd_data', 'rd_data')

# Internal state
wave_solver.add_signal_binding('count', 'fifo_count')

# Scenarios
signals_to_show=['clk', 'rst_n', 'wr_valid', 'wr_ready', 'wr_data', 'count']  # Write focus
signals_to_show=['clk', 'wr_valid', 'wr_data', 'rd_valid', 'rd_data', 'count']  # Coupling
```

### Pattern 2: APB Waveforms

```python
# Clock always first
wave_solver.add_signal_binding('clk', 'pclk')
wave_solver.add_signal_binding('rst_n', 'presetn')

# APB signals
wave_solver.add_signal_binding('psel', 'psel')
wave_solver.add_signal_binding('penable', 'penable')
wave_solver.add_signal_binding('pready', 'pready')
wave_solver.add_signal_binding('pwrite', 'pwrite')
wave_solver.add_signal_binding('paddr', 'paddr')
wave_solver.add_signal_binding('pwdata', 'pwdata')
wave_solver.add_signal_binding('prdata', 'prdata')

signals_to_show=['clk', 'psel', 'penable', 'pready', 'pwrite', 'paddr', 'pwdata']
```

### Pattern 3: Backpressure/Stall

Note the events here: backpressure is valid high *while* ready is low, captured as concurrent events. Ready-then-valid is just a handshake.

```python
# Show TRUE backpressure: valid high while ready low
TemporalConstraint(
    name="backpressure",
    events=[
        TemporalEvent("blocked", SignalTransition("ready", 1, 0)),
        TemporalEvent("waiting", SignalTransition("valid", 1, 1)),
    ],
    temporal_relation=TemporalRelation.CONCURRENT,  # Simultaneous
    signals_to_show=['clk', 'valid', 'ready', 'data', 'count']
)
```

---

## Integration with All Tests

**Goal:** wavedrom coverage on every test in the repository, eventually.

**Approach:**
1. Start with the critical tests (GAXI, APB, AXI4)
2. Use test_gaxi_wavedrom_example.py as the template
3. Follow the requirements above so every waveform looks like it came from the same hand
4. Add wavedrom to existing tests incrementally — don't boil the ocean

**Checklist for Adding WaveDrom to a Test:**
- [ ] Clock signal bound and shown first
- [ ] 2-3 initial setup cycles before events
- [ ] Reset signal included (for sync designs)
- [ ] Internal signals shown to explain behavior
- [ ] Arrows show meaningful relationships (not normal operation)
- [ ] Appropriate arrow types used
- [ ] No duplicate signal names
- [ ] Configurable context margins
- [ ] Test documented with scenario descriptions

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Starting at Time 0
```python
# BAD
await wave_solver.start_sampling()
dut.valid.value = 1  # Immediate event
```

```python
# GOOD
await wave_solver.start_sampling()
dut.valid.value = 0
await RisingEdge(dut.clk)  # Setup cycles
await RisingEdge(dut.clk)
dut.valid.value = 1  # Now event
```

### Anti-Pattern 2: Missing Clock
```python
# BAD
signals_to_show=['valid', 'ready', 'data']  # No clock!
```

```python
# GOOD
signals_to_show=['clk', 'valid', 'ready', 'data']  # Clock first
```

### Anti-Pattern 3: Meaningless Arrows
```python
# BAD: Normal handshake labeled as problem
TemporalEvent("ready_first", SignalTransition("ready", 0, 1)),
TemporalEvent("then_valid", SignalTransition("valid", 0, 1)),
# Arrow: "ready→valid" suggests problem, but this is NORMAL!
```

```python
# GOOD: Show actual problem
TemporalEvent("stall", SignalTransition("ready", 1, 0)),
TemporalEvent("blocked", SignalTransition("valid", 1, 1)),
# Arrow: "stall~>blocked" shows backpressure
```

### Anti-Pattern 4: Duplicate Names
```python
# BAD
wave_solver.add_signal_binding('valid', 'wr_valid')
wave_solver.add_signal_binding('valid', 'rd_valid')  # Duplicate!
```

```python
# GOOD
wave_solver.add_signal_binding('wr_valid', 'wr_valid')
wave_solver.add_signal_binding('rd_valid', 'rd_valid')
```

---

## Maintenance

**When Adding New Features:**
1. Update this requirements document
2. Update test_gaxi_wavedrom_example.py as the reference
3. Keep backward compatibility with existing tests
4. Add new arrow types or patterns to the Common Patterns section

**Version History:**
- v1.2 (2025-10-07): Mandatory grouping and quality requirements
  - **BREAKING:** ALL waveforms MUST use signal grouping (labeled groups)
  - Clock/Reset MUST be the first group (ALWAYS included)
  - Quality over quantity: 3-4 meaningful scenarios beat 12 nonsensical ones
  - Scenario selection criteria and checklist added
  - Maximum recommended scenario counts by module complexity
- v1.1 (2025-10-05): Signal naming and grouping improvements
  - Preserve interface prefixes (wr_, rd_) in display names
  - Added grouping support with '|' separators
  - Fixed duplicate signal name issues
- v1.0 (2025-10-05): Initial requirements based on user feedback
  - Clock always required
  - Initial setup cycles mandatory
  - Arrows must be meaningful
  - Backpressure correctly identified
  - Anti-patterns documented

**Maintained By:** RTL Design Sherpa Project
**Last Review:** 2025-10-07
