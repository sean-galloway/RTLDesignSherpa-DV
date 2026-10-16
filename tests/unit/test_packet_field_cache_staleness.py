"""RDS-DV #92. The Packet field cache must never serve a value computed for a different
field definition.

Two ways it did (shared/packet.py ``_FieldCache``, keyed by
``(id(field_config), field_name)``):

* id reuse -- a FieldConfig is freed, the next one is allocated at the same
  address, and inherits the dead one's masks. Seen in the CXS family as
  512-bit flit data silently masked to 256 bits after a 256-bit test.
* mutation -- ``update_field_width`` (or a direct edit of a FieldDefinition)
  after a packet has used the field leaves the old mask cached.
"""
from __future__ import annotations

import gc

import pytest

from CocoTBFramework.components.shared.field_config import FieldConfig, FieldDefinition
from CocoTBFramework.components.shared.packet import Packet, clear_field_cache


def _config(bits, fmt='hex'):
    fc = FieldConfig()
    fc.add_field(FieldDefinition(name='data', bits=bits, default=0, format=fmt,
                                 display_width=(bits + 3) // 4))
    return fc


def test_freed_config_id_reuse_does_not_leak_masks():
    """Allocate until CPython hands a new config the freed one's id (usually
    the first try), then require the new config's own width.

    The cache is cleared EVERY iteration so the entry at the reused id is the
    narrow config's own. Without that the old cache kept whichever config
    first claimed the address -- often an earlier 512-bit one -- and the
    reuse went unseen 7 runs in 20 against the unfixed code."""
    wide = (1 << 511) | 1
    for _ in range(200):
        clear_field_cache()
        narrow = _config(256)
        Packet(narrow, data=1)                 # populate the cache for this id
        narrow_id = id(narrow)
        del narrow
        gc.collect()
        big = _config(512)
        p = Packet(big, data=wide)
        assert p.fields['data'] == wide, "512-bit value masked by a freed config's entry"
        if id(big) == narrow_id:
            return                             # the reuse case happened and passed
    pytest.skip("allocator never reused the freed config's id; reuse case not exercised")


def test_update_field_width_invalidates_mask():
    clear_field_cache()
    fc = _config(8)
    assert Packet(fc, data=0x1FF).fields['data'] == 0xFF
    fc.update_field_width('data', 16)
    assert Packet(fc, data=0x1FF).fields['data'] == 0x1FF


def test_direct_field_definition_edit_invalidates_mask():
    clear_field_cache()
    fc = _config(8)
    Packet(fc, data=1)
    fc.get_field('data').bits = 12
    assert Packet(fc, data=0xFFF).fields['data'] == 0xFFF


def test_replaced_field_definition_invalidates_formatter():
    clear_field_cache()
    fc = _config(8, fmt='hex')
    str(Packet(fc, data=5))
    fc.remove_field('data')
    fc.add_field(FieldDefinition(name='data', bits=8, default=0, format='bin', display_width=8))
    assert '0b00000101' in str(Packet(fc, data=5))


def test_cache_still_hits_for_a_stable_config():
    from CocoTBFramework.components.shared.packet import get_field_cache_stats
    clear_field_cache()
    fc = _config(32)
    for i in range(50):
        Packet(fc, data=i)
    stats = get_field_cache_stats()
    assert stats['hits'] > stats['misses']
