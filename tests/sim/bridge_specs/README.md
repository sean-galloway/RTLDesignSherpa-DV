# Bridge Specs for BFM Concurrency Regression

6 bridge configurations designed to stress the cocotb-framework BFMs
across the full AMBA4 protocol matrix at high concurrency. Each:

- ≥ 8 ports total (masters + slaves)
- ≥ 2 masters (most have 3–5)
- Mixed AXI4 / AXIL4 / APB protocols on both sides
- Mixed data widths to exercise the dwidth converters
- Distinct address ranges per slave for misroute detection

## The 6 bridges

| Spec | Masters | Slaves | Total | Protocol mix | What it stresses |
|---|---|---|---|---|---|
| `bridge_a_axi4_widthmix_4x4.toml` | 4× AXI4 (32, 64, 128, 256-bit) | 4× AXI4 (mixed widths) | 8 | All AXI4 | `axi4_dwidth_converter_*` at every cross-width path; 16 concurrent BFMs |
| `bridge_b_axi4_axil_3x5.toml` | 2× AXI4 + 1× AXIL4 | 2× AXI4 + 2× AXIL4 + 1× APB | 8 | AXI4 master → all three slaves; AXIL4 master → all three slaves | Exercises `axi4_to_axil4`, `axi4_to_apb`, `axil4_to_axi4` shims simultaneously |
| `bridge_c_dma_heavy_3x6.toml` | 3× AXI4 (cpu, dma0, dma1) | 3× AXI4 + 2× AXIL4 + 1× APB | 9 | DMA-heavy AXI4 concurrency, slow APB tail | Per-ID lock contention on `completion_locks` (v0.1.1 #5); APBSlave's unified state machine (#15 Phase B) under bursty DMA traffic |
| `bridge_d_axil_emphasis_4x4.toml` | 2× AXI4 + 2× AXIL4 | 1× AXI4 + 2× AXIL4 + 1× APB | 8 | Lightweight protocols on both sides | AXIL4 BFM stress; validates the AXIL4 `base_addr` + AW/W FIFO matching fixes from v0.1.1 (#1, #2) |
| `bridge_e_grand_mix_5x5.toml` | 3× AXI4 + 2× AXIL4 | 2× AXI4 + 2× AXIL4 + 1× APB | 10 | Wide bridge — max arbitration contention | Multi-master arbitration; 25 master×slave paths exercise every protocol cross-combination at least 3× |
| `bridge_f_fanout_2x8.toml` | 2× AXI4 (cpu + dma) | 4× AXI4 + 2× AXIL4 + 2× APB | 10 | High fan-out, SoC interconnect shape | Single master burst routing across 8 destinations; APB queued pipeline (#15) under tail-end APB slaves |

## Protocol cross-coverage matrix

Each (master_protocol → slave_protocol) combination is exercised somewhere
in the suite:

| | → AXI4 slave | → AXIL4 slave | → APB slave |
|---|:---:|:---:|:---:|
| **AXI4 master →**  | a, b, c, d, e, f | b, c, d, e, f | b, c, d, e, f |
| **AXIL4 master →** | b, d, e | b, d, e | b, d, e |

(APB-as-master is not used — the bridge generator's converter library is
configured for AXI/AXIL masters into APB slaves, which is the realistic
SoC topology. If APB master support is added later, a `bridge_g_*` can
fill that row.)

## How to generate the RTL

The bridge generator lives in RDS at `projects/components/bridge/bin/`
and requires the RDS Python environment (`rtl_generators` package, etc.).

```bash
# In your RDS checkout:
cd $REPO_ROOT/projects/components/bridge
source $REPO_ROOT/env_python

# For each TOML in DV:
for toml in /path/to/RTLDesignSherpa-DV/tests/sim/bridge_specs/bridge_*.toml; do
  bin/bridge_generator.py --toml "$toml" --output-dir rtl/generated/
done

# Then copy the generated RTL back to DV:
for name in a_axi4_widthmix_4x4 b_axi4_axil_3x5 c_dma_heavy_3x6 \
            d_axil_emphasis_4x4 e_grand_mix_5x5 f_fanout_2x8; do
  cp -r rtl/generated/bridge_$name \
        /path/to/RTLDesignSherpa-DV/tests/sim/rtl/bridges/
done
```

Once generated, each bridge's `.f` filelist will reference
`$REPO_ROOT/rtl/amba/...` for the framework RTL deps — same resolution
path as the existing curated bridges, via `tests/sim/conftest.py`.

## Address map (shared across all 6 bridges)

For ease of cross-bridge test reuse, all bridges use the same address layout:

| Slave name | Base | Range | Used by bridge |
|---|---|---|---|
| `ddr0`           | `0x00000000` | 1 GB (`0x40000000`) | a, b, c, d, e, f |
| `ddr1`           | `0x40000000` | 1 GB (`0x40000000`) | a, c, e, f |
| `sram`           | `0x80000000` | 16 MB (`0x01000000`) | a, b, d, f |
| `scratch`        | `0x81000000` | 16 MB (`0x01000000`) | a, c, e, f |
| `axil_periph0`   | `0x90000000` | 64 KB (`0x00010000`) | b, c, d, e, f |
| `axil_periph1`   | `0x90010000` | 64 KB (`0x00010000`) | b, c, d, e |
| `apb_periph0`    | `0xA0000000` | 64 KB (`0x00010000`) | b, c, d, e, f |
| `apb_periph1`    | `0xA0010000` | 64 KB (`0x00010000`) | c, f |

A misroute is visible at hex-dump glance using the seed pattern from
`Bridge2x2RwTB._seed_value`:
`((slave_idx + 1) << 24) | (word_offset & 0xFFFFFF)`.
