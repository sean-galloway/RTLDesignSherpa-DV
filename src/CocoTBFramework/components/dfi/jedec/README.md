# JEDEC timing tables (provisional format)

CSV files in this directory feed the `DFISlavePHY`'s DRAM state model.
Each file pins one (memory_type, speed_grade) combination's relevant
JEDEC timings; the slave's runtime checker enforces them against the
sequence of commands it sees on the wire.

## Pre-alpha note

The format below is a first stab — pretty much guaranteed to be wrong
once we hit something we hadn't anticipated. Treat it as the v0 schema.
Iterate freely.

## File naming

```
<memory_type>-<speed_grade>.csv
```

Examples: `ddr3-1600.csv`, `ddr3-1866.csv`, `ddr4-2400.csv` (Phase 2),
`ddr5-6400.csv` (Phase 3).

## File format

UTF-8 CSV, four columns:

```csv
# Comments allowed on lines starting with '#'.
parameter, unit, value, description
tCK,        ns,  1.25,  Clock period
tRCD,       ns,  13.75, ACT → RD/WR same bank
tRP,        ns,  13.75, PRE → next ACT same bank
...
```

- Lines starting with `#` are ignored.
- Whitespace around fields is trimmed.
- Empty lines are ignored.
- `unit` is one of `ns` (converted to cycles at load time using `tCK`),
  `CK` (already in cycles), or `beats` (burst length).
- `description` is free-form — included in error messages.

## Required parameters (MVP — DDR3)

| Parameter | Description | Used by violation check |
|---|---|---|
| `tCK` | Clock period (ns) | Conversion factor — must be first |
| `tRCD` | Activate to Read/Write | hard: `tRCD` (RD/WR too soon after ACT) |
| `tRP` | Precharge to Activate | hard: `tRP` (ACT too soon after PRE) |
| `tRAS_min` | Activate to Precharge min | hard: `tRAS_min` (PRE too soon after ACT) |
| `tRC` | Active-to-Active same bank | hard: `tRC` |
| `tWR` | Write recovery | hard: `tWR` (PRE too soon after last WR data beat) |
| `tWTR` | Write to Read same bank | hard: `tWTR` |
| `tRTP` | Read to Precharge | hard: `tRTP` (PRE too soon after RD) |
| `tRRD` | Active-to-Active different bank | hard: `tRRD` |
| `tFAW` | Four-Activate window | soft: `tFAW` (windowed ACT count) |
| `tREFI` | Refresh interval (average) | soft: `tREFI` (refresh overdue) |
| `tRFC` | Refresh cycle time | hard: `tRFC` (command during refresh) |
| `CL` | CAS latency | reference (read-data timing) |
| `CWL` | CAS write latency | reference (write-data timing) |
| `BL` | Burst length (fixed) | reference (beat count) |

## Optional parameters (used when present)

Anything else in the CSV is preserved as raw values in
`JedecTimings.extras` so future violations can opt in without changing
the schema. Document new parameters here as they're added.

## Override the violation policy

Hard / soft / ignore sets are configurable per-slave at construction:

```python
from CocoTBFramework.components.dfi.jedec_timings import load_timings
from CocoTBFramework.components.dfi.dram_state import ViolationPolicy

timings = load_timings("jedec/ddr3-1600.csv")
policy = ViolationPolicy(
    hard={"tRCD", "tRP"},       # only these halt sim
    soft={"tFAW", "tRRD"},      # these warn
    ignore={"tREFI"},           # this is silently ignored
)
slave = DFISlavePHY(dut, clock, timings=timings, violation_policy=policy)
```

The defaults (`ViolationPolicy()` with no args) follow the split
documented in issue #16 — JEDEC-critical timings halt sim, windowed /
average timings warn, init-sequence specifics are ignored.

## HBM4

`hbm4-template.csv.example` is a fill-in sheet structured from
JESD270-4A Table 108 / Table 3. The standard leaves HBM4 core timing
values vendor-defined, so only the spec-fixed rows carry numbers
(tREFI = 3.9 us, tPPD = 2 CK, tCKSRX = 5 CK). To create a real
profile: copy to `hbm4-<vendor>-<part>.csv`, replace every FILL_ME
from the product datasheet, and drop the `.example` suffix — the unit
suite then auto-discovers and load-tests it like every other profile.
The `.example` extension keeps the unfilled template out of that
enumeration.

## Devices with no vendored profile

A profile is vendored only where a public JEDEC speed bin fixes the
numbers. Several supported devices do not qualify:

- **HBM4** — JESD270-4A leaves the AC timing table vendor-defined, so
  no correct profile can ever ship here.
- **DDR5 / LPDDR5 / LPDDR6** — no profile derived from the spec yet.

Their CA maps decode fine; it is only the timing table that is missing.
Since `DFIBase(timings=...)` is mandatory, supply your own — either in
code:

```python
from CocoTBFramework.components.dfi import timings_from_params

timings = timings_from_params(
    tCK_ns=0.5,                 # required; converts every _ns value
    tRCD_ns=14.0, tRP_ns=14.0,  # datasheet values in nanoseconds
    tWTR_ck=8,                  # ...or already in clock cycles
    ...,                        # (see the required-parameter table)
    CL=32, CWL=30, BL=8,        # unitless
)
```

or in a file, starting from a generated skeleton:

```python
from CocoTBFramework.components.dfi import (
    write_timings_template, load_timings)

write_timings_template("my-part.csv", device="ACME HBM4")
# ... fill in the value column from the datasheet ...
timings = load_timings("my-part.csv")
```

Both take the same route as a vendored CSV — identical rounding, and
extra parameters preserved in `extras` — so nothing downstream can tell
the difference. Every timing needs an explicit `_ns` or `_ck` suffix:
the two differ by roughly an order of magnitude, and a wrong guess would
silently mis-time every command rather than fail.

Use `available_timings()` to list what is vendored.
