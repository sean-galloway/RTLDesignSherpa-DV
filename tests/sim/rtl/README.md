# Curated RTL for Tier 2 Sim Regression

This directory contains a **curated snapshot** of RTL from the
[RTLDesignSherpa](https://github.com/sean-galloway/RTLDesignSherpa) (RDS)
repo, picked to exercise BFM concurrency across many interfaces at once.

## Provenance

| Field | Value |
|---|---|
| Source repo | `sean-galloway/RTLDesignSherpa` |
| Source commit | `7aee11af7a8363fbafa75465f7e704f0328debeb` |
| Source date | 2026-06-09 |
| Copied on | 2026-06-09 |

Per-bridge source paths (relative to RDS root):

- `bridges/bridge_2x2_rw/`     ← `projects/components/bridge/rtl/generated/bridge_2x2_rw/`
- `bridges/bridge_4x4_rw/`     ← `projects/components/bridge/rtl/generated/bridge_4x4_rw/`
- `bridges/bridge_mix_a/`      ← `projects/components/bridge/rtl/generated/bridge_mix_a/`
- `apb_xbar/apb_xbar_2to4.sv`  ← `projects/components/apb_xbar/rtl/apb_xbar_2to4.sv`
- `converters/`                ← `projects/components/converters/rtl/`

## Curation rationale

| Bridge | Concurrency profile | Why picked |
|---|---|---|
| `bridge_2x2_rw` | 2 masters × 2 slaves, AXI4 R/W | Baseline multi-master concurrency. Exercises AXI4MasterRead/Write + AXI4SlaveRead/Write at all four corners simultaneously |
| `bridge_4x4_rw` | 4 masters × 4 slaves | Stress: 4 concurrent masters into 4 concurrent slaves — maximum lock contention on the `completion_locks` paths fixed in v0.1.1 (#5) |
| `bridge_mix_a` | AXI4 + AXIL4 + APB mixed | **The interesting one.** Mixed-protocol bridge exercises the new APB↔AXIL4↔AXI4 BFM interactions — covers the protocol-converter paths from #15 (APB5 inherits APB) and the AXIL4 base-addr fixes from v0.1.1 (#1, #2) |
| `apb_xbar_2to4` | 2 APB masters × 4 APB slaves | Single-protocol APB concurrency. Validates APBMaster's queued pipeline (the one APB5Master gained in #15 Phase A) under contention |
| `converters/axi4_to_axil4*.sv` | Width/protocol conversion | Exercises the AXIL4 BFMs directly — the slaves fixed in v0.1.1 (#1, #2) |
| `converters/axil4_to_axi4*.sv` | Reverse direction | Same path in the other direction |
| `converters/axi4_to_apb_shim.sv` | AXI4 master ↔ APB slave bridge | Exercises APBSlave's unified state machine from #15 Phase B alongside AXI4MasterWrite |

## External dependencies

The curated bridges depend on RTL **outside this directory** — they aren't
self-contained. Each bridge's filelist (`.f`) references files under
`$REPO_ROOT` which must resolve to a checkout of the RDS repo. Typical
external deps (per bridge):

- `rtl/amba/includes/*.svh`        — common defines / interfaces
- `rtl/amba/axi4/axi4_slave_*.sv`  — timing wrappers used by master adapters
- `rtl/amba/axi4/axi4_master_*.sv` — timing wrappers used by slave adapters
- `rtl/amba/gaxi/gaxi_skid_buffer.sv`
- `projects/components/converters/rtl/axi4_dwidth_converter_*.sv`
- Mix bridges additionally pull in `axi4_to_apb_*.sv` / `axi4_to_axil4_*.sv`

Currently only `bridge_2x2_rw/bridge_2x2_rw.f` was available upstream;
filelists for the other configs will need to be generated from their
`.toml` or written by hand.

## How Tier 2 sim will resolve `$REPO_ROOT`

When the cocotb sim harness lands (`tests/sim/conftest.py`), it will look
for the RDS root in this order:

1. `RDS_RTL_PATH` env var (developer workflow — point at sibling RDS checkout)
2. `tests/sim/_rds/` git submodule (CI workflow — pinned to a specific RDS commit)
3. Error out with a clear message if neither is set up

A git submodule at the commit listed above is the recommended setup;
that keeps the DV regression reproducible to a fixed RDS revision.

## Updating this snapshot

When the curated set needs to track a newer RDS commit:

```bash
# from this DV repo, with RDS checked out at a sibling path
RDS=/path/to/RTLDesignSherpa
COMMIT=$(git -C "$RDS" rev-parse HEAD)
for d in bridge_2x2_rw bridge_4x4_rw bridge_mix_a; do
  cp "$RDS/projects/components/bridge/rtl/generated/$d"/* "tests/sim/rtl/bridges/$d/"
done
cp "$RDS/projects/components/apb_xbar/rtl/apb_xbar_2to4.sv" tests/sim/rtl/apb_xbar/
cp "$RDS/projects/components/converters/rtl/axi4_to_axil4"*.sv tests/sim/rtl/converters/
cp "$RDS/projects/components/converters/rtl/axil4_to_axi4"*.sv tests/sim/rtl/converters/
cp "$RDS/projects/components/converters/rtl/axi4_to_apb_shim.sv" tests/sim/rtl/converters/
# Then update the commit SHA in this README and commit.
```
