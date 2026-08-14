# Tasks

One place to see what is going on across the package. Each area has its own
directory with an `INDEX.md` and its lifecycle pages:

```
vault/Tasks/<area>/
  INDEX.md    rollup: counts + the active/open shortlist
  active.md   in progress right now
  open.md     accepted, ready to start
  deferred.md accepted, deliberately PARKED - waiting on a named external
              condition (a datasheet, a DUT, a decision), not on effort
  closed.md   done (completed; kept for history, not deleted)
  dropped.md  ended without completing (abandoned / superseded / won't do)
```

`closed` and `dropped` are both terminal but they are not the same thing:
`closed` means the work got done, `dropped` means we decided not to do it.
Keeping them apart is what makes the history honest — a dropped task should
never read as an accomplishment.

`open` and `deferred` are both pending but they are not the same either:
`open` means someone could start it today; `deferred` means starting it today
would be wrong, and its block must NAME the condition that un-defers it, so
the parking is a recorded decision rather than quiet neglect.

## Lifecycle

A task moves `open → active → closed` — or to `dropped` if it ends without
being completed, or `open ↔ deferred` when the blocker is an external
condition rather than effort — by **cutting** its block from one page and
pasting it into the next. Never copy: a task must exist in exactly one state.
Keep the `**Status:**` line current with a date, and for dropped/deferred a
one-line reason (for deferred: the condition that un-defers it).

## Areas

Areas mirror `src/CocoTBFramework/`. An area gets its own directory once it
has in-flight work worth a rollup; until then its row says where the work
actually lives, so the map is complete even where the pages are not.

| Area | Status | Covers | Where its work lives now |
|---|---|---|---|
| [dfi](dfi/INDEX.md) | **migrated** | DFI BFMs: CA maps, transport, dispatch, DRAM state model, BFM parity | here (`TODO.md` D1–D11 folded in 2026-08-13) |
| gaxi | pending | generic ready/valid infrastructure — the workhorse every AXI\* family builds on, so it carries the highest bar | GitHub issues |
| axi4 / axi5 | pending | AXI4 full + AXI5, compliance, sequences | GitHub issues |
| axil4 | pending | AXI4-Lite | GitHub issues |
| apb / apb5 | pending | APB4 + APB5 (sideband, parity, wakeup) | GitHub issues |
| axis4 / axis5 | pending | AXI-Stream | GitHub issues |
| fifo | pending | FIFO controllers | GitHub issues |
| smbus / uart | pending | SMBus, UART | GitHub issues |
| shared | pending | packet, field_config, memory_model, randomizer, statistics — the layer the parity items (DFI-012, DFI-014) pull DFI onto | GitHub issues; DFI's dependency on it tracked in [dfi](dfi/INDEX.md) |
| scoreboards | pending | `BaseScoreboard` and per-protocol scoreboards | GitHub issues; DFI-016 |
| wavedrom | pending | waveform generation | GitHub issues |
| packaging | pending | wheel/PyPI, package-data, release cuts | GitHub issues; the current cut is DFI-010; practice in [[packaging]] |

`pending` is not a backlog of empty files — it means that family's work is
tracked as GitHub issues and nobody has needed a rollup yet. Promote a row to
its own directory when you find yourself wanting to know "what is in flight
here" and the issue list cannot answer it.

**Do not create an area directory speculatively.** Five empty lifecycle pages
per family is scatter of exactly the kind this directory replaces; the map
above is the cheap version of the same information.

## Reporting status

`vault/Tasks/<area>/INDEX.md` is the human-readable rollup for that area;
this file is the cross-area map. When you start or finish work, update the
area INDEX counts so the one-place view stays true.
