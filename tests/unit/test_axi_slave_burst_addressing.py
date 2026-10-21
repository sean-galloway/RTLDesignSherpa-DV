"""The AXI3/AXI4/AXI5 memory slaves address each beat by the burst rules of
AXI A3.4.1, not by start + i * bytes: FIXED holds the address, INCR steps from
the ALIGNED start (only the first beat may be unaligned), WRAP wraps inside its
(len+1) * bytes container. Drives _generate_read_response and
_complete_write_transaction on bare instances, as test_axi4_slave_read_lanes
does: with no delays neither coroutine awaits a simulator trigger."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from CocoTBFramework.components.axi3.axi3_interfaces import AXI3SlaveRead, AXI3SlaveWrite
from CocoTBFramework.components.axi4.axi4_interfaces import AXI4SlaveRead, AXI4SlaveWrite
from CocoTBFramework.components.axi5.axi5_interfaces import AXI5SlaveRead, AXI5SlaveWrite
from CocoTBFramework.components.shared.axi_burst import beat_addr
from CocoTBFramework.components.shared.memory_model import MemoryModel

FIXED, INCR, WRAP = 0, 1, 2
BUS = 64                       # bits
LINES = 16                     # 128 bytes of memory


def _run(coro):
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("the BFM awaited a simulator trigger")


def _pattern(mem):
    for off in range(LINES * BUS // 8):
        mem.write(off, bytearray([(0x40 + off) & 0xFF]))


def _bare(cls, mem):
    s = cls.__new__(cls)
    s.log = None
    s.response_delay_cycles = 0
    s.memory_model = mem
    s.base_addr = 0
    s.data_width = BUS
    s.resp_override = None
    s.enable_ooo = False
    return s


def _read(cls, addr, size, burst, length):
    mem = MemoryModel(num_lines=LINES, bytes_per_line=BUS // 8)
    _pattern(mem)
    s = _bare(cls, mem)
    s.r_channel = SimpleNamespace(create_packet=lambda **kw: SimpleNamespace(**kw),
                                  transmit_queue=[], transmit_coroutine=object())
    s.interleave_r = False
    _run(s._generate_read_response(SimpleNamespace(addr=addr, len=length, id=0, size=size,
                                                   burst=burst)))
    return list(s.r_channel.transmit_queue)


def _lanes(data, a, size):
    """The bytes beat address a carries -- a up to the end of its aligned
    window (an unaligned beat carries none below a) -- from a bus word."""
    nb = 1 << size
    end = (a & ~(nb - 1)) + nb
    bus = BUS // 8
    return [(data >> (8 * (off % bus))) & 0xFF for off in range(a, end)]


# ---- the rule itself ---------------------------------------------------------

def test_beat_addr_rules():
    assert [beat_addr(0x13, i, 2, FIXED, 3) for i in range(4)] == [0x13] * 4
    assert [beat_addr(0x13, i, 2, INCR, 3) for i in range(4)] == [0x13, 0x14, 0x18, 0x1C]
    assert [beat_addr(0x18, i, 2, WRAP, 3) for i in range(4)] == [0x18, 0x1C, 0x10, 0x14]
    assert [beat_addr(0x30, i, 3, WRAP, 1) for i in range(2)] == [0x30, 0x38]
    assert [beat_addr(0x38, i, 3, WRAP, 1) for i in range(2)] == [0x38, 0x30]


# ---- reads -------------------------------------------------------------------

CASES = [
    # (addr, size, burst, len)
    (0x13, 2, INCR, 3),         # unaligned start: beats 1.. on the 4-byte grid
    (0x21, 3, INCR, 2),         # full-width unaligned
    (0x24, 2, FIXED, 3),        # FIXED narrow: same 4 bytes every beat
    (0x28, 3, FIXED, 1),
    (0x18, 2, WRAP, 3),         # WRAP 4 x 4 bytes around 0x10
    (0x38, 3, WRAP, 1),         # WRAP 2 x 8 bytes around 0x30
    (0x0C, 2, WRAP, 7),         # WRAP 8 x 4 bytes around 0x00
]


@pytest.mark.parametrize("cls", [AXI3SlaveRead, AXI4SlaveRead, AXI5SlaveRead])
@pytest.mark.parametrize("addr,size,burst,length", CASES)
def test_read_beats_follow_the_burst_rules(cls, addr, size, burst, length):
    beats = _read(cls, addr, size, burst, length)
    assert len(beats) == length + 1
    for i, b in enumerate(beats):
        a = beat_addr(addr, i, size, burst, length)
        end = (a & ~((1 << size) - 1)) + (1 << size)
        want = [(0x40 + off) & 0xFF for off in range(a, end)]
        assert _lanes(b.data, a, size) == want, f"beat {i} at 0x{a:X}"
    assert [b.last for b in beats] == [0] * length + [1]


# ---- writes ------------------------------------------------------------------

def _write(cls, addr, size, burst, length):
    mem = MemoryModel(num_lines=LINES, bytes_per_line=BUS // 8)
    s = _bare(cls, mem)
    s.pending_transactions = {}
    s.ooo_transaction_metadata = {}
    s.ooo_last_completed_seq = -1

    class _NoLock:                          # cocotb's Lock needs a simulator
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False
    s.completion_locks = {0: _NoLock()}
    sent = []

    async def _send(pkt):
        sent.append(pkt)
    s.b_channel = SimpleNamespace(create_packet=lambda **kw: SimpleNamespace(**kw), send=_send)
    nbus = BUS // 8
    w = []
    for i in range(length + 1):
        a = beat_addr(addr, i, size, burst, length)
        al = a & ~((1 << size) - 1)
        lane0, lane1 = a % nbus, (al % nbus) + (1 << size)
        strb = sum(1 << k for k in range(lane0, lane1))
        data = sum(((0x80 + i) & 0xFF) << (8 * k) for k in range(nbus))
        w.append(SimpleNamespace(data=data, strb=strb, last=int(i == length)))
    txn = {'aw_packet': SimpleNamespace(addr=addr, size=size, burst=burst, len=length, id=0),
           'w_packets': w, 'complete': True}
    s.pending_transactions[0] = [txn]
    _run(s._complete_write_transaction(0))
    assert sent and sent[0].resp == 0
    return mem


@pytest.mark.parametrize("cls", [AXI3SlaveWrite, AXI4SlaveWrite, AXI5SlaveWrite])
@pytest.mark.parametrize("addr,size,burst,length", CASES)
def test_write_beats_follow_the_burst_rules(cls, addr, size, burst, length):
    mem = _write(cls, addr, size, burst, length)
    # Expected memory: replay the beats in order by the burst rules; a later
    # beat to the same bytes (FIXED) overwrites an earlier one.
    want = {}
    for i in range(length + 1):
        a = beat_addr(addr, i, size, burst, length)
        al = a & ~((1 << size) - 1)
        for off in range(a, al + (1 << size)):
            want[off] = (0x80 + i) & 0xFF
    for off, v in want.items():
        assert mem.read(off, 1)[0] == v, f"byte 0x{off:X}"
    untouched = set(range(LINES * BUS // 8)) - set(want)
    assert all(mem.read(off, 1)[0] == 0 for off in untouched)


# ---- master W strobes ----------------------------------------------------------

from CocoTBFramework.components.shared.axi_burst import beat_lanes  # noqa: E402


def test_beat_lanes():
    bus = 8
    # full width, unaligned start: no strobes below the start address
    assert beat_lanes(0x13, 0, 3, INCR, 1, bus) == (0b11111000, 0)
    assert beat_lanes(0x13, 1, 3, INCR, 1, bus) == (0xFF, 0)
    # narrow INCR from an unaligned start: beat 1 on the grid
    assert beat_lanes(0x13, 0, 2, INCR, 3, bus) == (0b00001000, 0)
    assert beat_lanes(0x13, 1, 2, INCR, 3, bus) == (0b11110000, 4)
    # narrow FIXED holds its lanes; narrow WRAP wraps them
    assert [beat_lanes(0x24, i, 2, FIXED, 3, bus) for i in range(3)] == [(0xF0, 4)] * 3
    assert [beat_lanes(0x18, i, 2, WRAP, 3, bus)[1] for i in range(4)] == [0, 4, 0, 4]
