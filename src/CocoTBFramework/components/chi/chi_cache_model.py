# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: chi_cache_model
# Purpose: CHI coherence state models (IHI 0050H B4): the RN-F cache line
#          state machine (B4.7 / B4.8), a precise Home snoop filter (B4.4.2)
#          and the Home response policy read off the same tables
#
# Subsystem: framework
# Author: sean galloway
# Created: 2026-10-30
"""CHI cache-state models, transcribed from IHI 0050H Chapter B4.

Three things live here, all pure Python (no cocotb):

* :class:`RNCache` -- one RN-F's view of its own lines. The Requester
  transitions of Table B4.38 (reads), B4.41/B4.42 (MakeReadUnique), B4.43
  (dataless) and B4.44 (writes), and the Snoopee transitions of Tables B4.46
  to B4.50. Every table is a dict transcribed row by row so a test can
  spot-check a row against the page.
* :class:`SnoopFilter` -- the Home-side precise directory. Table B4.26
  picks the expected (non-forwarding) snoop per request; the B4.4.2 bullets
  decide which sharers need it at all.
* :class:`HomePolicy` -- what an HN-F puts in the Resp field of the Comp /
  CompData it sends back, read from the Requester tables in reverse.

Where a table gives both an *expected* and a *permitted* final state, the
model takes the expected one and records the permitted set beside it
(``*_PERMITTED`` dicts) so a checker can accept a DUT that chose the other
legal answer.

Scope of this release: no forwarding snoops (DCT), no stash, no atomics,
no DVM, no MTE (every TagOp table variant is folded as ``TagOp != Transfer``
/ ``TagOp != Fetch``; see :data:`READ_TRANSITIONS` for where that matters).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .chi_opcodes import (
    DIRTY_STATES,
    SC,
    SD,
    UC,
    UCE,
    UD,
    UDP,
    UNIQUE_STATES,
    DatOpcode,
    I,
    ReqOpcode,
    RspOpcode,
    SnpOpcode,
    resp_encode,
)

LINE_BYTES = 64
LINE_MASK = ~(LINE_BYTES - 1)
FULL_BE = (1 << LINE_BYTES) - 1


def line_addr(addr: int) -> int:
    """The 64-byte line containing ``addr`` (B4.1: coherence granule is 64 B)."""
    return int(addr) & LINE_MASK


@dataclass
class CacheLine:
    """One 64-byte line. ``valid`` is the byte-valid mask, only meaningful in
    UDP (B4.1: UniqueDirtyPartial holds some bytes of the line)."""
    state: str = I
    data: bytearray = field(default_factory=lambda: bytearray(LINE_BYTES))
    valid: int = 0

    @property
    def full(self) -> bool:
        return self.valid == FULL_BE


def _set_valid_for(ln: CacheLine, state: str):
    """Byte-valid mask implied by a state: nothing in I / UCE, every byte in
    the full-line states, whatever was already there in UDP."""
    if state in (I, UCE):
        ln.valid = 0
    elif state != UDP:
        ln.valid = FULL_BE


# ---------------------------------------------------------------------------
# Table B4.38 -- Requester transitions for Read requests
#
# {opcode: {initial_state: {comp_state: final_state}}}
#
# comp_state is the decoded Resp of the CompData / DataSepResp
# (resp_state('comp', ...)): 'I', 'SC', 'UC', 'UD_PD', 'SD_PD'.
#
# TagOp variants are folded: where the spec splits a request into
# "TagOp = Transfer" and "TagOp != Transfer" rows the transitions agree
# wherever both list the initial state, so the union is taken; ReadUnique
# uses the "TagOp != Fetch" rows (TagOp = Fetch would land in UD on
# CompData_UC, which no MTE-less requester does).
# ---------------------------------------------------------------------------
_SC_UC = {SC: SC, UC: UC}
_STAY_UC = {SC: UC, UC: UC}       # footnote b: UC/UCE stays UC on a _SC response
_STAY_UD = {SC: UD, UC: UD}       # footnote c: UD/UDP stays UD on a _SC response
_STAY_SD = {SC: SD, UC: UD}       # footnote d: SD stays SD on _SC, becomes UD on _UC

READ_TRANSITIONS: Dict[ReqOpcode, Dict[str, Dict[str, str]]] = {
    # Non-allocating reads: the Requester ignores the Resp state and assumes I.
    ReqOpcode.ReadNoSnp: {I: {I: I, UC: I}},
    ReqOpcode.ReadOnce: {I: {I: I, UC: I}},
    ReqOpcode.ReadClean: {
        I: dict(_SC_UC),
        UC: dict(_STAY_UC), UCE: dict(_STAY_UC),
        UD: dict(_STAY_UD), UDP: dict(_STAY_UD),
        SC: dict(_SC_UC),
        SD: dict(_STAY_SD),
    },
    ReqOpcode.ReadNotSharedDirty: {
        I: {SC: SC, UC: UC, 'UD_PD': UD},
        UCE: {SC: SC, UC: UC, 'UD_PD': UD},
    },
    ReqOpcode.ReadShared: {
        I: {SC: SC, UC: UC, 'SD_PD': SD, 'UD_PD': UD},
        UCE: {SC: SC, UC: UC, 'SD_PD': SD, 'UD_PD': UD},
    },
    ReqOpcode.ReadUnique: {
        I: {UC: UC, 'UD_PD': UD},
        SC: {UC: UC, 'UD_PD': UD},
        SD: {UC: UD, 'UD_PD': UD},
        # permitted initial states (UC, UCE for the I/SC row; UD, UDP for SD)
        UC: {UC: UC, 'UD_PD': UD},
        UCE: {UC: UC, 'UD_PD': UD},
        UD: {UC: UD, 'UD_PD': UD},
        UDP: {UC: UD, 'UD_PD': UD},
    },
    ReqOpcode.ReadPreferUnique: {
        I: {SC: SC, UC: UC, 'UD_PD': UD},
        UC: dict(_STAY_UC), UCE: dict(_STAY_UC),
        UD: dict(_STAY_UD), UDP: dict(_STAY_UD),
        SC: {SC: SC, UC: UC, 'UD_PD': UD},
        SD: dict(_STAY_SD),
    },
}

# Table B4.38 "Initial permitted state" column, per (opcode, expected initial)
READ_PERMITTED_INITIAL = {
    (ReqOpcode.ReadUnique, I): (UC, UCE),
    (ReqOpcode.ReadUnique, SC): (UC, UCE),
    (ReqOpcode.ReadUnique, SD): (UD, UDP),
}

# Table B4.41 (non-Excl and Excl) and B4.42 (Excl only) -- MakeReadUnique.
# Keyed by the state at the time the response is received, which is what
# decides the final state (B4.7.1.1.3), not the state at issue.
# {state_at_response: {comp_state: final}}; I/UC/UD are "Not permitted".
MAKE_READ_UNIQUE_TRANSITIONS: Dict[str, Dict[str, str]] = {
    SD: {UC: UD, SC: SD},                 # Comp_UC / CompData_UC -> UD; Comp_SC (Excl) -> SD
    SC: {UC: UC, 'UD_PD': UD, SC: SC},    # Comp_SC / CompData_SC only for Excl
    I: {UC: UC, 'UD_PD': UD, SC: SC},     # line lost to an invalidating snoop; data arrives
}

# ---------------------------------------------------------------------------
# Table B4.43 -- Requester transitions for Dataless requests
# {opcode: {initial: final}}. Comp is Comp_UC for CleanUnique / MakeUnique,
# Comp_I for Evict / CleanInvalid / MakeInvalid, and any of Comp_UC / _SC /
# _I for CleanShared, which the Requester ignores ("No Change").
# ---------------------------------------------------------------------------
DATALESS_TRANSITIONS: Dict[ReqOpcode, Dict[str, str]] = {
    ReqOpcode.CleanUnique: {I: UCE, SC: UC, SD: UD,
                            # permitted initial UC / UCE: already unique, keep what is held
                            UC: UC, UCE: UCE},
    ReqOpcode.MakeUnique: {I: UD, SC: UD, SD: UD, UC: UD, UCE: UD},
    ReqOpcode.Evict: {I: I},
    ReqOpcode.CleanShared: {I: I, SC: SC, UC: UC},
    ReqOpcode.CleanInvalid: {I: I},
    ReqOpcode.MakeInvalid: {I: I},
}
DATALESS_PERMITTED_INITIAL = {
    ReqOpcode.CleanUnique: (UC, UCE),
    ReqOpcode.MakeUnique: (UC, UCE),
}
# B4.7.2: before CleanInvalid / Evict the line may be UC, UCE or SC, and
# before MakeInvalid any state, but it MUST be moved to I before issue.
DATALESS_REQUIRES_I = (ReqOpcode.Evict, ReqOpcode.CleanInvalid, ReqOpcode.MakeInvalid)

# ---------------------------------------------------------------------------
# Table B4.44 -- Requester transitions for Write requests
# {opcode: {state_before_writedata: (writedata_resp_state, final_state)}}
# The same Resp suffix rides CompAck when Home chose Comp (footnote b).
# Where the table lists two legal WriteData responses (WriteCleanFull from
# UC: _UC or _I) the first listed is taken; the alternative is recorded in
# WRITE_PERMITTED_RESP.
# ---------------------------------------------------------------------------
WRITE_TRANSITIONS: Dict[ReqOpcode, Dict[str, Tuple[str, str]]] = {
    ReqOpcode.WriteNoSnpPtl: {I: (I, I)},
    ReqOpcode.WriteNoSnpFull: {I: (I, I)},
    ReqOpcode.WriteUniquePtl: {I: (I, I)},
    ReqOpcode.WriteUniqueFull: {I: (I, I)},
    ReqOpcode.WriteBackFull: {UD: ('UD_PD', I), UC: (UC, I), SD: ('SD_PD', I), SC: (SC, I), I: (I, I)},
    ReqOpcode.WriteBackPtl: {UDP: ('UD_PD', I), I: (I, I)},
    ReqOpcode.WriteCleanFull: {UD: ('UD_PD', UC), UC: (UC, UC), SD: ('SD_PD', SC), SC: (SC, SC), I: (I, I)},
    ReqOpcode.WriteEvictFull: {UC: (UC, I), SC: (SC, I), I: (I, I)},
    ReqOpcode.WriteEvictOrEvict: {UC: (UC, I), SC: (SC, I), I: (I, I)},
}
WRITE_PERMITTED_RESP = {
    (ReqOpcode.WriteCleanFull, UC): (UC, I),
    (ReqOpcode.WriteCleanFull, SC): (SC, I),
}
# Table B4.44 "Initial state at Requester" column
WRITE_INITIAL_STATES = {
    ReqOpcode.WriteBackFull: (UD, SD),
    ReqOpcode.WriteBackPtl: (UDP,),
    ReqOpcode.WriteCleanFull: (UD, SD),
    ReqOpcode.WriteEvictFull: (UC,),
    ReqOpcode.WriteEvictOrEvict: (UC, SC),
}
# Footnote b: Comp (no data) is an option for every CopyBack except
# WriteBackPtl, whose rows list only CompDBIDResp.
COPYBACK_COMP_ALLOWED = (ReqOpcode.WriteBackFull, ReqOpcode.WriteCleanFull,
                         ReqOpcode.WriteEvictFull, ReqOpcode.WriteEvictOrEvict)

# ---------------------------------------------------------------------------
# Tables B4.46 to B4.50 -- Snoopee transitions.
#
# Row = (final_expected, final_permitted, data_rule, resp_suffix)
#   data_rule: 'none'   -> SnpResp (no data)
#              'data'   -> SnpRespData always (dirty data must go to Home)
#              'ptl'    -> SnpRespDataPtl (UDP)
#              'rts'    -> SnpRespData only when RetToSrc = 1, else SnpResp
#                          (B4.1: a clean line is required NOT to return data
#                          when RetToSrc is 0 and recommended to when it is 1;
#                          the table marks these rows X or lists both forms)
#   resp_suffix: the spec's response suffix, e.g. 'SC_PD', 'UD' (SnpRespData_UD
#                encodes as Resp 0b010, the 'UC' encoding -- Table B4.33 note)
# ---------------------------------------------------------------------------
_SNP_ONCE = {                                                   # Table B4.46
    I: (I, (), 'none', I),
    UC: (UC, (I, SC), 'rts', UC),
    UCE: (UCE, (I,), 'none', UC),
    UD: (UD, (SD,), 'data', UD),
    UDP: (I, (), 'ptl', 'I_PD'),
    SC: (SC, (I,), 'rts', SC),
    SD: (SD, (), 'data', SD),
}
_SNP_SHARED = {                                                 # Table B4.47
    I: (I, (), 'none', I),
    UC: (SC, (I,), 'rts', SC),
    UCE: (I, (), 'none', I),
    UD: (SD, (), 'data', SD),           # footnote b: not when DoNotGoToSD
    UDP: (I, (), 'ptl', 'I_PD'),
    SC: (SC, (I,), 'rts', SC),
    SD: (SD, (), 'data', SD),           # footnote b
}
# Table B4.47 footnote b: with DoNotGoToSD the UD / SD rows fall to the
# permitted SC row, SnpRespData_SC_PD.
_SNP_SHARED_NO_SD = {UD: (SC, (I,), 'data', 'SC_PD'), SD: (SC, (I,), 'data', 'SC_PD')}
_SNP_UNIQUE = {                                                 # Table B4.48
    I: (I, (), 'none', I),
    UC: (I, (), 'rts', I),
    UCE: (I, (), 'none', I),
    UD: (I, (), 'data', 'I_PD'),
    UDP: (I, (), 'ptl', 'I_PD'),
    SC: (I, (), 'rts', I),
    SD: (I, (), 'data', 'I_PD'),
}
_SNP_CLEAN_SHARED = {                                           # Table B4.49
    I: (I, (), 'none', I),
    UC: (UC, (I, SC), 'none', UC),
    UCE: (I, (), 'none', I),
    UD: (UC, (I, SC), 'data', 'UC_PD'),
    UDP: (I, (), 'ptl', 'I_PD'),
    SC: (SC, (I,), 'none', SC),
    SD: (SC, (I,), 'data', 'SC_PD'),
}
_SNP_CLEAN_INVALID = {                                          # Table B4.49
    I: (I, (), 'none', I),
    UC: (I, (), 'none', I),
    UCE: (I, (), 'none', I),
    UD: (I, (), 'data', 'I_PD'),
    UDP: (I, (), 'ptl', 'I_PD'),
    SC: (I, (), 'none', I),
    SD: (I, (), 'data', 'I_PD'),
}
_SNP_MAKE_INVALID = {s: (I, (), 'none', I) for s in (I, UC, UCE, UD, UDP, SC, SD)}   # Table B4.49
_SNP_QUERY = {                                                  # Table B4.50
    I: (I, (), 'none', I),
    UC: (UC, (), 'none', UC),
    UCE: (UCE, (), 'none', UC),
    UD: (UD, (), 'none', UD),
    UDP: (UDP, (), 'none', UD),
    SC: (SC, (), 'none', SC),
    SD: (SD, (), 'none', SD),
}

SNOOP_TRANSITIONS: Dict[SnpOpcode, Dict[str, tuple]] = {
    SnpOpcode.SnpOnce: _SNP_ONCE,
    SnpOpcode.SnpClean: _SNP_SHARED,
    SnpOpcode.SnpShared: _SNP_SHARED,
    SnpOpcode.SnpNotSharedDirty: _SNP_SHARED,
    # B4.8.1.3: a Snoopee not mid-Exclusive is recommended to use Table B4.48
    SnpOpcode.SnpPreferUnique: _SNP_UNIQUE,
    SnpOpcode.SnpUnique: _SNP_UNIQUE,
    SnpOpcode.SnpCleanShared: _SNP_CLEAN_SHARED,
    SnpOpcode.SnpCleanInvalid: _SNP_CLEAN_INVALID,
    SnpOpcode.SnpMakeInvalid: _SNP_MAKE_INVALID,
    SnpOpcode.SnpQuery: _SNP_QUERY,
}
# Table B4.47 footnote b applies to the snoops that use that table
_DONOTGOTOSD_SNOOPS = (SnpOpcode.SnpClean, SnpOpcode.SnpShared, SnpOpcode.SnpNotSharedDirty)
# B13.10.34: RetToSrc is inapplicable (must be 0) in these
RETTOSRC_INAPPLICABLE = (SnpOpcode.SnpCleanShared, SnpOpcode.SnpCleanInvalid,
                         SnpOpcode.SnpMakeInvalid, SnpOpcode.SnpQuery)

# Table B4.31 / B4.33: SnpResp_UD and SnpRespData_UD use the UC encoding
_SNOOP_RESP_ENCODING_ALIAS = {UD: UC}


def snoop_resp_encode(resp_state: str) -> int:
    """Resp[2:0] for a snoop-response suffix (Tables B4.31 / B4.33)."""
    return resp_encode(_SNOOP_RESP_ENCODING_ALIAS.get(resp_state, resp_state))


@dataclass
class SnoopResponse:
    """What the Snoopee sends back (B4.5.3). ``with_data`` False -> SnpResp on
    RSP; True and ``partial`` -> SnpRespDataPtl, else SnpRespData on DAT.
    ``be`` is the 64-byte mask of the bytes carried (all ones for a full
    line, the UDP valid mask for partial)."""
    with_data: bool
    partial: bool
    resp_state: str
    final_state: str
    data: Optional[bytes]
    be: int
    permitted_final: Tuple[str, ...] = ()

    @property
    def opcode(self):
        if not self.with_data:
            return RspOpcode.SnpResp
        return DatOpcode.SnpRespDataPtl if self.partial else DatOpcode.SnpRespData

    @property
    def resp(self) -> int:
        return snoop_resp_encode(self.resp_state)

    @property
    def name(self) -> str:
        return f"{self.opcode.name}_{self.resp_state}"

    @property
    def pass_dirty(self) -> bool:
        return self.resp_state.endswith('_PD')


class RNCache:
    """One RN-F's cache state per 64-byte line (B4.1 states), with the
    transitions of B4.7 (as Requester) and B4.8 (as Snoopee).

    ``states`` is the subset the cache implements (B4.1: "A cache is
    permitted to implement a subset of these states"); a transition that
    lands outside it is an error, which is how a DUT that does not do UCE
    or SD is caught instead of silently modelled.
    """

    def __init__(self, states=(I, UC, UCE, UD, UDP, SC, SD)):
        if I not in states:
            raise ValueError("a cache must implement the I state")
        self.states = tuple(states)
        self.lines: Dict[int, CacheLine] = {}

    # -- line access --------------------------------------------------------
    def line(self, addr: int) -> CacheLine:
        return self.lines.setdefault(line_addr(addr), CacheLine())

    def state(self, addr: int) -> str:
        ln = self.lines.get(line_addr(addr))
        return ln.state if ln is not None else I

    def set_state(self, addr: int, state: str, data=None, valid=None) -> CacheLine:
        if state not in self.states:
            raise ValueError(f"state {state!r} is not implemented by this cache ({self.states})")
        ln = self.line(addr)
        ln.state = state
        if data is not None:
            if len(data) != LINE_BYTES:
                raise ValueError(f"line data must be {LINE_BYTES} bytes, got {len(data)}")
            ln.data = bytearray(data)
        if valid is not None:
            ln.valid = int(valid) & FULL_BE
        else:
            _set_valid_for(ln, state)
        return ln

    def read_hit_ok(self, addr: int) -> bool:
        """Data is valid locally: UC, UD, SC, SD; UDP only if every byte is."""
        st = self.state(addr)
        if st in (UC, UD, SC, SD):
            return True
        return st == UDP and self.line(addr).full

    def can_write_silently(self, addr: int) -> bool:
        """B4.1: a Unique line may be modified without a transaction."""
        return self.state(addr) in UNIQUE_STATES

    def write_bytes(self, addr: int, payload: bytes, be: Optional[int] = None):
        """Local store into a Unique line: UC -> UD, UCE/UDP -> UDP (or UD
        once full). Raises when the line is not Unique."""
        st = self.state(addr)
        if st not in UNIQUE_STATES:
            raise ValueError(f"cannot write silently in state {st}; obtain Unique first (B4.1)")
        ln = self.line(addr)
        off = addr - line_addr(addr)
        mask = FULL_BE if be is None else int(be)
        for i, b in enumerate(payload):
            if mask >> i & 1:
                ln.data[off + i] = b
                ln.valid |= 1 << (off + i)
        if st in (UC, UD):
            ln.state = UD
        else:
            ln.state = UD if ln.full else UDP
        self._check(ln.state)
        return ln

    def _check(self, state: str) -> str:
        if state not in self.states:
            raise ValueError(f"transition to {state!r}, which this cache does not implement ({self.states})")
        return state

    # -- B4.7.1 reads -------------------------------------------------------
    def complete_read(self, opcode: ReqOpcode, addr: int, comp_state: str, data: Optional[bytes]) -> str:
        """Apply Table B4.38 (B4.41/42 for MakeReadUnique) for the Comp /
        CompData state ``comp_state`` (decoded with ``resp_state('comp', ..)``)
        and the returned line ``data`` (64 bytes, or None for a Comp).

        Footnotes b/c/d (stay in UC / UD / SD on a _SC response) are rows of
        the table; footnote e (drop memory data when UD / SD, merge when UDP)
        is applied to the line payload here. Returns the final state."""
        opcode = ReqOpcode(opcode)
        before = self.state(addr)
        if opcode == ReqOpcode.MakeReadUnique:
            rows = MAKE_READ_UNIQUE_TRANSITIONS.get(before)
            if rows is None:
                raise ValueError(f"MakeReadUnique with the line in {before} is not permitted (Table B4.41)")
        else:
            table = READ_TRANSITIONS.get(opcode)
            if table is None:
                raise ValueError(f"{opcode.name} is not a Read request in this model")
            rows = table.get(before)
            if rows is None:
                raise ValueError(f"{opcode.name} from initial state {before} is not in Table B4.38")
        final = rows.get(comp_state)
        if final is None:
            raise ValueError(f"{opcode.name} from {before}: response state {comp_state} is not permitted "
                             f"(Table B4.38 lists {sorted(rows)})")
        self._check(final)
        ln = self.line(addr)
        if data is not None:
            self._apply_read_data(ln, before, data)
        ln.state = final
        _set_valid_for(ln, final)
        return final

    @staticmethod
    def _apply_read_data(ln: CacheLine, before: str, data: bytes):
        """Table B4.38 footnote e / B4.7.1.1.3: UD and SD keep their own copy,
        UDP merges the valid bytes over the memory data, SC/UC must match."""
        if len(data) != LINE_BYTES:
            raise ValueError(f"read data must be a {LINE_BYTES}-byte line, got {len(data)}")
        if before in (UD, SD):
            return
        if before == UDP:
            merged = bytearray(data)
            for i in range(LINE_BYTES):
                if ln.valid >> i & 1:
                    merged[i] = ln.data[i]
            ln.data = merged
            return
        ln.data = bytearray(data)

    # -- B4.7.2 dataless ----------------------------------------------------
    def complete_dataless(self, opcode: ReqOpcode, addr: int, comp_state: str) -> str:
        """Apply Table B4.43. ``comp_state`` is checked against the Comp the
        table lists for that request; the final state does not depend on it."""
        opcode = ReqOpcode(opcode)
        table = DATALESS_TRANSITIONS.get(opcode)
        if table is None:
            raise ValueError(f"{opcode.name} is not a Dataless request in this model")
        before = self.state(addr)
        if before not in table:
            raise ValueError(f"{opcode.name} from initial state {before} is not in Table B4.43")
        expect = {ReqOpcode.CleanUnique: (UC,), ReqOpcode.MakeUnique: (UC,),
                  ReqOpcode.CleanShared: (UC, SC, I)}.get(opcode, (I,))
        if comp_state not in expect:
            raise ValueError(f"{opcode.name}: Comp_{comp_state} is not a Table B4.43 response (expected one of {expect})")
        final = self._check(table[before])
        ln = self.line(addr)
        ln.state = final
        _set_valid_for(ln, final)
        return final

    # -- B4.7.3 writes ------------------------------------------------------
    def _write_row(self, opcode: ReqOpcode, addr: int) -> Tuple[str, str]:
        opcode = ReqOpcode(opcode)
        table = WRITE_TRANSITIONS.get(opcode)
        if table is None:
            raise ValueError(f"{opcode.name} is not a Write request in this model")
        st = self.state(addr)
        row = table.get(st)
        if row is None:
            raise ValueError(f"{opcode.name} with the line in {st} is not in Table B4.44")
        return row

    def writedata_resp(self, opcode: ReqOpcode, addr: int) -> Tuple[str, str]:
        """Table B4.44: the WriteData Resp suffix to send for a CopyBack given
        the state at the time the data is sent, and the final state.
        Returns ``(resp_state, final_state)``, e.g. ``('UD_PD', 'I')``."""
        return self._write_row(opcode, addr)

    def compack_resp(self, opcode: ReqOpcode, addr: int) -> Tuple[str, str]:
        """Table B4.44 footnote b: Home sent Comp (no data wanted); the
        CompAck carries the same suffix the WriteData would have."""
        opcode = ReqOpcode(opcode)
        if opcode not in COPYBACK_COMP_ALLOWED:
            raise ValueError(f"Table B4.44 lists no Comp-only completion for {opcode.name}")
        return self._write_row(opcode, addr)

    def complete_write(self, opcode: ReqOpcode, addr: int, final: str) -> None:
        """Move the line to ``final`` once the WriteData / CompAck has gone."""
        self._check(final)
        ln = self.line(addr)
        ln.state = final
        _set_valid_for(ln, final)

    # -- B4.8.1 snoops ------------------------------------------------------
    def on_snoop(self, opcode: SnpOpcode, addr: int, rettosrc: int = 0, donotgotosd: int = 0) -> SnoopResponse:
        """Tables B4.46 to B4.50: apply the EXPECTED transition and return the
        response to send. ``rettosrc`` decides data on the clean rows the
        table marks X (B4.1); ``donotgotosd`` applies Table B4.47 footnote b."""
        opcode = SnpOpcode(opcode)
        table = SNOOP_TRANSITIONS.get(opcode)
        if table is None:
            raise ValueError(f"{opcode.name} is not modelled (non-forwarding, non-stash snoops only)")
        if rettosrc and opcode in RETTOSRC_INAPPLICABLE:
            raise ValueError(f"RetToSrc must be 0 in {opcode.name} (B13.10.34)")
        st = self.state(addr)
        row = table[st]
        if donotgotosd and opcode in _DONOTGOTOSD_SNOOPS and st in _SNP_SHARED_NO_SD:
            row = _SNP_SHARED_NO_SD[st]
        final, permitted, rule, suffix = row
        ln = self.line(addr)
        with_data = rule == 'data' or rule == 'ptl' or (rule == 'rts' and bool(rettosrc))
        partial = rule == 'ptl'
        data = bytes(ln.data) if with_data else None
        be = (ln.valid if partial else FULL_BE) if with_data else 0
        self._check(final)
        ln.state = final
        _set_valid_for(ln, final)
        return SnoopResponse(with_data=with_data, partial=partial, resp_state=suffix,
                             final_state=final, data=data, be=be, permitted_final=tuple(permitted))


# ---------------------------------------------------------------------------
# Home side
# ---------------------------------------------------------------------------
# Table B4.26 expected snoop per request, non-forwarding form. A callable
# takes the sharer's state and returns the snoop or None for "nothing
# needed" (B4.4.2: the interconnect does not snoop a line already in the
# required state).
def _needs_downgrade(state: str):
    """A read that wants a Shared copy: Unique holders must drop to Shared,
    a dirty holder must supply the data; SC holders need nothing."""
    return state in UNIQUE_STATES or state in DIRTY_STATES


def _dirty_only(snoop):
    return lambda state: snoop if state in DIRTY_STATES else None


def _all_valid(snoop):
    return lambda state: snoop if state != I else None


def _invalidate_clean_or_dirty(clean_snoop, dirty_snoop):
    """B4.4.2: SnpMakeInvalid only when the Snoopee holds no dirty data."""
    return lambda state: None if state == I else (dirty_snoop if state in DIRTY_STATES else clean_snoop)


EXPECTED_SNOOP = {
    ReqOpcode.ReadNoSnp: lambda state: None,
    ReqOpcode.ReadOnce: _dirty_only(SnpOpcode.SnpOnce),
    ReqOpcode.ReadClean: lambda s: SnpOpcode.SnpClean if _needs_downgrade(s) else None,
    ReqOpcode.ReadNotSharedDirty: lambda s: SnpOpcode.SnpNotSharedDirty if _needs_downgrade(s) else None,
    ReqOpcode.ReadShared: lambda s: SnpOpcode.SnpShared if _needs_downgrade(s) else None,
    ReqOpcode.ReadUnique: _all_valid(SnpOpcode.SnpUnique),
    ReqOpcode.ReadPreferUnique: _all_valid(SnpOpcode.SnpPreferUnique),
    ReqOpcode.MakeReadUnique: _all_valid(SnpOpcode.SnpCleanInvalid),
    ReqOpcode.CleanUnique: _all_valid(SnpOpcode.SnpCleanInvalid),
    ReqOpcode.MakeUnique: _invalidate_clean_or_dirty(SnpOpcode.SnpMakeInvalid, SnpOpcode.SnpCleanInvalid),
    ReqOpcode.Evict: lambda state: None,
    ReqOpcode.CleanShared: _dirty_only(SnpOpcode.SnpCleanShared),
    ReqOpcode.CleanInvalid: _all_valid(SnpOpcode.SnpCleanInvalid),
    ReqOpcode.MakeInvalid: _invalidate_clean_or_dirty(SnpOpcode.SnpMakeInvalid, SnpOpcode.SnpCleanInvalid),
    ReqOpcode.WriteNoSnpPtl: lambda state: None,
    ReqOpcode.WriteNoSnpFull: lambda state: None,
    ReqOpcode.WriteUniquePtl: _all_valid(SnpOpcode.SnpCleanInvalid),
    ReqOpcode.WriteUniqueFull: _invalidate_clean_or_dirty(SnpOpcode.SnpMakeInvalid, SnpOpcode.SnpCleanInvalid),
    ReqOpcode.WriteBackFull: lambda state: None,
    ReqOpcode.WriteBackPtl: lambda state: None,
    ReqOpcode.WriteCleanFull: lambda state: None,
    ReqOpcode.WriteEvictFull: lambda state: None,
    ReqOpcode.WriteEvictOrEvict: lambda state: None,
    ReqOpcode.PCrdReturn: lambda state: None,
}


class SnoopFilter:
    """Home-side precise directory: per line, ``{rn_id: state}``. Table B4.26
    chooses the snoop; the B4.4.2 bullets filter out sharers already in the
    state the request needs."""

    def __init__(self):
        self.dir: Dict[int, Dict[int, str]] = {}

    def sharers(self, addr: int) -> Dict[int, str]:
        return dict(self.dir.get(line_addr(addr), {}))

    def _set(self, rn_id: int, addr: int, state: str):
        entry = self.dir.setdefault(line_addr(addr), {})
        if state == I:
            entry.pop(rn_id, None)
            if not entry:
                self.dir.pop(line_addr(addr), None)
        else:
            entry[rn_id] = state

    def snoops_for(self, opcode: ReqOpcode, addr: int, requester: int) -> List[Tuple[int, SnpOpcode]]:
        """The expected snoop (Table B4.26, non-forwarding) for every OTHER
        RN whose copy the request must change; sorted by RN for determinism."""
        chooser = EXPECTED_SNOOP.get(ReqOpcode(opcode))
        if chooser is None:
            raise ValueError(f"{ReqOpcode(opcode).name} is outside this model's request set")
        out = []
        for rn, state in sorted(self.sharers(addr).items()):
            if rn == requester:
                continue
            snoop = chooser(state)
            if snoop is not None:
                out.append((rn, snoop))
        return out

    def on_snoop_response(self, rn_id: int, addr: int, final_state: str):
        """Record the Snoopee's final state (B4.5.3: Resp gives the state
        after the response is sent). UD in a snoop response is the UC encoding;
        the caller passes the decoded state name."""
        self._set(rn_id, addr, final_state)

    def on_complete(self, rn_id: int, addr: int, final_state: str):
        """Record the Requester's final state after its own request. Table
        B4.38 footnotes b/c/d: a _SC response to a UC/UD/SD holder does not
        downgrade it, so the caller passes the RN's real final state."""
        self._set(rn_id, addr, final_state)

    def dirty_holder(self, addr: int) -> Optional[int]:
        for rn, state in sorted(self.sharers(addr).items()):
            if state in DIRTY_STATES:
                return rn
        return None


@dataclass
class HomeDecision:
    """Home's answer: the Resp suffix for the Comp / CompData, where the data
    comes from, and whether dirty data handed to Home must reach memory."""
    rsp_state: str
    data_from: Optional[str]      # 'memory' | 'snoop' | None
    needs_writeback: bool = False


class HomePolicy:
    """What an HN-F answers a request with, given its snoop filter and the
    snoop results (B4.7 tables read from the Home side)."""

    @staticmethod
    def read_response_state(opcode: ReqOpcode, requester_state_before: str,
                            other_sharers_after: bool, dirty_passed: bool) -> str:
        """Resp suffix of CompData / DataSepResp (Table B4.38 column 5).

        ``dirty_passed``: a snoop response carried _PD, so Home now owns
        dirty data it may pass on. ``other_sharers_after``: some other RN
        still holds the line once the snoops are done."""
        opcode = ReqOpcode(opcode)
        if opcode in (ReqOpcode.ReadNoSnp, ReqOpcode.ReadOnce):
            return I          # Requester ignores it; CompData_I is listed
        if opcode == ReqOpcode.ReadClean:
            return SC if other_sharers_after else UC
        if opcode == ReqOpcode.ReadNotSharedDirty:
            if other_sharers_after:
                return SC
            return 'UD_PD' if dirty_passed else UC
        if opcode == ReqOpcode.ReadShared:
            if other_sharers_after:
                return 'SD_PD' if dirty_passed else SC
            return 'UD_PD' if dirty_passed else UC
        if opcode == ReqOpcode.ReadPreferUnique:
            if other_sharers_after:
                return SC     # no SD_PD row for ReadPreferUnique; Home keeps the dirty data
            return 'UD_PD' if dirty_passed else UC
        if opcode in (ReqOpcode.ReadUnique, ReqOpcode.MakeReadUnique):
            return 'UD_PD' if dirty_passed else UC
        raise ValueError(f"{opcode.name} is not a Read request")

    @staticmethod
    def decide_read(opcode: ReqOpcode, requester_state_before: str,
                    other_sharers_after: bool, dirty_passed: bool, snoop_gave_data: bool) -> HomeDecision:
        state = HomePolicy.read_response_state(opcode, requester_state_before, other_sharers_after, dirty_passed)
        data_from = None
        if ReqOpcode(opcode) != ReqOpcode.MakeReadUnique or requester_state_before == I:
            data_from = 'snoop' if snoop_gave_data else 'memory'
        return HomeDecision(rsp_state=state, data_from=data_from,
                            needs_writeback=dirty_passed and not state.endswith('_PD'))

    @staticmethod
    def dataless_response_state(opcode: ReqOpcode, requester_state: str = I) -> str:
        """Resp suffix of the Comp (Table B4.43 last column)."""
        opcode = ReqOpcode(opcode)
        if opcode in (ReqOpcode.CleanUnique, ReqOpcode.MakeUnique):
            return UC
        if opcode in (ReqOpcode.Evict, ReqOpcode.CleanInvalid, ReqOpcode.MakeInvalid):
            return I
        if opcode == ReqOpcode.CleanShared:
            return requester_state if requester_state in (UC, SC) else I
        raise ValueError(f"{opcode.name} is not a Dataless request")


__all__ = [
    'LINE_BYTES', 'FULL_BE', 'line_addr', 'CacheLine', 'RNCache', 'SnoopResponse', 'snoop_resp_encode',
    'SnoopFilter', 'HomeDecision', 'HomePolicy',
    'READ_TRANSITIONS', 'READ_PERMITTED_INITIAL', 'MAKE_READ_UNIQUE_TRANSITIONS',
    'DATALESS_TRANSITIONS', 'DATALESS_PERMITTED_INITIAL', 'DATALESS_REQUIRES_I',
    'WRITE_TRANSITIONS', 'WRITE_PERMITTED_RESP', 'WRITE_INITIAL_STATES', 'COPYBACK_COMP_ALLOWED',
    'SNOOP_TRANSITIONS', 'RETTOSRC_INAPPLICABLE', 'EXPECTED_SNOOP',
]
