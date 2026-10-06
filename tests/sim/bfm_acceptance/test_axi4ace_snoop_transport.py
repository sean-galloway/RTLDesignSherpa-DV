# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: test_axi4ace_snoop_transport
# Purpose: BFM acceptance test for the new ACE snoop-channel BFMs against
#          the new ACE snoop transport RTL (axi4ace_snoop_slave and
#          axi4ace_snoop_master).
#
# Subsystem: tests

"""ACE snoop-channel BFM acceptance test.

Exercises ``AXI4ACESnoopMaster`` and ``AXI4ACESnoopSlave`` through the
snoop-channel skid-buffer RTL in both orientations:

* ``axi4ace_snoop_slave`` (cache-side transport): master on ``m_axi_``,
  responder on ``fub_``.
* ``axi4ace_snoop_master`` (CCU-side transport): master on ``fub_``,
  responder on ``m_axi_``.

A small stretch test also checks ``AXI4ACEMasterRead`` driving
``axi4ace_master_rd`` with an ``AXI4SlaveRead`` on the master-side AXI4
interface and verifies the auto-pulsed ``m_axi_rack``.
"""

import os
import random
import pytest
import cocotb
from cocotb.triggers import RisingEdge, Event, with_timeout
from cocotb_test.simulator import run

from TBClasses.shared.tbbase import TBBase
from TBClasses.shared.utilities import get_paths, create_view_cmd

from CocoTBFramework.components.ace.ace_interfaces import (
    AXI4ACESnoopMaster,
    AXI4ACESnoopSlave,
    AXI4ACEMasterRead,
)
from CocoTBFramework.components.ace.ace_transaction import (
    CRRESP,
    CacheState,
    SnoopType,
    ACETransactionType,
)
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4SlaveRead
from CocoTBFramework.components.shared.flex_randomizer import FlexRandomizer

# ---------------------------------------------------------------------------
# Local TB class
# ---------------------------------------------------------------------------

class AxeSnoopTB(TBBase):
    """Minimal TBBase subclass for the ACE snoop transport DUTs."""

    def __init__(self, dut):
        super().__init__(dut)

    async def start_test(self):
        """Start clock and apply the standard reset sequence."""
        await self.start_clock('aclk', 10, 'ns')
        await self.assert_reset()
        await self.wait_clocks('aclk', 5)
        await self.deassert_reset()
        await self.wait_clocks('aclk', 5)

    async def assert_reset(self):
        self.dut.aresetn.value = 0
        self.mark_progress('assert_reset')
        await self.wait_clocks('aclk', 1)

    async def deassert_reset(self):
        self.dut.aresetn.value = 1
        self.mark_progress('deassert_reset')
        await self.wait_clocks('aclk', 1)


# ---------------------------------------------------------------------------
# Filelist helper
# ---------------------------------------------------------------------------

def _sources_from_filelist(filelist_path: str, repo_root: str):
    """Parse a ``.f`` filelist, expanding ``$REPO_ROOT``.

    Returns a tuple ``(verilog_sources, include_dirs)``.  Lines beginning
    with ``+incdir+`` become absolute include directories; other non-comment
    lines become absolute Verilog source paths.
    """
    verilog_sources = []
    include_dirs = []
    with open(filelist_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.split('#')[0].strip()
            if not line:
                continue
            if line.startswith('+incdir+'):
                path_only = line[len('+incdir+'):].strip()
            else:
                path_only = line
            expanded = os.path.expandvars(path_only)
            if '$REPO_ROOT' in expanded and repo_root:
                expanded = expanded.replace('$REPO_ROOT', repo_root)
            expanded = os.path.abspath(expanded)
            if line.startswith('+incdir+'):
                include_dirs.append(expanded)
            else:
                verilog_sources.append(expanded)
    return verilog_sources, include_dirs


# ---------------------------------------------------------------------------
# Snoop responder model
# ---------------------------------------------------------------------------

def _make_snoop_handler(data_seed: int = 0xDEAD_BEEF):
    """Return a deterministic MESI snoop handler with non-zero data."""

    def handler(addr: int, snoop_type: SnoopType, state: CacheState):
        if state == CacheState.INVALID:
            return CRRESP(0), None

        if state == CacheState.SHARED:
            if snoop_type in (SnoopType.READ_SHARED, SnoopType.READ_ONCE):
                return CRRESP.from_bits(is_shared=True), None
            return CRRESP(0), None

        if state == CacheState.EXCLUSIVE:
            data = (addr ^ data_seed) & 0xFFFF_FFFF
            if snoop_type in (SnoopType.READ_SHARED, SnoopType.READ_ONCE):
                return CRRESP.from_bits(
                    data_transfer=True, is_shared=True, was_unique=True
                ), data
            if snoop_type == SnoopType.READ_UNIQUE:
                return CRRESP.from_bits(data_transfer=True, was_unique=True), data
            if snoop_type == SnoopType.CLEAN_SHARED:
                return CRRESP.from_bits(is_shared=True, was_unique=True), None
            return CRRESP(0), None

        if state == CacheState.MODIFIED:
            data = (addr ^ 0xBEEF_CAFE) & 0xFFFF_FFFF
            if snoop_type == SnoopType.READ_SHARED:
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), data
            if snoop_type == SnoopType.READ_UNIQUE:
                return CRRESP.from_bits(data_transfer=True, pass_dirty=True), data
            if snoop_type in (SnoopType.CLEAN_SHARED, SnoopType.CLEAN_INVALID):
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), data
            if snoop_type == SnoopType.MAKE_INVALID:
                return CRRESP(0), None
            if snoop_type == SnoopType.READ_ONCE:
                return CRRESP.from_bits(data_transfer=True, pass_dirty=True), data
            return CRRESP(0), None

        if state == CacheState.OWNED:
            data = (addr ^ 0xCAFE_BABE) & 0xFFFF_FFFF
            if snoop_type in (SnoopType.READ_SHARED, SnoopType.READ_ONCE):
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), data
            if snoop_type == SnoopType.READ_UNIQUE:
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), data
            if snoop_type in (SnoopType.CLEAN_SHARED, SnoopType.CLEAN_INVALID):
                return CRRESP.from_bits(
                    data_transfer=True, pass_dirty=True, is_shared=True
                ), data
            if snoop_type == SnoopType.MAKE_INVALID:
                return CRRESP(0), None
            return CRRESP(0), None

        return CRRESP(0), None

    return handler


# ---------------------------------------------------------------------------
# Core cocotb test body
# ---------------------------------------------------------------------------

async def _run_snoop_transport(dut, master_prefix: str, slave_prefix: str):
    tb = AxeSnoopTB(dut)

    seed = int(os.environ.get('SEED', '0'))
    random.seed(seed)
    tb.log.info(f"ACE snoop transport test starting with SEED={seed}")

    await tb.start_test()

    master = AXI4ACESnoopMaster(
        dut=dut,
        clock=dut.aclk,
        prefix=master_prefix,
        log=tb.log,
        ifc_name="init",
        data_width=32,
        addr_width=32,
    )
    slave = AXI4ACESnoopSlave(
        dut=dut,
        clock=dut.aclk,
        prefix=slave_prefix,
        log=tb.log,
        ifc_name="resp",
        data_width=32,
        addr_width=32,
    )

    # Program the responder-side cache-line state matrix.
    addr_map = {
        'invalid':   0x0000_0000,
        'shared':    0x0000_1000,
        'exclusive': 0x0000_2000,
        'modified':  0x0000_3000,
        'owned':     0x0000_4000,
    }
    slave.set_line_behavior(addr_map['shared'],    CacheState.SHARED)
    slave.set_line_behavior(addr_map['exclusive'], CacheState.EXCLUSIVE)
    slave.set_line_behavior(addr_map['modified'],  CacheState.MODIFIED)
    slave.set_line_behavior(addr_map['owned'],     CacheState.OWNED)
    slave.set_handler(_make_snoop_handler())

    handler = _make_snoop_handler()

    # --- Scenario 1: basic MESI matrix ------------------------------------
    tb.log.info("Scenario 1: basic MESI response matrix")
    cases = [
        (addr_map['invalid'],   CacheState.INVALID,   SnoopType.READ_SHARED),
        (addr_map['invalid'],   CacheState.INVALID,   SnoopType.READ_UNIQUE),
        (addr_map['shared'],    CacheState.SHARED,    SnoopType.READ_SHARED),
        (addr_map['shared'],    CacheState.SHARED,    SnoopType.READ_UNIQUE),
        (addr_map['exclusive'], CacheState.EXCLUSIVE, SnoopType.READ_SHARED),
        (addr_map['exclusive'], CacheState.EXCLUSIVE, SnoopType.READ_UNIQUE),
        (addr_map['modified'],  CacheState.MODIFIED,  SnoopType.READ_SHARED),
        (addr_map['modified'],  CacheState.MODIFIED,  SnoopType.READ_UNIQUE),
        (addr_map['modified'],  CacheState.MODIFIED,  SnoopType.CLEAN_INVALID),
        (addr_map['modified'],  CacheState.MODIFIED,  SnoopType.MAKE_INVALID),
    ]

    for addr, state, stype in cases:
        exp_crresp, exp_data = handler(addr, stype, state)
        result = await master.issue_snoop(addr, stype)
        _check_snoop_result(tb, addr, stype, result, exp_crresp, exp_data)

    # --- Scenario 2: multiple back-to-back snoops (in-order) --------------
    tb.log.info("Scenario 2: back-to-back in-order snoops")
    sequence = [
        (addr_map['modified'],  SnoopType.READ_SHARED),
        (addr_map['shared'],    SnoopType.READ_SHARED),
        (addr_map['exclusive'], SnoopType.READ_UNIQUE),
        (addr_map['modified'],  SnoopType.READ_UNIQUE),
        (addr_map['invalid'],   SnoopType.READ_ONCE),
    ]
    results = []
    for addr, stype in sequence:
        state = _state_for_addr(slave, addr)
        results.append(
            (addr, stype, state, await master.issue_snoop(addr, stype))
        )
    for addr, stype, state, result in results:
        exp_crresp, exp_data = handler(addr, stype, state)
        _check_snoop_result(tb, addr, stype, result, exp_crresp, exp_data)

    # --- Scenario 3: snoops under CR/CD backpressure ----------------------
    tb.log.info("Scenario 3: snoops under CR/CD backpressure")
    backpressure = FlexRandomizer({
        'ready_delay': ([(0, 0), (2, 5)], [1, 2])
    })
    master.cr_channel.set_randomizer(backpressure)
    master.cd_channel.set_randomizer(backpressure)

    bp_cases = [
        (addr_map['modified'], SnoopType.READ_SHARED),
        (addr_map['exclusive'], SnoopType.READ_SHARED),
        (addr_map['shared'], SnoopType.READ_SHARED),
        (addr_map['modified'], SnoopType.READ_UNIQUE),
    ]
    for addr, stype in bp_cases:
        state = _state_for_addr(slave, addr)
        exp_crresp, exp_data = handler(addr, stype, state)
        result = await master.issue_snoop(addr, stype)
        _check_snoop_result(tb, addr, stype, result, exp_crresp, exp_data)

    tb.log.info("ACE snoop transport test PASSED")


def _state_for_addr(slave: AXI4ACESnoopSlave, addr: int) -> CacheState:
    return slave.line_behaviors.get(addr, CacheState.INVALID)


def _check_snoop_result(tb, addr, stype, result, exp_crresp, exp_data):
    if result.crresp != exp_crresp:
        raise AssertionError(
            f"addr=0x{addr:08X} {stype.name}: CRRESP mismatch "
            f"got {result.crresp!r}, expected {exp_crresp!r}"
        )
    if exp_data is not None:
        if not result.crresp.data_transfer:
            raise AssertionError(
                f"addr=0x{addr:08X} {stype.name}: expected data transfer"
            )
        if len(result.data) != 1:
            raise AssertionError(
                f"addr=0x{addr:08X} {stype.name}: expected 1 data beat, "
                f"got {len(result.data)}"
            )
        if result.data[0] != exp_data:
            raise AssertionError(
                f"addr=0x{addr:08X} {stype.name}: data mismatch "
                f"got 0x{result.data[0]:08X}, expected 0x{exp_data:08X}"
            )
    else:
        if result.crresp.data_transfer:
            raise AssertionError(
                f"addr=0x{addr:08X} {stype.name}: unexpected data transfer"
            )
        if result.data:
            raise AssertionError(
                f"addr=0x{addr:08X} {stype.name}: unexpected data beats"
            )
    tb.log.info(
        f"OK addr=0x{addr:08X} {stype.name} -> {result.crresp} "
        f"data={result.data if result.data else '[]'}"
    )


# ---------------------------------------------------------------------------
# Cocotb test wrappers
# ---------------------------------------------------------------------------

@cocotb.test(timeout_time=5, timeout_unit="ms")
async def axi4ace_snoop_slave_transport_test(dut):
    """Cache-side snoop transport: master on m_axi_, responder on fub_."""
    await _run_snoop_transport(dut, master_prefix="m_axi_", slave_prefix="fub_")


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def axi4ace_snoop_master_transport_test(dut):
    """CCU-side snoop transport: master on fub_, responder on m_axi_."""
    await _run_snoop_transport(dut, master_prefix="fub_", slave_prefix="m_axi_")


# ---------------------------------------------------------------------------
# Stretch: AXI4ACE master read front-side test
# ---------------------------------------------------------------------------

async def _watch_rack(dut, rack_event: Event):
    await RisingEdge(dut.m_axi_rack)
    rack_event.set()


@cocotb.test(timeout_time=5, timeout_unit="ms")
async def axi4ace_master_rd_rack_test(dut):
    """AXI4ACEMasterRead -> axi4ace_master_rd -> AXI4SlaveRead; check RACK."""
    tb = AxeSnoopTB(dut)
    await tb.start_test()

    ace_master = AXI4ACEMasterRead(
        dut=dut,
        clock=dut.aclk,
        prefix="fub_axi_",
        log=tb.log,
        ifc_name="ace",
        data_width=32,
        addr_width=32,
        id_width=8,
    )
    axi_slave = AXI4SlaveRead(
        dut=dut,
        clock=dut.aclk,
        prefix="m_axi_",
        log=tb.log,
        ifc_name="axi",
        data_width=32,
        addr_width=32,
        id_width=8,
    )

    addr = 0x0000_4000
    rack_event = Event()
    cocotb.start_soon(_watch_rack(dut, rack_event))

    data = await ace_master.read_transaction(
        address=addr,
        burst_len=1,
        snoop_type=ACETransactionType.READ_SHARED,
        id=0xAB,
    )

    if data != [addr]:
        raise AssertionError(
            f"Read data mismatch: expected [0x{addr:08X}], got {data}"
        )

    try:
        await with_timeout(rack_event.wait(), 1, 'us')
    except Exception as exc:
        raise AssertionError(
            f"m_axi_rack did not pulse after RLAST: {exc}"
        ) from exc

    tb.log.info("axi4ace_master_rd RACK stretch test PASSED")


# ---------------------------------------------------------------------------
# Pytest harness
# ---------------------------------------------------------------------------

def _run_ace_test(request, dut_name: str, testcase: str):
    module, repo_root, tests_dir, log_dir, rtl_dict = get_paths({
        'rtl_cmn': 'rtl/common',
        'rtl_gaxi': 'rtl/amba/gaxi',
        'rtl_amba': 'rtl/amba',
        'rtl_amba_includes': 'rtl/amba/includes',
        'rtl_amba_filelists': 'rtl/amba/filelists',
        'rtl_ace': 'rtl/amba/ace',
    })

    filelist_path = os.path.join(
        rtl_dict['rtl_amba_filelists'], f"{dut_name}.f"
    )
    if os.path.exists(filelist_path):
        verilog_sources, filelist_includes = _sources_from_filelist(
            filelist_path, repo_root
        )
    else:
        verilog_sources = [
            os.path.join(rtl_dict['rtl_gaxi'], "gaxi_skid_buffer.sv"),
            os.path.join(rtl_dict['rtl_ace'], f"{dut_name}.sv"),
        ]
        filelist_includes = [rtl_dict['rtl_amba_includes']]

    worker_id = os.environ.get('PYTEST_XDIST_WORKER', 'gw0')
    test_name_plus_params = f"test_{worker_id}_{dut_name}"
    log_path = os.path.join(log_dir, f'{test_name_plus_params}.log')
    sim_build = os.path.join(tests_dir, 'local_sim_build', test_name_plus_params)
    enable_waves = bool(int(os.environ.get('WAVES', '0')))
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    results_path = os.path.join(log_dir, f'results_{test_name_plus_params}.xml')

    includes = list(dict.fromkeys(
        filelist_includes + [rtl_dict['rtl_amba_includes']]
    ))

    if dut_name == 'axi4ace_master_rd':
        rtl_parameters = {
            'AXI_ID_WIDTH': '8',
            'AXI_ADDR_WIDTH': '32',
            'AXI_DATA_WIDTH': '32',
            'AXI_USER_WIDTH': '1',
        }
    else:
        rtl_parameters = {
            'DATA_WIDTH': '32',
            'ADDR_WIDTH': '32',
        }

    extra_env = {
        'TRACE_FILE': f"{sim_build}/dump.fst",
        'VERILATOR_TRACE': '1',
        'DUT': dut_name,
        'LOG_PATH': log_path,
        'COCOTB_LOG_LEVEL': 'INFO',
        'COCOTB_RESULTS_FILE': results_path,
        'SEED': str(random.randint(0, 100000)),
        'COCOTB_TEST_TIMEOUT': '5000',
        'TEST_DUT': dut_name,
    }

    extra_args = [
        '--trace-fst',
        '--trace-structs',
        '-Wno-TIMESCALEMOD',
    ]
    sim_args = ['--trace'] if enable_waves else []
    if enable_waves:
        extra_env['COCOTB_TRACE_FILE'] = os.path.join(sim_build, 'dump.fst')

    cmd_filename = create_view_cmd(log_dir, log_path, sim_build, module, test_name_plus_params)

    print(f"\n{'='*80}")
    print(f"Running BFM acceptance test: {dut_name}")
    print(f"Testcase: {testcase}")
    print(f"Log: {log_path}")
    print(f"{'='*80}")

    try:
        run(
            python_search=[tests_dir],
            verilog_sources=verilog_sources,
            includes=includes,
            toplevel=dut_name,
            module=module,
            parameters=rtl_parameters,
            sim_build=sim_build,
            extra_env=extra_env,
            extra_args=extra_args,
            plus_args=sim_args,
            waves=enable_waves,
            keep_files=True,
            testcase=testcase,
            simulator="verilator",
        )
        print(f"PASSED: {dut_name} ({testcase})")
    except Exception as e:
        print(f"FAILED: {dut_name} ({testcase}): {e}")
        print(f"Logs: {log_path}")
        print(f"Waveform script: {cmd_filename}")
        raise


@pytest.mark.parametrize("dut_name,testcase", [
    ("axi4ace_snoop_slave",  "axi4ace_snoop_slave_transport_test"),
    ("axi4ace_snoop_master", "axi4ace_snoop_master_transport_test"),
])
def test_axi4ace_snoop_transport(request, dut_name, testcase):
    """Parameterized BFM acceptance test for both ACE snoop transports."""
    _run_ace_test(request, dut_name, testcase)


def test_axi4ace_master_rd_rack(request):
    """Stretch: verify RACK auto-pulse on axi4ace_master_rd."""
    _run_ace_test(request, "axi4ace_master_rd", "axi4ace_master_rd_rack_test")


if __name__ == "__main__":
    test_axi4ace_snoop_transport(None, "axi4ace_snoop_slave",
                                  "axi4ace_snoop_slave_transport_test")
