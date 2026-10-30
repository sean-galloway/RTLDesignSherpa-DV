"""CHI opcode tables (B13.12-B13.16) and field encodings: spot checks of
every table against the printed values, reserved values rejected."""
from __future__ import annotations

import pytest

from CocoTBFramework.components.chi import (
    AtomicOp,
    DatOpcode,
    MemAttr,
    Order,
    ReqOpcode,
    Resp,
    RespErr,
    RspOpcode,
    Size,
    SnpOpcode,
    atomic_opcode,
    data_id,
    data_ids_for,
    opcode_name,
    req_opcode_name,
    resp_encode,
    resp_state,
)


@pytest.mark.parametrize("name,value", [
    ('ReqLCrdReturn', 0x00), ('ReadShared', 0x01), ('ReadNoSnp', 0x04), ('PCrdReturn', 0x05),
    ('ReadUnique', 0x07), ('CleanUnique', 0x0B), ('MakeUnique', 0x0C), ('Evict', 0x0D),
    ('WriteEvictFull', 0x15), ('WriteCleanFull', 0x17), ('WriteUniquePtl', 0x18), ('WriteUniqueFull', 0x19),
    ('WriteBackPtl', 0x1A), ('WriteBackFull', 0x1B), ('WriteNoSnpPtl', 0x1C), ('WriteNoSnpFull', 0x1D),
    ('ReadNotSharedDirty', 0x26), ('AtomicSwap', 0x38), ('AtomicCompare', 0x39), ('PrefetchTgt', 0x3A),
    ('MakeReadUnique', 0x41), ('WriteEvictOrEvict', 0x42), ('ReadPreferUnique', 0x4C), ('WriteNoSnpDef', 0x4E),
    ('WriteBackFullCleanInvPoPA', 0x79),
])
def test_req_opcodes_table_b13_12(name, value):
    assert ReqOpcode[name] == value


@pytest.mark.parametrize("value", [0x06, 0x0F, 0x10, 0x12, 0x16, 0x1E, 0x1F, 0x3B, 0x40, 0x45, 0x4F, 0x7F])
def test_req_reserved_values_are_not_encodable(value):
    with pytest.raises(ValueError):
        ReqOpcode(value)


def test_atomic_sub_opcodes_table_b13_13():
    assert atomic_opcode(ReqOpcode.AtomicStore, AtomicOp.UMIN) == 0x2F
    assert atomic_opcode(ReqOpcode.AtomicLoad, AtomicOp.ADD) == 0x30
    assert req_opcode_name(0x33) == 'AtomicLoad.SET'
    with pytest.raises(ValueError):
        atomic_opcode(ReqOpcode.AtomicSwap, AtomicOp.ADD)


@pytest.mark.parametrize("name,value", [
    ('RespLCrdReturn', 0x00), ('SnpResp', 0x01), ('CompAck', 0x02), ('RetryAck', 0x03), ('Comp', 0x04),
    ('CompDBIDResp', 0x05), ('DBIDResp', 0x06), ('PCrdGrant', 0x07), ('ReadReceipt', 0x08),
    ('SnpRespFwded', 0x09), ('TagMatch', 0x0A), ('RespSepData', 0x0B), ('Persist', 0x0C),
    ('CompPersist', 0x0D), ('DBIDRespOrd', 0x0E), ('StashDone', 0x10), ('CompStashDone', 0x11), ('CompCMO', 0x14),
])
def test_rsp_opcodes_table_b13_14(name, value):
    assert RspOpcode[name] == value


@pytest.mark.parametrize("name,value", [
    ('SnpLCrdReturn', 0x00), ('SnpShared', 0x01), ('SnpClean', 0x02), ('SnpOnce', 0x03),
    ('SnpNotSharedDirty', 0x04), ('SnpUniqueStash', 0x05), ('SnpMakeInvalidStash', 0x06), ('SnpUnique', 0x07),
    ('SnpCleanShared', 0x08), ('SnpCleanInvalid', 0x09), ('SnpMakeInvalid', 0x0A), ('SnpStashUnique', 0x0B),
    ('SnpStashShared', 0x0C), ('SnpDVMOp', 0x0D), ('SnpQuery', 0x10), ('SnpSharedFwd', 0x11),
    ('SnpCleanFwd', 0x12), ('SnpOnceFwd', 0x13), ('SnpNotSharedDirtyFwd', 0x14), ('SnpPreferUnique', 0x15),
    ('SnpPreferUniqueFwd', 0x16), ('SnpUniqueFwd', 0x17),
])
def test_snp_opcodes_table_b13_15(name, value):
    assert SnpOpcode[name] == value


@pytest.mark.parametrize("name,value", [
    ('DataLCrdReturn', 0x0), ('SnpRespData', 0x1), ('CopyBackWriteData', 0x2), ('NonCopyBackWriteData', 0x3),
    ('CompData', 0x4), ('SnpRespDataPtl', 0x5), ('SnpRespDataFwded', 0x6), ('WriteDataCancel', 0x7),
    ('DataSepResp', 0xB), ('NonCopyBackWriteDataCompAck', 0xC),
])
def test_dat_opcodes_table_b13_16(name, value):
    assert DatOpcode[name] == value


def test_opcode_name_unknown_is_marked():
    assert opcode_name('rsp', 0x0F) == '?0x0F'
    assert opcode_name('dat', 0xD) == '?0x0D'
    assert opcode_name('req', 0x41) == 'MakeReadUnique'


def test_size_table_b13_17():
    assert [Size(i).nbytes for i in range(7)] == [1, 2, 4, 8, 16, 32, 64]
    assert Size.of(64) is Size.B64
    with pytest.raises(ValueError):
        Size(7)


def test_memattr_order_resperr_bits():
    assert MemAttr.EWA == 1 and MemAttr.DEVICE == 2 and MemAttr.CACHEABLE == 4 and MemAttr.ALLOCATE == 8
    assert Order.REQ_ORDER_OWO == 0b10 and Order.ENDPOINT == 0b11
    assert RespErr.EXOK == 0b01 and RespErr.DERR == 0b10 and RespErr.NDERR == 0b11


def test_resp_table_b13_35_per_message_class():
    assert resp_state('snoop', 0b100) == 'I_PD'
    assert resp_state('snoop', 0b110) == 'UC_PD'
    assert resp_state('comp', 0b110) == 'UD_PD'
    assert resp_state('comp', 0b111) == 'SD_PD'
    assert resp_state('writedata', 0b001) == 'SC'
    with pytest.raises(ValueError):
        resp_state('comp', 0b011)      # reserved for Comp responses
    with pytest.raises(ValueError):
        resp_state('snoop', 0b111)     # reserved for snoop responses
    assert resp_encode('UD_PD') == Resp.UD_PD == 0b110
    assert resp_encode('I_PD') == 0b100


def test_data_ids_table_b2_16():
    assert data_id(0x30, 128) == 3 and data_id(0x20, 256) == 2 and data_id(0x30, 512) == 0
    assert data_ids_for(64, 0x40, 128) == [0, 1, 2, 3]
    assert data_ids_for(64, 0x40, 256) == [0, 2]
    assert data_ids_for(64, 0x40, 512) == [0]
    assert data_ids_for(16, 0x30, 128) == [3]
    assert data_ids_for(32, 0x20, 128) == [2, 3]
