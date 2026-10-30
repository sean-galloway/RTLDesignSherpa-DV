# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for the CHI cache-state models (IHI 0050H B4).

Every table the model transcribes gets spot-checks against the page,
including a footnote row; every (snoop, state) pair of Tables B4.46 to
B4.50 is checked for the expected final state and response form.
"""

import pytest

from CocoTBFramework.components.chi.chi_cache_model import (
    COPYBACK_COMP_ALLOWED,
    DATALESS_TRANSITIONS,
    FULL_BE,
    LINE_BYTES,
    MAKE_READ_UNIQUE_TRANSITIONS,
    READ_PERMITTED_INITIAL,
    READ_TRANSITIONS,
    SNOOP_TRANSITIONS,
    WRITE_PERMITTED_RESP,
    WRITE_TRANSITIONS,
    HomePolicy,
    RNCache,
    SnoopFilter,
    SnoopResponse,
    line_addr,
    snoop_resp_encode,
)
from CocoTBFramework.components.chi.chi_opcodes import (
    CACHE_STATES,
    SC,
    SD,
    UC,
    UCE,
    UD,
    UDP,
    DatOpcode,
    I,
    ReqOpcode,
    RspOpcode,
    SnpOpcode,
    resp_state,
)

LINE = bytes(range(LINE_BYTES))
OTHER = bytes(reversed(LINE))
A = 0x1000


def cache_in(state, data=LINE, valid=None):
    c = RNCache()
    c.set_state(A, state, data=data, valid=valid)
    return c


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------
def test_line_addr_masks_to_64_bytes():
    assert line_addr(0x1234) == 0x1200
    assert line_addr(0x123F) == 0x1200
    assert line_addr(0x1240) == 0x1240


def test_cache_state_subset_is_enforced():
    c = RNCache(states=(I, UC, UD, SC))
    with pytest.raises(ValueError):
        c.set_state(A, UCE)
    with pytest.raises(ValueError):
        RNCache(states=(UC,))


def test_read_hit_and_silent_write_predicates():
    assert cache_in(UC).read_hit_ok(A) and cache_in(UC).can_write_silently(A)
    assert cache_in(SC).read_hit_ok(A) and not cache_in(SC).can_write_silently(A)
    assert not cache_in(UCE).read_hit_ok(A) and cache_in(UCE).can_write_silently(A)
    assert not cache_in(UDP, valid=0xFF).read_hit_ok(A)
    assert cache_in(UDP, valid=FULL_BE).read_hit_ok(A)
    assert not RNCache().read_hit_ok(A)


def test_silent_store_makes_udp_then_ud():
    c = cache_in(UCE)
    c.write_bytes(A, b'\xAA' * 8)
    assert c.state(A) == UDP and c.line(A).valid == 0xFF
    c.write_bytes(A, b'\xBB' * 56, be=(1 << 56) - 1)
    # 56 bytes written at A, so bytes 0..55 plus the earlier 0..7 -- not yet full
    assert c.state(A) == UDP
    c.write_bytes(A + 56, b'\xCC' * 8)
    assert c.state(A) == UD and c.line(A).full
    with pytest.raises(ValueError):
        cache_in(SC).write_bytes(A, b'\x00')


# ---------------------------------------------------------------------------
# Table B4.38 -- reads at the Requester
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("opcode, initial, comp, final", [
    (ReqOpcode.ReadShared, I, SC, SC),            # row: ReadShared I -> SC on CompData_SC
    (ReqOpcode.ReadShared, I, 'UD_PD', UD),       # row: CompData_UD_PD
    (ReqOpcode.ReadShared, I, 'SD_PD', SD),       # row: CompData_SD_PD (no separate form)
    (ReqOpcode.ReadShared, UCE, UC, UC),          # row: initial UCE (footnote a)
    (ReqOpcode.ReadClean, I, UC, UC),
    (ReqOpcode.ReadClean, UC, SC, UC),            # footnote b: UC stays UC on _SC
    (ReqOpcode.ReadClean, UD, SC, UD),            # footnote c
    (ReqOpcode.ReadClean, SD, SC, SD),            # footnote d
    (ReqOpcode.ReadClean, SD, UC, UD),            # row: SD + CompData_UC -> UD
    (ReqOpcode.ReadNotSharedDirty, I, 'UD_PD', UD),
    (ReqOpcode.ReadUnique, I, UC, UC),            # TagOp != Fetch rows
    (ReqOpcode.ReadUnique, SC, 'UD_PD', UD),
    (ReqOpcode.ReadUnique, SD, UC, UD),           # row: SD + CompData_UC -> UD
    (ReqOpcode.ReadPreferUnique, I, 'UD_PD', UD),
    (ReqOpcode.ReadPreferUnique, SC, UC, UC),
    (ReqOpcode.ReadPreferUnique, SD, SC, SD),     # footnote d
    (ReqOpcode.ReadNoSnp, I, UC, I),              # Requester must ignore the state
    (ReqOpcode.ReadOnce, I, I, I),
])
def test_table_b4_38_rows(opcode, initial, comp, final):
    c = cache_in(initial)
    assert c.complete_read(opcode, A, comp, LINE) == final
    assert c.state(A) == final


def test_table_b4_38_rejects_responses_the_row_does_not_list():
    with pytest.raises(ValueError, match="not permitted"):
        cache_in(I).complete_read(ReqOpcode.ReadClean, A, 'UD_PD', LINE)      # ReadClean never UD
    with pytest.raises(ValueError, match="not permitted"):
        cache_in(I).complete_read(ReqOpcode.ReadNotSharedDirty, A, 'SD_PD', LINE)
    with pytest.raises(ValueError, match="not in Table B4.38"):
        cache_in(UD).complete_read(ReqOpcode.ReadShared, A, SC, LINE)         # ReadShared only from I / UCE


def test_table_b4_38_permitted_initial_states_recorded():
    assert READ_PERMITTED_INITIAL[(ReqOpcode.ReadUnique, I)] == (UC, UCE)
    assert READ_PERMITTED_INITIAL[(ReqOpcode.ReadUnique, SD)] == (UD, UDP)
    assert set(READ_TRANSITIONS[ReqOpcode.ReadUnique]) >= {I, SC, SD, UC, UCE, UD, UDP}


def test_footnote_e_memory_data_dropped_when_dirty_merged_when_partial():
    c = cache_in(UD, data=OTHER)
    c.complete_read(ReqOpcode.ReadClean, A, UC, LINE)
    assert bytes(c.line(A).data) == OTHER                 # dropped
    c = cache_in(UDP, data=OTHER, valid=0xF)              # bytes 0..3 valid
    c.complete_read(ReqOpcode.ReadPreferUnique, A, UC, LINE)
    got = bytes(c.line(A).data)
    assert got[:4] == OTHER[:4] and got[4:] == LINE[4:]   # merged
    assert c.state(A) == UD and c.line(A).full
    c = cache_in(I)
    c.complete_read(ReqOpcode.ReadShared, A, SC, LINE)
    assert bytes(c.line(A).data) == LINE                  # taken


# ---------------------------------------------------------------------------
# Tables B4.41 / B4.42 -- MakeReadUnique
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("at_response, comp, data, final", [
    (SD, UC, None, UD),          # Comp_UC with precise SF
    (SD, UC, LINE, UD),          # CompData_UC, data could be stale: own copy kept
    (SC, UC, None, UC),
    (SC, 'UD_PD', None, UD),     # Comp_UD_PD: dirty responsibility passed without data
    (I, UC, LINE, UC),           # line lost to an invalidating snoop
    (I, 'UD_PD', LINE, UD),
    (SC, SC, None, SC),          # Table B4.42 Excl: Comp_SC, exclusive failed
    (SD, SC, None, SD),
])
def test_table_b4_41_make_read_unique(at_response, comp, data, final):
    c = cache_in(at_response, data=OTHER)
    assert c.complete_read(ReqOpcode.MakeReadUnique, A, comp, data) == final
    if at_response == SD and data is not None:
        assert bytes(c.line(A).data) == OTHER     # B4.7.1.1.3: use own copy over the response


def test_table_b4_41_not_permitted_states():
    for st in (I, UC, UD):
        assert st not in MAKE_READ_UNIQUE_TRANSITIONS or st == I
    with pytest.raises(ValueError, match="not permitted"):
        cache_in(UC).complete_read(ReqOpcode.MakeReadUnique, A, UC, None)
    with pytest.raises(ValueError, match="not permitted"):
        cache_in(UD).complete_read(ReqOpcode.MakeReadUnique, A, UC, None)


# ---------------------------------------------------------------------------
# Table B4.43 -- dataless
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("opcode, initial, comp, final", [
    (ReqOpcode.CleanUnique, I, UC, UCE),
    (ReqOpcode.CleanUnique, SC, UC, UC),
    (ReqOpcode.CleanUnique, SD, UC, UD),
    (ReqOpcode.MakeUnique, I, UC, UD),
    (ReqOpcode.MakeUnique, SD, UC, UD),
    (ReqOpcode.Evict, I, I, I),
    (ReqOpcode.CleanShared, SC, UC, SC),          # No Change, whatever the Comp says
    (ReqOpcode.CleanShared, UC, I, UC),
    (ReqOpcode.CleanInvalid, I, I, I),
    (ReqOpcode.MakeInvalid, I, I, I),
])
def test_table_b4_43_rows(opcode, initial, comp, final):
    c = cache_in(initial)
    assert c.complete_dataless(opcode, A, comp) == final
    assert c.state(A) == final


def test_table_b4_43_requires_i_before_invalidating_requests():
    with pytest.raises(ValueError, match="not in Table B4.43"):
        cache_in(UC).complete_dataless(ReqOpcode.Evict, A, I)
    with pytest.raises(ValueError, match="not a Table B4.43 response"):
        cache_in(I).complete_dataless(ReqOpcode.CleanUnique, A, I)
    assert DATALESS_TRANSITIONS[ReqOpcode.Evict] == {I: I}


# ---------------------------------------------------------------------------
# Table B4.44 -- writes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("opcode, before, resp, final", [
    (ReqOpcode.WriteBackFull, UD, 'UD_PD', I),
    (ReqOpcode.WriteBackFull, SC, SC, I),          # snooped down before the data went (footnote a)
    (ReqOpcode.WriteBackFull, I, I, I),
    (ReqOpcode.WriteBackPtl, UDP, 'UD_PD', I),
    (ReqOpcode.WriteCleanFull, UD, 'UD_PD', UC),   # line stays, now clean
    (ReqOpcode.WriteCleanFull, SD, 'SD_PD', SC),
    (ReqOpcode.WriteCleanFull, UC, UC, UC),
    (ReqOpcode.WriteEvictFull, UC, UC, I),
    (ReqOpcode.WriteEvictOrEvict, SC, SC, I),
    (ReqOpcode.WriteNoSnpFull, I, I, I),
])
def test_table_b4_44_writedata_resp(opcode, before, resp, final):
    c = cache_in(before)
    assert c.writedata_resp(opcode, A) == (resp, final)
    c.complete_write(opcode, A, final)
    assert c.state(A) == final


def test_table_b4_44_footnote_b_compack_mirrors_writedata():
    assert cache_in(UD).compack_resp(ReqOpcode.WriteBackFull, A) == ('UD_PD', I)
    assert cache_in(SD).compack_resp(ReqOpcode.WriteCleanFull, A) == ('SD_PD', SC)
    assert ReqOpcode.WriteBackPtl not in COPYBACK_COMP_ALLOWED
    with pytest.raises(ValueError, match="no Comp-only"):
        cache_in(UDP).compack_resp(ReqOpcode.WriteBackPtl, A)


def test_table_b4_44_rejects_states_not_in_the_row():
    with pytest.raises(ValueError, match="not in Table B4.44"):
        cache_in(UD).writedata_resp(ReqOpcode.WriteEvictFull, A)    # WriteEvictFull is for clean lines
    with pytest.raises(ValueError, match="not in Table B4.44"):
        cache_in(SC).writedata_resp(ReqOpcode.WriteBackPtl, A)
    assert WRITE_PERMITTED_RESP[(ReqOpcode.WriteCleanFull, UC)] == (UC, I)


# ---------------------------------------------------------------------------
# Tables B4.46 to B4.50 -- the Snoopee, every (snoop, state) pair
# ---------------------------------------------------------------------------
# (snoop, initial) -> (final, response name). RetToSrc = 0 unless the row
# needs 1 for a data response; those rows are covered separately.
SNOOP_EXPECTED = {
    # Table B4.46 SnpOnce
    (SnpOpcode.SnpOnce, I): (I, 'SnpResp_I'),
    (SnpOpcode.SnpOnce, UC): (UC, 'SnpResp_UC'),
    (SnpOpcode.SnpOnce, UCE): (UCE, 'SnpResp_UC'),
    (SnpOpcode.SnpOnce, UD): (UD, 'SnpRespData_UD'),
    (SnpOpcode.SnpOnce, UDP): (I, 'SnpRespDataPtl_I_PD'),
    (SnpOpcode.SnpOnce, SC): (SC, 'SnpResp_SC'),
    (SnpOpcode.SnpOnce, SD): (SD, 'SnpRespData_SD'),
    # Table B4.47 SnpClean / SnpShared / SnpNotSharedDirty
    (SnpOpcode.SnpShared, I): (I, 'SnpResp_I'),
    (SnpOpcode.SnpShared, UC): (SC, 'SnpResp_SC'),
    (SnpOpcode.SnpShared, UCE): (I, 'SnpResp_I'),
    (SnpOpcode.SnpShared, UD): (SD, 'SnpRespData_SD'),
    (SnpOpcode.SnpShared, UDP): (I, 'SnpRespDataPtl_I_PD'),
    (SnpOpcode.SnpShared, SC): (SC, 'SnpResp_SC'),
    (SnpOpcode.SnpShared, SD): (SD, 'SnpRespData_SD'),
    (SnpOpcode.SnpClean, UD): (SD, 'SnpRespData_SD'),
    (SnpOpcode.SnpNotSharedDirty, UC): (SC, 'SnpResp_SC'),
    # Table B4.48 SnpUnique / SnpPreferUnique
    (SnpOpcode.SnpUnique, I): (I, 'SnpResp_I'),
    (SnpOpcode.SnpUnique, UC): (I, 'SnpResp_I'),
    (SnpOpcode.SnpUnique, UCE): (I, 'SnpResp_I'),
    (SnpOpcode.SnpUnique, UD): (I, 'SnpRespData_I_PD'),
    (SnpOpcode.SnpUnique, UDP): (I, 'SnpRespDataPtl_I_PD'),
    (SnpOpcode.SnpUnique, SC): (I, 'SnpResp_I'),
    (SnpOpcode.SnpUnique, SD): (I, 'SnpRespData_I_PD'),
    (SnpOpcode.SnpPreferUnique, UD): (I, 'SnpRespData_I_PD'),
    (SnpOpcode.SnpPreferUnique, SC): (I, 'SnpResp_I'),
    # Table B4.49 SnpCleanShared
    (SnpOpcode.SnpCleanShared, I): (I, 'SnpResp_I'),
    (SnpOpcode.SnpCleanShared, UC): (UC, 'SnpResp_UC'),
    (SnpOpcode.SnpCleanShared, UCE): (I, 'SnpResp_I'),
    (SnpOpcode.SnpCleanShared, UD): (UC, 'SnpRespData_UC_PD'),
    (SnpOpcode.SnpCleanShared, UDP): (I, 'SnpRespDataPtl_I_PD'),
    (SnpOpcode.SnpCleanShared, SC): (SC, 'SnpResp_SC'),
    (SnpOpcode.SnpCleanShared, SD): (SC, 'SnpRespData_SC_PD'),
    # Table B4.49 SnpCleanInvalid
    (SnpOpcode.SnpCleanInvalid, I): (I, 'SnpResp_I'),
    (SnpOpcode.SnpCleanInvalid, UC): (I, 'SnpResp_I'),
    (SnpOpcode.SnpCleanInvalid, UCE): (I, 'SnpResp_I'),
    (SnpOpcode.SnpCleanInvalid, UD): (I, 'SnpRespData_I_PD'),
    (SnpOpcode.SnpCleanInvalid, UDP): (I, 'SnpRespDataPtl_I_PD'),
    (SnpOpcode.SnpCleanInvalid, SC): (I, 'SnpResp_I'),
    (SnpOpcode.SnpCleanInvalid, SD): (I, 'SnpRespData_I_PD'),
    # Table B4.49 SnpMakeInvalid
    **{(SnpOpcode.SnpMakeInvalid, s): (I, 'SnpResp_I') for s in CACHE_STATES},
    # Table B4.50 SnpQuery
    (SnpOpcode.SnpQuery, I): (I, 'SnpResp_I'),
    (SnpOpcode.SnpQuery, UC): (UC, 'SnpResp_UC'),
    (SnpOpcode.SnpQuery, UCE): (UCE, 'SnpResp_UC'),
    (SnpOpcode.SnpQuery, UD): (UD, 'SnpResp_UD'),
    (SnpOpcode.SnpQuery, UDP): (UDP, 'SnpResp_UD'),
    (SnpOpcode.SnpQuery, SC): (SC, 'SnpResp_SC'),
    (SnpOpcode.SnpQuery, SD): (SD, 'SnpResp_SD'),
}


@pytest.mark.parametrize("snoop, initial", sorted(SNOOP_EXPECTED, key=lambda k: (int(k[0]), k[1])))
def test_snoopee_tables_b4_46_to_b4_50(snoop, initial):
    final, name = SNOOP_EXPECTED[(snoop, initial)]
    c = cache_in(initial, valid=0xFF if initial == UDP else None)
    r = c.on_snoop(snoop, A)
    assert isinstance(r, SnoopResponse)
    assert (r.final_state, r.name) == (final, name)
    assert c.state(A) == final
    assert r.with_data == name.startswith('SnpRespData')
    assert r.partial == name.startswith('SnpRespDataPtl')
    assert r.pass_dirty == name.endswith('_PD')
    if r.with_data:
        assert r.data == LINE
        assert r.be == (0xFF if r.partial else FULL_BE)
    else:
        assert r.data is None and r.be == 0


def test_every_modelled_snoop_covers_every_state():
    for snoop, table in SNOOP_TRANSITIONS.items():
        assert set(table) == set(CACHE_STATES), snoop


def test_rettosrc_returns_clean_data_on_the_x_rows():
    # Table B4.46 SC row: RetToSrc 0 -> SnpResp_SC, 1 -> SnpRespData_SC
    assert cache_in(SC).on_snoop(SnpOpcode.SnpOnce, A, rettosrc=0).name == 'SnpResp_SC'
    assert cache_in(SC).on_snoop(SnpOpcode.SnpOnce, A, rettosrc=1).name == 'SnpRespData_SC'
    # Table B4.47 UC row: SC with or without data
    r = cache_in(UC).on_snoop(SnpOpcode.SnpShared, A, rettosrc=1)
    assert (r.name, r.final_state) == ('SnpRespData_SC', SC)
    # Table B4.48 SC row: RetToSrc 1 -> SnpRespData_I
    assert cache_in(SC).on_snoop(SnpOpcode.SnpUnique, A, rettosrc=1).name == 'SnpRespData_I'
    # dirty rows return data regardless
    assert cache_in(UD).on_snoop(SnpOpcode.SnpShared, A, rettosrc=0).with_data
    # B13.10.34: inapplicable (must be 0) in these
    with pytest.raises(ValueError, match="RetToSrc must be 0"):
        cache_in(UC).on_snoop(SnpOpcode.SnpCleanInvalid, A, rettosrc=1)


def test_table_b4_47_footnote_b_donotgotosd():
    r = cache_in(UD).on_snoop(SnpOpcode.SnpShared, A, donotgotosd=1)
    assert (r.name, r.final_state) == ('SnpRespData_SC_PD', SC)
    r = cache_in(SD).on_snoop(SnpOpcode.SnpNotSharedDirty, A, donotgotosd=1)
    assert (r.name, r.final_state) == ('SnpRespData_SC_PD', SC)
    # the footnote is on Table B4.47 only; SnpOnce from UD keeps UD
    r = cache_in(UD).on_snoop(SnpOpcode.SnpOnce, A, donotgotosd=1)
    assert (r.name, r.final_state) == ('SnpRespData_UD', UD)


def test_snoop_response_encodings_tables_b4_31_b4_33():
    """SnpResp_UD / SnpRespData_UD share the UC encoding 0b010; _PD forms."""
    assert snoop_resp_encode(UD) == 0b010 == snoop_resp_encode(UC)
    assert snoop_resp_encode('I_PD') == 0b100
    assert snoop_resp_encode('SC_PD') == 0b101
    assert snoop_resp_encode('UC_PD') == 0b110
    assert snoop_resp_encode(SD) == 0b011
    r = cache_in(UD).on_snoop(SnpOpcode.SnpQuery, A)
    assert r.resp == 0b010 and r.opcode == RspOpcode.SnpResp
    assert resp_state('snoop', r.resp) == UC
    r = cache_in(UDP, valid=1).on_snoop(SnpOpcode.SnpUnique, A)
    assert r.opcode == DatOpcode.SnpRespDataPtl and r.resp == 0b100


def test_permitted_final_states_are_recorded():
    r = cache_in(UC).on_snoop(SnpOpcode.SnpOnce, A)
    assert r.permitted_final == (I, SC)
    r = cache_in(UD).on_snoop(SnpOpcode.SnpCleanShared, A)
    assert r.permitted_final == (I, SC)
    r = cache_in(UD).on_snoop(SnpOpcode.SnpMakeInvalid, A)
    assert r.permitted_final == ()


def test_snoop_outside_scope_rejected():
    with pytest.raises(ValueError, match="not modelled"):
        cache_in(UC).on_snoop(SnpOpcode.SnpSharedFwd, A)


# ---------------------------------------------------------------------------
# SnoopFilter -- Table B4.26 and the B4.4.2 bullets
# ---------------------------------------------------------------------------
def filled(**rn_states):
    sf = SnoopFilter()
    for rn, st in rn_states.items():
        sf.on_complete(int(rn[2:]), A, st)
    return sf


def test_snoop_filter_tracks_and_drops_on_invalid():
    sf = filled(rn1=UC)
    assert sf.sharers(A) == {1: UC}
    sf.on_snoop_response(1, A, I)
    assert sf.sharers(A) == {} and sf.dirty_holder(A) is None
    sf.on_complete(2, A + 8, UD)
    assert sf.dirty_holder(A) == 2


@pytest.mark.parametrize("opcode, holders, requester, expect", [
    # ReadShared: SC sharers need nothing; a Unique or dirty holder gets SnpShared
    (ReqOpcode.ReadShared, {1: SC, 2: SC}, 3, []),
    (ReqOpcode.ReadShared, {1: UC}, 3, [(1, SnpOpcode.SnpShared)]),
    (ReqOpcode.ReadShared, {1: SD, 2: SC}, 3, [(1, SnpOpcode.SnpShared)]),
    (ReqOpcode.ReadClean, {1: UD}, 3, [(1, SnpOpcode.SnpClean)]),
    (ReqOpcode.ReadNotSharedDirty, {1: UC}, 3, [(1, SnpOpcode.SnpNotSharedDirty)]),
    # the requester itself is never snooped
    (ReqOpcode.ReadUnique, {1: SC, 3: SC}, 3, [(1, SnpOpcode.SnpUnique)]),
    (ReqOpcode.ReadUnique, {1: SC, 2: UD}, 3, [(1, SnpOpcode.SnpUnique), (2, SnpOpcode.SnpUnique)]),
    (ReqOpcode.ReadPreferUnique, {1: SC}, 3, [(1, SnpOpcode.SnpPreferUnique)]),
    (ReqOpcode.MakeReadUnique, {1: SD, 3: SC}, 3, [(1, SnpOpcode.SnpCleanInvalid)]),
    # ReadOnce: only a dirty holder has data memory does not
    (ReqOpcode.ReadOnce, {1: UC, 2: SC}, 3, []),
    (ReqOpcode.ReadOnce, {1: UD}, 3, [(1, SnpOpcode.SnpOnce)]),
    (ReqOpcode.ReadNoSnp, {1: UD}, 3, []),
    # dataless
    (ReqOpcode.CleanUnique, {1: SC, 3: SC}, 3, [(1, SnpOpcode.SnpCleanInvalid)]),
    (ReqOpcode.MakeUnique, {1: SC}, 3, [(1, SnpOpcode.SnpMakeInvalid)]),
    (ReqOpcode.MakeUnique, {1: UD}, 3, [(1, SnpOpcode.SnpCleanInvalid)]),     # B4.4.2: no SnpMakeInvalid on dirty
    (ReqOpcode.MakeInvalid, {1: SD, 2: UC}, 3, [(1, SnpOpcode.SnpCleanInvalid), (2, SnpOpcode.SnpMakeInvalid)]),
    (ReqOpcode.CleanInvalid, {1: UC}, 3, [(1, SnpOpcode.SnpCleanInvalid)]),
    (ReqOpcode.CleanShared, {1: UC, 2: UD}, 3, [(2, SnpOpcode.SnpCleanShared)]),
    (ReqOpcode.Evict, {1: UD}, 3, []),
    # writes
    (ReqOpcode.WriteUniqueFull, {1: SC}, 3, [(1, SnpOpcode.SnpMakeInvalid)]),
    (ReqOpcode.WriteUniqueFull, {1: UD}, 3, [(1, SnpOpcode.SnpCleanInvalid)]),
    (ReqOpcode.WriteUniquePtl, {1: SC, 2: UD}, 3, [(1, SnpOpcode.SnpCleanInvalid), (2, SnpOpcode.SnpCleanInvalid)]),
    (ReqOpcode.WriteNoSnpFull, {1: UD}, 3, []),
    (ReqOpcode.WriteBackFull, {1: SC}, 3, []),
    (ReqOpcode.WriteEvictOrEvict, {1: SC}, 3, []),
    (ReqOpcode.PCrdReturn, {1: UD}, 3, []),
])
def test_snoop_filter_chooses_table_b4_26_snoop(opcode, holders, requester, expect):
    sf = SnoopFilter()
    for rn, st in holders.items():
        sf.on_complete(rn, A, st)
    assert sf.snoops_for(opcode, A, requester) == expect


def test_snoop_filter_empty_line_needs_nothing():
    assert SnoopFilter().snoops_for(ReqOpcode.ReadUnique, A, 1) == []


# ---------------------------------------------------------------------------
# HomePolicy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("opcode, others, dirty, expect", [
    (ReqOpcode.ReadShared, False, False, UC),
    (ReqOpcode.ReadShared, True, False, SC),
    (ReqOpcode.ReadShared, False, True, 'UD_PD'),
    (ReqOpcode.ReadShared, True, True, 'SD_PD'),
    (ReqOpcode.ReadClean, False, True, UC),          # never UD
    (ReqOpcode.ReadClean, True, False, SC),
    (ReqOpcode.ReadNotSharedDirty, False, True, 'UD_PD'),
    (ReqOpcode.ReadNotSharedDirty, True, True, SC),  # no SD for NotSharedDirty
    (ReqOpcode.ReadUnique, False, False, UC),
    (ReqOpcode.ReadUnique, False, True, 'UD_PD'),
    (ReqOpcode.ReadPreferUnique, True, True, SC),
    (ReqOpcode.MakeReadUnique, False, True, 'UD_PD'),
    (ReqOpcode.ReadNoSnp, False, False, I),
    (ReqOpcode.ReadOnce, True, True, I),
])
def test_home_read_response_state(opcode, others, dirty, expect):
    assert HomePolicy.read_response_state(opcode, I, others, dirty) == expect


def test_home_decide_read_flags_writeback_when_dirty_not_passed():
    d = HomePolicy.decide_read(ReqOpcode.ReadClean, I, False, True, True)
    assert (d.rsp_state, d.data_from, d.needs_writeback) == (UC, 'snoop', True)
    d = HomePolicy.decide_read(ReqOpcode.ReadShared, I, False, True, True)
    assert (d.rsp_state, d.needs_writeback) == ('UD_PD', False)
    d = HomePolicy.decide_read(ReqOpcode.MakeReadUnique, SC, False, False, False)
    assert d.data_from is None                      # Comp, requester still holds the line
    d = HomePolicy.decide_read(ReqOpcode.ReadShared, I, False, False, False)
    assert d.data_from == 'memory'


def test_home_dataless_response_state():
    assert HomePolicy.dataless_response_state(ReqOpcode.CleanUnique) == UC
    assert HomePolicy.dataless_response_state(ReqOpcode.MakeUnique) == UC
    assert HomePolicy.dataless_response_state(ReqOpcode.Evict) == I
    assert HomePolicy.dataless_response_state(ReqOpcode.CleanInvalid) == I
    assert HomePolicy.dataless_response_state(ReqOpcode.MakeInvalid) == I
    assert HomePolicy.dataless_response_state(ReqOpcode.CleanShared, SC) == SC
    assert HomePolicy.dataless_response_state(ReqOpcode.CleanShared, UC) == UC
    assert HomePolicy.dataless_response_state(ReqOpcode.CleanShared, I) == I
    with pytest.raises(ValueError):
        HomePolicy.dataless_response_state(ReqOpcode.ReadShared)


# ---------------------------------------------------------------------------
# End to end: one line, two RNs, through the Home
# ---------------------------------------------------------------------------
def test_readshared_pulls_dirty_line_from_other_rn():
    rn1, rn2, sf = RNCache(), RNCache(), SnoopFilter()
    rn1.set_state(A, UD, data=OTHER)
    sf.on_complete(1, A, UD)
    # RN2 ReadShared: Home snoops RN1 with SnpShared
    assert sf.snoops_for(ReqOpcode.ReadShared, A, 2) == [(1, SnpOpcode.SnpShared)]
    r = rn1.on_snoop(SnpOpcode.SnpShared, A)
    sf.on_snoop_response(1, A, r.final_state)
    assert r.name == 'SnpRespData_SD' and sf.sharers(A) == {1: SD}
    state = HomePolicy.read_response_state(ReqOpcode.ReadShared, I, True, r.pass_dirty)
    assert state == SC
    assert rn2.complete_read(ReqOpcode.ReadShared, A, state, r.data) == SC
    assert bytes(rn2.line(A).data) == OTHER
    sf.on_complete(2, A, SC)
    assert sf.sharers(A) == {1: SD, 2: SC}
    # RN2 then wants it unique: SnpUnique to RN1 passes the dirty data
    assert sf.snoops_for(ReqOpcode.ReadUnique, A, 2) == [(1, SnpOpcode.SnpUnique)]
    r = rn1.on_snoop(SnpOpcode.SnpUnique, A)
    sf.on_snoop_response(1, A, r.final_state)
    assert r.name == 'SnpRespData_I_PD'
    state = HomePolicy.read_response_state(ReqOpcode.ReadUnique, SC, False, r.pass_dirty)
    assert state == 'UD_PD'
    assert rn2.complete_read(ReqOpcode.ReadUnique, A, state, r.data) == UD
    sf.on_complete(2, A, UD)
    assert sf.sharers(A) == {2: UD} and sf.dirty_holder(A) == 2
    # and writes it back
    assert rn2.writedata_resp(ReqOpcode.WriteBackFull, A) == ('UD_PD', I)
    rn2.complete_write(ReqOpcode.WriteBackFull, A, I)
    sf.on_complete(2, A, I)
    assert sf.sharers(A) == {}


# ---------------------------------------------------------------------------
# Table dictionaries are the transcription: a row count per table
# ---------------------------------------------------------------------------
def test_table_shapes():
    assert set(READ_TRANSITIONS) == {ReqOpcode.ReadNoSnp, ReqOpcode.ReadOnce, ReqOpcode.ReadClean,
                                     ReqOpcode.ReadNotSharedDirty, ReqOpcode.ReadShared, ReqOpcode.ReadUnique,
                                     ReqOpcode.ReadPreferUnique}
    assert set(WRITE_TRANSITIONS) == {ReqOpcode.WriteNoSnpPtl, ReqOpcode.WriteNoSnpFull, ReqOpcode.WriteUniquePtl,
                                      ReqOpcode.WriteUniqueFull, ReqOpcode.WriteBackFull, ReqOpcode.WriteBackPtl,
                                      ReqOpcode.WriteCleanFull, ReqOpcode.WriteEvictFull, ReqOpcode.WriteEvictOrEvict}
    assert len(SNOOP_TRANSITIONS) == 10
