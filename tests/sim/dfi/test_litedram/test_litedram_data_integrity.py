# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2026 sean galloway

"""Data-integrity test: DFII WR with payload → DFISlavePHY MemoryModel.

Where ``test_litedram_user_traffic`` exercises command coverage, this
test exercises the **write-data path**: each DFII write injection
carries a known 32-bit payload (per phase), and we verify the
DFISlavePHY's MemoryModel ends up holding that payload at the
expected (bank, row, col) → flat address.

DFII data-injection mechanism:
    Each PIx phase has, in addition to (CMD, COMMAND_ISSUE, ADDRESS,
    BADDRESS), a WRDATA register at PI_BASE + 0x10. To stage a write
    with payload:
        1. PIx.WRDATA = <payload>
        2. PIx.ADDRESS = <col>
        3. PIx.BADDRESS = <bank>
        4. PIx.COMMAND = WRITE | DFII_COMMAND_WRDATA
        5. PIx.COMMAND_ISSUE = 1
    The DFII drives ``wrdata_en`` on phase x and forwards the WRDATA
    register onto the DFI wrdata bus for that phase.

Data-integrity check:
    The DFISlavePHY listens on ``phy_dfi`` (post-shim) and latches
    wrdata into ``slave.memory`` keyed by flat(bank, open_row, col)
    × bytes_per_beat. After the test issues N writes with N distinct
    payloads, we recompute each expected flat byte address and assert
    ``slave.memory.read(addr, 16)`` matches what we sent.

Why this matters:
    Catches bugs in: the slave's wrdata sampling timing, address-
    mapping calculation, CL/CWL-pipelined commit ordering, and the
    adapter's wrdata propagation through gear demux.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run

from CocoTBFramework.components.dfi import (
    AddressMapping,
    DFIBase,
    DFIPhaseAdapter,
    DFIVersion,
    DRAMCommand,
    MemoryType,
    builtin_timings,
)
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.shared.memory_model import MemoryModel


CSR_DDRCTRL_INIT_DONE  = 0x000
CSR_SDRAM_DFII_CONTROL = 0x800
PI_BASE = {0: 0x804, 1: 0x81c, 2: 0x834, 3: 0x84c}

# CONTROL bits
CTRL_CKE     = 0x02
CTRL_ODT     = 0x04
CTRL_RESET_N = 0x08

# COMMAND register bit positions
CMD_CS     = 0x01
CMD_WE     = 0x02
CMD_CAS    = 0x04
CMD_RAS    = 0x08
CMD_WRDATA = 0x10
CMD_RDDATA = 0x20

# JEDEC DDR3 command encodings (in DFII bit-positions)
ACTIVATE   = CMD_RAS                            | CMD_CS
WRITE      =          CMD_CAS | CMD_WE          | CMD_CS
WRITE_WD   = WRITE                              | CMD_WRDATA
READ       =          CMD_CAS                   | CMD_CS
PRECHARGE  = CMD_RAS                  | CMD_WE  | CMD_CS
ZQC        =                            CMD_WE  | CMD_CS
MRS        = CMD_RAS | CMD_CAS        | CMD_WE  | CMD_CS

_PHASE_SIGNAL_NAMES = (
    "address", "bank", "cas_n", "ras_n", "we_n",
    "cs_n", "cke", "odt", "reset_n",
    "wrdata", "wrdata_en", "wrdata_mask",
    "rddata_en",
)


def pi_cmd(p):    return PI_BASE[p]
def pi_iss(p):    return PI_BASE[p] + 0x04
def pi_adr(p):    return PI_BASE[p] + 0x08
def pi_bad(p):    return PI_BASE[p] + 0x0c
def pi_wrdat(p):  return PI_BASE[p] + 0x10


async def wb_ctrl_write(dut, addr, data, timeout=100):
    dut.wb_ctrl_adr.value   = addr >> 2
    dut.wb_ctrl_dat_w.value = data
    dut.wb_ctrl_sel.value   = 0xF
    dut.wb_ctrl_cyc.value   = 1
    dut.wb_ctrl_stb.value   = 1
    dut.wb_ctrl_we.value    = 1
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        if int(dut.wb_ctrl_ack.value) == 1:
            break
    else:
        raise TimeoutError(f"wb_ctrl write to 0x{addr:x} never ack'd")
    dut.wb_ctrl_cyc.value = 0
    dut.wb_ctrl_stb.value = 0
    dut.wb_ctrl_we.value  = 0
    await RisingEdge(dut.clk)


async def _settle(dut, cycles):
    for _ in range(cycles):
        await RisingEdge(dut.clk)


async def litedram_ddr3_init(dut):
    """Canonical 7-step DDR3 init (ported from sdram_phy.h)."""
    await wb_ctrl_write(dut, pi_adr(0), 0x0)
    await wb_ctrl_write(dut, pi_bad(0), 0)
    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL, CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 200)

    await wb_ctrl_write(dut, CSR_SDRAM_DFII_CONTROL,
                       CTRL_CKE | CTRL_ODT | CTRL_RESET_N)
    await _settle(dut, 100)

    async def mrs(addr, bank):
        await wb_ctrl_write(dut, pi_adr(0), addr)
        await wb_ctrl_write(dut, pi_bad(0), bank)
        await wb_ctrl_write(dut, pi_cmd(0), MRS)
        await wb_ctrl_write(dut, pi_iss(0), 1)
        await _settle(dut, 20)

    await mrs(0x200, 2)   # MR2, CWL=5
    await mrs(0x000, 3)   # MR3
    await mrs(0x006, 1)   # MR1
    await mrs(0x920, 0)   # MR0, CL=6, BL=8
    await _settle(dut, 50)

    # ZQ Calibration
    await wb_ctrl_write(dut, pi_adr(0), 0x400)
    await wb_ctrl_write(dut, pi_bad(0), 0)
    await wb_ctrl_write(dut, pi_cmd(0), ZQC)
    await wb_ctrl_write(dut, pi_iss(0), 1)
    await _settle(dut, 100)

    await wb_ctrl_write(dut, CSR_DDRCTRL_INIT_DONE, 1)
    await _settle(dut, 30)


async def inject_cmd(dut, phase, command, address=0, bank=0,
                     wrdata=None):
    if wrdata is not None:
        await wb_ctrl_write(dut, pi_wrdat(phase), wrdata)
    await wb_ctrl_write(dut, pi_adr(phase),  address)
    await wb_ctrl_write(dut, pi_bad(phase),  bank)
    await wb_ctrl_write(dut, pi_cmd(phase),  command)
    await wb_ctrl_write(dut, pi_iss(phase),  1)
    await _settle(dut, 4)


async def _bring_up(dut, settle_cycles=20):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    cocotb.start_soon(Clock(dut.phy_clk, 2500, units="ps").start())
    dut.sim_trace.value = 0
    dut.dfi_rstn.value = 1
    for sig in (
        "user_port_wishbone_0_adr", "user_port_wishbone_0_dat_w",
        "user_port_wishbone_0_sel", "user_port_wishbone_0_cyc",
        "user_port_wishbone_0_stb", "user_port_wishbone_0_we",
        "wb_ctrl_adr", "wb_ctrl_dat_w", "wb_ctrl_sel",
        "wb_ctrl_cyc", "wb_ctrl_stb", "wb_ctrl_we",
        "wb_ctrl_cti", "wb_ctrl_bte",
    ):
        getattr(dut, sig).value = 0
    for _ in range(settle_cycles):
        await RisingEdge(dut.clk)


async def _sample_litedram_4phase(dut, adapter):
    while True:
        await RisingEdge(dut.clk)
        batch = []
        for p in range(4):
            phase = {}
            for sig in _PHASE_SIGNAL_NAMES:
                phase[sig] = int(getattr(dut, f"dfi_p{p}_{sig}").value)
            batch.append(phase)
        adapter.feed(batch)


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def litedram_data_integrity_test(dut):
    """Inject WRs with known wrdata payloads on all 4 phases; verify
    slave.memory holds the expected bytes at the computed flat
    addresses."""
    await _bring_up(dut)

    timings = builtin_timings("ddr3-1600")
    mapping = AddressMapping(
        num_ranks=1, num_banks=8, num_rows=16, num_cols=16,
    )
    base = DFIBase(
        dfi_version=DFIVersion.V3_1,
        memory_type=MemoryType.DDR4,
        timings=timings,
        mapping=mapping,
        beats_per_burst=1,
    )
    # 8 × 16 × 16 = 2048 col units × 16 B per beat = 32 KB
    memory = MemoryModel(num_lines=2048, bytes_per_line=16)
    slave = DFISlavePHY(dut, dut.phy_clk, base=base, memory=memory)

    adapter = DFIPhaseAdapter(
        dut, dest_prefix="mc_dfi", n_phases=4, dfi_clock=dut.phy_clk,
    )
    cocotb.start_soon(adapter.run())
    cocotb.start_soon(_sample_litedram_4phase(dut, adapter))
    await Timer(1, units="ns")

    await litedram_ddr3_init(dut)

    # ----- Programmed write set -----
    # Each entry: (phase, bank, row, col, payload32).
    # We pre-ACT each (bank, row) so the slave's bank state has
    # open_row set when WR comes in. Payloads are unique per write so
    # we can attribute slave.memory reads back to exact entries.
    writes = []
    payload_base = 0xCAFE_0000
    for bank in range(4):           # banks 0..3
        row = bank + 1              # rows 1..4
        for phase in range(4):
            col = phase             # col 0..3
            payload = payload_base + (bank << 8) + (phase << 4) + col
            writes.append((phase, bank, row, col, payload))

    # ----- Stage 1: ACT all (bank, row) pairs -----
    dut._log.info(f"Staging {len(writes)} writes — ACT phase first")
    for bank in range(4):
        row = bank + 1
        await inject_cmd(dut, phase=bank, command=ACTIVATE,
                         address=row, bank=bank)
    await _settle(dut, 20)   # tRCD respect

    # ----- Stage 2: WR with payload -----
    dut._log.info("WR injection with payloads...")
    for phase, bank, row, col, payload in writes:
        await inject_cmd(dut, phase=phase, command=WRITE_WD,
                         address=col, bank=bank, wrdata=payload)
    await _settle(dut, 200)   # CWL + commit drain

    cmd_counts = dict(slave.cmd_counts)
    dut._log.info(f"cmd_counts: {cmd_counts}")
    dut._log.info(f"adapter: {adapter}")
    dut._log.info(f"slave: {slave}")

    # ----- Assertions on traffic counts -----
    assert cmd_counts.get(DRAMCommand.MRS, 0) >= 4
    assert cmd_counts.get(DRAMCommand.ACT, 0) >= 4
    assert cmd_counts.get(DRAMCommand.WR, 0) >= len(writes)
    assert slave.writes_committed >= len(writes), (
        f"slave should have committed ≥{len(writes)} writes, "
        f"got {slave.writes_committed}"
    )

    # ----- Data integrity: read each address back from slave.memory -----
    # We re-derive the flat address by hand from (bank, row, col) using
    # the same formula the slave uses internally.
    dut._log.info("Verifying slave.memory contents...")
    mismatches = []
    for phase, bank, row, col, payload in writes:
        flat = mapping.tuple_to_flat(0, bank, row, col)
        byte_addr = flat * memory.bytes_per_line
        observed = memory.bytearray_to_integer(
            memory.read(byte_addr, memory.bytes_per_line)
        )
        # The DFI wrdata bus for our 4-phase DDR3 is 32 bits per phase,
        # but the slave reads `data_width = mem.bytes_per_line × 8`
        # which is 128 bits. The 32-bit payload lands in the low bits;
        # upper bits should be whatever was on the bus (idle = 0).
        low32 = observed & 0xFFFF_FFFF
        if low32 != payload:
            mismatches.append((bank, row, col, payload, observed))

    if mismatches:
        dut._log.info(f"  {len(mismatches)} mismatches (showing first 4):")
        for bank, row, col, want, got in mismatches[:4]:
            dut._log.info(
                f"    bank={bank} row={row} col={col}: "
                f"want=0x{want:x} got=0x{got:x}"
            )

    assert not mismatches, (
        f"{len(mismatches)}/{len(writes)} data-integrity mismatches "
        f"(see log for first few)"
    )

    dut._log.info("Data integrity verified for all DFII writes")


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------


def test_litedram_data_integrity(request):
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    litedram_dir = os.path.join(repo_root, "tests", "sim", "rtl", "litedram")
    core_v = os.path.join(litedram_dir, "ddr3", "gateware", "litedram_core.v")
    if not os.path.exists(core_v):
        import pytest
        pytest.skip(f"Generated LiteDRAM RTL missing: {core_v}")

    test_name = "test_litedram_data_integrity"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build", test_name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    extra_env = {
        "COCOTB_LOG_LEVEL": "INFO",
        "COCOTB_RESULTS_FILE": os.path.join(log_dir, f"results_{test_name}.xml"),
    }
    extra_args = [
        "-Wno-TIMESCALEMOD", "-Wno-COMBDLY", "-Wno-CASEINCOMPLETE",
        "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC", "-Wno-UNOPTFLAT",
        "-Wno-CMPCONST", "-Wno-UNUSEDSIGNAL", "-Wno-UNUSEDPARAM",
        "-Wno-MULTIDRIVEN", "-Wno-SELRANGE", "-Wno-LATCH",
        "-Wno-DECLFILENAME",
    ]

    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=[
            os.path.join(litedram_dir, "litedram_cosim_top.sv"),
            os.path.join(litedram_dir, "litedram_dfi_wrapper.sv"),
            core_v,
            os.path.join(repo_root, "tests", "sim", "rtl", "dfi", "dfi_shim.sv"),
        ],
        toplevel="litedram_cosim_top",
        module="test_litedram_data_integrity",
        sim_build=sim_build,
        extra_env=extra_env,
        extra_args=extra_args,
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
