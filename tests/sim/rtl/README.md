# Curated RTL for Tier 2 Sim Regression

Two kinds of RTL live here:

1. **Snapshots from RDS** — bridges and converters that already exist in
   the RDS repo, copied here at a pinned commit.
2. **DV-generated bridges** — six new bridges generated from the TOMLs
   in `tests/sim/bridge_specs/` specifically for stressing the BFMs
   under high concurrency. These don't exist in RDS; they were created
   for this regression.

Both groups depend on the broader RDS RTL library (axi4 wrappers, gaxi
skid buffers, dwidth converters) at the pinned commit — resolved via
`$REPO_ROOT` in each `.f` filelist at sim time.

## Provenance

| Field | Value |
|---|---|
| Source repo | `sean-galloway/RTLDesignSherpa` |
| Source commit | `cbe571c1e21e1b36f0dd0f3948c79292ee727893` |
| Source date | 2026-08-18 |
| Regenerated on | 2026-08-18 |

> **All nine bridges are regenerated output, not file copies.** They were
> originally snapshotted at `7aee11a` (2026-06-09) and went stale when RDS
> renamed APB→APB4 and moved the CDC blocks: the filelists still named
> `rtl/amba/apb/apb_master.sv`, `axi4_to_apb_shim.sv` and
> `rtl/amba/shared/cdc_{2,4}_phase_handshake.sv`, and the adapters
> instantiated the old module names, so every bridge failed to elaborate.
> Regenerating from each bridge's own TOML picked up the current generator,
> which pulls each component's own closure filelist (`-f .../axi4_to_apb4_shim.f`)
> instead of hand-listing sources — the reason this class of rot happened at
> all. Group 1's bridges gained filelists in the process; two never had one.
>
> Fix the generator, not these files: everything here is generated output.

### Group 1 — Originally snapshotted from RDS, now regenerated

Per-bridge source paths (relative to RDS root):

- `bridges/bridge_2x2_rw/`     ← `projects/components/bridge/rtl/generated/bridge_2x2_rw/`
- `bridges/bridge_4x4_rw/`     ← `projects/components/bridge/rtl/generated/bridge_4x4_rw/`
- `bridges/bridge_mix_a/`      ← `projects/components/bridge/rtl/generated/bridge_mix_a/`
- `apb_xbar/apb_xbar_2to4.sv`  ← `projects/components/apb_xbar/rtl/apb_xbar_2to4.sv`
- `converters/`                ← `projects/components/converters/rtl/`

### Group 2 — DV-generated bridges (from `tests/sim/bridge_specs/`)

Generated with RDS's `projects/components/bridge/bin/bridge_generator.py`
against the TOMLs in `tests/sim/bridge_specs/`:

- `bridges/bridge_a_axi4_widthmix_4x4/` — 4×4 all-AXI4, mixed widths
- `bridges/bridge_b_axi4_axil_3x5/`     — every protocol cross-combo
- `bridges/bridge_c_dma_heavy_3x6/`     — DMA-heavy AXI4 stress
- `bridges/bridge_d_axil_emphasis_4x4/` — AXIL4-heavy
- `bridges/bridge_e_grand_mix_5x5/`     — max arbitration contention
- `bridges/bridge_f_fanout_2x8/`        — SoC-shaped 2-master fan-out

To regenerate (e.g. after editing a TOML):

```bash
# In RDS with env_python sourced
export REPO_ROOT=/path/to/RTLDesignSherpa
export PYTHONPATH=$REPO_ROOT/bin:$REPO_ROOT/projects/components/bridge/bin
for spec in /path/to/DV/tests/sim/bridge_specs/bridge_*.toml; do
  $REPO_ROOT/venv/bin/python \
    $REPO_ROOT/projects/components/bridge/bin/bridge_generator.py \
    --ports "$spec" --output-dir /tmp/bridge_gen_out
done
# Copy back, then rewrite the generated-file paths.
#
# A bridge filelist deliberately carries two roots: shared RTL as
# $REPO_ROOT/... against RDS, and the generated files as paths relative
# to THIS repo. The generator anchors the latter on wherever it wrote
# them, so they need rewriting to their resting place here.
for d in /tmp/bridge_gen_out/bridge_*; do
  name=$(basename "$d")
  mkdir -p /path/to/DV/tests/sim/rtl/bridges/$name
  cp $d/* /path/to/DV/tests/sim/rtl/bridges/$name/
  cp /tmp/filelists/$name.f /path/to/DV/tests/sim/rtl/bridges/$name/
  sed -i "s|bridge_gen_out/$name/|tests/sim/rtl/bridges/$name/|g" \
    /path/to/DV/tests/sim/rtl/bridges/$name/$name.f
done
```

The Group 1 bridges keep their TOML alongside the RTL, so they
regenerate the same way — point `--ports` at
`tests/sim/rtl/bridges/<name>/<name>.toml`.

Afterwards, confirm every filelist still closes over real files and that
each bridge elaborates:

```bash
verilator --lint-only --top-module <name> <sources from the .f>
```

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
