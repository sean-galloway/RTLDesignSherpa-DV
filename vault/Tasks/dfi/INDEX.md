# dfi — task rollup

DFI (DDR PHY Interface) BFMs — `src/CocoTBFramework/components/dfi/`.
Umbrella issues: [#16](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/16)
(BFMs), [#66](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/66)
(HBM4 + the CA-map stack).

| State | Count |
|---|---|
| [active](active.md) | 0 |
| [open](open.md) | 15 |
| [deferred](deferred.md) | 2 |
| [closed](closed.md) | 6 |
| [dropped](dropped.md) | 0 |

## Open shortlist

- **DFI-007** — wire CA decode into `DFIMonitor`. The highest-value open
  item: the slave-PHY half shipped, so a monitor on a CA-bus DUT currently
  reports every command as NOP. Scoped, unblocked, pieces already built.
- **DFI-010** — cut the 0.6.4 release. `[Unreleased]` has held the entire
  CA-map stack since 0.6.3; the main repo consumes this as a built wheel,
  so nothing propagates until a release.
- **DFI-011** — `FlexRandomizer` into `DFIMasterMC`. Highest-leverage parity
  item: DFI already owns the `DramStateModel` violation checker the other
  families lack, so randomized stimulus becomes self-checking immediately.
- **DFI-008** — `dram_state` v6.0 semantics (per-pseudo-channel refresh,
  sub-channel selects, RFM as its own class). Decode already passes the
  fields through; this is state-model work.
- **DFI-009** — express LPDDR2's CA encoding as a `CAMap`, differentially
  tested against the hand codec that is shared with the RTL.

## Reading order for someone picking this up

Start with [closed.md](closed.md) DFI-001 → DFI-005 in order: they build one
stack (maps → transport → dispatch → streaming → BFM wiring) and each one
explains why the next exists. Then DFI-007 is the direct continuation.

The two [deferred](deferred.md) items are the honest limits of what has been
done. **DFI-023 matters most:** the whole CA stack is spec-verified and
unit-tested but has never run against RTL, because no v5/v6 co-simulation
target exists. That is why release notes must not advertise the
LPDDR/multi-version features yet.

## Local conventions worth knowing

- **Spec-verified rule.** Signal, command, and timing content in this area
  must be grounded in an on-disk specification — never fabricated to fill a
  gap. Where a spec genuinely leaves a value vendor-defined (HBM4 core
  timings), the template says `FILL_ME` and a test keeps it loadable.
- **Hand codecs stay the anchor.** Where a map duplicates a hand-written
  codec (HBM4 today, LPDDR2 under DFI-009), the hand codec remains the spec
  transcription and the map is differentially tested against it.
- **Device variation belongs in data.** If something varies per device —
  CA encodings, bank organization, timings — it should be a map, a factory
  argument, or a CSV, not a new branch.
