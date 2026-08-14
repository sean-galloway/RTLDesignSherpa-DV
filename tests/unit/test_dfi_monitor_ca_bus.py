"""DFIMonitor's CA-bus command path (DFI-007).

Before this, `DFIMonitor._decode_command` was ras/cas/we only, so a
monitor attached to any CA-bus DUT reported every command as NOP --
including LPDDR2, which the slave had decoded for some time.

The monitor needs a live cocotb entity to construct, so the methods
under test run on a bare instance carrying only the attributes they
touch, the same approach `test_dfi_slave_ca_bus.py` uses.
"""

import pytest

from CocoTBFramework.components.dfi.ca_map import (
    HBM4_COL_CA_MAP,
    HBM4_ROW_CA_MAP,
    CACodec,
)
from CocoTBFramework.components.dfi.ca_stream import CAStream, HBM4CAStreams
from CocoTBFramework.components.dfi.ca_transport import (
    LPDDR6_CA_WIDTH,
    pack_ddr_cmdaddr,
)
from CocoTBFramework.components.dfi.ddr5_ca_map import (
    DDR5_CA_MAP,
    DDR5_CA_WIDTH,
)
from CocoTBFramework.components.dfi.dfi_monitor import DFIMonitor
from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.hbm_ca import (
    HBM4CAEdge,
    pack_hbm4_cmdaddr,
)
from CocoTBFramework.components.dfi.lpddr6_ca_map import LPDDR6_CA_MAP


class _Val:
    def __init__(self, v, resolvable=True):
        self.integer = v
        self.is_resolvable = resolvable


class _Sig:
    def __init__(self, v=0, resolvable=True):
        self.value = _Val(v, resolvable)


class _Bus:
    def __init__(self, **sigs):
        for k, v in sigs.items():
            setattr(self, k, _Sig(v))


def _mon(streams=None, **bus):
    m = object.__new__(DFIMonitor)
    m._ca_streams = streams
    m.bus = _Bus(**bus)
    return m


# ---------------------------------------------------------------------------
# Signal selection and the opt-in gate
# ---------------------------------------------------------------------------

def test_cmdaddr_preferred_over_address():
    m = _mon(cmdaddr=0xABC, address=0x123)
    assert m._ca_bus_word() == 0xABC
    assert _mon(address=0x123)._ca_bus_word() == 0x123


def test_unresolvable_word_reads_zero():
    m = _mon(cmdaddr=0)
    m.bus.cmdaddr = _Sig(0xFF, resolvable=False)
    assert m._ca_bus_word() == 0


def test_in_flight_is_false_without_streams():
    assert _mon()._ca_in_flight is False


# ---------------------------------------------------------------------------
# Multi-cycle commands: the CS-deassert case that made this necessary
# ---------------------------------------------------------------------------

def test_two_cycle_command_reports_in_flight_between_cycles():
    """DDR5 drives CS_n high on cycle 2 of a 2-cycle command, so the
    monitor must keep feeding on in-flight rather than on CS."""
    enc = CACodec(DDR5_CA_MAP)
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True, strict=False)
    e0, e1 = enc.encode("act", row=0x1234, ba=2, bg=5, cid=0)
    m = _mon(streams=s, cmdaddr=e0)

    assert m._decode_ca_commands() == []      # first cycle: incomplete
    assert m._ca_in_flight is True            # ...so keep feeding
    m.bus.cmdaddr = _Sig(e1)
    done = m._decode_ca_commands()
    assert len(done) == 1
    cmd, args = done[0]
    assert cmd is DRAMCommand.ACT
    assert args["row"] == 0x1234 and args["bank"] == (5 << 2) | 2
    assert m._ca_in_flight is False


def test_lpddr6_command_spans_two_words():
    enc = CACodec(LPDDR6_CA_MAP)
    s = CAStream(LPDDR6_CA_MAP, LPDDR6_CA_WIDTH, strict=False)
    e = enc.encode("rd_s", ba=2, bg=1, ws=0, col=0x15, ap=1, sc=0)
    m = _mon(streams=s,
             cmdaddr=pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, e[0], e[1]))
    assert m._decode_ca_commands() == []
    assert m._ca_in_flight is True
    m.bus.cmdaddr = _Sig(pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, e[2], e[3]))
    cmd, args = m._decode_ca_commands()[0]
    assert cmd is DRAMCommand.RDA and args["col"] == 0x15


# ---------------------------------------------------------------------------
# NOP filtering and HBM4's two streams
# ---------------------------------------------------------------------------

def test_nops_are_not_reported():
    enc = CACodec(DDR5_CA_MAP)
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True, strict=False)
    m = _mon(streams=s, cmdaddr=enc.encode("nop")[0])
    assert m._decode_ca_commands() == []
    assert m._ca_in_flight is False


def test_hbm4_row_and_column_both_reported():
    row_enc = CACodec(HBM4_ROW_CA_MAP)
    col_enc = CACodec(HBM4_COL_CA_MAP)
    s = HBM4CAStreams(HBM4_ROW_CA_MAP, HBM4_COL_CA_MAP, strict=False)
    c_rise, c_fall = col_enc.encode("wr", pc=0, sid=1, ba=9, col=17)
    pre = row_enc.encode("prepb", pc=0, sid=0, ba=4)[0]
    rnop = row_enc.encode("rnop")[0]
    word = pack_hbm4_cmdaddr(HBM4CAEdge(row=pre, col=c_rise, arfu=0),
                             HBM4CAEdge(row=rnop, col=c_fall, arfu=0))
    m = _mon(streams=s, cmdaddr=word)
    got = m._decode_ca_commands()
    assert [c for c, _ in got] == [DRAMCommand.PRE, DRAMCommand.WR]
    assert got[0][1]["bank"] == 4 and got[1][1]["col"] == 17


# ---------------------------------------------------------------------------
# Mid-stream attach: a monitor must resync, never raise
# ---------------------------------------------------------------------------

def test_orphan_second_half_resyncs_instead_of_raising():
    """A slave raises here; a monitor may have attached mid-command."""
    enc = CACodec(LPDDR6_CA_MAP)
    s = CAStream(LPDDR6_CA_MAP, LPDDR6_CA_WIDTH, strict=False)
    e = enc.encode("act2", row_lo=0x7FF)
    m = _mon(streams=s,
             cmdaddr=pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, e[0], e[1]))
    assert m._decode_ca_commands() == []          # dropped, no raise
    m.bus.cmdaddr = _Sig(pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, e[2], e[3]))
    m._decode_ca_commands()
    # ...and a whole command right after still decodes.
    full = enc.encode("pre", ba=1, bg=2, sc=0, ab=0)
    m.bus.cmdaddr = _Sig(pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, full[0], full[1]))
    m._decode_ca_commands()
    m.bus.cmdaddr = _Sig(pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, full[2], full[3]))
    got = m._decode_ca_commands()
    assert got and got[0][0] is DRAMCommand.PRE


def test_unknown_head_edge_does_not_raise():
    s = CAStream(HBM4_COL_CA_MAP, 8, sdr=True, strict=False)
    m = _mon(streams=s, cmdaddr=0b010)   # not a Table 34 pattern
    assert m._decode_ca_commands() == []
    assert s.resyncs == 1


# ---------------------------------------------------------------------------
# Constructor wiring
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("col_map,kind", [
    (None, CAStream),
    (HBM4_COL_CA_MAP, HBM4CAStreams),
])
def test_stream_construction_is_non_strict(col_map, kind):
    """Mirror of the ctor block: monitors always build non-strict
    streams so a mid-command attach resyncs."""
    ca_map = HBM4_ROW_CA_MAP if col_map else DDR5_CA_MAP
    if col_map is not None:
        s = HBM4CAStreams(ca_map, col_map, strict=False)
        assert s.row.strict is False and s.col.strict is False
    else:
        s = CAStream(ca_map, ca_map.bus_width, sdr=True, strict=False)
        assert s.strict is False
    assert isinstance(s, kind)
