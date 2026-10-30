<!-- RTL Design Sherpa Documentation Header -->
<table>
<tr>
<td width="80">
  <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">
    <img src="https://raw.githubusercontent.com/sean-galloway/RTLDesignSherpa/main/docs/logos/Logo_200px.png" alt="RTL Design Sherpa" width="70">
  </a>
</td>
<td>
  <strong>CocoTB Framework</strong> · <em>Verification Infrastructure for RTL Testing</em><br>
  <sub>
    <a href="https://github.com/sean-galloway/RTLDesignSherpa-DV">GitHub</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/docs/DOCUMENTATION_INDEX.md">Documentation Index</a> ·
    <a href="https://github.com/sean-galloway/RTLDesignSherpa/blob/main/LICENSE">MIT License</a>
  </sub>
</td>
</tr>
</table>

---

<!-- End Header -->

# CHI Protocol Models

Three layers of pure Python (no cocotb) that the BFMs step: the link layer of chapter B14, the transaction flows of chapter B2, and the cache-state tables of chapter B4. Each is unit-tested on its own; the BFMs on the overview page only move flits between them and the wires.

## Link Layer (B14)

Every model is a per-cycle state machine with a `step()`, a `reset()` (B14.1.3: every output deasserted), `stats`, and where it checks something a `violations` dict. Credits are per channel (B14.5.1.3); the LINKACTIVE pair is per direction and its rules apply across every channel of that direction.

| Class | Role |
|---|---|
| `LCreditTx` | Transmitter pool for one channel. `on_lcrdv()` records this cycle's `LCRDV` into `pending`; `tick()` moves `pending` into `credits` at the start of the next cycle; `spend()` pays for one flit, protocol or LCrdReturn alike (B13.11: every flit costs one). A pool above `max_credit` counts `credit_overflow` and is not clamped, so the excess stays visible. `held` is usable plus pending. |
| `LCreditRx` | Receiver bookkeeping, slot-backed: "a Receiver must be able to accept every flit it has granted", so `grant_ok()` is `outstanding < max_credit and buffered + outstanding < buffer_depth`. `on_flit()` takes one outstanding credit back and, for a protocol flit, occupies a slot until the consumer `drain()`s it; an LCrdReturn takes no slot. `FLITV` with nothing outstanding counts `valid_without_credit`. |
| `TxChannel` | A queue of flits, an `LCreditTx`, and `FLITPEND` one cycle ahead (B14.4). `step(run, deactivating, lcrdv, pend=None)` returns `(flitpend, flitv, flit)`: `flitv` only if the previous step drove `flitpend`; in RUN with a credit and a queued flit the flit goes; in DEACTIVATE with a credit held an LCrdReturn goes instead (`flit` is the `LCRD_RETURN` sentinel) and credits arriving meanwhile are accepted and returned too (Table B14.2); in STOP or ACTIVATE nothing is sent but credits are still accepted. `pend_mode='exact'` asserts FLITPEND only while something could go next cycle, `'always'` holds it high; `pend=` scripts one cycle. `credit_count` is Figure B14.1's "Credit count" row. |
| `RxChannel` | Grants one credit per cycle in RUN while `LCreditRx` has a slot, spaced by `grant_gap`; the modelled buffer drains one protocol flit per cycle, each held `drain_gap` extra cycles. `step(run, flitv, is_lcrd_return)` returns `LCRDV`. Credits are sent in RUN only (Table B14.3). |
| `TxLink` | `LINKACTIVEREQ` for the TX direction. `auto=True` raises REQ when there is work and drops it after `idle_deactivate` idle RUN cycles (`None` = never on idleness); `want(True/False)` moves it by hand. Either way it follows the remote (B14.6): activates when the RX link is activated by the other side, deactivates when the other side's TX link deactivates once its queues are empty, and holds a link it did not initiate for the remote. B14.5: REQ never rises while the remote ACK is high and never falls while it is low. B14.6.3.4 against the local RX link: REQ does not rise before the local ACK has fallen and does not fall before it has risen. `ack_drop_with_credits` counts a remote ACK falling while credits were still held (Table B14.3). |
| `RxLink` | `LINKACTIVEACK` for the RX direction. ACK rises `ack_delay()` cycles after REQ is seen high (`enable=False` never acknowledges) and falls only when REQ is low **and** every credit of every RX channel has come back (Table B14.3). With `tx_req` given, the B14.6.3.4 ordering is applied: ACK neither rises before TXREQ has risen nor falls before it has fallen, same cycle allowed. |
| `SActive` | `TXSACTIVE` bookkeeping (B14.7): `begin()` / `end()` count open transactions, `step()` returns the value, asserted before or with the first flit and held until after the last. Available standalone; `CHIPort` computes TXSACTIVE through its `_sactive()` hook instead. |
| `LinkChecker` | The passive checker a monitor feeds once per cycle: `check(txreq, txack, rxreq, rxack, flits, lcrdv)` with `flits[key] = (flitpend_of_previous_cycle, flitv, is_lcrd_return)` and `lcrdv[key]` this cycle's grant. Keys are direction-qualified (`'txreq'`, `'rxdat'`) because an RN-F both sends and receives on RSP and DAT; a bare name works when unambiguous. `credits[key]` and `max_credits[key]` are the modelled transmitter count and its peak. The kinds it counts are the `link.*` rows of the overview's monitor table; `deactivate_credit_grace` (default 1) is how many cycles of DEACTIVATE may still carry an `LCRDV`. Messages are kept up to `MAX_MESSAGES` = 1000. |

`link_state(req, ack)` is Table B14.1: (0,0) STOP, (1,0) ACTIVATE, (1,1) RUN, (0,1) DEACTIVATE.

### Figure B14.1

`tests/unit/test_chi_link.py::test_figure_b14_1_exactly` steps one `TxChannel` with the figure's `LCRDV` and `FLITPEND` and checks the flits go in cycles 2, 5, 6 and 8 with the credit counter reading as drawn. A credit seen in cycle 1 is first usable in cycle 2; cycle 7 has a credit but no FLITPEND in cycle 6, so nothing goes.

| Cycle | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| LCRDV | 0 | 1 | 0 | 1 | 1 | 1 | 0 | 1 | 0 | 0 |
| FLITPEND | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 |
| FLITV | 0 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 1 | 0 |
| Credit count | 0 | 0 | 1 | 0 | 1 | 2 | 2 | 1 | 2 | 1 |

`figure_trace()` replays the same cycles through a `LinkChecker` and expects silence.

### Tables B14.4 and B14.5 paths

Two ports are run against each other in a closed loop (`TxLink` + `RxLink` + channels per side, no simulator) and the (TX link, RX link) state pairs of one side are recorded. Every path the spec draws is reached by choosing who has work and each side's `ack_delay`, and each is checked to step at most one state per link per cycle with the initiator leaving STOP first:

| Table | Path | States of (TX, RX) from one side |
|---|---|---|
| B14.4 activation | path1 | (S,S) (A,S) (A,A) (R,A) (R,R) |
| | path1, RX first to RUN | (S,S) (A,S) (A,A) (A,R) (R,R) |
| | path2 | (S,S) (S,A) (A,A) (A,R) (R,R) |
| | path2, TX first to RUN | (S,S) (S,A) (A,A) (R,A) (R,R) |
| B14.5 deactivation | path1 | (R,R) (D,R) (D,D) (S,D) (S,S) |
| | path2 | (R,R) (D,R) (D,D) (D,S) (S,S) |
| | path3 | (R,R) (R,D) (D,D) (S,D) (S,S) |
| | path4 | (R,R) (R,D) (D,D) (D,S) (S,S) |

A 4 x 4 sweep of `ack_delay` pairs in both initiator directions reaches all four activation paths and never trips a checker. The deactivation path is selected by how many credits each side must return: the side with fewer lets the other's ACK fall first. Further tests cover a full activate / deactivate / reactivate cycle with the roles swapped, that every credit is returned before ACK falls, that a credit raced into DEACTIVATE is returned, and that reset deasserts everything.

## Transaction Model (B2)

`CHITransaction` is one request plus the legal-sequence rules of the B2.3 flows for its class. A BFM feeds it every RSP / DAT flit addressed to its TxnID (`on_rsp`, `on_dat`) and gets back `Action` objects. Flits are duck-typed (anything with `opcode`, `srcid`, `txnid`, `resp`, `resperr`, `dbid`, `pcrdtype`, `homenid`, `dataid`, `data`, `be`; missing ones read as 0), so the unit tests run on `SimpleNamespace` and the BFMs on real flits.

| `ReqClass` | Spec | Opcodes | Legal sequence |
|---|---|---|---|
| `READ_ALLOC` | B2.3.1.1 | ReadClean, ReadNotSharedDirty, ReadShared, ReadUnique, ReadPreferUnique, MakeReadUnique | CompData (every DataID owed) **or** RespSepData + DataSepResp in either order, then CompAck; ExpCompAck must be 1 (Table B2.8). MakeReadUnique alone may complete with a bare Comp (alt 6). ReadReceipt first when Order != 0 |
| `READ_NOALLOC` | B2.3.1.2 | ReadNoSnp, ReadOnce, ReadOnceCleanInvalid, ReadOnceMakeInvalid | As above; CompAck only when ExpCompAck = 1, and an ordered one waits for both RespSepData and DataSepResp before it (B2.7.4) |
| `DATALESS` | B2.3.5 alt 1 | Evict, CleanShared, CleanInvalid, MakeInvalid | Comp only; ExpCompAck must be 0 |
| `DATALESS_ACK` | B2.3.5 alt 2 | CleanUnique, MakeUnique | Comp then CompAck; ExpCompAck must be 1 |
| `WRITE_IMM` | B2.3.2.1 | WriteNoSnpPtl / Full, WriteUniquePtl / Full | CompDBIDResp, **or** DBIDResp / DBIDRespOrd and Comp in either order (not both forms); NonCopyBackWriteData with TxnID = DBID after the DBID; CompAck after Comp when ExpCompAck = 1. A DBID that differs between DBIDResp and Comp from the same source is an error (B2.4.3) |
| `WRITE_COPYBACK` | B2.3.2.3 | WriteBackFull / Ptl, WriteCleanFull, WriteEvictFull, WriteEvictOrEvict | CompDBIDResp then CopyBackWriteData; **or** Comp then CompAck, only for WriteEvictOrEvict or CAH = 1 (alt 1a). ExpCompAck must be 0 |
| `PCRD_RETURN` | B2.10.1 | PCrdReturn | No response at all; AllowRetry forced to 0, Addr to 0, spends a banked P-Credit |

`validate()` runs the static checks before issue (the ExpCompAck rules above, PCrdType = 0 when AllowRetry = 1 per B2.10.2.2, payload length equals Size, TxnID fits 12 bits). `complete()` says whether the class's sequence is finished; `read_data()` assembles the window from the DataID chunks once all are in; `write_chunks(dw)` produces `(dataid, data, be)` per packet with bytes at their natural positions. A RespErr is recorded in `resperr` and counted, never fatal.

Every RSP / DAT the model rejects comes back as `Action('error', text=...)` with the sentence that names the rule: a second Comp, DBIDResp for a read, Comp for a CopyBack without DBID that is neither WriteEvictOrEvict nor CAH, RetryAck after another response was accepted, anything after `done`, a DataID not owed or seen twice, CompData mixed with DataSepResp, a Resp state that changes between packets, and so on.

| `Action.kind` | Parameters | Raised when |
|---|---|---|
| `send_compack` | `tgtid`, `txnid` (= DBID) | Comp / CompData (all data in) / RespSepData for a request that expects one (B2.7.3) |
| `send_write_data` | `tgtid`, `txnid` (= DBID), `opcode` (Table B4.44: CopyBackWriteData or NonCopyBackWriteData), `state` | DBIDResp / DBIDRespOrd / CompDBIDResp |
| `retry` | `pcrdtype` | RetryAck (status `retry_wait`), then PCrdGrant when the credit arrives |
| `done` | | `complete()` first became true |
| `error` | `text` | A sequence rule broke |

### TxnID and DBID pools, trackers

`TxnIdPool` allocates 12-bit TxnIDs round-robin with at most 1024 outstanding (B2.4.2); `reserve()` claims a given one and rejects a duplicate. `RequesterTracker(srcid)` keys the in-flight transactions of one Requester by TxnID: `issue()` validates and allocates, `route_rsp()` / `route_dat()` find the transaction, run it and retire it on `done` (freeing the TxnID), and a flit for an unknown TxnID comes back as an `error` Action. `CompleterTracker` is the Home side: `accept()` keys requests by (SrcID, TxnID) and rejects a duplicate or AllowRetry with PCrdType; `allocate_dbid()` hands out DBIDs from one pool, unique across every Requester, which satisfies the per-Requester rule; `on_write_data()` and `on_compack()` find the request by (SrcID, TxnID == DBID) (B2.4.3) and check the data opcode against Table B4.44, the DataID against the owed set, and duplicates; NonCopyBackWriteDataCompAck marks the CompAck seen; `retire()` frees the DBID.

### Retry (B2.10)

RetryAck is legal only before any other response and only for AllowRetry = 1. The transaction enters `retry_wait` and yields `retry(pcrdtype)`; the tracker then either spends a banked credit of that PCrdType and prepares the re-send at once, or queues the transaction. PCrdGrant carries no TxnID, so it goes through `route_rsp` to `grant()`: the oldest waiter of that type gets the credit (a `retry` Action), otherwise the credit is banked (B2.10: no fixed credit-to-transaction binding). The re-send keeps every field except AllowRetry = 0 and PCrdType = the granted type (`prepare_resend`). `cancel()` drops a waiting transaction; the credit, when it arrives, stays banked and must go back by `PCrdReturn`, which `issue()` only accepts when a credit of that type is banked.

## Cache Model (B4)

Lines are 64 bytes (`line_addr`, `LINE_BYTES`); `CacheLine` holds `state`, `data` and a byte-valid mask only meaningful in UDP. `RNCache(states=...)` is one RN-F's view of its lines; `states` is the subset the cache implements (B4.1), and a transition that lands outside it raises, which is how a DUT that does not do UCE or SD is caught instead of silently modelled. Every table is a dict transcribed row by row (`READ_TRANSITIONS`, `DATALESS_TRANSITIONS`, `WRITE_TRANSITIONS`, `SNOOP_TRANSITIONS`, ...) so a test can spot-check a row against the page; where the spec gives an expected and a permitted final state the model takes the expected one and records the permitted set beside it (`READ_PERMITTED_INITIAL`, `WRITE_PERMITTED_RESP`, `SnoopResponse.permitted_final`).

| Method | Implements |
|---|---|
| `state`, `set_state`, `line`, `read_hit_ok`, `can_write_silently`, `write_bytes` | B4.1: a Unique line may be modified without a transaction (UC to UD, UCE / UDP to UDP, UD once every byte is valid) |
| `complete_read(opcode, addr, comp_state, data)` | Table B4.38 keyed by opcode, initial state and the decoded CompData / DataSepResp Resp; footnotes b / c / d (a _SC response leaves a UC / UD / SD holder where it is) are rows; footnote e drops the memory data when the line was UD / SD and merges the valid bytes over it when UDP. MakeReadUnique uses Tables B4.41 / B4.42 keyed by the state **at the time the response arrives** (B4.7.1.1.3); I / UC / UD at that moment are not permitted. TagOp variants are folded |
| `complete_dataless(opcode, addr, comp_state)` | Table B4.43; the Comp's Resp is checked against what the row lists (Comp_UC for CleanUnique / MakeUnique, Comp_I for Evict / CleanInvalid / MakeInvalid, any of UC / SC / I for CleanShared) and does not change the final state. `DATALESS_REQUIRES_I` (B4.7.2): Evict, CleanInvalid, MakeInvalid are issued from I |
| `writedata_resp(opcode, addr)`, `compack_resp(opcode, addr)`, `complete_write(opcode, addr, final)` | Table B4.44: the WriteData Resp suffix for the state at the time the data is sent, and the final state; footnote b, the CompAck carries the same suffix when Home chose Comp (every CopyBack except WriteBackPtl, `COPYBACK_COMP_ALLOWED`). Where the row lists two legal responses (WriteCleanFull from UC: _UC or _I) the first is taken |
| `on_snoop(opcode, addr, rettosrc, donotgotosd)` | Tables B4.46 (SnpOnce), B4.47 (SnpClean, SnpShared, SnpNotSharedDirty; footnote b with DoNotGoToSD turns the UD / SD rows into SnpRespData_SC_PD), B4.48 (SnpUnique; SnpPreferUnique by the B4.8.1.3 recommendation), B4.49 (SnpCleanShared, SnpCleanInvalid, SnpMakeInvalid), B4.50 (SnpQuery). Applies the expected transition and returns a `SnoopResponse`: SnpResp on RSP, or SnpRespData / SnpRespDataPtl (UDP, with the valid mask as BE) on DAT; dirty data always goes to Home, a clean line returns data only when RetToSrc = 1 (the rows the table marks X), and RetToSrc = 1 raises in the snoops where B13.10.34 says it must be 0 |
| `snoop_resp_encode(state)` | Tables B4.31 / B4.33: SnpResp_UD and SnpRespData_UD use the UC encoding |

### SnoopFilter and Table B4.26

A precise Home-side directory, `{line: {rn_id: state}}`. `snoops_for(opcode, addr, requester)` returns the expected non-forwarding snoop of Table B4.26 for every **other** RN whose copy the request must change, sorted by RN; the B4.4.2 bullets filter out sharers already in the state the request needs: a read wanting a Shared copy snoops Unique and dirty holders only (SC holders need nothing), ReadOnce and CleanShared snoop dirty holders only, ReadNoSnp / WriteNoSnp / CopyBack / Evict / PCrdReturn snoop nobody, ReadUnique / ReadPreferUnique / MakeReadUnique / CleanUnique / CleanInvalid / WriteUniquePtl snoop every valid holder, and MakeUnique / MakeInvalid / WriteUniqueFull send SnpMakeInvalid to a clean holder and SnpCleanInvalid to a dirty one. `on_snoop_response()` and `on_complete()` record the Snoopee's and the Requester's final state (B4.5.3); the caller passes decoded names, so a UD snoop response is recorded as UD, not as the UC encoding it rode in. `dirty_holder()` names the first dirty sharer.

### HomePolicy

What an HN-F puts in the Resp of the Comp / CompData it sends back, read from the Requester tables in reverse:

| Method | Rule |
|---|---|
| `read_response_state(opcode, requester_state_before, other_sharers_after, dirty_passed)` | Table B4.38 column 5: ReadNoSnp / ReadOnce get I; ReadClean SC with other sharers else UC; ReadNotSharedDirty SC with sharers, else UD_PD when dirty data was passed to Home, else UC; ReadShared SD_PD / SC with sharers (dirty or not), UD_PD / UC without; ReadPreferUnique SC with sharers (no SD_PD row), UD_PD / UC without; ReadUnique and MakeReadUnique UD_PD / UC |
| `decide_read(...)` | The above plus where the data comes from (`'snoop'` when a snoop returned it, else `'memory'`, `None` for a MakeReadUnique that already holds data) and `needs_writeback` when dirty data was passed to Home but not on to the Requester, as a `HomeDecision` |
| `dataless_response_state(opcode, requester_state)` | Table B4.43 last column: UC for CleanUnique / MakeUnique, I for Evict / CleanInvalid / MakeInvalid, the Requester's UC / SC (else I) for CleanShared |

## The BFMs on These Models

### RN-F (`CHIRequestNode`)

`new_txn()` fills the CHI defaults an RN-F would use: MemAttr Cacheable | Allocate | EWA for allocating reads, dataless, CopyBack, WriteUnique and ReadOnce, EWA alone otherwise; SnpAttr = 1 except for NoSnp requests and PCrdReturn; ExpCompAck = 1 for `READ_ALLOC` and `DATALESS_ACK`; BE all ones over the payload. `issue()` registers it with the `RequesterTracker` (a validation failure counts `txn_fields` and raises), moves the line to I first for Evict / CleanInvalid / MakeInvalid (B4.7.2), and sends the REQ. On each response the tracker's Actions are carried out:

| Response | What the BFM does |
|---|---|
| CompData / DataSepResp | Collects the chunk; once every DataID is in, CompAck to HomeNID with TxnID = DBID if one is owed; on `done`, `complete_read` moves the line (allocating reads, and 64-byte non-allocating ones) |
| RespSepData | Takes the DBID and state; CompAck at once unless an ordered non-allocating read must wait for the data (B2.7.4) |
| Comp (dataless) | `complete_dataless` on `done`; CompAck first for CleanUnique / MakeUnique |
| Comp (MakeReadUnique, alt 6) | CompAck, then the line moves by Tables B4.41 / B4.42 |
| DBIDResp / DBIDRespOrd / CompDBIDResp | NonCopyBackWriteData (immediate) or CopyBackWriteData (CopyBack) with TxnID = DBID, one DAT flit per DataID, CCID from the address; for a CopyBack the Resp suffix and the final state come from `writedata_resp` (Table B4.44), and the payload from the cache line when none was given; `complete_write` then moves the line |
| Comp (immediate write) | CompAck when ExpCompAck = 1 |
| Comp (CopyBack, alt 1a) | CompAck with the Table B4.44 footnote b suffix from `compack_resp`, then `complete_write` |
| RetryAck, PCrdGrant | Re-sends the REQ with AllowRetry = 0 and the granted PCrdType when the tracker says the credit is in hand (`stats['retries']`) |
| ReadReceipt | Recorded; required before completion when Order != 0 |
| `error` Action | `violations['txn_sequence']`; a flit for an unknown TxnID is `txn_unknown` |

Every snoop on RXSNP goes to `cache.on_snoop` with the flit's RetToSrc and DoNotGoToSD, and the answer is a SnpResp on TXRSP or SnpRespData / SnpRespDataPtl flits on TXDAT addressed back to the snoop's SrcID and TxnID. TXSACTIVE is high while flits are queued or any transaction is outstanding (B14.7.2.1). `pcrd_return(pcrdtype)` sends a PCrdReturn for a banked credit.

### HN-F (`CHIHome` + `CHIHomeNode`)

`CHIHome` is the protocol shared by every port: a `MemoryModel` of 64-byte lines, a `SnoopFilter`, a `CompleterTracker`, the `HomeOptions`, and a per-line `Lock`. `CHIHomeNode` is one port facing one RN: it registers itself with the home under `rn_id` so the home can snoop that RN, serves every REQ on RXREQ as its own coroutine, and asserts TXSACTIVE while any request or snoop is open (B14.7.2.3). Serving is serialised per line: the lock is held from the snoops through the completion until the Requester's CompAck or the write data has arrived (B2.7.3), so the line is not snooped or served again before that. A PCrdReturn is counted and nothing else. A CompAck or write data that matches no DBID, a wrong write-data opcode or DataID, and a SnpResp matching no open snoop are `txn_sequence` / `txn_unknown`; any other RSP / DAT opcode arriving at Home is `txn_unexpected`.

| Request class | What the port does |
|---|---|
| Reads | Snoops per the filter (Table B4.26), waits for every answer; dirty data passed to Home (_PD) is written into memory as it arrives; picks the Resp with `HomePolicy.read_response_state`; serves the line from memory as CompData, or as RespSepData + DataSepResp with probability `read_separate`; allocates a DBID only when a CompAck is owed and then waits for it; records the Requester's new state in the filter |
| Dataless | Snoops, then Comp with `HomePolicy.dataless_response_state`; waits for CompAck when owed; records UD for MakeUnique, I for an I response, else the response state |
| Immediate writes | Snoops, allocates a DBID, sends CompDBIDResp, or DBIDResp then (after the data) Comp with probability `write_separate`; waits for every write-data DataID, applies the byte-enabled chunks to memory, waits for CompAck when ExpCompAck = 1 |
| CopyBack writes | With probability `copyback_comp`, and only for WriteEvictOrEvict or CAH = 1, a Comp (alt 1a) and a wait for CompAck; otherwise CompDBIDResp, wait for the data, write it to memory when its Resp carries _PD, and record the Requester's state: I for WriteBack* / WriteEvict*, otherwise the WriteData state with _PD stripped and UD read as UC |
| Any, AllowRetry = 1 | With probability `retry_rate`: RetryAck with `pcrdtype`, then after `retry_grant_delay` cycles a PCrdGrant, and the request is dropped from the tracker to be re-sent |

| `HomeOptions` | Default | Meaning |
|---|---|---|
| `read_separate` | 0.0 | P(RespSepData + DataSepResp) instead of CompData |
| `write_separate` | 0.0 | P(DBIDResp + Comp) instead of CompDBIDResp |
| `copyback_comp` | 0.0 | P(Comp, alt 1a) for a WriteEvictOrEvict / CAH = 1 CopyBack |
| `retry_rate` | 0.0 | P(RetryAck) for a request with AllowRetry = 1 |
| `retry_grant_delay` | 8 | Cycles from RetryAck to PCrdGrant |
| `pcrdtype` | 0 | The one credit type this home uses (B2.10.2.2) |
| `comp_delay` | (0, 0) | Extra cycles, uniform in (min, max), before serving a request |
| `snoop` | True | Send the snoops the filter asks for; False serves every request without snooping |
| `wait_timeout` | 20000 | Cycles the home waits for a CompAck, write data or a snoop response before counting a `timeout` violation and freeing the line |

`hn.home.snoop(rn_id, opcode, addr, rettosrc=0)` snoops an RN directly from a test and returns the collected response (`resp_state`, `data`, `be`); the loopback uses it to drive SnpCleanInvalid and SnpShared into the RN-F and check the dirty line reaches memory.
