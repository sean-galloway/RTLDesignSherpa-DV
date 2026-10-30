<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. -->

# chi — Active

## CHI-001 — Add the CHI BFM family (IHI 0050 Issue H, RN-F / HN-F / monitor)
**Status:** active 2026-10-30

`src/CocoTBFramework/components/chi/`: `chi_config.py` (B16 properties,
numbered legality rules, flit widths from Tables B13.6-B13.9),
`chi_opcodes.py` (every opcode table, Size/MemAttr/Order/RespErr/Resp/
FwdState, DataID arithmetic), `chi_flits.py` (one Packet subclass per
channel, bit-exact pack/unpack, shared-bit aliases), `chi_link.py`
(L-Credits, FLITPEND, LINKACTIVE per direction, LCrdReturn, checker),
`chi_transaction.py` (legal sequences per request class, TxnID/DBID pools,
retry), `chi_cache_model.py` (B4.1 states, Tables B4.38/43/44/46-50, snoop
filter, home policy), `chi_port.py` (clocked chassis), `chi_rn.py`,
`chi_hn.py`, `chi_monitor.py`, `chi_factories.py`.

Scope of this first cut: Issue H, no Resource Planes or shared credits, no
replicated channels; requests Read*, Dataless (CleanUnique, MakeUnique,
Evict, CleanShared, CleanInvalid, MakeInvalid), WriteNoSnp*, WriteUnique*,
CopyBack writes, PCrdReturn; non-forwarding snoops only. Not modelled: DCT
(Snp*Fwd), stash, atomics, DVM, MTE, RME, DMT/DWT, multi-request, C2C.

Verified by `tests/unit/test_chi_*.py` (spec-table transcription checks,
Figure B14.1 credit timing, Tables B14.4/B14.5 link paths, sequence rules)
and `tests/sim/chi/test_chi_loopback.py` (RN-F <-> chi_wires <-> HN-F with a
monitor each side). Spec on disk: `~/github/amba-specs/IHI0050H_amba_chi_architecture_spec.pdf`.

Un-close condition: the RTLDesignSherpa CHI interface modules (next task,
main repo) run against these BFMs; any BFM defect they expose reopens this.
