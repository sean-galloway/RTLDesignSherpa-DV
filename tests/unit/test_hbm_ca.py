"""HBM4 dfi_cmdaddr packing (DFI v6.0 section 3.1.2.4, Table 22) and
the HBM4-related catalog memberships (v6.0 Table 13)."""

import pytest

from CocoTBFramework.components.dfi.hbm_ca import (
    HBM4_CMDADDR_WIDTH,
    HBM4_EDGE_WIDTH,
    HBM4CAEdge,
    pack_hbm4_cmdaddr,
    pack_hbm4_edge,
    unpack_hbm4_cmdaddr,
)
from CocoTBFramework.components.dfi.dfi_signal_types import (
    DFIVersion,
    MemoryType,
    SubInterface,
)
from CocoTBFramework.components.dfi.dfi_signals import (
    SUPPORTED_MEMORY_BY_VERSION,
    signals_for,
)


def test_geometry_matches_table_22():
    assert HBM4_EDGE_WIDTH == 19
    assert HBM4_CMDADDR_WIDTH == 38


def test_edge_packing_bit_positions():
    # Row occupies [9:0], Column [17:10], ARFU [18] (Table 22).
    assert pack_hbm4_edge(row=0x3FF, col=0, arfu=0) == 0x3FF
    assert pack_hbm4_edge(row=0, col=0xFF, arfu=0) == 0xFF << 10
    assert pack_hbm4_edge(row=0, col=0, arfu=1) == 1 << 18


def test_word_packing_edge_lanes():
    # Rising edge on the lower 19 bits, falling on the upper 19.
    rise = HBM4CAEdge(row=0x155, col=0xA5, arfu=1)
    fall = HBM4CAEdge(row=0x2AA, col=0x5A, arfu=0)
    word = pack_hbm4_cmdaddr(rise, fall)
    assert word < (1 << HBM4_CMDADDR_WIDTH)
    assert (word & ((1 << 19) - 1)) == pack_hbm4_edge(*rise)
    assert (word >> 19) == pack_hbm4_edge(*fall)


@pytest.mark.parametrize("rise,fall", [
    (HBM4CAEdge(0, 0, 0), HBM4CAEdge(0, 0, 0)),
    (HBM4CAEdge(0x3FF, 0xFF, 1), HBM4CAEdge(0x3FF, 0xFF, 1)),
    (HBM4CAEdge(0x123, 0x45, 0), HBM4CAEdge(0x2BC, 0x9E, 1)),
])
def test_roundtrip(rise, fall):
    word = pack_hbm4_cmdaddr(rise, fall)
    got = unpack_hbm4_cmdaddr(word)
    assert got.rise == rise
    assert got.fall == fall


def test_range_checks():
    with pytest.raises(ValueError):
        pack_hbm4_edge(row=1 << 10, col=0)
    with pytest.raises(ValueError):
        pack_hbm4_edge(row=0, col=1 << 8)
    with pytest.raises(ValueError):
        pack_hbm4_edge(row=0, col=0, arfu=2)
    with pytest.raises(ValueError):
        unpack_hbm4_cmdaddr(1 << HBM4_CMDADDR_WIDTH)


def test_hbm4_supported_only_in_v6():
    for version, mems in SUPPORTED_MEMORY_BY_VERSION.items():
        assert (MemoryType.HBM4 in mems) == (version == DFIVersion.V6_0), \
            f"HBM4 support wrong for {version}"


def test_wck_memberships_v6_table_13():
    """wck_en/wck_toggle: LPDDR5+LPDDR6+HBM4; wck_cs: LPDDR5/6 only.
    Regression for the _WCK shadowing bug that replaced the membership
    frozensets with a SubInterface enum."""
    si = frozenset({SubInterface.WCK_CONTROL})

    def wck(mt):
        return sorted(s.name for s in signals_for(DFIVersion.V6_0, mt, si))

    assert wck(MemoryType.LPDDR5) == ["wck_cs", "wck_en", "wck_toggle"]
    assert wck(MemoryType.LPDDR6) == ["wck_cs", "wck_en", "wck_toggle"]
    assert wck(MemoryType.HBM4) == ["wck_en", "wck_toggle"]
    assert wck(MemoryType.DDR5) == []
