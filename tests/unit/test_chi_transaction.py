# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
"""Unit tests for CHI transaction tracking (IHI 0050H B2.3 / B2.4 / B2.7.3 /
B2.9.4 / B2.10). Flits are SimpleNamespaces: the trackers are duck-typed."""

from types import SimpleNamespace as NS

import pytest

from CocoTBFramework.components.chi.chi_cache_model import RNCache
from CocoTBFramework.components.chi.chi_opcodes import (
    UD,
    DatOpcode,
    I,
    ReqOpcode,
    Resp,
    RespErr,
    RspOpcode,
    Size,
    resp_encode,
)
from CocoTBFramework.components.chi.chi_transaction import (
    MAX_OUTSTANDING,
    REQ_CLASS,
    Action,
    CHITransaction,
    CompleterTracker,
    ReqClass,
    RequesterTracker,
    TxnIdPool,
    needs_compack,
    req_class,
    write_data_opcode,
)

HOME = 0x20
RN = 0x04


def rsp(opcode, txnid=0, srcid=HOME, resp=0, dbid=0, pcrdtype=0, resperr=0):
    return NS(opcode=int(opcode), txnid=txnid, srcid=srcid, tgtid=RN, resp=int(resp), dbid=dbid,
              pcrdtype=pcrdtype, resperr=resperr)


def dat(opcode, txnid=0, dataid=0, data=0, resp=0, dbid=0, srcid=HOME, homenid=HOME, be=-1, resperr=0):
    return NS(opcode=int(opcode), txnid=txnid, srcid=srcid, tgtid=RN, resp=int(resp), dbid=dbid,
              homenid=homenid, dataid=dataid, data=data, be=be, resperr=resperr)


def req(opcode, addr=0x1000, size=Size.B64, txnid=0, srcid=RN, **kw):
    f = dict(opcode=int(opcode), addr=addr, size=int(size), txnid=txnid, srcid=srcid, tgtid=HOME,
             expcompack=0, order=0, allowretry=1, pcrdtype=0, cah=0)
    f.update(kw)
    return NS(**f)


def kinds(actions):
    return [a.kind for a in actions]


def errors(actions):
    return [a.text for a in actions if a.kind == 'error']


def txn(opcode, addr=0x1000, size=Size.B64, **kw):
    kw.setdefault('txnid', 0)
    kw.setdefault('data_width', 128)
    if req_class(opcode) in (ReqClass.READ_ALLOC, ReqClass.DATALESS_ACK):
        kw.setdefault('expcompack', 1)
    return CHITransaction(opcode, addr, size, srcid=RN, tgtid=HOME, **kw)


def feed_compdata(t, resp=Resp.SC, dbid=0x11, width=128):
    acts = []
    for d in t.data_ids(width):
        acts += t.on_dat(dat(DatOpcode.CompData, txnid=t.txnid, dataid=d, data=d + 1, resp=resp, dbid=dbid))
    return acts


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def test_req_class_table():
    assert REQ_CLASS[ReqOpcode.ReadNoSnp] == ReqClass.READ_NOALLOC
    assert REQ_CLASS[ReqOpcode.ReadOnce] == ReqClass.READ_NOALLOC
    for op in (ReqOpcode.ReadClean, ReqOpcode.ReadNotSharedDirty, ReqOpcode.ReadShared, ReqOpcode.ReadUnique,
               ReqOpcode.ReadPreferUnique, ReqOpcode.MakeReadUnique):
        assert REQ_CLASS[op] == ReqClass.READ_ALLOC
    for op in (ReqOpcode.Evict, ReqOpcode.CleanShared, ReqOpcode.CleanInvalid, ReqOpcode.MakeInvalid):
        assert REQ_CLASS[op] == ReqClass.DATALESS
    assert REQ_CLASS[ReqOpcode.CleanUnique] == REQ_CLASS[ReqOpcode.MakeUnique] == ReqClass.DATALESS_ACK
    for op in (ReqOpcode.WriteNoSnpPtl, ReqOpcode.WriteNoSnpFull, ReqOpcode.WriteUniquePtl, ReqOpcode.WriteUniqueFull):
        assert REQ_CLASS[op] == ReqClass.WRITE_IMM
    for op in (ReqOpcode.WriteBackFull, ReqOpcode.WriteBackPtl, ReqOpcode.WriteCleanFull,
               ReqOpcode.WriteEvictFull, ReqOpcode.WriteEvictOrEvict):
        assert REQ_CLASS[op] == ReqClass.WRITE_COPYBACK
    assert REQ_CLASS[ReqOpcode.PCrdReturn] == ReqClass.PCRD_RETURN
    with pytest.raises(ValueError, match="outside"):
        req_class(ReqOpcode.AtomicSwap)


def test_needs_compack_table_b2_8():
    assert needs_compack(ReqOpcode.ReadShared, 1) and needs_compack(ReqOpcode.MakeReadUnique, 1)
    assert needs_compack(ReqOpcode.CleanUnique, 1) and needs_compack(ReqOpcode.MakeUnique, 1)
    assert needs_compack(ReqOpcode.ReadNoSnp, 1) and not needs_compack(ReqOpcode.ReadNoSnp, 0)     # O
    assert needs_compack(ReqOpcode.ReadOnce, 1) and not needs_compack(ReqOpcode.ReadOnce, 0)
    assert not needs_compack(ReqOpcode.CleanShared, 0) and not needs_compack(ReqOpcode.Evict, 0)   # N
    assert needs_compack(ReqOpcode.WriteNoSnpFull, 1) and not needs_compack(ReqOpcode.WriteUniquePtl, 0)
    assert not needs_compack(ReqOpcode.WriteBackFull, 0)       # H: decided when Home answers


def test_write_data_opcode_table_b4_44():
    assert write_data_opcode(ReqOpcode.WriteBackFull) == DatOpcode.CopyBackWriteData
    assert write_data_opcode(ReqOpcode.WriteEvictOrEvict) == DatOpcode.CopyBackWriteData
    assert write_data_opcode(ReqOpcode.WriteNoSnpPtl) == DatOpcode.NonCopyBackWriteData
    assert write_data_opcode(ReqOpcode.WriteUniqueFull) == DatOpcode.NonCopyBackWriteData
    with pytest.raises(ValueError):
        write_data_opcode(ReqOpcode.ReadShared)


def test_action_params_and_equality():
    a = Action('send_compack', tgtid=1, txnid=2)
    assert a.kind == 'send_compack' and a.tgtid == 1 and a.txnid == 2
    assert a == Action('send_compack', tgtid=1, txnid=2) and a != Action('done')
    assert 'send_compack' in repr(a)
    with pytest.raises(AttributeError):
        a.missing
    with pytest.raises(ValueError):
        Action('bogus')


def test_validate_catches_expcompack_and_pcrdtype_rules():
    t = CHITransaction(ReqOpcode.ReadShared, 0, Size.B64, txnid=0, expcompack=0)
    assert any('ExpCompAck = 1' in p for p in t.validate())
    t = CHITransaction(ReqOpcode.Evict, 0, Size.B64, txnid=0, expcompack=1)
    assert any('must not use CompAck' in p for p in t.validate())
    t = CHITransaction(ReqOpcode.WriteBackFull, 0, Size.B64, txnid=0, expcompack=1)
    assert any('CopyBack' in p for p in t.validate())
    t = CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64, txnid=0, allowretry=1, pcrdtype=3)
    assert any('PCrdType must be 0' in p for p in t.validate())
    t = CHITransaction(ReqOpcode.WriteNoSnpFull, 0, Size.B64, txnid=0, data=b'\x00' * 8)
    assert any('payload' in p for p in t.validate())
    assert CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64, txnid=0).validate() == []


def test_data_ids_table_b2_16():
    t = txn(ReqOpcode.ReadNoSnp, addr=0x40)
    assert t.data_ids(128) == [0, 1, 2, 3]
    assert t.data_ids(256) == [0, 2]
    assert t.data_ids(512) == [0]
    t = txn(ReqOpcode.WriteNoSnpPtl, addr=0x30, size=Size.B16)
    assert t.data_ids(128) == [3] and t.data_ids(256) == [2] and t.data_ids(512) == [0]
    assert t.nbytes == 16 and t.window == 0x30


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def test_readshared_compdata_then_compack():
    """B2.3.1.1 alt 1: CompData_SC in four packets, CompAck to HomeNID with TxnID = DBID."""
    t = txn(ReqOpcode.ReadShared, addr=0x1000)
    acts = []
    for d in range(4):
        acts += t.on_dat(dat(DatOpcode.CompData, dataid=d, data=0x11 * (d + 1), resp=Resp.SC, dbid=0x2A, homenid=0x21))
        if d < 3:
            assert t.status == 'issued' and not t.complete()
    assert acts == [Action('send_compack', tgtid=0x21, txnid=0x2A), Action('done')]
    assert t.status == 'done' and t.comp_state == 'SC' and t.compack_sent and t.dbid == 0x2A
    assert t.read_data() == bytes([0x11] + [0] * 15 + [0x22] + [0] * 15 + [0x33] + [0] * 15 + [0x44] + [0] * 15)
    assert t.stats['CompData'] == 4


def test_read_separate_response_and_data():
    """B2.3.1.1 alt 2: RespSepData then DataSepResp; CompAck follows RespSepData (B2.7.4)."""
    t = txn(ReqOpcode.ReadUnique)
    acts = t.on_rsp(rsp(RspOpcode.RespSepData, dbid=5, srcid=HOME))
    assert acts == [Action('send_compack', tgtid=HOME, txnid=5)]
    assert not t.complete()
    acts = []
    for d in range(4):
        acts += t.on_dat(dat(DatOpcode.DataSepResp, dataid=d, resp=Resp.UD_PD, dbid=5))
    assert acts == [Action('done')] and t.comp_state == 'UD_PD'


def test_data_sep_resp_may_arrive_before_resp_sep_data():
    t = txn(ReqOpcode.ReadShared)
    for d in range(4):
        assert t.on_dat(dat(DatOpcode.DataSepResp, dataid=d, resp=Resp.SC)) == []
    acts = t.on_rsp(rsp(RspOpcode.RespSepData, dbid=9))
    assert acts == [Action('send_compack', tgtid=HOME, txnid=9), Action('done')]


def test_ordered_readnosnp_waits_for_both_before_compack():
    """B2.7.4: ordered ReadNoSnp / ReadOnce with ExpCompAck: CompAck only after both."""
    t = txn(ReqOpcode.ReadOnce, order=2, expcompack=1)
    assert t.on_rsp(rsp(RspOpcode.ReadReceipt)) == []
    assert t.on_rsp(rsp(RspOpcode.RespSepData, dbid=3)) == []
    acts = []
    for d in range(4):
        acts += t.on_dat(dat(DatOpcode.DataSepResp, dataid=d, resp=Resp.UC, dbid=3))
    assert acts == [Action('send_compack', tgtid=HOME, txnid=3), Action('done')]


def test_readnosnp_without_compack_and_readreceipt_rules():
    t = txn(ReqOpcode.ReadNoSnp, addr=0x40, size=Size.B32, expcompack=0)
    acts = feed_compdata(t, resp=Resp.UC)
    assert acts == [Action('done')] and not t.compack_sent
    assert t.expected_ids == [0, 1]
    # Order = 0: a ReadReceipt is an error; Order != 0: it is required before done
    t = txn(ReqOpcode.ReadNoSnp, expcompack=0)
    assert errors(t.on_rsp(rsp(RspOpcode.ReadReceipt))) and 'Order = 0' in errors(t.on_rsp(rsp(RspOpcode.ReadReceipt)))[0]
    t = txn(ReqOpcode.ReadNoSnp, expcompack=0, order=1)
    assert feed_compdata(t) == []
    assert not t.complete() and t.readreceipt_pending()
    assert t.on_rsp(rsp(RspOpcode.ReadReceipt)) == [Action('done')]
    assert errors(t.on_rsp(rsp(RspOpcode.ReadReceipt)))


def test_make_read_unique_comp_only():
    """B2.3.1.1 alt 6: Comp without data, then CompAck."""
    t = txn(ReqOpcode.MakeReadUnique)
    acts = t.on_rsp(rsp(RspOpcode.Comp, resp=Resp.UC, dbid=7))
    assert acts == [Action('send_compack', tgtid=HOME, txnid=7), Action('done')]
    assert t.comp_state == 'UC' and t.read_data() is None
    # and with data when the line was lost
    t = txn(ReqOpcode.MakeReadUnique)
    assert kinds(feed_compdata(t, resp=Resp.UD_PD)) == ['send_compack', 'done']


def test_read_error_cases():
    t = txn(ReqOpcode.ReadShared)
    assert 'Comp for a read' in errors(t.on_rsp(rsp(RspOpcode.Comp)))[0]
    assert 'no write data' in errors(t.on_rsp(rsp(RspOpcode.DBIDResp)))[0]
    assert 'never received' in errors(t.on_rsp(rsp(RspOpcode.CompAck)))[0]
    assert 'RequesterTracker' in errors(t.on_rsp(rsp(RspOpcode.PCrdGrant)))[0]
    assert 'not a read data response' in errors(t.on_dat(dat(DatOpcode.SnpRespData)))[0]
    # wrong / duplicate DataID
    t = txn(ReqOpcode.ReadShared, addr=0x30, size=Size.B16)
    assert 'DataID 0 is not one of [3]' in errors(t.on_dat(dat(DatOpcode.CompData, dataid=0)))[0]
    assert kinds(t.on_dat(dat(DatOpcode.CompData, dataid=3, resp=Resp.SC, dbid=1))) == ['send_compack', 'done']
    assert 'after the transaction completed' in errors(t.on_dat(dat(DatOpcode.CompData, dataid=3)))[0]
    t = txn(ReqOpcode.ReadShared)
    t.on_dat(dat(DatOpcode.CompData, dataid=0, resp=Resp.SC))
    assert 'DataID 0 twice' in errors(t.on_dat(dat(DatOpcode.CompData, dataid=0, resp=Resp.SC)))[0]
    assert 'differs' in errors(t.on_dat(dat(DatOpcode.CompData, dataid=1, resp=Resp.UC)))[0]
    t = txn(ReqOpcode.ReadShared)
    t.on_dat(dat(DatOpcode.DataSepResp, dataid=0, resp=Resp.SC))
    assert 'mixed' in errors(t.on_dat(dat(DatOpcode.CompData, dataid=2, resp=Resp.SC)))[0]
    # alternatives do not mix
    t = txn(ReqOpcode.ReadShared)
    t.on_rsp(rsp(RspOpcode.RespSepData))
    assert 'RespSepData twice' in errors(t.on_rsp(rsp(RspOpcode.RespSepData)))[0]
    assert 'CompData after RespSepData' in errors(t.on_dat(dat(DatOpcode.CompData)))[0]
    t = txn(ReqOpcode.ReadShared)
    t.on_dat(dat(DatOpcode.CompData, resp=Resp.SC))
    assert 'RespSepData after CompData' in errors(t.on_rsp(rsp(RspOpcode.RespSepData)))[0]
    assert 'DataSepResp after CompData' in errors(t.on_dat(dat(DatOpcode.DataSepResp, dataid=1)))[0]
    assert t.stats['errors'] == 2


def test_resperr_is_recorded_not_fatal():
    t = txn(ReqOpcode.ReadNoSnp, expcompack=0)
    acts = []
    for d in range(4):
        acts += t.on_dat(dat(DatOpcode.CompData, dataid=d, resp=Resp.UC, resperr=RespErr.DERR if d == 2 else 0))
    assert acts == [Action('done')] and t.resperr == RespErr.DERR and t.stats['resperr'] == 1


def test_bus_width_must_be_known():
    t = CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64, txnid=0)
    with pytest.raises(ValueError, match="bus width"):
        t.on_dat(dat(DatOpcode.CompData))
    t = CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64, txnid=0)
    f = dat(DatOpcode.CompData, resp=Resp.UC)
    f.cfg = NS(data_width=512)
    assert t.on_dat(f) == [Action('done')] and t.bus_width == 512


# ---------------------------------------------------------------------------
# Dataless
# ---------------------------------------------------------------------------
def test_dataless_comp_only_and_with_compack():
    t = txn(ReqOpcode.CleanInvalid)
    assert t.on_rsp(rsp(RspOpcode.Comp, resp=Resp.I)) == [Action('done')]
    assert t.comp_state == 'I'
    t = txn(ReqOpcode.CleanUnique)
    acts = t.on_rsp(rsp(RspOpcode.Comp, resp=Resp.UC, dbid=4))
    assert acts == [Action('send_compack', tgtid=HOME, txnid=4), Action('done')]
    t = txn(ReqOpcode.Evict)
    t.on_rsp(rsp(RspOpcode.Comp))
    assert 'Comp twice' in errors(t.on_rsp(rsp(RspOpcode.Comp)))[0]
    t = txn(ReqOpcode.MakeInvalid)
    assert 'Comp only' in errors(t.on_rsp(rsp(RspOpcode.CompDBIDResp)))[0]


# ---------------------------------------------------------------------------
# Immediate writes
# ---------------------------------------------------------------------------
def test_writenosnpfull_compdbidresp_then_data_all_dataids():
    """B2.3.2.1 alt 2a2: CompDBIDResp -> NonCopyBackWriteData with TxnID = DBID."""
    payload = bytes(range(64))
    for width, n in ((128, 4), (256, 2), (512, 1)):
        t = txn(ReqOpcode.WriteNoSnpFull, addr=0x1000, data=payload, data_width=width)
        acts = t.on_rsp(rsp(RspOpcode.CompDBIDResp, dbid=0x33, srcid=HOME))
        assert acts == [Action('send_write_data', tgtid=HOME, txnid=0x33, opcode=DatOpcode.NonCopyBackWriteData,
                               state=None), Action('done')]
        chunks = t.write_chunks(width)
        assert len(chunks) == n and [c[0] for c in chunks] == t.data_ids(width)
        step = width // 8
        for i, (did, data, be) in enumerate(chunks):
            assert data.to_bytes(step, 'little') == payload[i * step:(i + 1) * step]
            assert be == (1 << step) - 1
        assert t.status == 'done' and t.data_sent


def test_sixteen_byte_write_at_0x30_is_one_chunk_dataid_3():
    payload = bytes(range(0x10, 0x20))
    t = txn(ReqOpcode.WriteNoSnpPtl, addr=0x30, size=Size.B16, data=payload)
    assert t.on_rsp(rsp(RspOpcode.CompDBIDResp, dbid=1)) == [
        Action('send_write_data', tgtid=HOME, txnid=1, opcode=DatOpcode.NonCopyBackWriteData, state=None),
        Action('done')]
    [(did, data, be)] = t.write_chunks(128)
    assert did == 3 and be == 0xFFFF and data.to_bytes(16, 'little') == payload
    # on a 512-bit bus the same bytes sit at their natural positions 48..63
    [(did, data, be)] = t.write_chunks(512)
    assert did == 0 and be == 0xFFFF << 48 and data.to_bytes(64, 'little')[48:] == payload
    # partial byte enables carry through
    t = txn(ReqOpcode.WriteNoSnpPtl, addr=0x30, size=Size.B16, data=payload, be=0x00F0)
    [(did, data, be)] = t.write_chunks(128)
    assert did == 3 and be == 0x00F0 and data.to_bytes(16, 'little')[4:8] == payload[4:8]
    assert data.to_bytes(16, 'little')[:4] == b'\0' * 4


def test_write_separate_dbidresp_and_comp_either_order():
    """B2.3.2.1 alt 2a1 / 3a1."""
    t = txn(ReqOpcode.WriteUniquePtl, data=bytes(64))
    assert kinds(t.on_rsp(rsp(RspOpcode.DBIDResp, dbid=8))) == ['send_write_data']
    assert not t.complete()
    assert t.on_rsp(rsp(RspOpcode.Comp, dbid=8)) == [Action('done')]
    # Comp first, then DBIDRespOrd; with ExpCompAck (OWO) CompAck follows Comp
    t = txn(ReqOpcode.WriteNoSnpFull, data=bytes(64), expcompack=1, order=2)
    assert t.on_rsp(rsp(RspOpcode.Comp, dbid=8)) == [Action('send_compack', tgtid=HOME, txnid=8)]
    assert kinds(t.on_rsp(rsp(RspOpcode.DBIDRespOrd, dbid=8))) == ['send_write_data', 'done']
    # CompDBIDResp with ExpCompAck: data then CompAck
    t = txn(ReqOpcode.WriteUniqueFull, data=bytes(64), expcompack=1)
    assert kinds(t.on_rsp(rsp(RspOpcode.CompDBIDResp, dbid=2))) == ['send_write_data', 'send_compack', 'done']


def test_write_error_cases():
    t = txn(ReqOpcode.WriteNoSnpFull, data=bytes(64))
    assert 'CompAck is a Requester' in errors(t.on_rsp(rsp(RspOpcode.CompAck)))[0]      # CompAck before Comp
    t.on_rsp(rsp(RspOpcode.DBIDResp, dbid=1))
    assert 'DBIDResp twice' in errors(t.on_rsp(rsp(RspOpcode.DBIDResp, dbid=1)))[0]
    assert 'B2.4.3' in errors(t.on_rsp(rsp(RspOpcode.Comp, dbid=2)))[0]                   # DBID mismatch
    assert 'not both' in errors(t.on_rsp(rsp(RspOpcode.CompDBIDResp, dbid=1)))[0]
    t.on_rsp(rsp(RspOpcode.Comp, dbid=1))
    assert 'Comp twice' in errors(t.on_rsp(rsp(RspOpcode.Comp, dbid=1)))[0]
    assert 'after the transaction completed' in errors(t.on_rsp(rsp(RspOpcode.RespSepData)))[0]
    t = txn(ReqOpcode.WriteNoSnpFull, data=bytes(64))
    assert 'receives no data' in errors(t.on_dat(dat(DatOpcode.CompData)))[0]
    assert 'not a legal response' in errors(t.on_rsp(rsp(RspOpcode.RespSepData)))[0]


# ---------------------------------------------------------------------------
# CopyBack writes
# ---------------------------------------------------------------------------
def test_writebackfull_compdbidresp_then_copyback_data():
    t = txn(ReqOpcode.WriteBackFull, data=bytes(64))
    acts = t.on_rsp(rsp(RspOpcode.CompDBIDResp, dbid=0x40))
    assert acts == [Action('send_write_data', tgtid=HOME, txnid=0x40, opcode=DatOpcode.CopyBackWriteData, state=None),
                    Action('done')]
    assert 'CompDBIDResp twice' in errors(t.on_rsp(rsp(RspOpcode.CompDBIDResp, dbid=0x40)))[0]


def test_writebackfull_comp_alt_1a_needs_cah_and_gives_compack():
    """B2.3.2.3 alt 1a: Comp (no data) only for WriteEvictOrEvict or CAH = 1; CompAck follows regardless of ExpCompAck."""
    t = txn(ReqOpcode.WriteBackFull, data=bytes(64))
    assert 'CAH = 0' in errors(t.on_rsp(rsp(RspOpcode.Comp, dbid=3)))[0]
    t = txn(ReqOpcode.WriteBackFull, data=bytes(64), cah=1)
    assert t.on_rsp(rsp(RspOpcode.Comp, dbid=3)) == [Action('send_compack', tgtid=HOME, txnid=3), Action('done')]
    assert not t.data_sent and t.compack_sent and t.expcompack == 0
    t = txn(ReqOpcode.WriteEvictOrEvict)
    assert kinds(t.on_rsp(rsp(RspOpcode.Comp, dbid=3))) == ['send_compack', 'done']
    t = txn(ReqOpcode.WriteEvictOrEvict)
    assert 'CompDBIDResp or Comp' in errors(t.on_rsp(rsp(RspOpcode.DBIDResp, dbid=3)))[0]


def test_writeback_compack_state_comes_from_the_cache():
    """The Resp on CompAck_UD_PD is Table B4.44's, read from RNCache at send time."""
    c = RNCache()
    c.set_state(0x1000, UD, data=bytes(64))
    t = txn(ReqOpcode.WriteBackFull, cah=1)
    [ack, done] = t.on_rsp(rsp(RspOpcode.Comp, dbid=3))
    state, final = c.compack_resp(t.opcode, t.addr)
    assert (state, final) == ('UD_PD', I) and resp_encode(state) == 0b110
    c.complete_write(t.opcode, t.addr, final)
    assert c.state(0x1000) == I


# ---------------------------------------------------------------------------
# Retry (B2.10)
# ---------------------------------------------------------------------------
def test_retryack_then_pcrdgrant_reissues_with_allowretry_0():
    rt = RequesterTracker(RN)
    t = rt.issue(CHITransaction(ReqOpcode.ReadShared, 0x1000, Size.B64, expcompack=1, qos=5, memattr=0xD,
                                snpattr=1, likelyshared=1, lpid=3, data_width=128))
    before = {k: getattr(t, k) for k in ('opcode', 'addr', 'size', 'txnid', 'expcompack', 'qos', 'memattr',
                                         'snpattr', 'likelyshared', 'lpid', 'order', 'excl')}
    got, acts = rt.route_rsp(rsp(RspOpcode.RetryAck, txnid=t.txnid, pcrdtype=2))
    assert got is t and acts == [] and t.status == 'retry_wait' and t.retry_pcrdtype == 2
    assert rt.credits_banked == {} and rt.waiting == {2: [t]}
    # a grant of the WRONG type is banked, not used
    assert rt.route_rsp(rsp(RspOpcode.PCrdGrant, pcrdtype=1)) == (None, [])
    assert rt.credits_banked == {1: 1} and t.status == 'retry_wait'
    got, acts = rt.route_rsp(rsp(RspOpcode.PCrdGrant, pcrdtype=2))
    assert got is t and acts == [Action('retry', pcrdtype=2)]
    assert t.status == 'retried' and t.allowretry == 0 and t.pcrdtype == 2
    assert {k: getattr(t, k) for k in before} == before     # every other field kept
    assert rt.issue(t) is t and rt.outstanding == 1          # re-send keeps the entry
    acts = []
    for d in range(4):
        _, a = rt.route_dat(dat(DatOpcode.CompData, txnid=t.txnid, dataid=d, resp=Resp.SC, dbid=6))
        acts += a
    assert kinds(acts) == ['send_compack', 'done'] and rt.outstanding == 0 and t.stats['retries'] == 1


def test_pcrdgrant_before_retryack_is_banked():
    rt = RequesterTracker(RN)
    t = rt.issue(CHITransaction(ReqOpcode.WriteNoSnpFull, 0x1000, Size.B64, data=bytes(64)))
    assert rt.route_rsp(rsp(RspOpcode.PCrdGrant, pcrdtype=0)) == (None, [])
    assert rt.credits_banked == {0: 1}
    got, acts = rt.route_rsp(rsp(RspOpcode.RetryAck, txnid=t.txnid, pcrdtype=0))
    assert got is t and acts == [Action('retry', pcrdtype=0)] and t.status == 'retried'
    assert rt.credits_banked == {0: 0} and rt.waiting == {}


def test_retry_rules():
    t = txn(ReqOpcode.ReadShared)
    t.on_dat(dat(DatOpcode.CompData, resp=Resp.SC))
    assert 'either accepted or retried' in errors(t.on_rsp(rsp(RspOpcode.RetryAck)))[0]
    t = txn(ReqOpcode.ReadShared, allowretry=0, pcrdtype=1)
    assert 'AllowRetry = 0' in errors(t.on_rsp(rsp(RspOpcode.RetryAck)))[0]
    t = txn(ReqOpcode.ReadShared)
    assert t.on_rsp(rsp(RspOpcode.RetryAck, pcrdtype=4)) == [Action('retry', pcrdtype=4)]
    assert 'waiting for PCrdGrant' in errors(t.on_rsp(rsp(RspOpcode.Comp)))[0]
    assert 'waiting for PCrdGrant' in errors(t.on_dat(dat(DatOpcode.CompData)))[0]


def test_pcrd_return_spends_a_banked_credit():
    rt = RequesterTracker(RN)
    rt.grant(3)
    with pytest.raises(ValueError, match="no banked"):
        rt.issue(CHITransaction(ReqOpcode.PCrdReturn, 0, Size.B1, pcrdtype=1))
    t = rt.issue(CHITransaction(ReqOpcode.PCrdReturn, 0x1234, Size.B1, pcrdtype=3))
    assert t.status == 'done' and t.allowretry == 0 and t.addr == 0 and t.complete()
    assert rt.credits_banked == {3: 0} and rt.outstanding == 0 and not rt.pool.in_use(t.txnid)
    assert 'no response' in errors(t.on_rsp(rsp(RspOpcode.Comp, txnid=t.txnid)))[0]


def test_cancel_while_waiting_keeps_the_credit_for_return():
    rt = RequesterTracker(RN)
    t = rt.issue(CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64))
    rt.route_rsp(rsp(RspOpcode.RetryAck, txnid=t.txnid, pcrdtype=0))
    rt.cancel(t)
    assert t.status == 'cancelled' and rt.outstanding == 0 and rt.waiting == {0: []}
    assert rt.route_rsp(rsp(RspOpcode.PCrdGrant, pcrdtype=0)) == (None, [])
    assert rt.credits_banked == {0: 1}


# ---------------------------------------------------------------------------
# TxnIdPool / RequesterTracker
# ---------------------------------------------------------------------------
def test_txnid_pool_exhaustion_and_reuse():
    p = TxnIdPool(max_outstanding=3)
    ids = [p.allocate() for _ in range(3)]
    assert ids == [0, 1, 2] and p.outstanding == 3 and p.in_use(1)
    with pytest.raises(RuntimeError, match="exhausted"):
        p.allocate()
    p.free(1)
    assert p.allocate() == 3 and not p.in_use(1)
    with pytest.raises(ValueError, match="already in use"):
        p.reserve(3)
    with pytest.raises(ValueError):
        TxnIdPool(MAX_OUTSTANDING + 1)


def test_txnid_pool_wraps_at_12_bits():
    p = TxnIdPool()
    p._next = 4095
    assert p.allocate() == 4095 and p.allocate() == 0


def test_tracker_allocates_and_rejects_bad_requests():
    rt = RequesterTracker(RN, TxnIdPool(2))
    a = rt.issue(CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64))
    b = rt.issue(CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64))
    assert (a.txnid, b.txnid, a.srcid) == (0, 1, RN)
    with pytest.raises(RuntimeError, match="exhausted"):
        rt.issue(CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64))
    with pytest.raises(ValueError, match="ExpCompAck"):
        RequesterTracker(RN).issue(CHITransaction(ReqOpcode.ReadShared, 0, Size.B64))
    with pytest.raises(ValueError, match="already in use"):
        rt.issue(CHITransaction(ReqOpcode.ReadNoSnp, 0, Size.B64, txnid=0))


def test_tracker_routes_unknown_txnid_to_error():
    rt = RequesterTracker(RN)
    t, acts = rt.route_rsp(rsp(RspOpcode.Comp, txnid=77))
    assert t is None and 'unknown TxnID 77' in acts[0].text
    t, acts = rt.route_dat(dat(DatOpcode.CompData, txnid=78))
    assert t is None and 'unknown TxnID 78' in acts[0].text


def test_tracker_retires_on_done_and_frees_txnid():
    rt = RequesterTracker(RN)
    t = rt.issue(CHITransaction(ReqOpcode.CleanUnique, 0, Size.B64, expcompack=1))
    got, acts = rt.route_rsp(rsp(RspOpcode.Comp, txnid=t.txnid, resp=Resp.UC, dbid=1))
    assert got is t and kinds(acts) == ['send_compack', 'done']
    assert rt.outstanding == 0 and not rt.pool.in_use(t.txnid) and rt.retired_count == 1


# ---------------------------------------------------------------------------
# CompleterTracker
# ---------------------------------------------------------------------------
def test_completer_rendezvous_write_data_by_srcid_dbid():
    ct = CompleterTracker(data_width=128)
    e = ct.accept(req(ReqOpcode.WriteNoSnpFull, txnid=5, srcid=RN))
    assert ct.by_txnid(RN, 5) is e and e.cls == ReqClass.WRITE_IMM and e.nbytes == 64
    dbid = ct.allocate_dbid(e)
    assert ct.by_dbid(RN, dbid) is e and ct.allocate_dbid(e) == dbid
    assert ct.expected_data_ids(e, 128) == [0, 1, 2, 3] and ct.expected_data_ids(e, 512) == [0]
    for d in range(4):
        got = ct.on_write_data(dat(DatOpcode.NonCopyBackWriteData, txnid=dbid, srcid=RN, dataid=d, data=d, resp=0))
        assert got is e and e.write_complete == (d == 3)
    assert e.writedata_state == 'I' and sorted(e.data_chunks) == [0, 1, 2, 3]
    # another RN using the same DBID value is a different entry (B2.4.3)
    with pytest.raises(LookupError, match="matches no DBID"):
        ct.on_write_data(dat(DatOpcode.NonCopyBackWriteData, txnid=dbid, srcid=RN + 1, dataid=0))
    ct.retire(e)
    assert ct.outstanding == 0 and ct.by_dbid(RN, dbid) is None and not ct.pool.in_use(dbid)


def test_completer_rejects_wrong_data_opcode_and_dataid():
    ct = CompleterTracker(data_width=256)
    e = ct.accept(req(ReqOpcode.WriteBackFull, txnid=1))
    dbid = ct.allocate_dbid(e)
    with pytest.raises(ValueError, match="wants CopyBackWriteData"):
        ct.on_write_data(dat(DatOpcode.NonCopyBackWriteData, txnid=dbid, srcid=RN, dataid=0))
    with pytest.raises(ValueError, match="CopyBack data cannot carry CompAck"):
        ct.on_write_data(dat(DatOpcode.NonCopyBackWriteDataCompAck, txnid=dbid, srcid=RN, dataid=0))
    with pytest.raises(ValueError, match="DataID 1 is not one of \\[0, 2\\]"):
        ct.on_write_data(dat(DatOpcode.CopyBackWriteData, txnid=dbid, srcid=RN, dataid=1))
    ct.on_write_data(dat(DatOpcode.CopyBackWriteData, txnid=dbid, srcid=RN, dataid=0, resp=Resp.UD_PD))
    with pytest.raises(ValueError, match="twice"):
        ct.on_write_data(dat(DatOpcode.CopyBackWriteData, txnid=dbid, srcid=RN, dataid=0))
    assert e.writedata_state == 'UD_PD' and not e.write_complete


def test_completer_compack_rendezvous_and_combined_data_compack():
    ct = CompleterTracker(data_width=512)
    e = ct.accept(req(ReqOpcode.ReadShared, txnid=9, expcompack=1))
    dbid = ct.allocate_dbid(e)
    with pytest.raises(LookupError):
        ct.on_compack(rsp(RspOpcode.CompAck, txnid=dbid + 1, srcid=RN))
    got = ct.on_compack(rsp(RspOpcode.CompAck, txnid=dbid, srcid=RN, resp=0))
    assert got is e and e.compack_seen and e.compack_state == 'I'
    with pytest.raises(ValueError, match="CompAck twice"):
        ct.on_compack(rsp(RspOpcode.CompAck, txnid=dbid, srcid=RN))
    w = ct.accept(req(ReqOpcode.WriteNoSnpFull, txnid=10, expcompack=1))
    wd = ct.allocate_dbid(w)
    ct.on_write_data(dat(DatOpcode.NonCopyBackWriteDataCompAck, txnid=wd, srcid=RN, dataid=0))
    assert w.write_complete and w.compack_seen


def test_completer_accept_rules():
    ct = CompleterTracker()
    ct.accept(req(ReqOpcode.ReadNoSnp, txnid=1))
    with pytest.raises(ValueError, match="already in flight"):
        ct.accept(req(ReqOpcode.ReadNoSnp, txnid=1))
    ct.accept(req(ReqOpcode.ReadNoSnp, txnid=1, srcid=RN + 1))      # same TxnID, other RN: fine
    with pytest.raises(ValueError, match="PCrdType must be 0"):
        ct.accept(req(ReqOpcode.ReadNoSnp, txnid=2, allowretry=1, pcrdtype=1))
    e = ct.accept(req(ReqOpcode.ReadNoSnp, txnid=3, allowretry=0, pcrdtype=1))
    assert e.pcrdtype == 1 and ct.outstanding == 3


def test_completer_dbid_pool_exhaustion():
    ct = CompleterTracker(max_dbid=1)
    a = ct.accept(req(ReqOpcode.WriteNoSnpFull, txnid=1))
    b = ct.accept(req(ReqOpcode.WriteNoSnpFull, txnid=2))
    ct.allocate_dbid(a)
    with pytest.raises(RuntimeError, match="exhausted"):
        ct.allocate_dbid(b)
    ct.retire(a)
    assert ct.allocate_dbid(b) == 1 and ct.by_dbid(RN, 1) is b     # round-robin, not immediate reuse


# ---------------------------------------------------------------------------
# Requester and Completer against each other
# ---------------------------------------------------------------------------
def test_requester_and_completer_agree_on_a_write():
    rt, ct = RequesterTracker(RN), CompleterTracker(data_width=256)
    t = rt.issue(CHITransaction(ReqOpcode.WriteUniqueFull, 0x2000, Size.B64, data=bytes(range(64)), data_width=256))
    e = ct.accept(req(ReqOpcode.WriteUniqueFull, addr=0x2000, txnid=t.txnid, srcid=RN))
    dbid = ct.allocate_dbid(e)
    _, acts = rt.route_rsp(rsp(RspOpcode.CompDBIDResp, txnid=t.txnid, dbid=dbid, srcid=HOME))
    send = acts[0]
    assert send.kind == 'send_write_data' and send.txnid == dbid and send.tgtid == HOME
    for did, data, be in t.write_chunks(256):
        ct.on_write_data(dat(send.opcode, txnid=send.txnid, srcid=RN, dataid=did, data=data, be=be))
    assert e.write_complete and e.data_chunks[2][0].to_bytes(32, 'little') == bytes(range(32, 64))
    assert t.status == 'done' and rt.outstanding == 0
