"""Cross-protocol concurrency tests for ``bridge_b_axi4_axil_3x5``.

bridge_b is the "every protocol cross-combo" bridge: 2 AXI4 + 1 AXIL master
into 2 AXI4 + 2 AXIL + 1 APB slaves. Every master-protocol × slave-protocol
combination is exercised at least once. Tests here focus on **simultaneous
heterogeneous-protocol traffic** rather than same-protocol stress.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent))  # makes TBClasses/ importable
sys.path.insert(0, str(_HERE))

import cocotb
from cocotb.triggers import ClockCycles
from cocotb_test.simulator import run as cocotb_run

from TBClasses.shared.utilities import get_paths, get_wave_config
from TBClasses.shared.filelist_utils import get_sources_from_filelist

from tbclasses.concurrent_bridge_tb import ConcurrentBridgeTB


_TOML = str(_HERE.parent / "bridge_specs" / "bridge_b_axi4_axil_3x5.toml")


@cocotb.test(timeout_time=200, timeout_unit="ms")
async def cocotb_test_bridge_b_basic_connectivity(dut):
    tb = ConcurrentBridgeTB(dut, toml_path=_TOML)
    await tb.setup_clocks_and_reset()

    for m_idx in range(tb.num_masters):
        for s_idx in range(tb.num_slaves):
            if not tb.can_route(m_idx, s_idx):
                continue
            base = tb._parse_addr(tb.slave_descs[s_idx]["base_addr"])
            bpw = tb.master_descs[m_idx]["data_width"] // 8
            addr = base + (4 * bpw)
            data = 0xB0000000 | (m_idx << 20) | (s_idx << 16)
            await tb.master_write(m_idx, addr, data, bpw)
            await tb.master_read(m_idx, addr, bpw)

    await tb.settle()
    assert tb.verify_scoreboard(), "scoreboard failed"


@cocotb.test(timeout_time=400, timeout_unit="ms")
async def cocotb_test_bridge_b_cross_protocol_race(dut):
    """AXI4 + AXIL masters all dispatch transactions in the same cycle window.

    The point isn't volume — it's interleaving. The cocotb scheduler must
    correctly serialize AXI4MasterWrite's AW+W lock with AXIL4MasterWrite's
    issue path with the bridge's protocol shim activity.
    """
    tb = ConcurrentBridgeTB(dut, toml_path=_TOML)
    await tb.setup_clocks_and_reset()
    await tb.cross_protocol_race(per_master_txns=6)
    await tb.settle()
    assert tb.verify_scoreboard(), "scoreboard failed under cross-protocol race"


@cocotb.test(timeout_time=500, timeout_unit="ms")
async def cocotb_test_bridge_b_parallel_storm(dut):
    tb = ConcurrentBridgeTB(dut, toml_path=_TOML)
    await tb.setup_clocks_and_reset()
    await tb.parallel_storm(per_master_txns=20, write_fraction=0.5)
    await tb.settle()
    assert tb.verify_scoreboard(), "scoreboard failed"


# ---- Pytest wrappers ----


def _wrap(testcase: str):
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
    worker_suffix = f"_{worker_id}" if worker_id else ""

    module, repo_root, tests_dir, log_dir, _rtl = get_paths({})
    bridge_dir = _HERE.parent / "rtl" / "bridges" / "bridge_b_axi4_axil_3x5"
    filelist = bridge_dir / "bridge_b_axi4_axil_3x5.f"
    verilog_sources, includes = get_sources_from_filelist(
        repo_root=repo_root, filelist_path=str(filelist),
    )

    dut_name = "bridge_b_axi4_axil_3x5"
    test_name = f"test_{dut_name}_{testcase}{worker_suffix}"
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
            "LOG_PATH": os.path.join(log_dir, f"{test_name}.log"),
            "COCOTB_RESULTS_FILE": os.path.join(log_dir, f"results_{test_name}.xml"),
            **waves["extra_env"],
        },
        extra_args=["--assert"] + waves["extra_args"],
        testcase=f"cocotb_test_bridge_b_{testcase}",
    )


def test_bridge_b_basic_connectivity(request):
    _wrap("basic_connectivity")


def test_bridge_b_cross_protocol_race(request):
    _wrap("cross_protocol_race")


def test_bridge_b_parallel_storm(request):
    _wrap("parallel_storm")
