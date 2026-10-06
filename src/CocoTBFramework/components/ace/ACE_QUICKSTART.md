# AXI4-ACE BFM Support - Usage Guide

**Implementation Date:** 2026-10-05
**Feature:** ACE (AXI Coherency Extensions) master and snoop-channel BFMs
**Package:** `CocoTBFramework.components.ace`
**Full documentation:** `docs/components/ace/` in the repository (Overview,
Interfaces, Packet, Compliance) and the rendered `CocoTB_ACE.pdf` book.

---

## Overview

The `ace` family extends the `axi4` BFMs with ACE capabilities:

- `AXI4ACEMasterRead` / `AXI4ACEMasterWrite` — AXI4 masters with
  `arsnoop[3:0]` / `awsnoop[2:0]` on the address channels and automatic
  RACK/WACK generation.
- `AXI4ACESnoopMaster` / `AXI4ACESnoopSlave` — the three ACE snoop channels
  (AC: snoop address, CR: snoop response, CD: snoop data) as a CCU-side
  initiator and a cache-side responder.

**Scope (family "D2" subset):** the front-side read/write channels carry the
snoop fields only. There is no `ardomain/arbar/awdomain/awbar`, and ACE-Lite
masters are not modeled. If a design needs those, extend
`AXI4ACEFieldConfigHelper` before constructing the interfaces.

Validated on cocotb 1.9.2 and cocotb 2.x.

---

## Quick Start 1: Front-side ACE read with RACK

```python
from CocoTBFramework.components.ace.ace_interfaces import AXI4ACEMasterRead
from CocoTBFramework.components.ace.ace_transaction import ACETransactionType
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4SlaveRead

ace_master = AXI4ACEMasterRead(
    dut=dut,
    clock=dut.aclk,
    prefix='fub_axi_',      # binds fub_axi_araddr, ..., fub_axi_rvalid, ...
    log=log,
    id_width=8, addr_width=32, data_width=32,
)
responder = AXI4SlaveRead(
    dut=dut,
    clock=dut.aclk,
    prefix='m_axi_',
    log=log,
    id_width=8, addr_width=32, data_width=32,
)

# Every ACETransactionType member is accepted for snoop_type; the field is
# transported on AR's arsnoop[3:0].
data = await ace_master.read_transaction(
    address=0x1000,
    burst_len=4,
    snoop_type=ACETransactionType.READ_SHARED,
    id=0xAB,
)
```

RACK/WACK behavior:

- When the ACE master BFM is the master and the DUT has a `{prefix}rack` /
  `{prefix}wack` input, the BFM drives a **one-cycle acknowledge exactly one
  cycle after the RLAST (RACK) or B (WACK) handshake**.
- If the pin does not exist on the DUT (e.g. a slave port with no ack), the
  pulser is not started; the same BFM object binds cleanly either way. Pass
  `auto_ack=False` to take the acknowledge back under manual control.

---

## Quick Start 2: Snoop channels (CCU issues, cache responds)

```python
from cocotb.triggers import RisingEdge
from CocoTBFramework.components.ace.ace_interfaces import (
    AXI4ACESnoopMaster, AXI4ACESnoopSlave,
)
from CocoTBFramework.components.ace.ace_transaction import (
    CRRESP, CacheState, SnoopType,
)

# Both bind prefix + 'acaddr' style names, e.g. m_axi_acaddr, m_axi_crresp.
master = AXI4ACESnoopMaster(dut, dut.aclk, prefix='m_axi_', log=log,
                            data_width=32, addr_width=32)
slave = AXI4ACESnoopSlave(dut, dut.aclk, prefix='m_axi_', log=log,
                          data_width=32, addr_width=32)

# Program the responder's cache-state map (per address; default Invalid).
slave.set_line_behavior(0x2000, CacheState.MODIFIED)

# Optional: replace the default MESI responder matrix entirely.
# Handler receives (addr, snoop_type, state) and returns (CRRESP, data|None);
# data may be an int (one beat) or a list of ints (multi-beat CD).
slave.set_handler(my_handler)

result = await master.issue_snoop(0x2000, SnoopType.READ_UNIQUE)
# result.crresp: CRRESP bitfield; result.data: list of CD beats.
```

The default responder matrix returns `CRRESP(0)` with **no data** for
MakeInvalid on Modified/Owned lines: IHI0022 forbids DataTransfer for
MakeInvalid, and `CRRESP.validate_for_snoop()` enforces it (PassDirty also
requires DataTransfer).

### Ordering rules

- Multiple outstanding snoops are allowed; CR and CD each return in AC-issue
  order, and only after the AC handshake.
- Family convention (stricter than the spec, which allows either order after
  the AC handshake): the responder sends **all CD beats first, then CR**, per
  transaction.

### Violation handling in user handlers

If `set_handler()` returns a protocol-violating CRRESP, the slave logs an
error and continues when a logger is attached (raise `RuntimeError` without
one). Use this deliberately to test a DUT's error handling.

---

## Factories and signal maps

```python
from CocoTBFramework.components.ace.ace_factories import (
    create_axi4ace_master_rd,      # -> {'AR', 'R', 'interface'}
    create_axi4ace_master_wr,      # -> {'AW', 'W', 'B', 'interface'}
    create_axi4ace_snoop_master,   # -> {'AC', 'CR', 'CD', 'interface'}
    create_axi4ace_snoop_slave,    # -> {'AC', 'CR', 'CD', 'interface'}
    create_complete_axi4ace_testbench_components,  # prefix-probing helper
)
```

The family registers `axi4ace_*` signal-map identifiers with
`SignalResolver` (see `signal_mapping_helper.py`), so prefixed names such as
`m_axi_acaddr` or `s_axi_arsnoop` resolve the same way as the `axi4` family.
The snoop transports accept **shared-prefix binding**: constructing a
snoop master and a snoop slave with the same prefix is safe — the master
drives AC and sinks CR/CD, the slave does the complement, so every wire has
exactly one driver.

---

## Compliance checking

```python
from CocoTBFramework.components.ace.ace_compliance_checker import ACEComplianceChecker

checker = ACEComplianceChecker(log=log)
# The snoop BFM validates every CRRESP with CRRESP.validate_for_snoop()
# internally (log-and-continue with a logger attached). For explicit
# checking, drive the checker's methods around stimulus and print the
# summary at end of test:
checker.check_crresp_validity(crresp, snoop_type)
checker.check_cr_order(snoop_seq)
checker.print_compliance_report()
```

Note: unlike the `axi4` family there is no `create_if_enabled()` helper and
no automatic DUT binding — `AXI4ACEMasterRead/Write.compliance_checker` is
`None` by design; construct `ACEComplianceChecker` directly in the
testbench, as `bin/TBClasses/ace/ace_snoop_transport_tb.py` does.
