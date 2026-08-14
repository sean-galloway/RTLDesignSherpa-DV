<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. Move a task between pages by cutting its block, do not copy. -->

# dfi — Deferred (accepted, parked on a named external condition)

Everything here is shaped and ready; starting it today would be wrong
because the named condition is not met. Each block must say what un-defers
it.

---

## DFI-022 — Real HBM4 timing profile
**Status:** deferred 2026-08-13 — **un-defers when:** a vendor HBM4 datasheet
(SK hynix / Samsung / Micron) is available on disk

JESD270-4A leaves the core array timing *values* vendor-defined — the
min/max columns in Table 108 are blank in the standard itself. Only a
handful are spec-fixed (tREFI = 3.9 µs, tPPD = 2 CK, tCKSRX = 5 CK), and
those are already filled in.

The fill-in sheet is in place at
`src/CocoTBFramework/components/dfi/jedec/hbm4-template.csv.example`: the
15 loader-required rows plus the HBM4-native split parameters (tRCDRD /
tRCDWR, tRRDL / tRRDS, tRFCab / tRFCpb, tCCDL / S / R), each marked
`FILL_ME`. A unit test substitutes dummy values and runs the real loader,
so the template cannot rot while it waits.

**Do not invent the numbers.** The spec-verified rule for this area is that
timing, signal, and command content must be grounded in an on-disk
specification. Copy from a datasheet, or leave `FILL_ME`.

## DFI-023 — Exercise the v5/v6 CA path in simulation
**Status:** deferred 2026-08-13 — **un-defers when:** a v5/v6-era DUT exists to
run against

The whole CA stack (DFI-001…006) is unit-tested — golden vectors derived
from the JEDEC truth tables, differential tests against the hand-written
codecs, streaming and dispatch tests per protocol — but it has **never run
against RTL**. There is no v5/v6 co-simulation target in either repo: the
existing DFI co-sim is pumice, which is DDR2/LPDDR2 on DFI 2.1.

This is the honest gap behind the standing rule not to advertise the
LPDDR/multi-version DFI features in release notes ([[DFI-010]]). Spec-verified
is not the same as silicon-verified, and neither is the same as
simulation-exercised.

Candidate un-deferring events, in rough order of likelihood:
- the fresh DDR2/3/4 + LPDDR2/3/4 designs planned for ~2026-09/10 — these
  raise the validation bar but are mostly *older* DFI versions, so they
  would exercise the CA path only via [[DFI-009]] (LPDDR2 as a map);
- a v6-era controller or a vendor PHY model to run the BFM against.
