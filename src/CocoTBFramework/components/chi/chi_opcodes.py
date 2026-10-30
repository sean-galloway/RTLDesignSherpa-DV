# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_opcodes
# Purpose: CHI opcode and field-value encodings (IHI 0050H B13.10)
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI channel opcodes and field encodings, transcribed from IHI 0050H.

Tables: B13.12 (REQ), B13.13 (Atomic sub-opcodes), B13.14 (RSP), B13.15
(SNP), B13.16 (DAT), B13.17 (Size), B13.18 (MemAttr), B13.22 (Order),
B13.33 (RespErr), B13.34/35 (Resp), B13.37 (FwdState), B13.39 (DataID),
B4.1 (cache states). Every reserved value is left out on purpose, so
``ReqOpcode(0x06)`` raises -- a BFM must not encode what the spec does not
name (see the DV handbook's spec-fidelity note).

A REQ opcode is 7 bits: Table B13.12 lists Opcode[5:0] in two columns for
Opcode[6] = 0 and 1, so the second column's values are ``0x40 | low``.
"""

from enum import IntEnum


class ReqOpcode(IntEnum):
    """Table B13.12 REQ channel opcodes (7-bit)."""
    ReqLCrdReturn = 0x00
    ReadShared = 0x01
    ReadClean = 0x02
    ReadOnce = 0x03
    ReadNoSnp = 0x04
    PCrdReturn = 0x05
    ReadUnique = 0x07
    CleanShared = 0x08
    CleanInvalid = 0x09
    MakeInvalid = 0x0A
    CleanUnique = 0x0B
    MakeUnique = 0x0C
    Evict = 0x0D
    CleanInvalidStorage = 0x0E
    ReadNoSnpSep = 0x11
    CleanSharedPersistSep = 0x13
    DVMOp = 0x14
    WriteEvictFull = 0x15
    WriteCleanFull = 0x17
    WriteUniquePtl = 0x18
    WriteUniqueFull = 0x19
    WriteBackPtl = 0x1A
    WriteBackFull = 0x1B
    WriteNoSnpPtl = 0x1C
    WriteNoSnpFull = 0x1D
    WriteUniqueFullStash = 0x20
    WriteUniquePtlStash = 0x21
    StashOnceShared = 0x22
    StashOnceUnique = 0x23
    ReadOnceCleanInvalid = 0x24
    ReadOnceMakeInvalid = 0x25
    ReadNotSharedDirty = 0x26
    CleanSharedPersist = 0x27
    # 0x28-0x2F AtomicStore, 0x30-0x37 AtomicLoad: Opcode[2:0] is the
    # sub-opcode (Table B13.13); see AtomicOp and atomic_opcode()
    AtomicStore = 0x28
    AtomicLoad = 0x30
    AtomicSwap = 0x38
    AtomicCompare = 0x39
    PrefetchTgt = 0x3A
    # Opcode[6] = 1 column
    MakeReadUnique = 0x41
    WriteEvictOrEvict = 0x42
    WriteUniqueZero = 0x43
    WriteNoSnpZero = 0x44
    StashOnceSepShared = 0x47
    StashOnceSepUnique = 0x48
    ReadPreferUnique = 0x4C
    CleanInvalidPoPA = 0x4D
    WriteNoSnpDef = 0x4E
    WriteNoSnpFullCleanSh = 0x50
    WriteNoSnpFullCleanInv = 0x51
    WriteNoSnpFullCleanShPerSep = 0x52
    WriteUniqueFullCleanSh = 0x54
    WriteUniqueFullCleanShPerSep = 0x56
    WriteUniqueFullCleanInvStrg = 0x57
    WriteBackFullCleanSh = 0x58
    WriteBackFullCleanInv = 0x59
    WriteBackFullCleanShPerSep = 0x5A
    WriteBackFullCleanInvStrg = 0x5B
    WriteCleanFullCleanSh = 0x5C
    WriteCleanFullCleanShPerSep = 0x5E
    WriteNoSnpPtlCleanSh = 0x60
    WriteNoSnpPtlCleanInv = 0x61
    WriteNoSnpPtlCleanShPerSep = 0x62
    WriteUniquePtlCleanSh = 0x64
    WriteUniquePtlCleanShPerSep = 0x66
    WriteNoSnpPtlCleanInvPoPA = 0x70
    WriteNoSnpFullCleanInvPoPA = 0x71
    WriteNoSnpFullCleanInvStrg = 0x72
    WriteBackFullCleanInvPoPA = 0x79


class AtomicOp(IntEnum):
    """Table B13.13 sub-opcodes for AtomicStore / AtomicLoad (Opcode[2:0])."""
    ADD = 0
    CLR = 1
    EOR = 2
    SET = 3
    SMAX = 4
    SMIN = 5
    UMAX = 6
    UMIN = 7


def atomic_opcode(base: ReqOpcode, op: AtomicOp) -> int:
    """The 7-bit opcode of an AtomicStore / AtomicLoad with sub-opcode ``op``."""
    if base not in (ReqOpcode.AtomicStore, ReqOpcode.AtomicLoad):
        raise ValueError("only AtomicStore and AtomicLoad carry a sub-opcode (Table B13.13)")
    return int(base) | int(op)


def req_opcode_name(value: int) -> str:
    """Name for any legal 7-bit REQ opcode, including the atomic ranges."""
    v = int(value)
    if 0x28 <= v <= 0x2F:
        return f"AtomicStore.{AtomicOp(v & 7).name}"
    if 0x30 <= v <= 0x37:
        return f"AtomicLoad.{AtomicOp(v & 7).name}"
    return ReqOpcode(v).name


class RspOpcode(IntEnum):
    """Table B13.14 RSP channel opcodes (5-bit). 0x1C-0x1F are C2C."""
    RespLCrdReturn = 0x00
    SnpResp = 0x01
    CompAck = 0x02
    RetryAck = 0x03
    Comp = 0x04
    CompDBIDResp = 0x05
    DBIDResp = 0x06
    PCrdGrant = 0x07
    ReadReceipt = 0x08
    SnpRespFwded = 0x09
    TagMatch = 0x0A
    RespSepData = 0x0B
    Persist = 0x0C
    CompPersist = 0x0D
    DBIDRespOrd = 0x0E
    StashDone = 0x10
    CompStashDone = 0x11
    CompCMO = 0x14


class SnpOpcode(IntEnum):
    """Table B13.15 SNP channel opcodes (5-bit)."""
    SnpLCrdReturn = 0x00
    SnpShared = 0x01
    SnpClean = 0x02
    SnpOnce = 0x03
    SnpNotSharedDirty = 0x04
    SnpUniqueStash = 0x05
    SnpMakeInvalidStash = 0x06
    SnpUnique = 0x07
    SnpCleanShared = 0x08
    SnpCleanInvalid = 0x09
    SnpMakeInvalid = 0x0A
    SnpStashUnique = 0x0B
    SnpStashShared = 0x0C
    SnpDVMOp = 0x0D
    SnpQuery = 0x10
    SnpSharedFwd = 0x11
    SnpCleanFwd = 0x12
    SnpOnceFwd = 0x13
    SnpNotSharedDirtyFwd = 0x14
    SnpPreferUnique = 0x15
    SnpPreferUniqueFwd = 0x16
    SnpUniqueFwd = 0x17


class DatOpcode(IntEnum):
    """Table B13.16 DAT channel opcodes (4-bit). 0xD is C2C."""
    DataLCrdReturn = 0x0
    SnpRespData = 0x1
    CopyBackWriteData = 0x2
    NonCopyBackWriteData = 0x3
    CompData = 0x4
    SnpRespDataPtl = 0x5
    SnpRespDataFwded = 0x6
    WriteDataCancel = 0x7
    DataSepResp = 0xB
    NonCopyBackWriteDataCompAck = 0xC


OPCODE_ENUMS = {'req': ReqOpcode, 'rsp': RspOpcode, 'snp': SnpOpcode, 'dat': DatOpcode}


def opcode_name(channel: str, value: int) -> str:
    """Opcode name on ``channel`` ('req'|'rsp'|'snp'|'dat'), or ``?0xNN``."""
    try:
        return req_opcode_name(value) if channel == 'req' else OPCODE_ENUMS[channel](int(value)).name
    except ValueError:
        return f"?0x{int(value):02X}"


# ---------------------------------------------------------------------------
# Field encodings
# ---------------------------------------------------------------------------
class Size(IntEnum):
    """Table B13.17 Size[2:0] -> bytes = 1 << Size. 0b111 is reserved."""
    B1 = 0
    B2 = 1
    B4 = 2
    B8 = 3
    B16 = 4
    B32 = 5
    B64 = 6

    @property
    def nbytes(self):
        return 1 << int(self)

    @classmethod
    def of(cls, nbytes: int):
        return cls(nbytes.bit_length() - 1) if nbytes in (1, 2, 4, 8, 16, 32, 64) else cls(-1)


class MemAttr(IntEnum):
    """Table B13.18 MemAttr bit positions (OR them)."""
    EWA = 1 << 0
    DEVICE = 1 << 1
    CACHEABLE = 1 << 2
    ALLOCATE = 1 << 3


class Order(IntEnum):
    """Table B13.22 Order[1:0]."""
    NONE = 0b00
    REQ_ACCEPTED = 0b01       # HN-F to SN-F / HN-I to SN-I only
    REQ_ORDER_OWO = 0b10      # RN to HN: Request Order, or OWO when ExpCompAck = 1
    ENDPOINT = 0b11


class RespErr(IntEnum):
    """Table B13.33 RespErr[1:0]."""
    OK = 0b00
    EXOK = 0b01
    DERR = 0b10
    NDERR = 0b11


class CacheState(str):
    """B4.1 cache line states. Plain strings so they print and compare
    naturally; the module-level constants are the vocabulary."""


I, UC, UCE, UD, UDP, SC, SD = 'I', 'UC', 'UCE', 'UD', 'UDP', 'SC', 'SD'  # noqa: E741 (the spec's name)
CACHE_STATES = (I, UC, UCE, UD, UDP, SC, SD)
UNIQUE_STATES = (UC, UCE, UD, UDP)
DIRTY_STATES = (UD, UDP, SD)


class Resp(IntEnum):
    """Table B13.34/35 Resp[2:0]. The name says the message class it is
    legal in; the same encoding reads differently per class (B13.35), so
    use :func:`resp_state` with the message type rather than the enum name
    when decoding."""
    I = 0b000  # noqa: E741
    SC = 0b001
    UC = 0b010          # UC, UD in snoop responses; UC in Comp / WriteData
    SD = 0b011          # snoop responses only
    I_PD = 0b100        # snoop responses
    SC_PD = 0b101       # snoop responses
    UD_PD = 0b110       # Comp / WriteData / CompAck: UD_PD; snoop: UC_PD
    SD_PD = 0b111       # Comp / WriteData / CompAck


# Table B13.35: the state a Resp encoding means, per message class
_RESP_STATE = {
    'snoop': {0: I, 1: SC, 2: UC, 3: SD, 4: 'I_PD', 5: 'SC_PD', 6: 'UC_PD'},
    'comp': {0: I, 1: SC, 2: UC, 6: 'UD_PD', 7: 'SD_PD'},
    'writedata': {0: I, 1: SC, 2: UC, 6: 'UD_PD', 7: 'SD_PD'},
    'compack': {0: I, 1: SC, 2: UC, 6: 'UD_PD', 7: 'SD_PD'},
}


def resp_state(kind: str, resp: int) -> str:
    """Decode Resp[2:0] for a message class: 'snoop' (SnpResp*), 'comp'
    (Comp, CompData, DataSepResp), 'writedata', 'compack'. Raises for a
    reserved encoding (Table B13.35)."""
    table = _RESP_STATE[kind]
    if int(resp) not in table:
        raise ValueError(f"Resp 0b{int(resp):03b} is reserved for {kind} responses (Table B13.35)")
    return table[int(resp)]


def resp_encode(state: str) -> int:
    """Resp[2:0] for a state name such as 'UC', 'I_PD', 'UD_PD'."""
    for table in _RESP_STATE.values():
        for v, name in table.items():
            if name == state:
                return v
    raise ValueError(f"no Resp encoding for state {state!r}")


class FwdState(IntEnum):
    """Table B13.37 FwdState[2:0]."""
    I = 0b000  # noqa: E741
    SC = 0b001
    UC = 0b010
    UD_PD = 0b110
    SD_PD = 0b111


def data_id(addr: int, data_width: int) -> int:
    """B2.9.4: DataID of the packet holding byte ``addr`` for a bus width."""
    if data_width == 128:
        return (addr >> 4) & 0b11
    if data_width == 256:
        return (addr >> 5 & 1) << 1
    return 0


def data_ids_for(size_bytes: int, addr: int, data_width: int):
    """DataIDs of the packets a transfer of ``size_bytes`` at ``addr`` needs,
    in incrementing address order (B2.9.4). A 64-byte transfer on a 128-bit
    bus is 4 packets 0,1,2,3; on 256-bit it is 0,2; on 512-bit it is 0."""
    step = data_width // 8
    if size_bytes <= step:
        return [data_id(addr, data_width)]
    lo = (addr // size_bytes) * size_bytes
    return [data_id(a, data_width) for a in range(lo, lo + size_bytes, step)]


def data_window_lo(line: int, did: int, data_width: int) -> int:
    """Byte address of the first byte of the DW-wide window DataID ``did``
    names within the 64-byte ``line`` (Table B2.16)."""
    line &= ~63
    if data_width == 128:
        return line + did * 16
    if data_width == 256:
        return line + (did >> 1) * 32
    return line


def data_windows(addr: int, nbytes: int, data_width: int):
    """[(DataID, window_lo)] for the packets a transfer of ``nbytes`` at
    ``addr`` needs, in incrementing address order (B2.9.4)."""
    return [(did, data_window_lo(addr, did, data_width)) for did in data_ids_for(nbytes, addr, data_width)]


__all__ = [
    'ReqOpcode', 'RspOpcode', 'SnpOpcode', 'DatOpcode', 'AtomicOp', 'atomic_opcode',
    'req_opcode_name', 'opcode_name', 'OPCODE_ENUMS',
    'Size', 'MemAttr', 'Order', 'RespErr', 'Resp', 'FwdState', 'resp_state', 'resp_encode',
    'I', 'UC', 'UCE', 'UD', 'UDP', 'SC', 'SD', 'CACHE_STATES', 'UNIQUE_STATES', 'DIRTY_STATES',
    'data_id', 'data_ids_for', 'data_window_lo', 'data_windows',
]
