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

The DFI BFM verifies memory controllers (MCs) and FPGA PHY shims
against the DDR PHY Interface specification, versions 2.1 through
5.x. It models the PHY side as a programmable slave with a
numpy-backed memory and a JEDEC-timing-aware state machine, exposes
an MC-side driver with a primitive command API, and dispatches
per-spec-version semantic behaviors through a Strategy + Registry
pattern so version differences stay isolated.

> **Scope:** DFI v2.1 through v5.x. Covers DDR1-5 + LPDDR1-5. v6.0
> dropped legacy DDR/LPDDR support and is treated as a future BFM
> generation. See
> [`docs/internal/dfi-semantic-shifts.md`](../../internal/dfi-semantic-shifts.md)
> for the architecture pressure-test that preceded the implementation.

## Architecture

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
       │     mc_dfi_* ⇄ phy_dfi_*  (29 signals)    │
       └───────────────────────────────────────────┘
```

The slave runs a falling-edge sampling loop. Every cycle it:

1. Ticks the DRAM state model.
2. Decodes any command on the wire (`cs_n` active) and updates per-bank
   state.
3. Commits any write whose CWL elapsed; serves any read whose CL
   elapsed (reads serialize behind in-flight writes).
4. Dispatches the per-version `behavior.X(bus, state)` method for each
   of eight semantic-shift areas (error / CRC / update / training /
   CA parity / freq change / disconnect / PHY master). Events land in
   per-area `slave.X_events` deques.

## Minimal end-to-end example

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

## Per-version behavior selection

`DFIBase.__init__` looks up the right behavior class from
`VERSION_BEHAVIOR` based on `dfi_version`:

| `dfi_version` | Behavior class | Notes |
|---|---|---|
| `V2_1` | `DFIv2_1Behavior` | All post-v2.1 areas raise `NotSupportedInThisVersionError` |
| `V3_1` | `DFIv3_1Behavior` | CRC / Update / Training / Error / CA parity / freq-indicator |
| `V4_0` | `DFIv4_0Behavior` | PHY Master / Disconnect / Acknowledged freq change / per-slice training |
| `V5_2` | `DFIv4_0Behavior` | PHY Master rename has no behavior implication |

Override the lookup with a custom class (board-specific PHY quirks,
broken-behavior modeling, etc.):

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

Eight per-area deques on `DFISlavePHY` collect events from the
behavior dispatch each cycle:

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

Per-area queues:

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

For automated consumption, see the scoreboard hooks (TBD — separate
documentation).

## Driving the wire

| Direction | Driven by | Primitive |
|---|---|---|
| Command + write | `DFIMasterMC` | `activate`, `read`, `write`, `precharge`, `refresh`, `nop`, `write_data`, `write_burst` |
| MC→PHY update / parity / freq / acks | `DFIMasterMC` | `set_ctrlupd_req`, `set_phyupd_ack`, `set_parity_in`, `set_freq_change`, `set_disconnect_ack`, `set_phymstr_ack` |
| Read data + memory | `DFISlavePHY` | (auto-serves reads via DRAM model + MemoryModel) |
| PHY→MC error / CRC / update / training / parity / etc. | `DFISlavePHY` | `set_error`, `set_crc_alert`, `set_phyupd_req`, `set_ctrlupd_ack`, `set_training`, `set_parity_check`, `set_freq_change_ack`, `set_disconnect_req`, `set_phymstr_req` |

## SystemVerilog shim for two-monitor tests

`tests/sim/rtl/dfi/dfi_shim.sv` is a pure-passthrough RTL module with
all 29 DFI signals exposed on both MC- and PHY-facing ports. Attach
a master + slave + monitor on either side and verify the same packet
stream lands on both sides. This is what the cocotb tests in
`tests/sim/dfi/` use; for your own MC RTL, replace the shim with the
DUT and connect to one side only.

## Related documentation

- **Architecture pressure-test:**
  [`docs/internal/dfi-semantic-shifts.md`](../../internal/dfi-semantic-shifts.md)
- **JEDEC timing format:**
  `src/CocoTBFramework/components/dfi/jedec/README.md`
- **Reference open-source DDR controller (LiteDRAM):**
  `../mem-ctrl-ref/litedram/`
- **Reference DRAM simulator (DRAMsim3):**
  `../mem-ctrl-ref/DRAMsim3/`
