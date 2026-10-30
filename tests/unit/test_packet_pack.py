"""Packet.pack()/unpack() honour FieldDefinition.bit_position (the declared
wire layout), unlike the combined-signal packer in data_strategies, which
walks field_names() from bit 0 and inverts it."""
from CocoTBFramework.components.shared.field_config import FieldConfig, FieldDefinition
from CocoTBFramework.components.shared.packet import Packet


def _cfg():
    fc = FieldConfig()
    fc.add_field(FieldDefinition('qos', 4))
    fc.add_field(FieldDefinition('opcode', 7))
    fc.add_field(FieldDefinition('addr', 44))
    return fc


def test_pack_matches_declared_bit_positions():
    fc = _cfg()
    assert fc.get_field('qos').bit_position == (3, 0)
    assert fc.get_field('opcode').bit_position == (10, 4)
    assert fc.get_field('addr').bit_position == (54, 11)
    p = Packet(fc, qos=0xA, opcode=0x5, addr=0x1234)
    assert p.pack() == 0xA | (0x5 << 4) | (0x1234 << 11)


def test_unpack_is_the_inverse_and_masks():
    fc = _cfg()
    word = 0x3 | (0x7F << 4) | (((1 << 44) - 1) << 11) | (1 << 60)   # a stray bit above the layout
    p = Packet(fc).unpack(word)
    assert p.qos == 3 and p.opcode == 0x7F and p.addr == (1 << 44) - 1
    assert p.pack() == word & ((1 << 55) - 1)
