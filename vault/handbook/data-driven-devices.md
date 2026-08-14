---
title: Device variation belongs in data
summary: Encodings, geometries and timings vary per device and per configuration. Express that as a table, a factory argument, or a CSV - never as another branch in the BFM.
---

# Device variation belongs in data

Ask the question that started the DFI CA work: *"CA encoding varies per device
quite often — is there a way to have a table or dict that can be passed in
that defines these?"* The answer should almost always be yes, and the reason
is not elegance. A branch per device means every new part edits shared code,
and the BFM slowly becomes a museum of other people's silicon.

**If it varies per device or per configuration, it is data.** Three forms, in
order of preference:

1. **A declarative table** the engine interprets — `CAMap` describes a command
   set as opcode-bit patterns plus field bit-runs, and one `CACodec` encodes
   and decodes any of them. A vendor with a different encoding writes a map,
   not a code path. `camap_from_dict` loads one from JSON so a device can ship
   its encoding as a file.
2. **A constructor/factory argument** when the choice is not derivable —
   `DFISlavePHY(ca_map=...)`. Note it is explicit *because* it cannot be
   inferred: LPDDR5's bank organization is a property of the part, not of the
   DFI signals, so guessing it from the bus would be guessing.
3. **A CSV** for pure value sets — the JEDEC timing profiles. See
   [[packaging]] for the trap that data files do not ship by default.

## Variation hides inside a single protocol, too

This is not only about different vendors. LPDDR5 alone rewrites its field
layout across three bank organizations: BG mode, 16B, and 8B — and in 8B mode
a read carries a burst-start bit in the slot a bank bit occupies elsewhere,
while three commands do not exist at all. That is why `lpddr5_ca_map()` is a
factory rather than a constant.

## When you cannot decode it, do not pretend you can

Some variation is device *state*, not bus content. LPDDR5's PRECHARGE has two
MR75-gated address-sample variants that redefine the same pins. Folding all
three into one map would produce a decoder that returns a confident wrong
answer, because MR75 is simply not on the CA bus. The honest form is a
selection (`pre_mode=`), and the map validator *rejects* ambiguous patterns
outright unless they are declared aliases.

A map that cannot represent something should fail at construction, not decode
time. Construction-time validation — bus bounds, field-width coverage,
pattern distinguishability — turns a device table typo into a loud error at
load instead of a subtle mis-decode a thousand cycles in.

## What stays in code

Structure, not values. The engine, the streaming layer, the dispatch to
`DRAMCommand` — those encode *how protocols work in general*. The moment a
change would read as "and if it is part X, do this instead", it belongs in a
table.

See [[differential-testing]] for keeping a generated table honest against a
hand transcription.
