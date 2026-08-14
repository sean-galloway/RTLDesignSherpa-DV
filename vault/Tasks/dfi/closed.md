<!-- Managed by the `tasks` convention: see /vault/Tasks/INDEX.md. Move a task between pages by cutting its block, do not copy. -->

# dfi — Closed (completed)

Kept for history. All of the 2026-08 work below sits under issue
[#66](https://github.com/sean-galloway/RTLDesignSherpa-DV/issues/66) and is
in `CHANGELOG.md` `[Unreleased]` pending the 0.6.4 cut ([[DFI-010]]).

---

## DFI-006 — HBM4 support in the DFI collateral
**Status:** closed 2026-08-12 — #66

DFI v6.0 §3.1.2.4 / Table 22 transport (`hbm_ca.py`: 38-bit `dfi_cmdaddr`
as two independent 19-bit DDR command edges, each carrying Row 10b +
Col 8b + ARFU 1b), JESD270-4A Tables 33/34 row and column opcodes
(`hbm4_commands.py`, 26 golden vectors), the fill-in timing template, and
package-data so the CSVs ship in the wheel.

Also fixed a **pre-existing** catalog bug found on the way: `_WCK` was a
membership frozenset later rebound to a `SubInterface` enum, so the
wck_en/wck_toggle vs wck_cs memberships were wrong. Split into
`_WCK_MEM` / `_WCK_MEM_ALL` with a regression test against v6.0 Table 13.

## DFI-005 — Wire CA decode into `DFISlavePHY`
**Status:** closed 2026-08-13 — 4d835a1

`ca_stream.py` covers the part where the protocols disagree most: how much
bus a command occupies. `CACodec.match` reads the edge count off the head
edge, so one mechanism spans DDR5 (1–2 SDR words), LPDDR5 (one word, both
phases), LPDDR6 (two words / four edges) and HBM4 (independent row and
column streams in lanes of one 38-bit word). Feeding is cycle-driven.

`DFISlavePHY` takes an opt-in `ca_map=` (plus `ca_map_col=` for HBM4);
default `None` leaves the ras/cas/we and LPDDR2 paths bit-identical. The
map is **explicit rather than inferred** because it is not derivable from
the DFI signals — LPDDR5's bank organization is a device property.

Decoded args fold into the `(bank, addr)` pair the command handler already
speaks (AP / all-banks on addr bit 10), so the CA path reuses the existing
command handling instead of forking it. The `_is_lpddr2_family()` gates
became `_uses_ca_bus()`, which also keeps CA protocols off the multi-phase
ras/cas/we decoder — a second site that needed the same fix.

Monitor half is **not** done: [[DFI-007]].

## DFI-004 — CA dispatch to `DRAMCommand`
**Status:** closed 2026-08-12 — 5f1c012

`ca_dispatch.py` turns a decoded CA command into the BFM's canonical
`(DRAMCommand, args)` — the contract `decode_lpddr2_ca` already returns.
Handles what a lookup table cannot: split ACT-1/ACT-2 and MRW-1/MRW-2
pairs latched across intervening commands (JESD209-5C note 4); flat bank
composition `(bg << ba_width) | ba` with the width read from the map; and
AP/all-banks arriving either as distinct commands (DDR5 RDA, HBM4 PREab)
or as operand bits (LPDDR5/6).

A unit test caught the subtle case: on a split ACTIVATE the bank fields
come from the *latched* half, so the width lookup must consider the owning
command, not the emitted one, or `bg` gets shifted by zero.

## DFI-003 — LPDDR5 and LPDDR6 CA maps
**Status:** closed 2026-08-12 — efae3fe

LPDDR5 (JESD209-5C Table 201) ships as a **factory**, `lpddr5_ca_map()`,
because bank organization rewrites the field layout: BG / 16B / 8B, where
8B reads carry burst-start B4 in the slot a bank bit would occupy and
WR32/RD32/DRFM do not exist at all. PRE's MR75-gated address-sample
variants are a `pre_mode=` selection rather than an ambiguous map, since
MR75 is device state and not decodable from the bus.

LPDDR6 (JESD209-6 Table 254) is one map — bank organization is fixed — but
every command is two clock cycles: four CA edges on a 4-bit bus. DES and
PDX-NT have no CA pattern at all (pure CS framing) and are documented
rather than invented, as is the mode-gated CA parity overlay.

## DFI-002 — DDR5 CA map + v6.0 DDR-CA transport
**Status:** closed 2026-08-12 — b3be002

`DDR5_CA_MAP` covers JESD79-5B Table 31 in full. DDR5 forced the engine to
grow **multi-edge opcode signatures**: WR/WRA, RD/RDA and WRP/WRPA are
identical on cycle 1 and split only on the cycle-2 CA10 auto-precharge
bit. Validation is pairwise over the full signature, with a same-`n_edges`
constraint for commands that tie on edge 0 so a streaming consumer can
still learn the edge count from the head edge.

`ca_transport.py` adds the v6.0 §3.1.2 phase-lane packers for LPDDR5
(Table 15) and LPDDR6 DDR mode (Table 16); DDR5 (Table 18) and LPDDR6 SDR
(Table 17) are width-matched passthrough and are documented, not wrapped.

## DFI-001 — Declarative CA maps
**Status:** closed 2026-08-12 — 8880a8c

Answers "CA encoding varies per device — can it be a table or dict?".
A `CAMap` describes a command set as data: opcode-bit patterns plus named
fields as lists of contiguous bit runs, which expresses non-contiguous
scatters (the HBM4 MRS MA/OP interleave) as just several runs. One
`CACodec` engine encodes, stream-matches, and decodes any map. Maps
validate at construction — bus bounds, field-width coverage, and
first-edge distinguishability with declared aliases (RNOP vs
state-selected PDX/SRX). `camap_from_dict` loads JSON-shaped maps so
vendor devices can ship their encodings as files.

`HBM4_ROW_CA_MAP` / `HBM4_COL_CA_MAP` ship as the reference maps,
differentially tested bit-for-bit against the hand-written
`hbm4_commands` codecs — the hand codecs stay the spec anchor, the maps
are what integration consumes.
