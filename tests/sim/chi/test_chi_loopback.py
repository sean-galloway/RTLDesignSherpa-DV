# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# Module: test_chi_loopback
# Purpose: CHI RN-F BFM <-> chi_wires <-> HN-F BFM, with a monitor on each
#          side, exercising the flows the family models
#
# Subsystem: tests/sim
# Author: sean galloway
# Created: 2026-10-30
"""End-to-end CHI BFM-to-BFM simulation.

The DUT is wires, so every rule being checked is the BFMs' own: link
activation, L-Credits, FLITPEND, the transaction flows, snoops, retry,
data integrity against the home's memory. Each phase records counts; the
verdict fails on a zero count as well as on a violation, so a phase that
silently did nothing cannot pass.

TEST_LEVEL basic | medium | full scales the random phase. REG_LEVEL GATE |
FUNC | FULL picks the parameter grid (data width, home options).
"""

from __future__ import annotations

import os
import random
from itertools import product

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb_test.simulator import run

from CocoTBFramework.components.chi import (
    SC,
    UC,
    UD,
    CHIConfig,
    HomeOptions,
    ReqOpcode,
    Size,
    SnpOpcode,
    create_chi_home,
    create_chi_monitor,
    create_chi_requester,
)

RANDOM_OPS = {'basic': 40, 'medium': 150, 'full': 500}


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


def _env_int(name, default):
    return int(os.environ.get(name, default))


class Checker:
    """Reference memory + counts; the verdict needs every count > 0."""

    def __init__(self):
        self.ref = {}
        self.counts = {}
        self.errors = []

    def bump(self, k, n=1):
        self.counts[k] = self.counts.get(k, 0) + n

    def note_write(self, addr, data, be=None):
        for i, b in enumerate(data):
            if be is None or (be >> i) & 1:
                self.ref[addr + i] = b

    def check_read(self, addr, data, what):
        exp = bytes(self.ref.get(addr + i, 0) for i in range(len(data)))
        if data != exp:
            self.errors.append(f"{what} at {addr:#x}: got {data.hex()} exp {exp.hex()}")
        self.bump('reads_checked')

    def verdict(self, mons, nodes):
        viol = {}
        for m in mons + nodes:
            for k, v in m.all_violations().items():
                viol[f"{m.title}.{k}"] = v
        for m in mons:
            left = m.unfinished()
            if left:
                viol[f"{m.title}.unfinished"] = len(left)
                self.errors += left[:5]
        zero = [k for k, v in self.counts.items() if v == 0]
        ok = not self.errors and not viol and not zero
        return ok, viol, zero


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def chi_loopback_test(dut):
    level = os.environ.get('TEST_LEVEL', 'basic').lower()
    seed = _env_int('SEED', 1)
    rng = random.Random(seed)
    dw = _env_int('TEST_DATA_WIDTH', 128)
    opts = HomeOptions(read_separate=float(os.environ.get('TEST_READ_SEP', '0')),
                       write_separate=float(os.environ.get('TEST_WRITE_SEP', '0')),
                       copyback_comp=float(os.environ.get('TEST_COPYBACK_COMP', '0')),
                       retry_rate=float(os.environ.get('TEST_RETRY_RATE', '0')),
                       comp_delay=(0, 4))
    await _bring_up(dut)
    rn_cfg = CHIConfig(node_type='RN-F', data_width=dw)
    hn_cfg = CHIConfig(node_type='HN-F', data_width=dw)
    rn = create_chi_requester(dut, "RN", "rn_", dut.clk, rn_cfg, node_id=1, home_id=0, reset=dut.rst_n,
                              seed=seed)
    hn = create_chi_home(dut, "HN", "hn_", dut.clk, hn_cfg, rn_id=1, options=opts, node_id=0,
                         reset=dut.rst_n, seed=seed)
    mon_rn = create_chi_monitor(dut, "MonRN", "rn_", dut.clk, rn_cfg, reset=dut.rst_n)
    mon_hn = create_chi_monitor(dut, "MonHN", "hn_", dut.clk, hn_cfg, reset=dut.rst_n)
    chk = Checker()
    log = dut._log
    log.info(f"CHI loopback level={level} seed={seed} DW={dw} opts={opts}")

    # ---- phase 1: non-coherent writes and reads (WriteNoSnpFull / ReadNoSnp) ----
    for i in range(8):
        addr = 0x1000 + i * 64
        data = bytes(rng.getrandbits(8) for _ in range(64))
        t = await rn.write(addr, data, opcode=ReqOpcode.WriteNoSnpFull)
        assert t.status == 'done', t
        chk.note_write(addr, data)
        chk.bump('writenosnp')
    for i in range(8):
        addr = 0x1000 + i * 64
        t = await rn.read(addr, opcode=ReqOpcode.ReadNoSnp)
        chk.check_read(addr, t.read_data(), 'ReadNoSnp')
        chk.bump('readnosnp')
    # partial write: 16 bytes at an unaligned-to-line offset
    for i in range(4):
        addr = 0x2000 + i * 64 + 16 * (i % 4)
        data = bytes(rng.getrandbits(8) for _ in range(16))
        await rn.write(addr, data, opcode=ReqOpcode.WriteNoSnpPtl)
        chk.note_write(addr, data)
        t = await rn.read(addr, opcode=ReqOpcode.ReadNoSnp, size=Size.B16)
        chk.check_read(addr, t.read_data(), 'ReadNoSnp 16B')
        chk.bump('writenosnpptl')

    # ---- phase 2: coherent reads and the cache model ----
    for i in range(4):
        addr = 0x1000 + i * 64
        t = await rn.read(addr, opcode=ReqOpcode.ReadShared)
        chk.check_read(addr, t.read_data(), 'ReadShared')
        assert rn.cache.state(addr) in (UC, SC), rn.cache.state(addr)
        assert t.compack_sent, "ReadShared must end with CompAck (B2.7.3)"
        chk.bump('readshared')
    for i in range(4, 8):
        addr = 0x1000 + i * 64
        t = await rn.read(addr, opcode=ReqOpcode.ReadUnique)
        chk.check_read(addr, t.read_data(), 'ReadUnique')
        assert rn.cache.state(addr) in (UC, UD)
        chk.bump('readunique')
    # dirty the line locally, write it back, read it back non-coherently
    for i in range(4, 8):
        addr = 0x1000 + i * 64
        new = bytes(rng.getrandbits(8) for _ in range(64))
        rn.cache.set_state(addr, UD, data=new)
        t = await rn.writeback(addr, opcode=ReqOpcode.WriteBackFull)
        chk.note_write(addr, new)
        chk.bump('writeback')
        t = await rn.read(addr, opcode=ReqOpcode.ReadNoSnp)
        chk.check_read(addr, t.read_data(), 'after WriteBackFull')
    # dataless
    for i in range(4):
        addr = 0x1000 + i * 64
        t = await rn.dataless(ReqOpcode.CleanUnique, addr)
        assert t.compack_sent
        chk.bump('cleanunique')
        t = await rn.dataless(ReqOpcode.Evict, addr)
        chk.bump('evict')

    # ---- phase 3: snoops from the home into this RN ----
    addr = 0x1000
    t = await rn.read(addr, opcode=ReqOpcode.ReadUnique)
    rn.cache.set_state(addr, UD, data=bytes(rng.getrandbits(8) for _ in range(64)))
    dirty = bytes(rn.cache.line(addr).data)
    s = await hn.home.snoop(1, SnpOpcode.SnpCleanInvalid, addr)
    assert s.resp_state == 'I_PD' and bytes(s.data) == dirty, (s.resp_state, s.data)
    chk.note_write(addr, dirty)
    t = await rn.read(addr, opcode=ReqOpcode.ReadNoSnp)
    chk.check_read(addr, t.read_data(), 'after SnpCleanInvalid writeback')
    chk.bump('snoop_data')
    t = await rn.read(addr, opcode=ReqOpcode.ReadShared)
    s = await hn.home.snoop(1, SnpOpcode.SnpShared, addr)
    assert s.resp_state == 'SC' and s.data is None, s.resp_state
    chk.bump('snoop_nodata')

    # ---- phase 4: random mix, several outstanding ----
    # Several outstanding, but never two to one line: with Order = 0 and a
    # RetryAck in play, two requests to the same address may complete in
    # either order (B2.7), so a line with an operation in flight is not a
    # legal target for a reference model that assumes issue order.
    ops = RANDOM_OPS[level]
    lines = [0x4000 + i * 64 for i in range(16)]
    inflight = []
    for n in range(ops):
        busy = {t.addr for t, _ in inflight}
        addr = rng.choice([a for a in lines if a not in busy])
        kind = rng.random()
        if kind < 0.35:
            data = bytes(rng.getrandbits(8) for _ in range(64))
            inflight.append((rn.issue(rn.new_txn(ReqOpcode.WriteNoSnpFull, addr, Size.B64, data=data)), data))
        elif kind < 0.7:
            inflight.append((rn.issue(rn.new_txn(ReqOpcode.ReadNoSnp, addr, Size.B64)), None))
        else:
            inflight.append((rn.issue(rn.new_txn(ReqOpcode.ReadOnce, addr, Size.B64)), None))
        if len(inflight) >= rng.randint(1, 6):
            for t, data in inflight:
                await rn.wait(t)
                if data is not None:
                    chk.note_write(t.addr, data)
                    chk.bump('random_writes')
                else:
                    chk.bump('random_reads')
            inflight = []
    for t, data in inflight:
        await rn.wait(t)
        if data is not None:
            chk.note_write(t.addr, data)
    for addr in lines:
        t = await rn.read(addr, opcode=ReqOpcode.ReadNoSnp)
        chk.check_read(addr, t.read_data(), 'final sweep')
    if opts.retry_rate:
        chk.bump('retries', rn.stats['retries'])

    # ---- drain and verdict ----
    await rn.wait_tx_idle()
    await hn.wait_tx_idle()
    for _ in range(50):
        await RisingEdge(dut.clk)
    chk.bump('peak_credits_req', mon_hn.max_credits.get('rxreq', 0))
    chk.bump('peak_credits_dat', mon_rn.max_credits.get('rxdat', 0))
    ok, viol, zero = chk.verdict([mon_rn, mon_hn], [rn, hn])
    log.info(rn.summary())
    log.info(hn.summary())
    log.info(mon_rn.summary())
    log.info(mon_hn.summary())
    log.info(f"VERDICT counts={chk.counts} violations={viol} zero={zero} errors={len(chk.errors)}")
    for e in chk.errors[:10]:
        log.error(e)
    assert ok, f"violations={viol} zero_counts={zero} data_errors={chk.errors[:5]}"


# ---------------------------------------------------------------------
# Pytest runner
# ---------------------------------------------------------------------
def generate_params():
    """(data_width, read_sep, write_sep, copyback_comp, retry_rate, level)"""
    reg = os.environ.get('REG_LEVEL', 'FUNC').upper()
    if reg == 'GATE':
        return [(128, 0.0, 0.0, 0.0, 0.0, 'basic')]
    if reg == 'FUNC':
        return [(128, 0.0, 0.0, 0.0, 0.0, 'medium'), (256, 0.5, 0.5, 0.5, 0.2, 'medium'),
                (512, 1.0, 1.0, 1.0, 0.0, 'basic')]
    return list(product((128, 256, 512), (0.0, 0.5), (0.0, 0.5), (0.0, 1.0), (0.0, 0.3), ('medium', 'full')))


@pytest.mark.parametrize("data_width,read_sep,write_sep,copyback_comp,retry_rate,level", generate_params())
def test_chi_loopback(request, data_width, read_sep, write_sep, copyback_comp, retry_rate, level):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    name = f"test_chi_loopback_dw{data_width}_r{read_sep}_w{write_sep}_c{copyback_comp}_t{retry_rate}_{level}"
    sim_build = os.path.join(repo_root, "tests", "sim", "local_sim_build", name)
    log_dir = os.path.join(repo_root, "tests", "sim", "logs")
    os.makedirs(sim_build, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    cfg = CHIConfig(data_width=data_width)
    run(
        python_search=[os.path.dirname(__file__)],
        verilog_sources=[os.path.join(repo_root, "tests", "sim", "rtl", "chi", "chi_wires.sv")],
        toplevel="chi_wires",
        module="test_chi_loopback",
        parameters={'REQ_W': cfg.req_flit_width, 'RSP_W': cfg.rsp_flit_width,
                    'SNP_W': cfg.snp_flit_width, 'DAT_W': cfg.dat_flit_width},
        sim_build=sim_build,
        extra_env={
            'COCOTB_LOG_LEVEL': 'INFO',
            'COCOTB_RESULTS_FILE': os.path.join(log_dir, f"results_{name}.xml"),
            'TEST_LEVEL': level, 'TEST_DATA_WIDTH': str(data_width),
            'TEST_READ_SEP': str(read_sep), 'TEST_WRITE_SEP': str(write_sep),
            'TEST_COPYBACK_COMP': str(copyback_comp), 'TEST_RETRY_RATE': str(retry_rate),
            'SEED': os.environ.get('SEED', str(random.randint(1, 1_000_000))),
        },
        extra_args=["-Wno-TIMESCALEMOD", "-Wno-DECLFILENAME"],
        timescale="1ns/1ps",
        waves=bool(int(os.environ.get("WAVES", "0"))),
    )
