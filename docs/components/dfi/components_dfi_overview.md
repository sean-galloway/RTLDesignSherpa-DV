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

# DFI (DDR PHY Interface) Components Overview

If you're bringing up a memory controller — or a PHY shim in front of
one — this BFM is the other end of that wire. It verifies MCs and FPGA
PHY shims against the DDR PHY Interface specification, versions 2.1
through 5.x. The PHY side is modeled as a programmable slave with a
numpy-backed memory and a state machine that actually respects JEDEC
timing; the MC side is a driver with a primitive command API
(`activate`, `read`, `write`, and friends) to poke it with.

The piece that earns its keep is the version handling. Each spec
version's semantics live in their own behavior class, dispatched
through a Strategy + Registry pattern, so the quirks of v2.1 stay
quarantined from your v4.0 tests.

> **Scope:** DFI v2.1 through v5.x — that covers DDR1-5 and LPDDR1-5.
> v6.0 dropped legacy DDR/LPDDR support, which makes it a different
> enough animal that it's slated as a future BFM generation rather
> than something to bolt on here. The architecture pressure-test that
> preceded this implementation lives in
> [`docs/internal/dfi-semantic-shifts.md`](../../internal/dfi-semantic-shifts.md).

## Architecture

A typical testbench hangs three BFMs around the DUT — a master to
drive the MC side, a slave to play PHY, and a monitor to watch — plus
a shared configuration stack (`timings`, `mapping`, `base`) that tells
everyone which spec version and memory type they're pretending to be:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Your testbench                                                     │
│                                                                     │
│   timings = builtin_timings("ddr3-1600")                            │
│   mapping = AddressMapping(num_ranks=1, num_banks=8, …)             │
│   base    = DFIBase(dfi_version=V3_1, memory_type=DDR4, …)          │
│              │                                                      │
│              │   ┌─────────────────────────────────────────────┐    │
│              ├──▶│ DFIBase.behavior = DFIv3_1Behavior          │    │
│              │   │  (auto-selected via VERSION_BEHAVIOR dict)  │    │
│              │   └─────────────────────────────────────────────┘    │
│              │                                                      │
│   master = DFIMasterMC(dut, dut.dfi_clk)                            │
│   slave  = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=mem)     │
│   mon    = DFIMonitor(dut, dut.dfi_clk, side="phy")                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │
       ┌─────────────────────▼─────────────────────┐
       │     dfi_shim.sv  (or your MC RTL)         │
       │     mc_dfi_* ⇄ phy_dfi_*  (33 signals)    │
       └───────────────────────────────────────────┘
```

The slave runs its sampling loop on the falling edge of the clock.
Every cycle, in order:

1. Tick the DRAM state model.
2. Decode any command on the wire (`cs_n` active) and update per-bank
   state.
3. Commit any write whose CWL has elapsed; serve any read whose CL
   has elapsed. Reads serialize behind in-flight writes — that's what
   keeps a read-after-write from handing back stale data.
4. Dispatch the per-version `behavior.X(bus, state)` method for each
   of the eight semantic-shift areas (error / CRC / update / training /
   CA parity / freq change / disconnect / PHY master). Whatever the
   behavior sees lands in the matching `slave.X_events` deque.

Step 4 is where the version differences live. The signals look mostly
the same across DFI versions, but what an error pulse or a training
request *means* shifts — and the behavior class owns that knowledge,
not the sampling loop.

## Minimal end-to-end example

Here's the smallest test that still does a full round trip: clock and
reset, the configuration stack, an activate/write/read sequence, then
a check of the slave's counters.

```python
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from CocoTBFramework.components.dfi import (
    AddressMapping, DFIBase, DFIMasterMC, DFIVersion, MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


@cocotb.test()
async def example_test(dut):
    # Clock and reset
    cocotb.start_soon(Clock(dut.dfi_clk, 10, units="ns").start())
    dut.dfi_rstn.value = 0
    await RisingEdge(dut.dfi_clk)
    await RisingEdge(dut.dfi_clk)
    dut.dfi_rstn.value = 1
    await RisingEdge(dut.dfi_clk)

    # Build the configuration stack
    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=8192, num_cols=1024,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V3_1,
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,  # BL=1 conceptually; override for BL=4/8
    )

    # Build the BFMs
    memory = MemoryModel(num_lines=8 * 8192 * 1024, bytes_per_line=8)
    master = DFIMasterMC(dut, dut.dfi_clk)
    slave  = DFISlavePHY(dut, dut.dfi_clk, base=base, memory=memory)
    await Timer(1, units="ns")

    # Drive a command sequence
    await master.activate(bank=0, row=0x100)
    await master.nop(timings.tRCD_cycles)
    await master.write(bank=0, col=0x10)
    await master.nop(timings.CWL - 1)
    await master.write_data(data=0xDEADBEEFCAFEBABE)
    await master.nop(timings.CWL + 4)
    await master.read(bank=0, col=0x10)
    await master.nop(timings.CL + 4)

    # Verify the slave saw what we expected
    assert slave.writes_committed == 1
    assert slave.reads_served == 1
```

Two things worth stealing for your own tests: `beats_per_burst=1`
keeps this to one beat per command (override it for BL=4/8), and the
`MemoryModel` is sized to the full address space — banks × rows ×
columns, 8 bytes a line. The counter asserts at the bottom are the
quick-and-dirty option; for anything past a smoke test, use the event
queues in the next section instead.

## Per-version behavior selection

Hand `DFIBase` a version and it picks the matching behavior class
itself, via the `VERSION_BEHAVIOR` lookup:

| `dfi_version` | Behavior class | Notes |
|---|---|---|
| `V2_1` | `DFIv2_1Behavior` | Everything added after v2.1 raises `NotSupportedInThisVersionError` |
| `V3_1` | `DFIv3_1Behavior` | CRC / Update / Training / Error / CA parity / freq indicator |
| `V4_0` | `DFIv4_0Behavior` | PHY Master / Disconnect / acknowledged freq change / per-slice training |
| `V5_2` | `DFIv4_0Behavior` | The PHY Master rename is naming-only — no behavior change |

That lookup is a default, not a cage. If your PHY has quirks — and
real ones always do — subclass the behavior for your version and pass
it in. This is the hook for board-specific decoding, or for
deliberately modeling a broken PHY to see how your MC copes:

```python
class MyBoardSpecificV3Behavior(DFIv3_1Behavior):
    def error_event(self, bus, state):
        # Custom decoding of bus.error_info for our PHY
        ...

base = DFIBase(
    dfi_version=DFIVersion.V3_1,
    memory_type=MemoryType.DDR4,
    timings=timings, mapping=mapping,
    behavior=MyBoardSpecificV3Behavior(),
)
```

## Consuming events from the slave queues

Each of the eight areas gets its own deque on `DFISlavePHY`, and the
behavior dispatch appends to them as things happen. Drive something on
the wire, then take it off the queue:

```python
# Slave drives PHY-side signals…
slave.set_error(active=1, info=0x42)
await RisingEdge(dut.dfi_clk)
slave.set_error(active=0)

# …and the behavior catches them
evt = slave.error_events[0]
assert evt.kind == ErrorKind.OTHER
assert evt.code == 0x42
```

The queues, by area:

| Area | Queue | Event type |
|---|---|---|
| Error interface | `slave.error_events` | `ErrorEvent` (kind, code) |
| CRC | `slave.crc_events` | `CRCEvent` (kind, slice_idx) |
| Update | `slave.update_events` | `UpdateEvent` (state, initiator) |
| Training | `slave.training_events` | `TrainingEvent` (phase, slice_idx) |
| CA parity | `slave.ca_parity_events` | `CAParityEvent` (bits) |
| Freq change | `slave.freq_change_events` | `FreqChangeEvent` (protocol) |
| Disconnect | `slave.disconnect_events` | `DisconnectEvent` (phase) |
| PHY Master | `slave.takeover_events` | `TakeoverEvent` (reason) |

Polling eight deques by hand gets old fast, so there's a scoreboard
that does it for you:
`CocoTBFramework.scoreboards.dfi_scoreboard.DFIScoreboard` drains the
per-area queues, fires any `on_<area>(callback)` hooks you've
registered, and tallies counts via `poll()` / `report()`.

## Driving the wire

Who drives what, and with which primitives:

| Direction | Driven by | Primitive |
|---|---|---|
| Command + write | `DFIMasterMC` | `activate`, `read`, `write`, `precharge`, `refresh`, `nop`, `write_data`, `write_burst`, `set_rddata_en` |
| MC→PHY update / parity / freq / acks | `DFIMasterMC` | `set_ctrlupd_req`, `set_phyupd_ack`, `set_parity_in`, `set_freq_change`, `set_disconnect_ack`, `set_phymstr_ack` |
| Read data + memory | `DFISlavePHY` | (auto-served by the DRAM model + MemoryModel) |
| PHY→MC error / CRC / update / training / parity / etc. | `DFISlavePHY` | `set_error`, `set_crc_alert`, `set_phyupd_req`, `set_ctrlupd_ack`, `set_training`, `set_parity_check`, `set_freq_change_ack`, `set_disconnect_req`, `set_phymstr_req` |

## SystemVerilog shim for two-monitor tests

`tests/sim/rtl/dfi/dfi_shim.sv` is a pure passthrough — all 33 DFI
signals exposed on both an MC-facing and a PHY-facing port, no logic
in between. Dumb is the point. You hang a master, a slave, and
monitors off either side and check that the same packet stream lands
on both. The cocotb tests in `tests/sim/dfi/` are built exactly that
way. When you move to your own MC RTL, the shim goes away: drop the
DUT in where it was and connect the BFMs to one side only.

## Related documentation

- **Architecture pressure-test:**
  [`docs/internal/dfi-semantic-shifts.md`](../../internal/dfi-semantic-shifts.md)
  — why the design looks the way it does. Read this before you
  subclass a behavior.
- **JEDEC timing format:**
  `src/CocoTBFramework/components/dfi/jedec/README.md`
  — how the timing data for this component is specified.

No Problems section this round — nothing in the page met the "reader gets burned" bar. The example's `ddr3-1600` timings paired with `MemoryType.DDR4` looks odd to a DDR person, but it was audited against the source and won't fail for anyone who copies it, so I left it alone.
