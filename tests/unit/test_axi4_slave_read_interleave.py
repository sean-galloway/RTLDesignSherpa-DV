"""AXI4SlaveRead(interleave_r=True) sends R beats of different IDs
interleaved, one beat at a time round-robin across the waiting bursts,
while beats of one ID stay in order, burst after burst. Drives
_generate_read_response and the feeder's fill step on a bare instance (no
simulator): the feeder task is pre-set so none is started."""
from __future__ import annotations

from types import SimpleNamespace

from CocoTBFramework.components.axi4.axi4_interfaces import AXI4SlaveRead


def _slave(interleave=True):
    s = AXI4SlaveRead.__new__(AXI4SlaveRead)
    s.log = None
    s.response_delay_cycles = 0
    s.memory_model = None              # data = beat address
    s.base_addr = 0
    s.data_width = 32
    s.resp_override = None
    s.enable_ooo = False
    s.interleave_r = interleave
    s._ilv_pending = []
    s._ilv_task = object()             # truthy: no feeder task is started
    s._ilv_rr = 0
    s.r_channel = SimpleNamespace(
        create_packet=lambda **kw: SimpleNamespace(**kw),
        transmit_queue=[],
        transmit_coroutine=object(),
    )
    return s


def _run(coro):
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("response generation awaited a simulator trigger")


def _ar(s, addr, length, rid):
    _run(s._generate_read_response(SimpleNamespace(addr=addr, len=length, id=rid, size=2)))


def _drain(s):
    out = []
    while s._ilv_pending or s.r_channel.transmit_queue:
        s._interleave_fill(depth=1)
        out.extend(s.r_channel.transmit_queue)
        s.r_channel.transmit_queue.clear()
    return out


def test_beats_of_different_ids_interleave():
    s = _slave()
    _ar(s, 0x100, 3, rid=1)
    _ar(s, 0x200, 3, rid=2)
    beats = _drain(s)
    assert [b.id for b in beats] == [1, 2, 1, 2, 1, 2, 1, 2]
    for rid, base in ((1, 0x100), (2, 0x200)):
        mine = [b for b in beats if b.id == rid]
        assert [b.data for b in mine] == [base + 4 * i for i in range(4)]
        assert [b.last for b in mine] == [0, 0, 0, 1]


def test_same_id_bursts_stay_in_order():
    s = _slave()
    _ar(s, 0x100, 1, rid=1)
    _ar(s, 0x200, 1, rid=1)            # a second burst of ID 1 waits behind the first
    _ar(s, 0x300, 3, rid=2)
    beats = _drain(s)
    one = [b.data for b in beats if b.id == 1]
    assert one == [0x100, 0x104, 0x200, 0x204], "ID 1's bursts crossed"
    assert [b.id for b in beats][:4] == [1, 2, 1, 2]


def test_default_is_contiguous():
    s = _slave(interleave=False)
    _ar(s, 0x100, 1, rid=1)
    _ar(s, 0x200, 1, rid=2)
    assert [b.id for b in s.r_channel.transmit_queue] == [1, 1, 2, 2]
