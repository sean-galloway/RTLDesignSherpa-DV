"""DFISlavePHY's CA-bus command path (DFI v5/v6 encoded dfi_cmdaddr).

The PHY glue is deliberately thin — CAStream and ca_dispatch carry the
protocol logic and are tested directly — so these tests pin the glue
itself: signal selection, the NOP-while-incomplete contract, and the
multi-command-per-cycle dispatch. A DFISlavePHY needs a live cocotb
entity to construct, so the methods under test are exercised on a
bare instance with only the attributes they touch.
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
from CocoTBFramework.components.dfi.dfi_packet import DRAMCommand
from CocoTBFramework.components.dfi.dfi_slave_phy import DFISlavePHY
from CocoTBFramework.components.dfi.hbm_ca import (
    HBM4CAEdge,
    pack_hbm4_cmdaddr,
)
from CocoTBFramework.components.dfi.lpddr6_ca_map import LPDDR6_CA_MAP


class _Sig:
    """Minimal stand-in for a cocotb signal handle."""

    def __init__(self, value=0, resolvable=True):
        self.value = _Val(value, resolvable)


class _Val:
    def __init__(self, value, resolvable):
        self.integer = value
        self.is_resolvable = resolvable


class _Bus:
    def __init__(self, **sigs):
        for k, v in sigs.items():
            setattr(self, k, _Sig(v))


def _phy(streams=None, lpddr2=False, **bus):
    """A DFISlavePHY with only the CA-path attributes populated."""
    p = object.__new__(DFISlavePHY)
    p._ca_streams = streams
    p._ca_args = None
    p.bus = _Bus(**bus)
    p._is_lpddr2_family = lambda: lpddr2
    p.handled = []
    p._handle_command = lambda cmd, phase_override=None: \
        p.handled.append((cmd, p._ca_args))
    return p


# ---------------------------------------------------------------------------
# Signal selection and the opt-in gate
# ---------------------------------------------------------------------------

def test_ca_bus_gate_is_opt_in():
    assert _phy()._uses_ca_bus() is False
    assert _phy(lpddr2=True)._uses_ca_bus() is True
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True)
    assert _phy(streams=s)._uses_ca_bus() is True


def test_cmdaddr_preferred_over_address():
    """v6.0 renamed dfi_address to dfi_cmdaddr; both are accepted."""
    p = _phy(cmdaddr=0xABC, address=0x123)
    assert p._ca_bus_word() == 0xABC
    p = _phy(address=0x123)
    assert p._ca_bus_word() == 0x123


def test_unresolvable_bus_reads_as_zero():
    p = _phy(cmdaddr=0)
    p.bus.cmdaddr = _Sig(0xFF, resolvable=False)
    assert p._ca_bus_word() == 0


# ---------------------------------------------------------------------------
# Cycle-driven decode: NOP until a command completes
# ---------------------------------------------------------------------------

def test_multi_cycle_command_reports_nop_until_complete():
    enc = CACodec(DDR5_CA_MAP)
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True)
    e0, e1 = enc.encode("act", row=0x1234, ba=2, bg=5, cid=0)
    p = _phy(streams=s, cmdaddr=e0)

    assert p._decode_command() is DRAMCommand.NOP   # first cycle
    assert p._ca_args is None
    p.bus.cmdaddr = _Sig(e1)
    assert p._decode_command() is DRAMCommand.ACT   # second cycle
    assert p._ca_args["row"] == 0x1234
    assert p._ca_args["bank"] == (5 << 2) | 2
    assert p.handled == []      # the caller dispatches the returned cmd


def test_idle_bus_decodes_as_nop_without_args():
    enc = CACodec(DDR5_CA_MAP)
    s = CAStream(DDR5_CA_MAP, DDR5_CA_WIDTH, sdr=True)
    p = _phy(streams=s, cmdaddr=enc.encode("nop")[0])
    assert p._decode_command() is DRAMCommand.NOP
    assert p._ca_args is None


def test_lpddr6_command_spans_two_cycles():
    enc = CACodec(LPDDR6_CA_MAP)
    s = CAStream(LPDDR6_CA_MAP, LPDDR6_CA_WIDTH)
    e = enc.encode("rd_s", ba=2, bg=1, ws=0, col=0x15, ap=1, sc=0)
    p = _phy(streams=s, cmdaddr=pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, e[0], e[1]))
    assert p._decode_command() is DRAMCommand.NOP
    p.bus.cmdaddr = _Sig(pack_ddr_cmdaddr(LPDDR6_CA_WIDTH, e[2], e[3]))
    assert p._decode_command() is DRAMCommand.RDA
    assert p._ca_args["col"] == 0x15


# ---------------------------------------------------------------------------
# Several commands completing in one DFI cycle
# ---------------------------------------------------------------------------

def test_extra_commands_in_one_cycle_are_dispatched():
    """HBM4 can complete a row and a column command in the same word.
    The last is returned to the caller; the rest are handled here, so
    none are dropped."""
    row_enc = CACodec(HBM4_ROW_CA_MAP)
    col_enc = CACodec(HBM4_COL_CA_MAP)
    s = HBM4CAStreams(HBM4_ROW_CA_MAP, HBM4_COL_CA_MAP)

    c_rise, c_fall = col_enc.encode("wr", pc=0, sid=1, ba=9, col=17)
    pre = row_enc.encode("prepb", pc=0, sid=0, ba=4)[0]
    rnop = row_enc.encode("rnop")[0]
    word = pack_hbm4_cmdaddr(HBM4CAEdge(row=pre, col=c_rise, arfu=0),
                             HBM4CAEdge(row=rnop, col=c_fall, arfu=0))
    p = _phy(streams=s, cmdaddr=word)

    last = p._decode_command()
    # Row PRE completes on the first edge, column WR on the second.
    assert [c for c, _ in p.handled] == [DRAMCommand.PRE]
    assert p.handled[0][1]["bank"] == 4
    assert last is DRAMCommand.WR
    assert p._ca_args["col"] == 17


def test_nops_never_reach_the_handler():
    row_enc = CACodec(HBM4_ROW_CA_MAP)
    col_enc = CACodec(HBM4_COL_CA_MAP)
    s = HBM4CAStreams(HBM4_ROW_CA_MAP, HBM4_COL_CA_MAP)
    rnop = row_enc.encode("rnop")[0]
    cnop = col_enc.encode("cnop")[0]
    word = pack_hbm4_cmdaddr(HBM4CAEdge(row=rnop, col=cnop, arfu=0),
                             HBM4CAEdge(row=rnop, col=cnop, arfu=0))
    p = _phy(streams=s, cmdaddr=word)
    assert p._decode_command() is DRAMCommand.NOP
    assert p.handled == []


# ---------------------------------------------------------------------------
# Constructor wiring (no cocotb entity needed for the stream setup)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs,kind", [
    (dict(ca_map=DDR5_CA_MAP, ca_sdr=True), CAStream),
    (dict(ca_map=LPDDR6_CA_MAP), CAStream),
    (dict(ca_map=HBM4_ROW_CA_MAP, ca_map_col=HBM4_COL_CA_MAP),
     HBM4CAStreams),
])
def test_stream_construction_matches_map_kind(kwargs, kind):
    """Mirror of the ctor block: a col map selects the HBM4 twin-stream
    form, otherwise a single stream defaulting to the map's bus width."""
    ca_map = kwargs["ca_map"]
    if kwargs.get("ca_map_col") is not None:
        streams = HBM4CAStreams(ca_map, kwargs["ca_map_col"])
    else:
        streams = CAStream(ca_map, ca_map.bus_width,
                           sdr=kwargs.get("ca_sdr", False))
    assert isinstance(streams, kind)
    if kind is CAStream:
        assert streams.ca_width == ca_map.bus_width
