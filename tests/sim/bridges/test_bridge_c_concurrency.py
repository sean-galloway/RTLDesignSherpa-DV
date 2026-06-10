"""Concurrent stress tests for ``bridge_c_dma_heavy_3x6``.

bridge_c is the DMA-heavy AXI4 stress config: 3 AXI4 masters (cpu + 2 DMAs)
into 6 mixed slaves (3 AXI4 + 2 AXIL + 1 APB). It's the right target for the
BFM-side concurrency tests because:

1. **Three AXI4 masters with wider ID widths** → exercises per-ID dequeue
   paths in AXI4MasterRead's ``_response_by_id`` deque (v0.1.1 #3) when
   many same-ID and different-ID responses are in flight simultaneously.

2. **DMA-style burst traffic** → forces concurrent issuance of AW+W
   bursts. AXI4MasterWrite's ``cocotb.triggers.Lock`` around
   ``(send AW, send all W beats)`` (v0.1.1 #4) is the critical path.

3. **APB peripheral tail** → applies backpressure that propagates back
   to the AXI4 path via an axi4_to_apb shim. Exercises APBSlave's unified
   state machine from #15 Phase B under fan-in from a fast AXI4 source.

4. **AXIL4 peripherals** → mixes the AXIL4 BFM into the same concurrency
   window (v0.1.1 #1 base_addr offset, #2 AW/W FIFO matching).

These tests do **not** assert specific cycle counts — the BFM fixes were
about correctness under concurrency, not timing. We verify that:
- Every dispatched transaction completes (no hang/timeout)
- Slave memory contents match what was written
- Per-ID read responses match the seeded pattern (no response mis-routing)
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import pytest

# Path setup — `TBClasses` is installed by tests/sim/conftest.py
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / "_tb_support"))
sys.path.insert(0, str(_HERE))

import cocotb
from cocotb.triggers import ClockCycles
from cocotb_test.simulator import run as cocotb_run

from TBClasses.shared.utilities import get_paths, get_wave_config
from TBClasses.shared.filelist_utils import get_sources_from_filelist

from tbclasses.concurrent_bridge_tb import ConcurrentBridgeTB


# ----------------------------------------------------------------------
# Cocotb tests
# ----------------------------------------------------------------------


@cocotb.test(timeout_time=200, timeout_unit="ms")
async def cocotb_test_bridge_c_basic_connectivity(dut):
    """Sanity: one write + one read per (master, reachable slave) pair.

    No concurrency yet — just confirms the BFM topology is wired up and
    routing is correct. If this passes, the more advanced tests below
    have a baseline that means hangs / mismatches are concurrency-induced.
    """
    tb = ConcurrentBridgeTB(dut, toml_path=str(
        Path(__file__).parent.parent / "bridge_specs" /
        "bridge_c_dma_heavy_3x6.toml"
    ))
    await tb.setup_clocks_and_reset()

    rng = random.Random(0x1)
    for m_idx in range(tb.num_masters):
        for s_idx in range(tb.num_slaves):
            if not tb.can_route(m_idx, s_idx):
                continue
            base = tb._parse_addr(tb.slave_descs[s_idx]["base_addr"])
            bpw = tb.master_descs[m_idx]["data_width"] // 8
            addr = base + ((rng.randint(0, 7) * bpw) & ~(bpw - 1))
            data = 0xA0000000 | (m_idx << 20) | (s_idx << 16) | rng.randint(0, 0xFFFF)
            await tb.master_write(m_idx, addr, data, bpw)
            await tb.master_read(m_idx, addr, bpw)

    await tb.settle()
    assert tb.verify_scoreboard(), "scoreboard failed — see log"


@cocotb.test(timeout_time=500, timeout_unit="ms")
async def cocotb_test_bridge_c_parallel_storm(dut):
    """Every master fires 24 transactions concurrently.

    Hot path: per-ID dequeue (v0.1.1 #3), AW+W lock (#4), completion_locks (#5).
    With 3 masters × 24 transactions = 72 simultaneous BFM coroutines, this
    is the realistic load the BFM concurrency fixes were sized for.
    """
    tb = ConcurrentBridgeTB(dut, toml_path=str(
        Path(__file__).parent.parent / "bridge_specs" /
        "bridge_c_dma_heavy_3x6.toml"
    ))
    await tb.setup_clocks_and_reset()
    await tb.parallel_storm(per_master_txns=24, write_fraction=0.5)
    await tb.settle()
    assert tb.verify_scoreboard(), "scoreboard failed — see log"


@cocotb.test(timeout_time=300, timeout_unit="ms")
async def cocotb_test_bridge_c_same_id_completion_lock(dut):
    """24 concurrent same-ID writes from dma0 to ddr0.

    This is the worst case for ``AXI4SlaveWrite.completion_locks``: every
    transaction shares ID 0 and targets the same slave, so the per-ID
    lock is contended on every B-response generation. If the v0.1.1 #5
    fix is missing or regressed, this test will hang or produce mis-routed
    B-responses.
    """
    tb = ConcurrentBridgeTB(dut, toml_path=str(
        Path(__file__).parent.parent / "bridge_specs" /
        "bridge_c_dma_heavy_3x6.toml"
    ))
    await tb.setup_clocks_and_reset()

    # Find dma0 (master 1) and ddr0 (slave 0) from the TOML
    dma0_idx = next(i for i, m in enumerate(tb.master_descs)
                    if m["name"] == "dma0")
    ddr0_idx = next(i for i, s in enumerate(tb.slave_descs)
                    if s["name"] == "ddr0")

    await tb.same_id_storm(
        master_idx=dma0_idx,
        slave_idx=ddr0_idx,
        txn_id=0,
        count=24,
        operation="write",
    )
    await tb.settle()
    assert tb.verify_scoreboard(), "scoreboard failed under same-ID storm"


@cocotb.test(timeout_time=300, timeout_unit="ms")
async def cocotb_test_bridge_c_per_id_response_race(dut):
    """16 concurrent reads from dma0 to ddr0 with 4 IDs in rotation.

    Tests AXI4MasterRead's per-ID ``_response_by_id`` deque demultiplexer
    (v0.1.1 #3). With 16 reads sharing 4 IDs (4 per ID) all in flight,
    the bridge will return R beats out of order across IDs, and the
    master must demux them per-ID without losing or mis-routing any.
    """
    tb = ConcurrentBridgeTB(dut, toml_path=str(
        Path(__file__).parent.parent / "bridge_specs" /
        "bridge_c_dma_heavy_3x6.toml"
    ))
    await tb.setup_clocks_and_reset()

    dma0_idx = next(i for i, m in enumerate(tb.master_descs)
                    if m["name"] == "dma0")
    ddr0_idx = next(i for i, s in enumerate(tb.slave_descs)
                    if s["name"] == "ddr0")

    await tb.read_response_race(
        master_idx=dma0_idx,
        slave_idx=ddr0_idx,
        num_concurrent=16,
        ids_in_play=4,
    )
    await tb.settle()
    assert tb.verify_scoreboard(), "scoreboard failed under per-ID race"


@cocotb.test(timeout_time=400, timeout_unit="ms")
async def cocotb_test_bridge_c_apb_fan_in(dut):
    """All 3 AXI4 masters hammer apb_periph0 concurrently.

    Exercises APBSlave's unified ``_monitor_recv`` (from #15 Phase B) under
    multi-source fan-in via the bridge's axi4_to_apb shim. The APB slave
    state machine has to serialize incoming requests from three protocol
    paths that converge on its single response port.
    """
    tb = ConcurrentBridgeTB(dut, toml_path=str(
        Path(__file__).parent.parent / "bridge_specs" /
        "bridge_c_dma_heavy_3x6.toml"
    ))
    await tb.setup_clocks_and_reset()

    apb_idx = next(i for i, s in enumerate(tb.slave_descs)
                   if s["name"] == "apb_periph0")
    apb_base = tb._parse_addr(tb.slave_descs[apb_idx]["base_addr"])

    tasks = []
    for m_idx in range(tb.num_masters):
        if not tb.can_route(m_idx, apb_idx):
            continue
        bpw = tb.master_descs[m_idx]["data_width"] // 8
        for n in range(8):
            addr = apb_base + ((m_idx * 8 + n) * 4)  # disjoint addresses per master
            data = 0xAB000000 | (m_idx << 16) | n
            tasks.append(cocotb.start_soon(
                tb.master_write(m_idx, addr, data, bpw, txn_id=n)
            ))
    for t in tasks:
        await t.join()

    await tb.settle(300)
    assert tb.verify_scoreboard(), "scoreboard failed under APB fan-in"


# ----------------------------------------------------------------------
# Pytest wrappers
# ----------------------------------------------------------------------


def _bridge_test_pytest_wrapper(testcase: str):
    """Shared scaffolding for the four parametrized cocotb tests below.

    Each wrapper:
    - Resolves RTL paths via TBClasses.shared.utilities.get_paths
    - Loads bridge_c's filelist for `verilog_sources`
    - Builds a per-test sim_build directory (xdist-worker-isolated)
    - Calls cocotb_test.simulator.run(...)
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
    worker_suffix = f"_{worker_id}" if worker_id else ""

    module, repo_root, tests_dir, log_dir, rtl_dict = get_paths({})

    bridge_dir = Path(__file__).parent.parent / "rtl" / "bridges" / "bridge_c_dma_heavy_3x6"
    filelist = bridge_dir / "bridge_c_dma_heavy_3x6.f"
    verilog_sources, includes = get_sources_from_filelist(
        repo_root=repo_root,
        filelist_path=str(filelist),
    )

    dut_name = "bridge_c_dma_heavy_3x6"
    test_name = f"test_{dut_name}_{testcase}{worker_suffix}"
    log_path = os.path.join(log_dir, f"{test_name}.log")
    results_path = os.path.join(log_dir, f"results_{test_name}.xml")
    sim_build = os.path.join(tests_dir, "local_sim_build", test_name)
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    waves = get_wave_config(sim_build)

    cocotb_run(
        verilog_sources=verilog_sources,
        includes=includes,
        toplevel=dut_name,
        module=module,
        sim_build=sim_build,
        extra_env={
            "COCOTB_LOG_LEVEL": "INFO",
            "LOG_PATH": log_path,
            "COCOTB_RESULTS_FILE": results_path,
            **waves["extra_env"],
        },
        extra_args=["--assert"] + waves["extra_args"],
        testcase=f"cocotb_test_bridge_c_{testcase}",
    )


def test_bridge_c_basic_connectivity(request):
    _bridge_test_pytest_wrapper("basic_connectivity")


def test_bridge_c_parallel_storm(request):
    _bridge_test_pytest_wrapper("parallel_storm")


def test_bridge_c_same_id_completion_lock(request):
    _bridge_test_pytest_wrapper("same_id_completion_lock")


def test_bridge_c_per_id_response_race(request):
    _bridge_test_pytest_wrapper("per_id_response_race")


def test_bridge_c_apb_fan_in(request):
    _bridge_test_pytest_wrapper("apb_fan_in")
