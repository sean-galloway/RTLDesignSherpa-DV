---
title: Spec fidelity for protocol collateral
summary: Signal, command, and timing content must be grounded in an on-disk specification. Never fabricate to fill a gap - and when the spec itself leaves a value undefined, say FILL_ME and keep it loadable.
---

# Spec fidelity for protocol collateral

This package models real protocols — JEDEC DRAM, DFI, AMBA. A BFM that
encodes a plausible-but-wrong bit is worse than one that refuses to encode
it: the plausible version passes review, ships, and then disagrees with
silicon in a way nobody traces back here.

**The rule: signal names, command encodings, and timing values come from a
specification on disk. If it is not in a spec you can open, it does not go
in.**

## Why this is a rule and not a preference

**Case study — the 2026-08 DFI purge.** The DFI BFM had accumulated signals
that did not exist in any DFI specification. They looked right, they were
consistently named, and nothing in the test suite could tell — the tests
asserted the BFM against itself. They were found only when the real v2.1.1
through v6.0 PDFs were read side by side, and the fix was deletion.

A test suite cannot catch a fabricated fact. Only a spec can.

## Where the specs are

Local archives, both outside the repos:

- `~/github/dfi-specs/` — DFI 2.1.1 / 3.1 / 4.0 / 5.2 / 6.0, JESD270-4A
  (HBM4), JESD209-5C (LPDDR5), JESD209-6 (LPDDR6)
- `~/github/cold_storage/MemorySpecs/` — JEDEC DDR2/3/4/5, LPDDR2/3/4,
  GDDR6, plus vendor datasheets

Extract truth tables with `pdftotext -layout`. Without `-layout` a multi-column
truth table linearizes into meaningless order — the columns interleave and you
will silently read the wrong bit against the wrong signal. Also note that the
PDF page number and the document page number differ; find the table by its
caption, not by arithmetic.

## When the spec deliberately leaves a value open

Some values are genuinely vendor-defined. JESD270-4A Table 108 prints the HBM4
core array timings with **blank** min/max columns: the standard fixes only a
few (tREFI = 3.9 us, tPPD = 2 CK, tCKSRX = 5 CK) and leaves the rest to the
part.

Do not guess, and do not quietly omit. Ship a template that names every row and
marks the unknowns:

```
tRCD,  ns,  FILL_ME,  ACT to RD delay - HBM4 tRCDRD (tRCDWR goes in extras)
tREFI, ns,  3900,     Average refresh interval - spec-fixed (section 6.9)
```

Then add a unit test that substitutes dummy values and runs the **real
loader**, so the template cannot rot while it waits for a datasheet. A
template nobody can load is not a placeholder, it is a trap. The waiting
itself is a tracked, deferred task with a named un-defer condition — see
`vault/Tasks/dfi/deferred.md`.

## What this implies for claims

Spec-verified, unit-tested, simulation-exercised, and silicon-verified are
four different things and the gap between them belongs in writing. The DFI CA
maps are spec-verified and unit-tested but have never run against RTL, which
is why release notes must not yet advertise the LPDDR/multi-version support.
State the limit in the release notes, the task block, and the module
docstring — the reader who needs it is the one who did not do the work.

See also [[differential-testing]] for keeping a second implementation honest
against a spec transcription, and [[data-driven-devices]] for where
per-device values live.
