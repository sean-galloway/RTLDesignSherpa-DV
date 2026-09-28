"""AXI4SlaveRead places a narrow read's bytes in the lanes its address selects,
the way the write path already positions narrow W data. Drives
_generate_read_response directly on a bare instance: with response_delay 0 the
coroutine never awaits a simulator trigger, so it runs to completion here."""
from __future__ import annotations

from types import SimpleNamespace

from CocoTBFramework.components.axi4.axi4_interfaces import AXI4SlaveRead
from CocoTBFramework.components.shared.memory_model import MemoryModel, oor_read_data


def _slave(data_width=64, num_lines=8):
    mem = MemoryModel(num_lines=num_lines, bytes_per_line=data_width // 8)
    s = AXI4SlaveRead.__new__(AXI4SlaveRead)
    s.log = None
    s.response_delay_cycles = 0
    s.memory_model = mem
    s.base_addr = 0
    s.data_width = data_width
    s.resp_override = None
    s.enable_ooo = False
    s.r_channel = SimpleNamespace(
        create_packet=lambda **kw: SimpleNamespace(**kw),
        transmit_queue=[],
        transmit_coroutine=object(),      # truthy: no pipeline start
    )
    return s, mem


def _run(coro):
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("response generation awaited a simulator trigger")


def _read(s, addr, size, length=0):
    _run(s._generate_read_response(SimpleNamespace(addr=addr, len=length, id=0, size=size)))
    beats = list(s.r_channel.transmit_queue)
    s.r_channel.transmit_queue.clear()
    return beats


def _preload(mem):
    for i, word in enumerate((0x11111111, 0x22222222, 0x33333333, 0x44444444)):
        mem.write(4 * i, bytearray(word.to_bytes(4, "little")))


def test_narrow_read_rides_the_addressed_lane():
    s, mem = _slave(64)
    _preload(mem)
    (beat,) = _read(s, addr=4, size=2)
    assert beat.data == 0x22222222 << 32
    assert beat.resp == 0 and beat.last == 1


def test_narrow_read_on_lane_zero_is_unshifted():
    s, mem = _slave(64)
    _preload(mem)
    (beat,) = _read(s, addr=8, size=2)
    assert beat.data == 0x33333333


def test_incr_burst_walks_the_lanes():
    s, mem = _slave(64)
    _preload(mem)
    beats = _read(s, addr=0, size=2, length=3)
    assert [b.data for b in beats] == [0x11111111, 0x22222222 << 32, 0x33333333, 0x44444444 << 32]
    assert [b.last for b in beats] == [0, 0, 0, 1]


def test_full_width_read_is_unchanged():
    s, mem = _slave(64)
    _preload(mem)
    (beat,) = _read(s, addr=0, size=3)
    assert beat.data == (0x22222222 << 32) | 0x11111111


def test_out_of_range_narrow_read_keeps_slverr_and_positions_the_pattern():
    s, mem = _slave(64, num_lines=2)          # 16 bytes
    (beat,) = _read(s, addr=0x14, size=2)     # lane 1, past the end
    assert beat.resp == 2
    assert beat.data == oor_read_data(4) << 32
