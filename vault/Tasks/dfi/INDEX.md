# dfi — task rollup

DFI (DDR PHY Interface) BFMs — `src/CocoTBFramework/components/dfi/`.
Umbrella issues: [#16](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/16)
(BFMs), [#66](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/66)
(HBM4 + the CA-map stack).

| State | Count |
|---|---|
| [active](active.md) | 0 |
| [open](open.md) | 0 |
| [deferred](deferred.md) | 15 |
| [closed](closed.md) | 8 |
| [dropped](dropped.md) | 0 |

## The area is parked

**The DFI protocol and BFM programme is deferred as of 2026-08-14**, on the
owner's steer that it is not needed until the memory-controller work that
consumes it is close. Thirteen shaped tasks sit in `deferred` (fourteen
moved from `open`; DFI-007 was pulled straight back out and fixed) — they had been filed as ready-to-start, which overstated their
priority. Nothing is blocked on effort or on an unknown; it is blocked on
having a consumer. See the note at the top of [deferred.md](deferred.md)
for the un-defer condition and the order to restart in.

The CA-map stack is complete and green, so the pause lands at a coherent
point rather than mid-change.

## Open shortlist

Nothing open. 0.6.4 shipped the CA-map stack on 2026-08-17; everything
else in the area is deferred pending the memory-controller work.

## Reading order for someone picking this up

Start with [closed.md](closed.md) DFI-001 → DFI-006 in order: they build one
stack (maps → transport → dispatch → streaming → BFM wiring) and each one
explains why the next exists. Then read the parking note in
[deferred.md](deferred.md), which says where to resume.

Two of the deferred items are the honest limits of what has been done, and
predate the parking. **DFI-023 matters most:** the whole CA stack is
spec-verified and unit-tested but has never run against RTL, because no
v5/v6 co-simulation target exists. That is why release notes must not
advertise the LPDDR/multi-version features yet.

**DFI-007 was fixed rather than parked** (2026-08-14): it was a
correctness bug, not an enhancement — `DFIMonitor` had no CA-bus decode
at all, so a monitor on any CA-bus DUT, LPDDR2 included, silently
reported every command as NOP. See [closed.md](closed.md).

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
