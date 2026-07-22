"""Consolidation tests for the duplicate APBtoGAXITransformer.

The canonical implementation lives in
``scoreboards/apb_gaxi_transformer.py``. ``scoreboards/apb_scoreboard.py``
historically defined a second, incompatible class of the same name; it is
now a thin compatibility shim over the canonical one. Both import paths
must keep working (published package).
"""

from __future__ import annotations

from CocoTBFramework.components.apb.apb_packet import APBPacket
from CocoTBFramework.components.gaxi.gaxi_packet import GAXIPacket
from CocoTBFramework.components.shared.field_config import FieldConfig, FieldDefinition
from CocoTBFramework.scoreboards.apb_gaxi_transformer import (
    APBtoGAXITransformer as CanonicalTransformer,
)
from CocoTBFramework.scoreboards.apb_scoreboard import (
    APBtoGAXITransformer as ShimTransformer,
)
from CocoTBFramework.scoreboards.base_scoreboard import ProtocolTransformer


def _gaxi_field_config() -> FieldConfig:
    config = FieldConfig()
    config.add_field(FieldDefinition(name="cmd", bits=1, default=0))
    config.add_field(FieldDefinition(name="addr", bits=32, default=0, format="hex"))
    config.add_field(FieldDefinition(name="data", bits=32, default=0, format="hex"))
    config.add_field(FieldDefinition(name="strb", bits=4, default=0, format="bin"))
    return config


def _write_packet() -> APBPacket:
    return APBPacket(pwrite=1, paddr=0x120, pwdata=0xDEADBEEF, pstrb=0xF)


def _read_packet() -> APBPacket:
    return APBPacket(pwrite=0, paddr=0x40, prdata=0xCAFE0001)


def test_both_import_paths_resolve_to_one_implementation():
    """The shim must be the canonical class (plus compatibility API)."""
    assert issubclass(ShimTransformer, CanonicalTransformer)
    assert issubclass(ShimTransformer, ProtocolTransformer)


def test_shim_preserves_historical_constructor_contract():
    t = ShimTransformer(_gaxi_field_config(), GAXIPacket)
    # Historical attribute name and ProtocolTransformer metadata
    assert t.packet_class is GAXIPacket
    assert t.source_type == "APB"
    assert t.target_type == "GAXI"
    # Canonical attribute name also present (inherited contract)
    assert t.gaxi_packet_class is GAXIPacket


def test_shim_transform_write_maps_fields():
    t = ShimTransformer(_gaxi_field_config(), GAXIPacket)
    result = t.transform(_write_packet())
    assert len(result) == 1
    pkt = result[0]
    assert isinstance(pkt, GAXIPacket)
    assert pkt.fields["addr"] == 0x120
    assert pkt.fields["data"] == 0xDEADBEEF
    assert pkt.fields["strb"] == 0xF
    assert t.num_transformations == 1


def test_shim_transform_read_maps_prdata():
    t = ShimTransformer(_gaxi_field_config(), GAXIPacket)
    result = t.transform(_read_packet())
    assert len(result) == 1
    assert result[0].fields["data"] == 0xCAFE0001


def test_shim_transform_rejects_non_apb_packet():
    t = ShimTransformer(_gaxi_field_config(), GAXIPacket)
    assert t.transform("not a packet") == []
    assert t.num_failures == 1


def test_shim_inherits_canonical_bidirectional_api():
    """apb_to_gaxi / gaxi_to_apb from the canonical class work on the shim."""
    t = ShimTransformer(_gaxi_field_config(), GAXIPacket)
    pkt = t.apb_to_gaxi(_write_packet())
    assert pkt.fields["cmd"] == 1
    assert pkt.fields["addr"] == 0x120
    assert pkt.fields["data"] == 0xDEADBEEF


def test_canonical_transformer_unchanged_contract():
    """Canonical constructor: packet class is keyword with GAXIPacket default."""
    t = CanonicalTransformer(_gaxi_field_config())
    assert t.gaxi_packet_class is GAXIPacket
    pkt = t.apb_to_gaxi(_read_packet())
    assert pkt.fields["cmd"] == 0
    assert pkt.fields["data"] == 0xCAFE0001
